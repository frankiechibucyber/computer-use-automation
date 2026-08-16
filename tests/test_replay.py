"""Deterministic replay — the production path. Covers the 3-way result contract, determinism,
every recoverable condition, and the two hard-failure shapes. Mirrors spikes 1/2/5/6."""
from __future__ import annotations

from cua.replay.engine import ReplayConfig, replay
from cua.schema import Status


def test_success_and_extract(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "12345"})
    assert r.status == Status.SUCCESS
    assert r.outputs["savings_balance"] == "$4,210.55"


def test_business_outcome_not_found(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "00001"})
    assert r.status == Status.BUSINESS_OUTCOME and r.outcome_code == "NO_SUCH_MEMBER"


def test_business_outcome_denied(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "99999"})
    assert r.status == Status.BUSINESS_OUTCOME and r.outcome_code == "PERMISSION_DENIED"


def test_determinism(surf, lookup_artifact):
    outs = [replay(surf, lookup_artifact, {"member_id": "12345"}).outputs for _ in range(3)]
    assert all(o == outs[0] for o in outs)


def test_recoverable_interstitial(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "55555"})
    assert r.status == Status.SUCCESS and r.outputs["savings_balance"] == "$1,000.00"
    assert any("interstitial" in x for x in r.recovered)


def test_recoverable_transient_retry(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "77777"})
    assert r.status == Status.SUCCESS and r.outputs["savings_balance"] == "$2,718.28"
    assert any("transient" in x for x in r.recovered)


def test_recoverable_session_timeout(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "88888"})
    assert r.status == Status.SUCCESS and r.outputs["savings_balance"] == "$9,999.99"
    assert any("session_timeout" in x for x in r.recovered)


def test_slow_load_resolved_by_web_first_wait(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "66666"},
               ReplayConfig(checkpoint_timeout_ms=3000))
    assert r.status == Status.SUCCESS and r.outputs["savings_balance"] == "$3,141.59"


def test_slow_load_misfires_when_timeout_too_short(surf, lookup_artifact):
    # justifies the configurable timeout: a too-short one misclassifies a valid slow load
    r = replay(surf, lookup_artifact, {"member_id": "66666"},
               ReplayConfig(checkpoint_timeout_ms=400))
    assert r.status == Status.HARD_FAILURE


def test_hard_timeout_carries_observed_state(surf, lookup_artifact):
    r = replay(surf, lookup_artifact, {"member_id": "00000"},
               ReplayConfig(checkpoint_timeout_ms=1500))
    assert r.status == Status.HARD_FAILURE and r.observed == "Loading..."
