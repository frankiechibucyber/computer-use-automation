"""The artifact schema is the focal point, so its contract is tested directly:
round-trip losslessness, agent-callable JSON-Schema export, and op-set completeness."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from cua.schema import Artifact, Checkpoint, Locator, Step


def test_roundtrip_lossless(lookup_artifact):
    js = lookup_artifact.model_dump_json()
    assert Artifact.model_validate_json(js) == lookup_artifact


def test_json_schema_exports_for_agent_tool_calling():
    js = Artifact.model_json_schema()
    props = js["properties"]
    for key in ("name", "params", "steps", "checkpoint"):
        assert key in props


@pytest.mark.parametrize("op", ["fill", "click", "select", "navigate"])
def test_op_set_complete(op):
    Step(op=op, target=Locator(role="button", name="x"))   # must not raise


def test_unknown_op_rejected_loud():
    with pytest.raises(ValidationError):
        Step(op="drag", target=Locator(role="button", name="x"))
