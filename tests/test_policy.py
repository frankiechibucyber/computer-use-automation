"""The safety choke point: allowlist, URL fence, risk gate, and redaction. Mirrors spikes 3/4."""
from __future__ import annotations

import pytest

from cua.policy.guard import PolicyViolation, redact


def test_off_allowlist_op_blocked_loud(guard, target_url):
    with pytest.raises(PolicyViolation):
        guard.check("drag", target_url, None)


def test_url_off_allowlist_blocked_loud(guard):
    with pytest.raises(PolicyViolation):
        guard.check("click", "http://evil.example/x", "Search")


def test_risky_action_gated_for_automation(guard, target_url):
    assert guard.check("click", target_url, "Confirm Open") == "risky_requires_confirmation"


def test_risky_action_allowed_for_operator(guard, target_url):
    assert guard.check("click", target_url, "Confirm Open", controller="operator") is None


def test_ordinary_action_allowed(guard, target_url):
    assert guard.check("fill", target_url, "Member ID") is None


def test_redaction_masks_secrets_and_pii():
    s = redact("token sk-or-v1-DEADBEEF01234567 card 4111111111111111 ssn 123-45-6789")
    assert "sk-or" not in s and "4111111111111111" not in s and "123-45-6789" not in s


def test_redaction_keeps_member_ids():
    # a 5-digit member id must NOT be mistaken for a PAN
    assert redact("member 12345") == "member 12345"
