"""Shared fixtures. The target is the local legacy fixture, addressed as a file:// URL derived
from the repo root — no absolute path is hardcoded anywhere (R027)."""
from __future__ import annotations

import pathlib

import pytest

from cua.policy.guard import Guard, Policy
from cua.schema import (Artifact, BusinessOutcome, Checkpoint, Extract, Locator,
                        Provenance, Recoverable, Step)
from cua.surface.web import WebSurface

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET_URL = (ROOT / "target" / "hostile.html").as_uri()


@pytest.fixture(scope="session")
def target_url() -> str:
    return TARGET_URL


@pytest.fixture
def surf():
    s = WebSurface(headless=True)
    yield s
    s.close()


@pytest.fixture
def guard() -> Guard:
    pol = Policy.from_yaml(str(ROOT / "catalogs" / "policy.yaml"))
    pol.allowed_url_prefixes = [TARGET_URL.rsplit("/", 1)[0]]
    return Guard(pol)


def _prov() -> Provenance:
    return Provenance(discovered_at="test", model="test", target=TARGET_URL)


@pytest.fixture
def lookup_artifact() -> Artifact:
    return Artifact(
        name="lookup_member_savings_balance",
        params={"member_id": "string"},
        steps=[
            Step(op="fill", target=Locator(role="textbox", name="Member ID"), value_param="member_id"),
            Step(op="click", target=Locator(role="button", name="Search")),
        ],
        extracts=[Extract(name="savings_balance", row_label="Savings Balance")],
        checkpoint=Checkpoint(text="Savings Balance"),
        business_outcomes=[
            BusinessOutcome(code="NO_SUCH_MEMBER", detect_alert_text="Record not found"),
            BusinessOutcome(code="PERMISSION_DENIED", detect_alert_text="Permission denied"),
        ],
        recoverables=[
            Recoverable(kind="interstitial", detect="Confirm you have consent", action="Continue"),
            Recoverable(kind="transient", detect="Temporarily unavailable", max_retries=3),
            Recoverable(kind="session_timeout", detect="Session expired",
                        action="Re-authenticate", no_reload=True),
        ],
        provenance=_prov(),
    )


@pytest.fixture
def subaccount_artifact() -> Artifact:
    return Artifact(
        name="open_sub_account",
        params={"member_id": "string", "account_type": "string", "initial_deposit": "string"},
        steps=[
            Step(op="fill", target=Locator(role="textbox", name="Member ID"), value_param="member_id"),
            Step(op="click", target=Locator(role="button", name="Search")),
            Step(op="click", target=Locator(role="button", name="Open Sub-Account")),
            Step(op="select", target=Locator(role="combobox", name="Account Type"),
                 value_param="account_type", option_label="Checking"),
            Step(op="fill", target=Locator(role="textbox", name="Initial Deposit"),
                 value_param="initial_deposit"),
            Step(op="click", target=Locator(role="button", name="Review")),
        ],
        extracts=[],
        checkpoint=Checkpoint(text="Review Sub-Account"),
        provenance=_prov(),
    )
