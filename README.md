# CUA — Computer-Use Automation

Banks run a long tail of old back-office apps that have no API — the only way in is to drive the
screen the way a human operator would. This is my system for that case. An LLM works out how to
accomplish a plain-English goal by driving the live UI once; I capture that successful run as a
reusable recording that takes inputs (like a member ID) and returns typed results; and from then on
I replay the recording with **no model in the loop** — same inputs, same steps, same result. That
makes it cheap to run and easy to audit, because nothing is being re-decided each time.

A person can step in mid-run: if the automation gets stuck, it hands control of the *same* live
session to a human, who finishes the step and hands control back.

Put simply: the model works the flow out once, that recording becomes a reusable capability, and
replaying it is how an agent runs it later — no model needed the second time.

See [`REPORT.md`](REPORT.md) for the architecture, why I shaped the recording's schema the way I did,
how I handle runtime errors, and what I deliberately left out. Real, redacted logs from a discovery
run and a replay run are in [`/evidence`](evidence).

---

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env      # then put your key in .env (or export it)
export OPENROUTER_KEY=sk-or-...
```

Only discovery needs a key. Replay never calls the model, so it needs none.

## Run the end-to-end flow

The target is a local legacy page ([`target/hostile.html`](target/hostile.html)); pass it as a
`file://` URL so nothing tied to my machine is baked in.

```bash
TARGET="file://$(pwd)/target/hostile.html"

# 1) DISCOVER — the LLM drives the page once and saves a recording that checks itself
python -m cua.cli discover lookup_member_savings_balance --target "$TARGET"

# 2) CATALOG — list what an agent can now invoke by name
python -m cua.cli catalog

# 3) REPLAY — deterministic, no model. A normal lookup, then one that is denied.
#    --evidence appends a redacted replay log to evidence/<capability>.replay.jsonl
python -m cua.cli replay lookup_member_savings_balance --params '{"member_id":"12345"}' --evidence
python -m cua.cli replay lookup_member_savings_balance --params '{"member_id":"99999"}' --evidence  # permission denied

# A longer, 6-step flow with a dropdown and an irreversible final step:
python -m cua.cli discover open_sub_account --target "$TARGET"
python -m cua.cli replay  open_sub_account --params '{"member_id":"12345","account_type":"Checking","initial_deposit":"500"}'
```

A successful replay prints a JSON result — the status plus the values it read back, e.g.
`{"status": "success", "outputs": {"savings_balance": "$4,210.55"}}`. A denied lookup instead prints
`{"status": "business_outcome", "outcome_code": "PERMISSION_DENIED"}` — a real answer the caller
needs, not a crash.

`/evidence/` then holds logs from **both** a discovery run (`*.transcript.jsonl`, `*.artifact.json`,
`*.run.json`, `*.final.png`) and a replay run (`*.replay.jsonl`, with one success line and one
error-state line, plus a screenshot per outcome).

## Tests

```bash
pytest -q      # runs against a real browser; no API key needed
```

The suite covers the three results a replay can return (success, a known business outcome, or a hard
failure), replay repeatability, and every recoverable condition (consent dialog, transient error,
session timeout, slow load). It also checks the locator fallbacks (the ordered ways it finds a
control if the first no longer matches), the one place every action is checked plus redaction
(hiding sensitive data like account numbers), the check that a recording can replay itself before I
trust it (and that it rejects an incomplete one), and the same-session human takeover.

---

## Layout

```
cua/
  schema.py          the recording's shape (the part I designed most carefully) and the result it returns
  surface/           how we read and act on a screen: base.py (the interface),
                     web.py (Playwright; reads the accessibility tree — the screen-reader view — first)
  policy/            guard.py — the one place every action is checked: allowlist, risky-action gate, redaction
  replay/            engine.py — runs a recording with no model; handles recoverable conditions; timeouts are configurable
  llm/               client.py — talks to the model; used only during discovery
  discovery/         agent.py — the record-once loop; stops loudly rather than dropping a step;
                     turns the concrete values typed during discovery into named inputs; replays its own output before saving it
  escalation/        handoff.py — who's in control, the structured "I'm stuck" request, and same-session takeover
  evidence/          writer.py — redacted logs, the saved recording, a cost summary, and screenshots
  cli.py             discover / replay / catalog
catalogs/
  policy.yaml        allowlist and risky-action names (data a reviewer can read and edit)
  tasks.yaml         discovery jobs (the goal plus its typed inputs and outputs) as data
  capabilities/      saved recordings land here (generated; git-ignored)
target/hostile.html  the deliberately messy legacy page I test against
tests/               pytest suite
evidence/            example discovery and replay logs (generated; git-ignored)
```
