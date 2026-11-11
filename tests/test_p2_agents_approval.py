"""The lead's approval of the agent arm's live pilot (``configs/workflows/p2_live_approval.yaml``).

The lead's words of 2026-11-11, "merge 50, approve the pilot, and match", relayed by the
coordinator at 00:58 and 08:58 UTC. These tests pin the committed record and show
:func:`tools.p2_live.require_live_approval` accepts exactly it against the committed agent
configuration and refuses what it must: the previous agent freeze, other caps, a tampered
digest, the procedural configuration, a run it does not list, another store. Each refusal
has the committed record as its control. The git-cleanliness check is tested on its own
(``tests/test_p2_live.py``) and is stood down here, since a branch under review is not
``main``. **No test here reaches a model**: the record is read and checked, nothing runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.p2_power import H4_CELLS, H4_REPLICATES
from tests.test_p2_agents_freeze import COMMITTED_AGENT_CONFIG_SHA256, COMMITTED_AGENT_FROZEN_SHA256
from tests.test_p2_live import COMMITTED_FROZEN_SHA256
from tools import p2_live
from tools.workflow_config import load_p2

REPO = Path(__file__).resolve().parents[1]
PREVIOUS_AGENT_FROZEN_SHA256 = "b02f19c73d09794ad8edf7317c55b3b4731de1b3227281cd23d51f2bc01d95ba"
"""The agent record of 2026-11-08, before the lead's "match": an approval naming it is refused."""
COMMITTED_APPROVAL_DIGEST = "67422d5b0e5cd8d3cb0286b50f947bb7b3588e58a32ed4273ad2df72335374a1"
"""The committed record's own digest (``approval_digest``)."""
H4_RUNS = [
    {"scenario": s, "plant": p, "tier": t, "replicate": r}
    for s, p, t in H4_CELLS
    for r in H4_REPLICATES
]


COMMITTED_APPROVAL = REPO / "configs" / "workflows" / "p2_live_approval.yaml"


def _committed() -> dict[str, Any]:
    """The committed record, read from its path in the tree whatever the check points at."""
    return yaml.safe_load(COMMITTED_APPROVAL.read_text(encoding="utf-8"))


@pytest.fixture
def clean_tree(monkeypatch):
    """The record as if pushed on a clean tree (the real check is tested on its own)."""
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (True, ""))


@pytest.fixture
def record_at(tmp_path, monkeypatch, clean_tree):
    """Write a record to a temporary approval path and point the check at it."""
    path = tmp_path / "p2_live_approval.yaml"
    monkeypatch.setattr(p2_live, "APPROVAL_FILE", path)

    def write(record: dict[str, Any]) -> dict[str, Any]:
        path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
        return record

    return write


def test_the_committed_record_names_the_pilot_the_lead_approved():
    arm = load_p2(p2_live.COMMITTED_P2_AGENTS)
    rec = _committed()
    assert sorted(rec) == sorted([*p2_live.APPROVAL_FIELDS, "digest"])
    assert rec["ruling_date"] == "2026-11-11"
    assert '"merge 50, approve the pilot, and match"' in rec["word"]  # the lead's words
    assert "00:58 UTC" in rec["word"] and "08:58 UTC" in rec["word"]  # the relays
    assert arm.model.model_id == "gpt-5.6-luna" and "gpt-5.6-luna" in rec["word"]
    assert rec["runs"] == H4_RUNS and len(rec["runs"]) == 8
    assert rec["caps"] == p2_live.run_caps(arm).model_dump(mode="json")
    assert rec["caps"] == {
        "max_requests": 240,
        "max_total_tokens": 14000000,
        "max_usd": 1.0,
        "input_chars_per_token": 2.0,
    }
    # the total is the proposers' and the verifier's caps added, as configured
    assert arm.agents.caps.max_usd == 0.5 and arm.agents.verifier_caps.max_usd == 0.5
    assert arm.agents.caps.max_requests == 200 and arm.agents.verifier_caps.max_requests == 40
    assert (
        rec["frozen_sha256"] == p2_live.frozen_record_sha256(arm) == COMMITTED_AGENT_FROZEN_SHA256
    )
    assert rec["config_sha256"] == p2_live.config_digest(arm) == COMMITTED_AGENT_CONFIG_SHA256
    assert rec["frozen_sha256"] != PREVIOUS_AGENT_FROZEN_SHA256
    assert rec["runs_root"] == "/home/user/p2_agents_pilot_store/runs"
    assert not (REPO / "runs").exists() or REPO not in Path(rec["runs_root"]).parents
    assert p2_live.approval_digest(rec) == rec["digest"] == COMMITTED_APPROVAL_DIGEST


