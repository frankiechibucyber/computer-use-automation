"""Deterministic replay — the production path (brief §3.3).

This is the whole point of the system: once a flow is discovered, the model is *removed from the
loop*. Replay is not re-execution of the discovery run; it is execution of the artifact. No LLM,
no reasoning, no per-run variability — the same inputs produce the same outputs, which is what
makes the result auditable and cheap.

Order of checks after the steps run, and why it is this order:
  1. recoverables  — clear known transient/interstitial/session conditions FIRST (bounded retries,
                     never open-ended re-reasoning), because an un-cleared interstitial would look
                     like a checkpoint miss.
  2. business outcomes — a legitimate non-happy result (no such member, permission denied) is
                     DATA the caller wants, checked BEFORE we call anything a failure.
  3. checkpoint    — only now assert success; a missed checkpoint within the configured timeout is
                     a hard failure carrying the observed state (never a bare exception).
"""
from __future__ import annotations

from pydantic import BaseModel

from ..schema import Artifact, Recoverable, Result, Status
from ..surface.base import LocatorMiss
from ..surface.web import WebSurface


class ReplayConfig(BaseModel):
    """Every wait/limit is a config knob derived from the worst *legitimate* case, not a guess.

    A too-short checkpoint timeout misclassifies a slow-but-valid load as a failure (measured in
    the slow-load spike); a too-long one delays real failures. So it is exposed, with a default
    sized to the observed worst legitimate load plus margin.
    """

    checkpoint_timeout_ms: int = 3000
    recoverable_detect_timeout_ms: int = 1000
    max_transient_retries: int = 3
    transient_backoff_s: float = 0.1


def _run_steps(surf: WebSurface, art: Artifact, params: dict[str, str],
               navigate: bool) -> list[str]:
    """Execute the recorded steps once. Returns the rung labels that resolved each target.

    `navigate=False` re-issues steps WITHOUT reloading — required for session recovery, where a
    reload would drop the re-authenticated session (a real bug caught in the session-timeout spike).
    """
    rungs: list[str] = []
    if navigate and art.provenance and art.provenance.target:
        surf.goto(art.provenance.target)
    for step in art.steps:
        value = params.get(step.value_param) if step.value_param else None
        res = surf.act(step.op, step.target, value=value, option_label=step.option_label)
        rungs.append(res.rung or "?")
    return rungs


def _handle_recoverables(surf: WebSurface, recs: list[Recoverable], cfg: ReplayConfig,
                         art: Artifact, params: dict[str, str],
                         recovered: list[str]) -> Result | None:
    """Bounded recovery. Returns a HARD_FAILURE Result if a transient never clears, else None."""
    import time

    for rec in recs:
        tries = 0
        while surf.find_text(rec.detect):
            if rec.action:                                  # interstitial / session_timeout
                surf.click_button(rec.action)
                recovered.append(f"{rec.kind}:{rec.detect} -> {rec.action}")
                if rec.kind == "session_timeout":
                    _run_steps(surf, art, params, navigate=not rec.no_reload)  # retry, keep session
                break
            # transient with no action: bounded backoff-retry of the steps
            if tries >= (rec.max_retries or cfg.max_transient_retries):
                return Result(status=Status.HARD_FAILURE, expected=f"{rec.detect} cleared",
                              observed=rec.detect, recovered=recovered)
            tries += 1
            time.sleep(cfg.transient_backoff_s * (2 ** (tries - 1)))
            recovered.append(f"transient:{rec.detect} retry {tries}")
            _run_steps(surf, art, params, navigate=False)
    return None


def replay(surf: WebSurface, art: Artifact, params: dict[str, str],
           cfg: ReplayConfig | None = None) -> Result:
    cfg = cfg or ReplayConfig()
    recovered: list[str] = []
    try:
        _run_steps(surf, art, params, navigate=True)
    except LocatorMiss as e:
        return Result(status=Status.HARD_FAILURE, expected=str(e.locator), observed="locator miss")

    hard = _handle_recoverables(surf, art.recoverables, cfg, art, params, recovered)
    if hard is not None:
        return hard

    for bo in art.business_outcomes:
        alert = surf.alert_text()
        if alert and bo.detect_alert_text in alert:
            return Result(status=Status.BUSINESS_OUTCOME, outcome_code=bo.code, recovered=recovered)

    if not surf.wait_for_text(art.checkpoint.text, cfg.checkpoint_timeout_ms):
        observed = surf.alert_text() or surf.loading_text()
        return Result(status=Status.HARD_FAILURE, error_step=len(art.steps),
                      expected=f"text {art.checkpoint.text!r}", observed=observed,
                      recovered=recovered)

    outputs: dict[str, str] = {}
    for ex in art.extracts:
        outputs[ex.name] = surf.read_row_value(ex.row_label)
    return Result(status=Status.SUCCESS, outputs=outputs, recovered=recovered)
