"""Provider-agnostic LLM client for the discovery loop only (never touched at replay).

Deliberately thin and stdlib-only (`urllib`) — the model is a commodity behind an OpenAI-style
chat endpoint, so the whole system stays swappable by changing `model`/`base_url`, not code. We
default to a small, cheap model (gpt-4o-mini class): discovery reads a compact accessibility tree
and emits one typed JSON action per turn, which small models do reliably and ~30x cheaper than a
frontier model or a screenshot-vision loop (cost math in REPORT §3).

The key is read from the environment only — never a constant, never logged (R027: no
machine-specific secrets baked into the deliverable).
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: dict) -> None:
        self.prompt_tokens += other.get("prompt_tokens", 0)
        self.completion_tokens += other.get("completion_tokens", 0)

    def cost_usd(self, in_per_m: float, out_per_m: float) -> float:
        return self.prompt_tokens / 1e6 * in_per_m + self.completion_tokens / 1e6 * out_per_m


@dataclass
class Decision:
    action: dict          # one typed action: {"op": "...", "name": "...", "value": "..."} | {"op":"done"}
    usage: dict


# The action grammar the model must speak. Kept in the client because it is the contract between
# the model and the discovery recorder; every op here MUST be representable by the artifact schema
# (else the recorder fails loud — see discovery/agent.py).
SYSTEM_PROMPT = (
    "You operate a legacy web UI like a careful back-office operator. You are given the GOAL and "
    "the current ACCESSIBILITY TREE of the page. Reply with EXACTLY ONE action as strict minified "
    "JSON, no prose, no code fences. Allowed actions: "
    '{"op":"fill","name":"<accessible name of textbox>","value":"<text>"} | '
    '{"op":"select","name":"<accessible name of combobox>","value":"<option label>"} | '
    '{"op":"click","name":"<accessible name of button>"} | '
    '{"op":"done"} when the goal state is visible. '
    "Target controls by their accessible name exactly as shown in the tree."
)


class LLMClient:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key_env: str = "OPENROUTER_KEY", timeout_s: int = 60):
        self.model = model or os.environ.get("OR_MODEL", "openai/gpt-4o-mini")
        self.base_url = base_url or os.environ.get(
            "OR_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
        self.api_key = os.environ[api_key_env]
        self.timeout_s = timeout_s

    def decide(self, goal: str, aria: str, history: list) -> Decision:
        user = f"GOAL: {goal}\n\nACCESSIBILITY TREE:\n{aria}\n\nDONE SO FAR: {history}\n\nNext action JSON:"
        body = json.dumps({
            "model": self.model,
            "temperature": 0,                       # determinism at discovery too, as far as possible
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }).encode()
        req = urllib.request.Request(
            self.base_url, data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=self.timeout_s))
        txt = d["choices"][0]["message"]["content"].strip()
        if txt.startswith("```"):                   # some models fence despite instructions
            txt = txt[txt.find("{"):txt.rfind("}") + 1]
        action = json.loads(txt)
        if isinstance(action, list):                # some models wrap the single action in a list
            action = action[0]
        return Decision(action=action, usage=d.get("usage", {}))