def test_the_committed_record_is_accepted_for_every_approved_run(clean_tree):
    arm = load_p2(p2_live.COMMITTED_P2_AGENTS)
    assert p2_live.require_live_approval(arm)["digest"] == COMMITTED_APPROVAL_DIGEST
    for cell in H4_RUNS:
        got = p2_live.require_live_approval(
            arm, cell, runs_root=Path("/home/user/p2_agents_pilot_store/runs")
        )
        assert got["digest"] == COMMITTED_APPROVAL_DIGEST
    # the negative controls: a run it does not list, and another store
    with pytest.raises(ValueError, match="does not list this run"):
        p2_live.require_live_approval(arm, {**H4_RUNS[0], "replicate": 2})
    with pytest.raises(ValueError, match="does not list this run"):
        p2_live.require_live_approval(
            arm, {"scenario": "S0-01", "plant": "B", "tier": "B", "replicate": 0}
        )
    with pytest.raises(ValueError, match="another run store"):
        p2_live.require_live_approval(arm, H4_RUNS[0], runs_root=Path("/home/user/other/runs"))


def test_a_record_naming_the_previous_agent_freeze_is_refused(record_at):
    arm = load_p2(p2_live.COMMITTED_P2_AGENTS)
    rec = _committed()
    record_at(rec)
    assert p2_live.require_live_approval(arm)["digest"] == rec["digest"]  # the control
    stale = {**rec, "frozen_sha256": PREVIOUS_AGENT_FROZEN_SHA256}
    stale["digest"] = p2_live.approval_digest(stale)  # re-digested: the freeze alone differs
    record_at(stale)
    with pytest.raises(ValueError, match="another freeze"):
        p2_live.require_live_approval(arm)
    # and the procedural freeze, which the archived record names, is refused for the arm
    older = {**rec, "frozen_sha256": COMMITTED_FROZEN_SHA256}
    older["digest"] = p2_live.approval_digest(older)
    record_at(older)
    with pytest.raises(ValueError, match="another freeze"):
        p2_live.require_live_approval(arm)


def test_a_record_naming_other_caps_is_refused(record_at):
    arm = load_p2(p2_live.COMMITTED_P2_AGENTS)
    rec = _committed()
    record_at(rec)
    assert p2_live.require_live_approval(arm)["digest"] == rec["digest"]  # the control
    for caps in (
        arm.agents.caps.model_dump(mode="json"),  # the proposers' alone
        arm.agents.verifier_caps.model_dump(mode="json") | {"input_chars_per_token": 2.0},
        load_p2().caps.model_dump(mode="json"),  # p2.yaml's
        {**rec["caps"], "max_usd": 2.0},
    ):
        other = {**rec, "caps": caps}
        other["digest"] = p2_live.approval_digest(other)
        record_at(other)
        with pytest.raises(ValueError, match="other caps"):
            p2_live.require_live_approval(arm)


def test_a_tampered_record_is_refused_on_its_digest(record_at):
    arm = load_p2(p2_live.COMMITTED_P2_AGENTS)
    rec = _committed()
    record_at(rec)
    assert p2_live.require_live_approval(arm)["digest"] == rec["digest"]  # the control
    for edit in (
        {"word": rec["word"] + " and more"},
        {"runs": [*rec["runs"], {"scenario": "S0-01", "plant": "B", "tier": "B", "replicate": 0}]},
        {"caps": {**rec["caps"], "max_usd": 5.0}},
        {"runs_root": "/home/user/other/runs"},
        {"ruling_date": "2026-11-12"},
    ):
        record_at({**rec, **edit})  # the digest left as it was
        with pytest.raises(ValueError, match="digest"):
            p2_live.require_live_approval(arm)


def test_the_agent_record_is_refused_for_the_procedural_configuration(clean_tree):
    with pytest.raises(ValueError, match=r"other caps|another freeze|another configuration"):
        p2_live.require_live_approval(load_p2())
