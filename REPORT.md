# REPORT — Computer-Use Automation

## 1. Architecture

The system is **record-once / replay-many** with the LLM deliberately **outside the production
path**. Three phases, one seam:

```
 goal ─▶ DISCOVERY (LLM drives UI once) ─▶ ARTIFACT (typed capability) ─▶ REPLAY (no LLM, deterministic)
                    │                            ▲                              │
                    └──────── evidence ──────────┘        escalation ◀──────────┘ (stuck → human → resume)
```

Everything above the **Surface** seam speaks *roles, names, checkpoints* — never CSS or pixels — so
the same recorded flow extends from web to legacy-web to desktop by swapping only the Surface
implementation.

**Key decisions and trade-offs.**
- *LLM out of the production path.* The alternative — keep a cheap model in the loop for
  "self-healing" — is worse for this context: the target UI is stable, so per-run model cost,
  added latency, and non-determinism buy nothing. Per-step errors also compound (0.9¹⁰ ≈ 0.35), so
  removing the model from replay is what makes it reliable *and* free. Measured discovery cost was
  **$0.0001** (2-step) and **$0.0004** (6-step) with `gpt-4o-mini`; replay cost is **$0**.
- *Accessibility-tree perception, not screenshots.* On legacy table-based pages with no test-ids,
  the a11y role+name is the most stable identity available and is what a screen-reader-driven human
  operator keys on. A screenshot-stability loop (the Tsenta/fast-apply style) pays vision-token cost
  *and* model latency on every step and every run; the a11y tree is a few hundred characters
  (measured `aria_len` 291–797 here) and needs no model at replay at all.
- *Rules as data.* The allowlist, risky-control list, and discovery tasks live in
  `catalogs/*.yaml`, so a reviewer/auditor reads and changes policy without touching Python.
- *One concrete surface, real depth.* Per the brief, a single vertical slice touching every core
  requirement, with the load-bearing pieces (schema, replay+taxonomy, escalation) done for real,
  surface heterogeneity argued at the seam, and multi-tenant reuse *demonstrated* on a second
  reskinned surface (§4).

## 2. Artifact schema

The artifact (`cua/schema.py`) is the focal point: a typed, versioned, serializable **capability
contract** read by *both* a human reviewer and a calling agent (it exports JSON-Schema via
`Artifact.model_json_schema()` for tool-calling). It is **decoupled from the raw transcript** — the
transcript is evidence in `/evidence`; the artifact is the reusable thing.

Shape and why:
- **`Locator` is an ordered fallback chain**, not one selector: `role+name` → `text` → `css` →
  `coords`. Anchored on the accessible name because it survives markup churn that CSS/xpath do not;
  the lower rungs exist for controls with *no* accessible name (a real case on the fixture). Replay
  records which rung actually resolved, so locator drift is an early warning even while it succeeds.
- **The op set `fill | click | select | navigate` is complete and every variant is exercised
  end-to-end.** This is load-bearing: an earlier version omitted `select`, and the recorder
  *silently dropped* the model's successful select — shipping a capability missing a step. The fix
  is structural, not cosmetic: the recorder now **fails loud** (an unrepresentable action aborts
  discovery), and `select` records **both** `value_param` and `option_label` so replay is
  unambiguous when value ≠ label.
- **Params via canonicalization.** Concrete values the operator typed (a member id, a deposit) are
  turned into params at record time, so the artifact is reusable across inputs/tenants rather than
  frozen to one run. Verified: discovery of member `12345` emitted `params: {member_id}` with the
  fill step bound to `member_id`.
- **`checkpoint`, `extracts`, `business_outcomes`, `recoverables`, `provenance`** make success,
  outputs, expected non-happy results, known transients, and the discovery cost/target all explicit
  and typed.

## 3. Determinism & error handling

**Replay is not re-execution of the discovery run — it is execution of the artifact.** That single
sentence is the design: no LLM, no reasoning, no per-run variability, so identical inputs produce
identical outputs (verified: 3× identical extraction). This is what makes a result auditable and
cheap.

Runtime states are classified into a **result contract**, checked in a deliberate order after the
steps run:
1. **Recoverables** (cleared first, always bounded — never open-ended re-reasoning):
   *interstitial* (dismiss a consent dialog), *transient* (exponential-backoff retry),
   *session-timeout* (re-authenticate, then retry **without reloading** — a reload would drop the
   re-authed session), *slow-load* (a web-first wait, not a fixed sleep).
2. **Business outcomes** — a legitimate non-happy result (`NO_SUCH_MEMBER`, `PERMISSION_DENIED`) is
   **data the caller wants**, returned *before* anything is called a failure. Conflating this with a
   crash is the most common design mistake in this space; the contract keeps them separate.
3. **Checkpoint** — only now is success asserted. A miss within the **configured** timeout is a
   hard failure carrying the *observed* state (e.g. `"Loading..."`), never a bare exception.

Every wait/limit is a **config knob derived from the worst legitimate case**, not a guess. This is
demonstrated, not asserted: the slow-load path succeeds at a 3000 ms timeout and *misfires* at
400 ms — a too-short timeout misclassifies a valid slow load, which is exactly why the timeout is
exposed. **UI drift** (secondary) is surfaced by the rung the locator resolved on: a flow that
starts resolving on rung 3 instead of rung 1 is drifting even while it still passes.

