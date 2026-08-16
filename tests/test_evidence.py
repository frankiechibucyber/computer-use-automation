"""Evidence writer: a replay run must be persisted as a redacted log line, and sensitive param
values must be masked before they hit disk. Guards the §6 "logs from a replay run" requirement
and the §3.4 "never persist raw sensitive data" requirement together."""
from __future__ import annotations

import json

from cua.evidence.writer import EvidenceWriter
from cua.replay.engine import replay
from cua.schema import Status


def test_replay_log_written_and_appended(surf, lookup_artifact, tmp_path):
    w = EvidenceWriter(str(tmp_path))
    r1 = replay(surf, lookup_artifact, {"member_id": "12345"})
    w.write_replay(lookup_artifact, {"member_id": "12345"}, r1, "lookup", screenshot_surface=surf)
    r2 = replay(surf, lookup_artifact, {"member_id": "99999"})
    w.write_replay(lookup_artifact, {"member_id": "99999"}, r2, "lookup", screenshot_surface=surf)

    lines = (tmp_path / "lookup.replay.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2                                  # append, not overwrite
    recs = [json.loads(x) for x in lines]
    assert recs[0]["result"]["status"] == "success"
    assert recs[1]["result"]["outcome_code"] == "PERMISSION_DENIED"
    assert recs[0]["executed_steps"][0]["op"] == "fill"     # the replay log records what ran


def test_replay_log_redacts_sensitive_params(surf, lookup_artifact, tmp_path):
    w = EvidenceWriter(str(tmp_path))
    # a param carrying a card-like PAN must never land raw in evidence
    r = replay(surf, lookup_artifact, {"member_id": "00001"})
    w.write_replay(lookup_artifact, {"member_id": "4111111111111111"}, r, "lookup")
    body = (tmp_path / "lookup.replay.jsonl").read_text()
    assert "4111111111111111" not in body and "[REDACTED_PAN]" in body
