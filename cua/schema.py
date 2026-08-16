"""The artifact schema — the focal point of the system (brief §3.2).

An Artifact is a typed, versioned, serializable *capability contract*: what a calling agent
supplies (params), what steps run, how each control is located (a robustness-ordered fallback
chain, not a single brittle selector), what it returns (extracts), and how we know it worked
(checkpoint). It is decoupled from the raw model transcript on purpose — the transcript is
evidence; the artifact is the reusable thing.

Both a human reviewer and a calling agent read this, so it is pydantic (typed + validated) and
exports JSON-Schema (`Artifact.model_json_schema()`) for agent tool-calling.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Locator(BaseModel):
    """Ordered fallback chain — replay tries strategies top to bottom until one resolves.

    Anchored on the accessibility tree (role + name) because legacy bank apps have no stable
    selectors or test-ids; the accessible name survives markup churn that CSS/xpath do not.
    `text`/`css`/`coords` are lower rungs for controls with no accessible name (a real case on
    hostile surfaces — see the reviewer note in REPORT §3). `coords` is the vision fallback,
    used only on surfaces with no DOM at all.
    """

    role: str | None = None
    name: str | None = None
    text: str | None = None
    css: str | None = None
    coords: tuple[int, int] | None = None


# The op set is complete and every variant is exercised end-to-end (see tests). A recorder that
# silently drops an op it can't represent ships a capability that fails on replay — the op set
# must fail loud, not drop (this exact bug was caught during discovery of the multi-field flow).
Op = Literal["fill", "click", "select", "navigate"]


class Step(BaseModel):
    op: Op
    target: Locator
    value_param: str | None = None      # name of the param whose value is typed/selected/navigated
    option_label: str | None = None     # for `select`: the visible option label; recorded alongside
                                        # value_param so replay is unambiguous when value != label


class Extract(BaseModel):
    """A typed output the calling agent gets back."""

    name: str
    row_label: str                      # read the cell in the row whose first cell == row_label


class Checkpoint(BaseModel):
    """The success condition, asserted before returning — never assume a click worked."""

    kind: Literal["text_visible"] = "text_visible"
    text: str


class BusinessOutcome(BaseModel):
    """A legitimate non-happy result the caller needs to know about (e.g. "no such member").

    This is data, not a crash — conflating the two is the most common design mistake here.
    The capability, not the caller, knows what each outcome looks like.
    """

    code: str
    detect_alert_text: str              # substring of a role=alert that signals this outcome


class Recoverable(BaseModel):
    """A transient/known interstitial condition replay clears without escalating.

    `action` is an optional button to click (dismiss a dialog / re-authenticate); `no_reload`
    means the retry re-issues the recorded steps WITHOUT navigating (re-auth persists via the
    session — a full reload would drop it).
    """

    kind: str                           # "interstitial" | "transient" | "session_timeout" | "slow_load"
    detect: str                         # text that signals this condition
    action: str | None = None           # button name to click to recover, if any
    max_retries: int = 2
    no_reload: bool = False


class Provenance(BaseModel):
    """Links the artifact to its evidence and records the measured discovery cost.

    Deliberately does NOT embed the transcript — it references it (§3.2 decoupling).
    """

    discovered_at: str
    model: str
    target: str
    transcript_ref: str | None = None
    cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Artifact(BaseModel):
    """A reusable, reviewable, parameterized capability."""

    schema_version: str = "0.1"
    name: str
    description: str | None = None
    params: dict[str, str] = Field(default_factory=dict)   # param name -> type
    steps: list[Step]
    extracts: list[Extract] = Field(default_factory=list)
    checkpoint: Checkpoint
    business_outcomes: list[BusinessOutcome] = Field(default_factory=list)
    recoverables: list[Recoverable] = Field(default_factory=list)
    provenance: Provenance | None = None


# ---------- Result contract (what replay returns to the caller) ----------
class Status(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    HARD_FAILURE = "hard_failure"
    # `recoverable` is not a terminal status — it is handled inside replay and either resolves
    # (→ success/business_outcome) or exhausts (→ hard_failure / escalation).


class Result(BaseModel):
    status: Status
    outputs: dict[str, str] = Field(default_factory=dict)
    outcome_code: str | None = None
    error_step: int | None = None
    expected: str | None = None
    observed: str | None = None
    recovered: list[str] = Field(default_factory=list)   # trace of recoverable conditions cleared