The discovery output is trusted because of the **self-replay gate**: discovery is not "done" until
the emitted artifact **replays once**. An artifact that can't replay itself is nothing. For a flow
whose tail is irreversible (`Confirm Open`), the gate **dry-runs**: it replays the reversible prefix
and asserts the risky control is *reachable and gated*, without firing the side effect. Both
directions are tested — the gate **accepts** a complete 6-step flow and **rejects** a truncated one
missing the select.

## 4. Heterogeneity & multi-tenant

Surface heterogeneity is argued at the seam (per the brief's "design, don't build" scope for §3.7);
multi-tenant reuse is **demonstrated** on a second surface.
- **Other surfaces.** Everything above `Surface` (schema, replay, discovery, result contract) is
  surface-agnostic. `WebSurface` is the built implementation; a `LegacyWebSurface` (e.g. Citrix/HTML
  frames) or `DesktopSurface` (UIA/AX accessibility APIs — the desktop equivalent of the a11y tree,
  with `coords` as the vision fallback) slot in *without touching anything above the seam*. Because
  perception is already role+name+checkpoint, the artifact format needs no change.
- **Multi-tenant reuse (demonstrated).** `target/hostile_tenantB.html` is the *same* vendor product
  reskinned the way a second institution runs it, with `Search` relabelled `Find Member`.
  `cua/reuse.py::specialize(base, overrides)` reuses the tenant-A capability on tenant B by applying
  a one-line control override — no re-discovery. Retargeting is `replay --target ...`; the override
  is `replay --overrides '{"Search":"Find Member"}'`. Both directions are tested
  (`tests/test_tenant.py`): with the override the base artifact **succeeds** on tenant B; *without*
  it, the renamed control is drift that **fails loud** (rung-1 role+name miss → hard failure the
  caller sees), never a silent wrong action — because role+name is an identity match, not fuzzy. So
  per-tenant divergence is either absorbed by a declared override or surfaced as a clear signal to
  add one / re-discover that single flow; it is never a silent break. (A softer rewording that still
  matches a lower locator rung shows up first as a rung *downgrade* recorded on the run — an early
  warning before it ever fails.)

## 5. Escalation & handoff

When replay hits a state with no known recovery, it does **not** guess and does **not** re-reason —
it raises a structured `InterventionRequest` carrying the capability, step, reason, and live page
state, and control transfers to an **operator on the same session**. The operator acts on the very
page the automation was driving (not a fresh copy, which would lose all in-progress state), then
hands control back and automation resumes and verifies. "Stuck" is detected concretely: checkpoint
not reached within the stuck-timeout **and** an unknown blocking dialog present. A `who's-in-control`
token (`automation` ↔ `operator`) governs the transfer, modeled on shipping HITL designs (Cloudflare
Browser Rendering). The remote "live view" transport is a CDP screencast of the same session (proven
buildable during discovery); this module encodes the control protocol and leaves the wire to the
deployment. Verified: with no interstitial recovery configured, automation escalates on the consent
dialog, the operator dismisses it on the same page, control returns, and the balance is read back.

## 6. Safety

Every action — from the discovery LLM *and* from a calling agent — passes through **exactly one
Guard** (`cua/policy/guard.py`). One site on purpose: a guardrail scattered across call sites is a
guardrail with gaps. Three enforcements:
1. **Allowlist** — the op must be permitted and the live URL must be under an allowed prefix (the
   blast-radius fence; automation cannot wander off the sanctioned surface). A breach raises, loud.
2. **Risk gate** — an irreversible/high-impact control (`Confirm Open`, `Transfer`, `Delete`, `Wire`)
   is **refused for automation** and permitted only for a human-confirmed `operator`. Refusal is a
   normal return value, not a crash.
3. **Redaction** — financial PII / secrets (keys, PANs, SSNs) are masked before anything is written
   to evidence; a leak scan of the generated evidence is clean, and a 5-digit member id is *not*
   mistaken for a PAN.

**Limits (stated honestly).** The prompt-injection risk is real — untrusted page text could try to
hijack an agent holding real powers; the architectural mitigations here (least-privilege session,
allowlist, HITL confirm for risky/irreversible acts, redaction) reduce but do not eliminate it. The
redactor is pattern-based (good for known formats, not a DLP system). The URL fence assumes the
sanctioned surface is itself trustworthy.

## 7. Cuts

Deliberately **not** built (and why): Docker (the reviewer wants `clone → run`; a headless-browser
stack in a container adds friction with no upside here); a real operator console (§3.6 says mock the
UI, make the *mechanism* real — we did); a desktop-automation implementation (one surface, design
the extension); queues/clusters/metrics stacks (explicitly anti-rewarded — the logging consumer is
"a reviewer debugging a run," so structured JSONL + a failure screenshot is the whole need);
CAPTCHA/anti-bot defeat (out of scope and irrelevant to a controlled target).

**What I'd build next**, in order: (1) an artifact **version-migration** path for when the schema
evolves; (2) a **re-discovery trigger** wired to sustained locator-rung downgrades (drift → auto
re-record one flow); (3) the `DesktopSurface` behind the existing seam; (4) a richer risk model
(amount thresholds, dual-control) beyond the name allowlist.
