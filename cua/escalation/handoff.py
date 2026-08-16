"""Human-in-the-loop escalation (brief §3.5).

When replay hits a state it has no recovery for, it does NOT guess and does NOT open-endedly
re-reason (that is how automation causes damage). It raises a structured InterventionRequest
carrying enough context for a human to act — capability, step, reason, and the live page state —
and control transfers to an operator on the SAME session. The operator acts on the very page the
automation was driving (not a fresh copy, which would lose all in-progress state), then hands
control back and automation resumes and verifies.

The transport for "operator sees and clicks" is a CDP screencast of the same session (proven
buildable in the discovery spikes via Page.startScreencast); this module encodes the control
protocol, leaving the wire transport to the deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from ..schema import Artifact, Result, Status
from ..surface.web import WebSurface


class Controller(str, Enum):
    AUTOMATION = "automation"
    OPERATOR = "operator"


@dataclass
class InterventionRequest:
    capability: str
    at_step: int
    reason: str
    state_aria: str
    who_should_control: str = Controller.OPERATOR.value


@dataclass
class EscalationTrace:
    final_controller: Controller = Controller.AUTOMATION
    events: list = field(default_factory=list)
    result: Result | None = None


def replay_with_escalation(
    surf: WebSurface,
    art: Artifact,
    params: dict[str, str],
    operator_handler: Callable[[WebSurface, InterventionRequest], None],
    *,
    stuck_timeout_ms: int = 1000,
) -> EscalationTrace:
    """Run the recorded steps; if the checkpoint is not reached and an unknown blocking dialog is
    present, escalate to the operator on the same page, then resume and verify.

    `operator_handler` is what a human (or a test) does with control — it acts on `surf.page`
    directly. In production this is driven by the live operator through the screencast."""
    trace = EscalationTrace()
    if art.provenance and art.provenance.target:
        surf.goto(art.provenance.target)
    for step in art.steps:
        value = params.get(step.value_param) if step.value_param else None
        surf.act(step.op, step.target, value=value, option_label=step.option_label)

    if not surf.wait_for_text(art.checkpoint.text, stuck_timeout_ms):
        if surf.page.get_by_role("dialog").count():
            req = InterventionRequest(
                capability=art.name, at_step=len(art.steps),
                reason="unexpected blocking dialog, no known recovery",
                state_aria=surf.page.get_by_role("dialog").aria_snapshot(),
            )
            trace.events.append(("intervention_request", req))
            trace.final_controller = Controller.OPERATOR
            operator_handler(surf, req)                       # operator acts on the SAME page
            trace.events.append(("operator_acted", req.capability))
            trace.final_controller = Controller.AUTOMATION    # hand back
            trace.events.append(("control_returned", Controller.AUTOMATION.value))

    if surf.wait_for_text(art.checkpoint.text, stuck_timeout_ms):
        outputs = {ex.name: surf.read_row_value(ex.row_label) for ex in art.extracts}
        trace.result = Result(status=Status.SUCCESS, outputs=outputs)
    else:
        trace.result = Result(status=Status.HARD_FAILURE, expected=art.checkpoint.text,
                              observed="checkpoint not reached after escalation")
    return trace
