"""Cross-tenant reuse — specialize one base capability for a tenant variant (brief §3.7, §8).

Hundreds of tenants run the same vendor product, reskinned and rebranded. Re-discovering the same
flow per tenant is the brittle, doesn't-scale path the brief warns against. Instead the SAME base
artifact is reused, and where a tenant renames a control the difference is a small, declared
OVERRIDE — data, not a new recording.

`specialize(base, overrides)` returns a new Artifact with the human-visible control identifiers
remapped old -> new. What stays identical (the ordered steps, params, outcomes, provenance) is the
shared capability; what changes is only the per-tenant naming. This is the reuse seam REPORT §4
describes, made concrete.

Drift that ISN'T overridden stays loud, never silent: the locator chain fails to resolve on rung 1
(role+name) and either drops to a weaker rung — an early warning the run records — or misses
entirely and the caller gets a hard failure. A renamed control never resolves to the *wrong*
control, because role+name is an identity match, not a fuzzy one.
"""
from __future__ import annotations

from .schema import Artifact


def specialize(base: Artifact, control_overrides: dict[str, str]) -> Artifact:
    """Return a per-tenant copy of `base` with control names/labels remapped by `control_overrides`.

    The mapping is applied to every place a human-visible identifier appears — step targets, select
    option labels, the checkpoint, extract row labels, and recovery/outcome detectors — so a rebrand
    that renames a label in one place is handled in one place.
    """
    art = base.model_copy(deep=True)
    m = control_overrides
    for step in art.steps:
        if step.target.name in m:
            step.target.name = m[step.target.name]
        if step.target.text in m:
            step.target.text = m[step.target.text]
        if step.option_label in m:
            step.option_label = m[step.option_label]
    if art.checkpoint.text in m:
        art.checkpoint.text = m[art.checkpoint.text]
    for ex in art.extracts:
        if ex.row_label in m:
            ex.row_label = m[ex.row_label]
    for rec in art.recoverables:
        if rec.action in m:
            rec.action = m[rec.action]
        if rec.detect in m:
            rec.detect = m[rec.detect]
    for bo in art.business_outcomes:
        if bo.detect_alert_text in m:
            bo.detect_alert_text = m[bo.detect_alert_text]
    return art
