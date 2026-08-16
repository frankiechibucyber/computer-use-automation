"""Cross-tenant reuse (brief §3.7, §8).

The SAME base capability, discovered on tenant A, is applied to a reskinned tenant-B surface that
renamed "Search" to "Find Member". Two things are proven:
  - without an override, the renamed control is per-tenant drift and replay fails LOUD (a hard
    failure the caller sees), never a silent wrong action;
  - with one declared override the base artifact is reused as-is — no re-discovery.
"""
from __future__ import annotations

from cua.replay.engine import replay
from cua.reuse import specialize
from cua.schema import Status


def test_tenant_b_drifts_without_override(surf, lookup_artifact, tenant_b_url):
    lookup_artifact.provenance.target = tenant_b_url
    res = replay(surf, lookup_artifact, {"member_id": "12345"})
    assert res.status is Status.HARD_FAILURE          # renamed control -> locator miss, surfaced
    assert res.observed == "locator miss"


def test_tenant_b_reused_with_override(surf, lookup_artifact, tenant_b_url):
    art = specialize(lookup_artifact, {"Search": "Find Member"})
    art.provenance.target = tenant_b_url
    res = replay(surf, art, {"member_id": "12345"})
    assert res.status is Status.SUCCESS               # one override reuses the capability, no re-record
    assert res.outputs["savings_balance"] == "$4,210.55"


def test_specialize_does_not_mutate_base(lookup_artifact):
    specialize(lookup_artifact, {"Search": "Find Member"})
    assert lookup_artifact.steps[1].target.name == "Search"   # base capability is left intact
