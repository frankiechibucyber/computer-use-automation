"""The safety choke point (brief §3.4).

Every action an agent (or the discovery LLM) wants to take passes through exactly one Guard.
Single site on purpose: a guardrail scattered across call sites is a guardrail with gaps. Rules
are DATA (`catalogs/policy.yaml`), not code, so a reviewer can read and change what is allowed
without editing Python — the allowlist is the thing auditors will ask to see.

Three enforcements:
  1. allowlist    — op must be permitted and the URL must be under an allowed prefix.
  2. risk gate    — a risky/irreversible control is refused for `automation` and permitted only
                    for `operator` (human-confirmed). Refusal is a return value, not an exception:
                    a blocked risky action is a normal, expected branch, not a crash.
  3. redaction    — financial PII / secrets are masked before anything is written to evidence.
"""
from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field


class PolicyViolation(Exception):
    """A hard policy breach (op not allowlisted, URL off-domain) — never silently allowed."""


# Redaction patterns live with the guard because redaction is a policy decision, not a util.
# Ordered widest-first; each is anchored to avoid over-masking ordinary ids like member numbers.
_REDACTORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-[A-Za-z0-9\-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED_PAN]"),          # card-like PANs
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
]


def redact(s: str) -> str:
    for pat, repl in _REDACTORS:
        s = pat.sub(repl, s)
    return s


class Policy(BaseModel):
    allowed_ops: set[str] = Field(default_factory=lambda: {"fill", "click", "select", "navigate"})
    allowed_url_prefixes: list[str] = Field(default_factory=list)
    risky_control_names: set[str] = Field(default_factory=set)

    @classmethod
    def from_yaml(cls, path: str) -> "Policy":
        data = yaml.safe_load(open(path)) or {}
        return cls(
            allowed_ops=set(data.get("allowed_ops", [])) or None,
            allowed_url_prefixes=list(data.get("allowed_url_prefixes", [])),
            risky_control_names=set(data.get("risky_control_names", [])),
        )


class Guard:
    """Wraps a Surface. Nothing acts on the surface except through here."""

    def __init__(self, policy: Policy):
        self.policy = policy

    def check(self, op: str, url: str, control_name: str | None,
              controller: str = "automation") -> str | None:
        """Return None if allowed; a block-reason string if refused by the risk gate.

        Raises PolicyViolation on a hard breach (off-allowlist op or URL).
        """
        if op not in self.policy.allowed_ops:
            raise PolicyViolation(f"op {op!r} not in allowlist {sorted(self.policy.allowed_ops)}")
        if self.policy.allowed_url_prefixes and not any(
            url.startswith(p) for p in self.policy.allowed_url_prefixes
        ):
            raise PolicyViolation(f"url off allowlist: {url}")
        is_risky = op == "click" and control_name in self.policy.risky_control_names
        if is_risky and controller != "operator":
            return "risky_requires_confirmation"
        return None
