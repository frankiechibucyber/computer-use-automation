"""Same-session human-in-the-loop: automation gets stuck on an unknown blocking dialog, escalates,
an operator acts on the SAME live page, control returns, automation resumes and verifies.
Mirrors spike 2(C). Here the lookup artifact has NO interstitial recoverable configured, so the
consent dialog forces a genuine escalation rather than an automatic recovery."""
from __future__ import annotations

from cua.escalation.handoff import Controller, replay_with_escalation
from cua.schema import (Artifact, BusinessOutcome, Checkpoint, Extract, Locator, Provenance, Step)


def _bare_lookup(target_url: str) -> Artifact:
    return Artifact(
        name="lookup_no_recovery",
        params={"member_id": "string"},
        steps=[
            Step(op="fill", target=Locator(role="textbox", name="Member ID"), value_param="member_id"),
            Step(op="click", target=Locator(role="button", name="Search")),
        ],
        extracts=[Extract(name="savings_balance", row_label="Savings Balance")],
        checkpoint=Checkpoint(text="Savings Balance"),
        provenance=Provenance(discovered_at="t", model="t", target=target_url),
    )


def test_same_session_operator_takeover(surf, target_url):
    art = _bare_lookup(target_url)

    def operator(s, req):                      # the human dismisses the consent on the same page
        s.click_button("Continue")

    trace = replay_with_escalation(surf, art, {"member_id": "55555"}, operator)
    assert trace.final_controller == Controller.AUTOMATION
    assert trace.result.status.value == "success"
    assert trace.result.outputs["savings_balance"] == "$1,000.00"
    assert any(e[0] == "operator_acted" for e in trace.events)
