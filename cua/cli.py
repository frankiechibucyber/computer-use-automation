"""CLI — the operator/agent entry point. Three verbs mirror the system's lifecycle:

  discover  — drive the target once with the LLM, emit + gate a capability artifact, save evidence.
  replay    — invoke a saved capability deterministically (NO LLM), print the typed Result.
  catalog   — list the capabilities the calling agent can invoke.

Everything machine-specific is a flag or env var, never a constant (R027): the target is passed
as `--target` (a file:// or http(s):// URL), the API key comes from the environment, and the
policy URL fence is set from the target at run time. Nothing here hardcodes a path or key.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

from .discovery.agent import discover
from .evidence.writer import EvidenceWriter
from .llm.client import LLMClient
from .policy.guard import Guard, Policy
from .replay.engine import ReplayConfig, replay
from .schema import (Artifact, BusinessOutcome, Checkpoint, Extract, Recoverable)
from .surface.web import WebSurface

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOGS = ROOT / "catalogs"


def _load_policy(target_url: str) -> Policy:
    pol = Policy.from_yaml(str(CATALOGS / "policy.yaml"))
    # Fence automation to the target's own directory/origin — the blast-radius boundary.
    prefix = target_url.rsplit("/", 1)[0] if "/" in target_url else target_url
    pol.allowed_url_prefixes = [prefix]
    return pol


def cmd_discover(args) -> int:
    tasks = yaml.safe_load(open(CATALOGS / "tasks.yaml"))
    if args.task not in tasks:
        print(f"unknown task {args.task!r}; known: {list(tasks)}", file=sys.stderr)
        return 2
    t = tasks[args.task]

    guard = Guard(_load_policy(args.target))
    llm = LLMClient()
    surf = WebSurface(headless=not args.headed)
    try:
        dr = discover(
            surf, llm, guard,
            goal=t["goal"], target_url=args.target, name=args.task,
            params=t.get("params", {}), known={str(k): v for k, v in t.get("known", {}).items()},
            checkpoint=Checkpoint(text=t["checkpoint"]),
            extracts=[Extract(**e) for e in t.get("extracts", [])],
            business_outcomes=[BusinessOutcome(**b) for b in t.get("business_outcomes", [])],
            recoverables=[Recoverable(**r) for r in t.get("recoverables", [])],
            replay_params=t.get("replay_params", {}),
        )
        paths = EvidenceWriter(args.evidence).write_discovery(dr, args.task, screenshot_surface=surf)
    finally:
        surf.close()

    # publish the gated capability into the registry so `replay`/`catalog` can find it
    if dr.self_replay_ok:
        (CATALOGS / "capabilities").mkdir(exist_ok=True)
        (CATALOGS / "capabilities" / f"{args.task}.artifact.json").write_text(
            dr.artifact.model_dump_json(indent=2, exclude_none=True))

    print(json.dumps({
        "task": args.task, "steps_recorded": len(dr.artifact.steps),
        "recorded_ok": f"{dr.succeeded}/{dr.attempted}",
        "self_replay_ok": dr.self_replay_ok,
        "wall_s": round(dr.wall_s, 2), "cost_usd": dr.artifact.provenance.cost_usd,
        "published": dr.self_replay_ok, "evidence": paths,
    }, indent=2))
    return 0 if dr.self_replay_ok else 1


def cmd_replay(args) -> int:
    art_path = CATALOGS / "capabilities" / f"{args.capability}.artifact.json"
    if not art_path.exists():
        print(f"no such capability: {args.capability}", file=sys.stderr)
        return 2
    art = Artifact.model_validate_json(art_path.read_text())
    if args.target:                                # allow retargeting the same capability
        art.provenance.target = args.target
    params = json.loads(args.params) if args.params else {}
    cfg = ReplayConfig(checkpoint_timeout_ms=args.timeout_ms)

    surf = WebSurface(headless=not args.headed)
    try:
        res = replay(surf, art, params, cfg)
        if args.evidence:                              # persist the replay log while the page is live
            EvidenceWriter(args.evidence).write_replay(art, params, res, args.capability,
                                                        screenshot_surface=surf)
    finally:
        surf.close()
    print(res.model_dump_json(indent=2, exclude_none=True))
    return 0 if res.status.value in ("success", "business_outcome") else 1


def cmd_catalog(args) -> int:
    reg = CATALOGS / "capabilities"
    caps = sorted(reg.glob("*.artifact.json")) if reg.exists() else []
    out = []
    for p in caps:
        art = Artifact.model_validate_json(p.read_text())
        out.append({"name": art.name, "params": art.params,
                    "checkpoint": art.checkpoint.text, "steps": len(art.steps)})
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cua", description="Computer-Use Automation: discover once, replay forever.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="drive the target once with the LLM and emit a capability")
    d.add_argument("task", help="task name from catalogs/tasks.yaml")
    d.add_argument("--target", required=True, help="target URL (file:// or http(s)://)")
    d.add_argument("--evidence", default="evidence")
    d.add_argument("--headed", action="store_true")
    d.set_defaults(func=cmd_discover)

    r = sub.add_parser("replay", help="invoke a saved capability deterministically (no LLM)")
    r.add_argument("capability", help="capability name in catalogs/capabilities/")
    r.add_argument("--params", help="JSON object of param values")
    r.add_argument("--target", help="override the target URL")
    r.add_argument("--timeout-ms", type=int, default=3000)
    r.add_argument("--evidence", nargs="?", const="evidence", default=None,
                   help="persist a redacted replay log (default dir: evidence/)")
    r.add_argument("--headed", action="store_true")
    r.set_defaults(func=cmd_replay)

    c = sub.add_parser("catalog", help="list invocable capabilities")
    c.set_defaults(func=cmd_catalog)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
