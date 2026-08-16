"""Evidence writer — the audit trail for every discovery/replay run.

Two consumers: a human reviewer (does the flow do what it claims? is anything sensitive leaking?)
and a regression check (did discovery reproduce?). Everything written here goes through the
policy redactor first — financial data must never land in a transcript on disk. Redaction lives in
the guard, not here, so there is one definition of "sensitive" across the system.

Files, and why each exists:
  <name>.artifact.json        the reusable capability (the deliverable of discovery)
  <name>.transcript.jsonl     one line per model turn (action + aria length only, no raw PII)
  <name>.run.json            machine summary: cost, tokens, wall time, self-replay verdict
  <name>.final.png            a screenshot of the end state (visual proof)
  <name>.replay.jsonl        APPEND-only log of replay runs — one line per invocation (params,
                             executed steps, and the structured result). The brief (§6) asks for
                             logs from *both* a discovery run AND a replay run; this is the second.
  <name>.replay.<status>.png a screenshot per distinct replay outcome (esp. the failure/error one)
"""
from __future__ import annotations

import json
import pathlib
import time

from ..discovery.agent import DiscoveryResult
from ..policy.guard import redact
from ..schema import Artifact, Result


class EvidenceWriter:
    def __init__(self, root: str = "evidence"):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_discovery(self, dr: DiscoveryResult, name: str,
                        screenshot_surface=None) -> dict[str, str]:
        art_path = self.root / f"{name}.artifact.json"
        art_path.write_text(dr.artifact.model_dump_json(indent=2, exclude_none=True))

        tr_path = self.root / f"{name}.transcript.jsonl"
        with open(tr_path, "w") as f:
            for t in dr.transcript:
                f.write(redact(json.dumps(t)) + "\n")

        run_path = self.root / f"{name}.run.json"
        run_path.write_text(json.dumps({
            "model": dr.artifact.provenance.model if dr.artifact.provenance else None,
            "steps_recorded": len(dr.artifact.steps),
            "attempted": dr.attempted, "succeeded": dr.succeeded,
            "self_replay_ok": dr.self_replay_ok,
            "wall_s": round(dr.wall_s, 2),
            "prompt_tokens": dr.usage.prompt_tokens,
            "completion_tokens": dr.usage.completion_tokens,
            "cost_usd": dr.artifact.provenance.cost_usd if dr.artifact.provenance else None,
        }, indent=2))

        paths = {"artifact": str(art_path), "transcript": str(tr_path), "run": str(run_path)}
        if screenshot_surface is not None:
            shot = self.root / f"{name}.final.png"
            screenshot_surface.page.screenshot(path=str(shot))
            paths["screenshot"] = str(shot)
        return paths

    def write_replay(self, art: Artifact, params: dict[str, str], result: Result, name: str,
                     screenshot_surface=None) -> dict[str, str]:
        """Append one replay run to <name>.replay.jsonl and snapshot the outcome.

        Append (not overwrite) so a single evidence file can show several runs side by side — e.g.
        a success and a `business_outcome` — which is exactly the "one replay that hits an error/
        exceptional state" the brief wants demonstrated. Params and the whole record go through the
        redactor: a param could carry sensitive data, and evidence on disk must never leak it.
        """
        log_path = self.root / f"{name}.replay.jsonl"
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "capability": art.name,
            "params": params,
            "executed_steps": [
                {"op": s.op, "role": s.target.role, "name": s.target.name} for s in art.steps
            ],
            "result": result.model_dump(exclude_none=True),
        }
        with open(log_path, "a") as f:
            f.write(redact(json.dumps(record)) + "\n")

        paths = {"replay_log": str(log_path)}
        if screenshot_surface is not None:
            shot = self.root / f"{name}.replay.{result.status.value}.png"
            screenshot_surface.page.screenshot(path=str(shot))
            paths["screenshot"] = str(shot)
        return paths
