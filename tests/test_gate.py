"""The self-replay gate: an artifact isn't accepted until it replays. It must ACCEPT a complete
flow and REJECT a truncated one (the silent-drop bug class), and must DRY-RUN an irreversible tail
without firing the side effect. Mirrors spikes 7/8."""
from __future__ import annotations

from cua.discovery.agent import _self_replay_gate
from cua.schema import Artifact, Checkpoint, Locator, Step


def test_gate_accepts_complete_flow(surf, guard, subaccount_artifact):
    ok = _self_replay_gate(surf, guard, subaccount_artifact,
                           {"member_id": "12345", "account_type": "Checking", "initial_deposit": "500"})
    assert ok is True


def test_gate_rejects_truncated_flow(surf, guard, subaccount_artifact):
    # drop the 'select' step — exactly the class of silent drop the gate exists to catch
    truncated = subaccount_artifact.model_copy(deep=True)
    truncated.steps = [s for s in truncated.steps if s.op != "select"]
    ok = _self_replay_gate(surf, guard, truncated,
                           {"member_id": "12345", "account_type": "Checking", "initial_deposit": "500"})
    assert ok is False


def test_gate_dry_runs_irreversible_tail(surf, guard, subaccount_artifact):
    # append the risky, irreversible confirm; gate must reach it, prove it's gated, NOT click it
    risky = subaccount_artifact.model_copy(deep=True)
    risky.steps = list(risky.steps) + [
        Step(op="click", target=Locator(role="button", name="Confirm Open"))
    ]
    ok = _self_replay_gate(surf, guard, risky,
                           {"member_id": "12345", "account_type": "Checking", "initial_deposit": "500"})
    assert ok is True
    # side effect ("opened") never fired: we're still on the review screen
    assert surf.find_text("Review Sub-Account") > 0
