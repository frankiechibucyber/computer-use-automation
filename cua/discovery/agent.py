"""Discovery — the record-once phase (brief §3.1, §3.4).

An LLM drives the UI once toward a goal. Every model action passes the Guard, then is recorded as
a typed Step. Three invariants make the emitted artifact trustworthy enough to replay in
production without a human re-checking it:

  (1) FAIL-LOUD recorder — if an action executes on the page but cannot be represented as a Step,
      we ABORT. A recorder that silently drops an op ships a capability that is missing a step and
      fails on replay. (This exact class of bug — a 'select' silently dropped by a too-narrow op
      set — is why this invariant exists.)

  (2) CANONICALIZATION — concrete values the caller supplied (a member id, a deposit amount) are
      turned into params at record time, so the artifact is reusable across tenants/inputs rather
      than frozen to one run. Values NOT known to be params are recorded as literals.

  (3) SELF-REPLAY GATE — discovery is not "done" until the emitted artifact replays cleanly once.
      Discovery that produced an artifact which cannot itself be replayed has produced nothing.
      For flows whose tail is irreversible (e.g. "Confirm Open"), the gate does a DRY RUN: it
      replays the reversible prefix and asserts the risky control is reachable and gated, without
      firing the side effect.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..llm.client import LLMClient, Usage
from ..policy.guard import Guard
from ..replay.engine import ReplayConfig, replay
from ..schema import (Artifact, Checkpoint, Locator, Provenance, Result, Status, Step)
from ..surface.web import WebSurface

# role each op targets, so the recorder builds the right Locator without guessing
_ROLE_FOR_OP = {"fill": "textbox", "select": "combobox", "click": "button"}


class RecorderError(RuntimeError):
    """Raised when an action was executed but could not be recorded as a Step (fail-loud)."""


@dataclass
class DiscoveryResult:
    artifact: Artifact
    transcript: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    attempted: int = 0
    succeeded: int = 0
    self_replay_ok: bool = False
    wall_s: float = 0.0


def _record_step(action: dict, known: dict[str, str]) -> Step:
    """Translate one model action into a typed Step, canonicalizing known values to params.

    Raises so the caller can fail loud; never returns None (a None here is exactly the silent
    drop we refuse to ship).
    """
    op = action["op"]
    role = _ROLE_FOR_OP.get(op)
    if role is None:
        raise RecorderError(f"no schema representation for op {op!r} in action {action}")
    name = action.get("name")
    value = action.get("value")
    value_param = known.get(str(value)) if value is not None else None
    if op == "click":
        return Step(op="click", target=Locator(role=role, name=name))
    if op == "fill":
        return Step(op="fill", target=Locator(role=role, name=name),
                    value_param=value_param or "literal")
    if op == "select":
        return Step(op="select", target=Locator(role=role, name=name),
                    value_param=value_param or "literal", option_label=value)
    raise RecorderError(f"unhandled op {op!r}")


def discover(surf: WebSurface, llm: LLMClient, guard: Guard, *, goal: str, target_url: str,
             name: str, params: dict[str, str], known: dict[str, str],
             checkpoint: Checkpoint, extracts=None, business_outcomes=None, recoverables=None,
             stop_text: str | None = None, max_steps: int = 10,
             replay_params: dict[str, str] | None = None) -> DiscoveryResult:
    extracts = extracts or []
    business_outcomes = business_outcomes or []
    recoverables = recoverables or []
    stop_text = stop_text or checkpoint.text

    surf.goto(target_url)
    steps: list[Step] = []
    transcript: list[dict] = []
    usage = Usage()
    attempted = succeeded = 0
    t0 = time.time()

    for i in range(max_steps):
        obs = surf.perceive()
        decision = llm.decide(goal, obs.aria_snapshot, [t["action"] for t in transcript])
        usage.add(decision.usage)
        action = decision.action
        transcript.append({"step": i, "action": action, "aria_len": len(obs.aria_snapshot)})
        if action.get("op") == "done":
            break

        # single choke point: allowlist + risk gate. A blocked risky action ends discovery of the
        # automatable prefix — the risky tail is recorded but gated, never auto-executed.
        block = guard.check(action["op"], surf.page.url, action.get("name"))
        if block:
            transcript[-1]["blocked"] = block
            steps.append(_record_step(action, known))   # record it so replay knows it's the tail
            break

        attempted += 1
        surf.act(action["op"], Locator(role=_ROLE_FOR_OP.get(action["op"]), name=action.get("name")),
                 value=action.get("value"), option_label=action.get("value")
                 if action["op"] == "select" else None)
        succeeded += 1
        steps.append(_record_step(action, known))        # fail-loud: raises if unrepresentable

        if stop_text and surf.find_text(stop_text):
            break

    artifact = Artifact(
        name=name, params=params, steps=steps, extracts=extracts,
        checkpoint=checkpoint, business_outcomes=business_outcomes, recoverables=recoverables,
        provenance=Provenance(
            discovered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            model=llm.model, target=target_url,
            cost_usd=round(usage.cost_usd(0.15, 0.60), 6),
            prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
        ),
    )

    # (3) self-replay gate — reuse the SAME surface; the artifact must replay before we return it.
    self_ok = _self_replay_gate(surf, guard, artifact, replay_params or {})

    return DiscoveryResult(artifact=artifact, transcript=transcript, usage=usage,
                           attempted=attempted, succeeded=succeeded, self_replay_ok=self_ok,
                           wall_s=time.time() - t0)


def _self_replay_gate(surf: WebSurface, guard: Guard, art: Artifact,
                      params: dict[str, str]) -> bool:
    """Replay the artifact once to prove it works. If the tail is risky, dry-run it:
    replay the reversible prefix and assert the risky control is reachable and gated."""
    risky_tail = art.steps and art.steps[-1].op == "click" and \
        art.steps[-1].target.name in guard.policy.risky_control_names
    if risky_tail:
        prefix = Artifact(**{**art.model_dump(), "steps": [s.model_dump() for s in art.steps[:-1]]})
        res = replay(surf, prefix, params)
        # prefix must reach the review/checkpoint state AND the risky control must be present+gated
        reachable = surf.find_text(art.steps[-1].target.name) > 0
        gated = guard.check("click", surf.page.url, art.steps[-1].target.name) == \
            "risky_requires_confirmation"
        return res.status in (Status.SUCCESS, Status.BUSINESS_OUTCOME) and reachable and gated
    res = replay(surf, art, params)
    return res.status in (Status.SUCCESS, Status.BUSINESS_OUTCOME)
