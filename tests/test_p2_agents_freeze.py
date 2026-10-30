"""The agent arm's own frozen record (``docs/p2_agents_design.md`` §6).

The lead's word of 2026-10-30 ("Yes to all three"): the record is cut first, with the
prompts as they stand after PR #43. ``p2_agents.yaml``'s ``agents.frozen`` names each
role's prompt, the message and finding schemas, each role's tool specifications, the
allow-list, the turn budgets, the round limit, the projection rule and the caps;
:func:`tools.p2_live.check_p2_agents_frozen` recomputes every item before every run of the
arm (through :func:`check_p2_frozen`, which the frozen runner calls) and refuses the run on
any difference. Each frozen item has its test and its control here; the procedural freeze,
its digest and the pilot's approval are unchanged.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.test_p2_agents_harness import AGENTS_YAML, PILOT_CONFIG_SHA256
from tests.test_p2_live import COMMITTED_FROZEN_SHA256, _edit_yaml
from tools import p2_live
from tools.p2_live import (
    AGENT_FROZEN_SCHEMAS,
    agent_frozen_digests,
    check_p2_agents_frozen,
    check_p2_frozen,
    frozen_record_sha256,
)
from tools.workflow_config import load_p1, load_p2, sandbox_config
from workflows.p2_multi_agent import agents, messages

REPO = Path(__file__).resolve().parents[1]
COMMITTED_AGENT_FROZEN_SHA256 = "2089b2e2f6378b8b3bd88bab3431ff1bf483afe209da329d2a1c4f27885ba77b"
"""The digest of both committed records an approval of the agent arm names (the procedural
``frozen`` and ``agents.frozen``): a new agent freeze edits it, the procedural one stands."""
ROLES = ("data_quality", "influent", "identifiability", "calibration", "design", "verification")


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / "workflows"
    shutil.copytree(REPO / "configs" / "workflows", dest)
    return dest / "p2_agents.yaml"


def test_the_committed_record_passes_and_freezes_every_item_the_design_names():
    arm = load_p2(AGENTS_YAML)
    procedural = check_p2_frozen(arm)  # the procedural record, checked first, as before
    assert procedural.date == "2026-10-19"
    record = check_p2_agents_frozen(arm)
    assert record.date == "2026-10-30" and "Yes to all three" in record.word
    assert "01d78ac" in record.word  # the prompts as they stand after PR #43
    for part in (record.prompts_sha256, record.tools_sha256, record.allow_list, record.turns):
        assert set(part) == set(ROLES)
    assert set(record.schemas_sha256) == set(AGENT_FROZEN_SCHEMAS)
    assert len(AGENT_FROZEN_SCHEMAS) == 12
    assert all(hasattr(messages, name) for name in AGENT_FROZEN_SCHEMAS)
    assert record.rounds == 2 and record.turns["verification"] == 14
    assert record.allow_list == {r: tuple(s.tools) for r, s in arm.agents.roles.items()}
    assert record.projection.max_points == 200 and record.projection.preview == 12
    assert record.model == load_p1().model == arm.model  # decision d
    assert record.caps == arm.agents.caps and record.verifier_caps == arm.agents.verifier_caps
    assert record.verifier_budget == arm.agents.verifier_budget
    assert record == arm.agents.frozen
    # the record is what the code recomputes now
    now = agent_frozen_digests(arm)
    for key, value in now.items():
        recorded = getattr(record, key)
        recorded = recorded.model_dump(mode="json") if hasattr(recorded, "model_dump") else recorded
        assert recorded == value, key


def test_the_procedural_freeze_its_digest_and_the_pilot_approval_are_unchanged():
    from scripts.p2_pilot import pilot_config_digest

    arm = load_p2(AGENTS_YAML)
    # the procedural digest, with or without a configuration, is what it was (B-4)
    assert frozen_record_sha256() == COMMITTED_FROZEN_SHA256
    assert frozen_record_sha256(load_p2()) == COMMITTED_FROZEN_SHA256
    assert pilot_config_digest() == PILOT_CONFIG_SHA256
    # the agent arm's digest names both records; it is pinned, and it is not the procedural one
    assert frozen_record_sha256(arm) == COMMITTED_AGENT_FROZEN_SHA256 != COMMITTED_FROZEN_SHA256
    # the committed approval of the procedural pilot still names the committed freeze and
    # its own digest; an approval of the agent arm would have to name the agent digest
    approval = yaml.safe_load(p2_live.APPROVAL_FILE.read_text(encoding="utf-8"))
    assert approval["frozen_sha256"] == frozen_record_sha256(load_p2())
    assert approval["config_sha256"] == PILOT_CONFIG_SHA256
    assert p2_live.approval_digest(approval) == approval["digest"]
    assert approval["frozen_sha256"] != frozen_record_sha256(arm)
    # the jail document carries no record and no caps: the privileged side keeps them
    doc = sandbox_config(arm)["agents"]
    assert "frozen" not in doc and "caps" not in doc and "prompts" in doc


def _prompt_file(path: Path, role: str) -> Path:
    return path.parent / load_p2(path).agents.prompts[role]


@pytest.mark.parametrize(
    ("name", "change", "why"),
    [
        (
            "prompt",
            lambda path: _prompt_file(path, "calibration").write_text(
                _prompt_file(path, "calibration").read_text() + "\nBe decisive.\n"
            ),
            r"agent prompt of 'calibration' is not the frozen one",
        ),
        (
            "allow_list",
            lambda path: _edit_yaml(
                path, lambda r: r["agents"]["roles"]["design"]["tools"].append("simulate")
            ),
            r"agent allow-list of 'design' is not the frozen one",
        ),
        (
            "turns",
            lambda path: _edit_yaml(path, lambda r: r["agents"]["roles"]["design"].update(turns=7)),
            r"agent turn budget of 'design' is not the frozen one \(7 vs 6\)",
        ),
        (
            "rounds",
            lambda path: _edit_yaml(path, lambda r: r["agents"].update(rounds=1)),
            r"agent round limit is not the frozen one \(1 vs 2\)",
        ),
        (
            "projection",
            lambda path: _edit_yaml(
                path, lambda r: r["agents"]["projection"].update(max_points=100)
            ),
            r"agent projection rule is not the frozen one \(\['max_points'\]\)",
        ),
        (
            "caps",
            lambda path: _edit_yaml(path, lambda r: r["agents"]["caps"].update(max_usd=0.6)),
            r"agent caps block is not the frozen one \(\['max_usd'\]\)",
        ),
        (
            "verifier_caps",
            lambda path: _edit_yaml(
                path, lambda r: r["agents"]["verifier_caps"].update(max_requests=41)
            ),
            r"agent verifier_caps block is not the frozen one \(\['max_requests'\]\)",
        ),
        (
            "verifier_budget",
            lambda path: _edit_yaml(
                path, lambda r: r["agents"]["verifier_budget"].update(simulator_evals=81)
            ),
            r"agent verifier_budget block is not the frozen one \(\['simulator_evals'\]\)",
        ),
    ],
)
def test_each_frozen_item_of_the_configuration_changed_is_refused(tmp_path, name, change, why):
    path = _copy(tmp_path)
    assert check_p2_frozen(load_p2(path)).date  # the negative control: the copy passes
    change(path)
    with pytest.raises(ValueError, match=why):
        check_p2_frozen(load_p2(path))
    # the same change written into the copy's own record too: not the committed one
    frozen = agent_frozen_digests(load_p2(path))

    def rewrite(r: dict[str, Any]) -> None:
        for key, value in frozen.items():
            r["agents"]["frozen"][key] = json.loads(json.dumps(value, default=list))
        a = r["agents"]
        r["agents"]["frozen"]["caps"] = a["caps"]
        r["agents"]["frozen"]["verifier_caps"] = a["verifier_caps"]
        r["agents"]["frozen"]["verifier_budget"] = a["verifier_budget"]

    _edit_yaml(path, rewrite)
    with pytest.raises(ValueError, match="agent frozen record is not the committed one"):
        check_p2_frozen(load_p2(path))


def test_a_record_missing_or_the_arm_absent_is_refused(tmp_path):
    path = _copy(tmp_path)
    _edit_yaml(path, lambda r: r["agents"].pop("frozen"))
    with pytest.raises(ValueError, match=r"no agents\.frozen record"):
        check_p2_frozen(load_p2(path))
    with pytest.raises(ValueError, match="no agents block"):
        check_p2_agents_frozen(load_p2())
    with pytest.raises(ValueError, match="no agents block"):
        agent_frozen_digests(load_p2())
    assert check_p2_frozen(load_p2()).date  # the procedural arm needs no agent record


def test_a_schema_a_tool_or_the_redaction_rule_changed_in_the_code_is_refused(monkeypatch):
    arm = load_p2(AGENTS_YAML)
    assert check_p2_agents_frozen(arm).date  # the negative control
    # a message schema
    monkeypatch.setattr(messages, "Verdict", messages.Grant)
    with pytest.raises(ValueError, match=r"agent schema of 'Verdict' is not the frozen one"):
        check_p2_frozen(arm)
    monkeypatch.undo()
    # a role's tool specifications, apart from the allow-list (a description)
    original = agents.role_tool_specs

    def changed(role: str, allowed: list[str]) -> list[dict[str, Any]]:
        specs = original(role, allowed)
        if role == "design":
            specs = [{**s, "description": "Decide."} for s in specs]
        return specs

    monkeypatch.setattr(agents, "role_tool_specs", changed)
    with pytest.raises(ValueError, match=r"agent tools of 'design' is not the frozen one"):
        check_p2_frozen(arm)
    monkeypatch.undo()
    # the redaction rule: the token pattern, the declared free-text fields, the hidden tools
    for attr, module, value in (
        ("TOKEN_PATTERN", messages, r"^.*$"),
        ("REDACTED", agents, {}),
        ("HIDDEN_FROM_PROPOSERS", agents, ()),
    ):
        monkeypatch.setattr(module, attr, value)
        with pytest.raises(ValueError, match=r"projection rule is not the frozen one"):
            check_p2_frozen(arm)
        monkeypatch.undo()
    # the record's model block against the frozen P1's (decision d)
    p1 = load_p1()
    other = p1.model_copy(update={"model": p1.model.model_copy(update={"effort": "low"})})
    monkeypatch.setattr("tools.workflow_config.load_p1", lambda *a, **k: other)
    with pytest.raises(ValueError, match="frozen P1's"):
        check_p2_agents_frozen(arm)
    monkeypatch.undo()
    assert check_p2_agents_frozen(arm).date  # restored, it passes again


def test_the_runner_refuses_an_unfrozen_agent_arm_before_any_launch(tmp_path, monkeypatch):
    from tools import runner

    path = _copy(tmp_path)
    _prompt_file(path, "verification").write_text(
        _prompt_file(path, "verification").read_text() + "\nPass everything.\n"
    )

    def never(*a: Any, **k: Any) -> Any:
        raise AssertionError("the registry was opened")

    monkeypatch.setattr(runner, "open_registry", never)
    with pytest.raises(ValueError, match=r"agent prompt of 'verification' is not the frozen one"):
        runner.run_workflow("run_x", "p2", config_path=path, runs_root=tmp_path / "runs")
