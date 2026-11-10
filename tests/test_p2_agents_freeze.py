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
    agent_frozen_record_sha256,
    agent_rule_tables,
    check_p2_agents_frozen,
    check_p2_frozen,
    config_digest,
    frozen_record_sha256,
    p2_provenance,
)
from tools.workflow_config import load_p1, load_p2, sandbox_config
from workflows.p2_multi_agent import agents, messages

REPO = Path(__file__).resolve().parents[1]
COMMITTED_AGENT_FROZEN_SHA256 = "b02f19c73d09794ad8edf7317c55b3b4731de1b3227281cd23d51f2bc01d95ba"
"""The digest of both committed records an approval of the agent arm names (the procedural
``frozen`` and ``agents.frozen``): a new agent freeze edits it, the procedural one stands.
It moved from ``2089b2e2…a77b`` when the rule tables joined the record (2026-11-01), from
``b373dfaf…4a82`` when the routing rules joined them (the lead's "a", 2026-11-03, first
``2ed56ecf…9ead``, then ``501893b3…1fa4`` with the leading claim's label tie-break), and
from ``501893b3…1fa4`` when the record was re-dated 2026-11-08 for the secondary labels
(Q-H4, the lead's "a", 2026-11-05)."""
H4_CELLS_AGENT_FROZEN_SHA256 = "501893b3ff1902bf800115f3af3e09f00aed16fe04d37da34c6b0f75fc4b1fa4"
"""The digest of the record the committed H4 offline cells passed (PR #48), before the
secondary labels re-dated it."""
RULE_TABLES_AGENT_FROZEN_SHA256 = "b373dfaf01636999d0a80ff2b211108a3c9ab94f786a2a208342eb8333f34a82"
"""The digest of the record with the rule tables of 2026-11-01, before the routing rules."""
FIRST_AGENT_FROZEN_SHA256 = "2089b2e2f6378b8b3bd88bab3431ff1bf483afe209da329d2a1c4f27885ba77b"
"""The digest of the record as first cut on 2026-10-30, before the rule tables."""
COMMITTED_AGENT_CONFIG_SHA256 = "30752c9d37fb2caa092efd46d41c1f57d51d4254edceb484b57155170de654e5"
"""``config_digest`` of the committed ``p2_agents.yaml`` (the review of PR #46 at 9f5ffed):
any edit to the agent configuration, its record included, moves it. It was ``85a608b8…``
before the routing rules joined the record, ``ba8efb16…`` before the label tie-break did
(both 2026-11-03), and ``618f4825…6dd8`` before the secondary labels re-dated the record
(2026-11-08)."""
PROCEDURAL_CONFIG_SHA256 = "def3c42bc638608e28c240b52f7ecc1c12c776f31a4b516cfd8d60ff23e0ba36"
"""``config_digest(load_p2())``, the procedural configuration's own digest (not the pilot's
``cf59bcbb…f404``, which is the pilot copy's): the agent record must not move it."""
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
    assert record.date == "2026-11-08" and "Yes to all three" in record.word
    assert "lead's word of 2026-11-03" in record.word  # the routing rules (the lead's "a")
    assert "lead''s word of 2026-11-05" not in record.word  # the YAML quoting is unescaped
    assert "lead's word of 2026-11-05" in record.word and "Q-H4" in record.word  # the labels
    assert "First frozen 2026-10-30" in record.word and "yes to the rule tables" in record.word
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
    # the pilot configuration's digest (the approval's config_sha256) and the procedural
    # configuration's own digest are both unchanged (the review of PR #45, N2)
    assert pilot_config_digest() == PILOT_CONFIG_SHA256
    assert config_digest(load_p2()) == PROCEDURAL_CONFIG_SHA256
    assert config_digest(arm) not in (PILOT_CONFIG_SHA256, PROCEDURAL_CONFIG_SHA256)
    # the agent configuration's own digest is pinned, as the record's is
    assert config_digest(arm) == COMMITTED_AGENT_CONFIG_SHA256
    # the agent arm's digest names both records; it is pinned, and it is not the procedural one
    assert frozen_record_sha256(arm) == COMMITTED_AGENT_FROZEN_SHA256 != COMMITTED_FROZEN_SHA256
    assert COMMITTED_AGENT_FROZEN_SHA256 != FIRST_AGENT_FROZEN_SHA256  # the rule tables moved it
    assert COMMITTED_AGENT_FROZEN_SHA256 != RULE_TABLES_AGENT_FROZEN_SHA256  # and the routing
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
            "preview",
            lambda path: _edit_yaml(path, lambda r: r["agents"]["projection"].update(preview=8)),
            r"agent projection rule is not the frozen one \(\['preview'\]\)",
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
    # the record's model block against the frozen P1's (decision d): through
    # check_p2_frozen the procedural check fires first, so the agent-side check is the
    # direct caller's guard of the record itself (N1); both messages are checked
    p1 = load_p1()
    other = p1.model_copy(update={"model": p1.model.model_copy(update={"effort": "low"})})
    monkeypatch.setattr("tools.workflow_config.load_p1", lambda *a, **k: other)
    with pytest.raises(ValueError, match="agent record's model block is not the frozen P1's"):
        check_p2_agents_frozen(arm)
    with pytest.raises(ValueError, match=r"^the model block is not the frozen P1's"):
        check_p2_frozen(arm)
    monkeypatch.undo()
    assert check_p2_agents_frozen(arm).date  # restored, it passes again


def test_the_set_of_frozen_schemas_is_itself_frozen(monkeypatch):
    """S1: a schema dropped from, or added to, the frozen set trips the freeze."""
    arm = load_p2(AGENTS_YAML)
    assert check_p2_agents_frozen(arm).date  # the negative control: the full set passes
    monkeypatch.setattr(p2_live, "AGENT_FROZEN_SCHEMAS", AGENT_FROZEN_SCHEMAS[:-1])
    with pytest.raises(ValueError, match=r"frozen agent schemas must name exactly"):
        check_p2_frozen(arm)
    monkeypatch.setattr(p2_live, "AGENT_FROZEN_SCHEMAS", (*AGENT_FROZEN_SCHEMAS, "_Msg"))
    with pytest.raises(ValueError, match=r"frozen agent schemas must name exactly"):
        check_p2_frozen(arm)
    monkeypatch.undo()
    assert check_p2_agents_frozen(arm).date


def test_the_provenance_of_an_agent_run_names_the_record_it_passed(monkeypatch):
    """N4: ``llm_calls.jsonl`` and the summary carry the agent record's digest."""
    monkeypatch.setattr("tools.runner.git_commit", lambda: "test")
    arm = load_p2(AGENTS_YAML)
    record = arm.agents.frozen.model_dump(mode="json")
    expected = __import__("hashlib").sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    assert agent_frozen_record_sha256(arm) == expected
    assert p2_provenance(arm, live=False)["agents_frozen_sha256"] == expected
    assert p2_provenance(arm, live=True)["agents_frozen_sha256"] == expected
    # the digest is the record's alone, not the approval's (both records) and not the
    # procedural freeze's; the procedural arm's provenance carries no such key (control)
    assert expected not in (frozen_record_sha256(arm), frozen_record_sha256())
    assert "agents_frozen_sha256" not in p2_provenance(load_p2(), live=False)
    with pytest.raises(ValueError, match="no agent frozen record"):
        agent_frozen_record_sha256(load_p2())


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


# ---------------------------------------------- the rule tables (the lead's word, 2026-11-01)


def test_the_rule_tables_are_named_and_their_digest_is_in_the_committed_record():
    """The lead's "yes to the rule tables": the record binds them, offline as live."""
    arm = load_p2(AGENTS_YAML)
    tables = agent_rule_tables()
    assert set(tables) == {
        "claims_for_label", "round_two_only_claims", "specialists", "verifier",
        "confidence_order", "p0_order", "abstain_label", "rule", "never_in_objective",
        "balance_stats", "qc_first", "round_one_order", "null_case_routes",
        "design_on_conflict", "conflict_min_distinct_claims", "not_responders",
        "assay_holder", "operator_notes_roles", "not_a_separating_test", "label_tie_break",
    }  # fmt: skip
    assert tables["claims_for_label"]["structural"] == ["calibration"]
    assert tables["round_two_only_claims"] == ["structural"]
    assert tables["specialists"][0] == "data_quality" and tables["abstain_label"] == "abstain"
    digest = __import__("hashlib").sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    assert arm.agents.frozen.rules_sha256 == digest == agent_frozen_digests(arm)["rules_sha256"]
    assert check_p2_agents_frozen(arm).rules_sha256 == digest  # the committed record passes


def _swap_routing_order(seq: tuple[str, ...]) -> tuple[str, ...]:
    return (seq[1], seq[0], *seq[2:])


RULE_TABLE_CHANGES = [
    ("CLAIMS_FOR_LABEL", agents, lambda v: {**v, "structural": ("calibration", "influent")}),
    ("CLAIMS_FOR_LABEL", agents, lambda v: {k: x for k, x in v.items() if k != "sensor"}),
    ("ROUND_TWO_ONLY_CLAIMS", messages, lambda v: frozenset()),
    ("ROUND_TWO_ONLY_CLAIMS", messages, lambda v: frozenset({*v, "parameter"})),
    ("SPECIALISTS", agents, _swap_routing_order),
    ("VERIFIER", agents, lambda v: "verifier"),
    ("CONFIDENCE_ORDER", agents, lambda v: {"low": 0, "medium": 1, "high": 2}),
    ("ABSTAIN_LABEL", agents, lambda v: "none"),
    ("RULE", agents, lambda v: "agents_v2"),
]


@pytest.mark.parametrize(("attr", "module", "change"), RULE_TABLE_CHANGES)
def test_each_rule_table_changed_in_the_code_is_refused(monkeypatch, attr, module, change):
    arm = load_p2(AGENTS_YAML)
    assert check_p2_frozen(arm).date  # the negative control: the code as committed passes
    monkeypatch.setattr(module, attr, change(getattr(module, attr)))
    with pytest.raises(ValueError, match=r"coordinator's rule tables are not the frozen ones"):
        check_p2_frozen(arm)
    monkeypatch.undo()
    assert check_p2_agents_frozen(arm).date  # restored, it passes again


SHARED_TABLE_CHANGES = [
    ("P0_ORDER", "workflow", lambda v: tuple(reversed(v))),
    ("NEVER_IN_OBJECTIVE", "evidence", lambda v: ()),
    ("BALANCE_STATS", "evidence", lambda v: v[:-1]),
]


@pytest.mark.parametrize(("attr", "module_name", "change"), SHARED_TABLE_CHANGES)
def test_the_shared_tables_that_decide_the_label_are_frozen_too(
    monkeypatch, attr, module_name, change
):
    """P0's order (the leading claim's tie-break) and the null rule's two constants."""
    import importlib

    module = importlib.import_module(f"workflows.p2_multi_agent.{module_name}")
    arm = load_p2(AGENTS_YAML)
    assert check_p2_frozen(arm).date
    monkeypatch.setattr(module, attr, change(getattr(module, attr)))
    with pytest.raises(ValueError, match=r"coordinator's rule tables are not the frozen ones"):
        check_p2_frozen(arm)
    # the procedural arm carries no agent record: its freeze does not read the agent tables
    assert check_p2_frozen(load_p2()).date


# ------------------------------- the routing rules (the lead's "a", 2026-11-03)


ROUTING_CHANGES = [
    ("QC_FIRST", lambda v: "influent"),
    ("ROUND_ONE_ORDER", lambda v: tuple(reversed(v))),
    ("ROUND_ONE_ORDER", lambda v: tuple(r for r in v if r != "identifiability")),
    ("NULL_CASE_ROUTES", lambda v: ((("NB",), "calibration", ("calibration",)), *v[1:])),
    ("NULL_CASE_ROUTES", lambda v: (v[0], (("NM", "NS"), "calibration", ("calibration",)))),
    ("DESIGN_ON_CONFLICT", lambda v: "calibration"),
    ("CONFLICT_MIN_DISTINCT_CLAIMS", lambda v: 3),
    ("NOT_RESPONDERS", lambda v: frozenset()),
    ("ASSAY_HOLDER", lambda v: "calibration"),
    ("OPERATOR_NOTES_ROLES", lambda v: ("data_quality",)),
    ("NOT_A_SEPARATING_TEST", lambda v: frozenset()),
    ("LABEL_TIE_BREAK", lambda v: ("none", *v[:-1])),
    ("LABEL_TIE_BREAK", lambda v: tuple(reversed(v[:-1])) + v[-1:]),
]


@pytest.mark.parametrize(("attr", "change"), ROUTING_CHANGES)
def test_each_routing_rule_changed_in_the_code_is_refused(monkeypatch, attr, change):
    """The lead's "a": every routing constant is in the rule tables' digest."""
    arm = load_p2(AGENTS_YAML)
    assert check_p2_agents_frozen(arm).date  # the negative control: the committed rules pass
    monkeypatch.setattr(agents, attr, change(getattr(agents, attr)))
    with pytest.raises(ValueError, match=r"coordinator's rule tables are not the frozen ones"):
        check_p2_agents_frozen(arm)
    monkeypatch.undo()
    assert check_p2_agents_frozen(arm).date  # restored, it passes again


def test_every_rule_table_has_a_mutation_test():
    """Every table ``agent_rule_tables()`` names has a test that changing it is refused.

    The set is derived from the tables' keys (the review of 0f11477, N6): a table added
    without its own mutation test fails here. Each key names its constant (upper case).
    """
    mutated = (
        {attr for attr, _, _ in RULE_TABLE_CHANGES}
        | {attr for attr, _, _ in SHARED_TABLE_CHANGES}
        | {attr for attr, _ in ROUTING_CHANGES}
    )
    wanted = {key.upper() for key in agent_rule_tables()}
    assert wanted <= mutated, sorted(wanted - mutated)
    assert mutated <= wanted, sorted(mutated - wanted)  # no test of a table not frozen
    # the control: a table the code named but no test mutated would be caught
    assert {*wanted, "SOME_NEW_TABLE"} - mutated == {"SOME_NEW_TABLE"}


def test_the_design_role_never_answers_a_fail(monkeypatch):
    """The exclusion in ``responders_for`` matters (the one mutation no test caught).

    Design claims no label, so it can join the responders only through the claimants of
    the alternative; this makes it one (for ``parameter``) and shows the exclusion keeps it
    out, with the exclusion emptied as the control.
    """
    from tests.test_p2_agents_harness import FakeTools, _cfg, _install

    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    claims = {**agents.CLAIMS_FOR_LABEL, "parameter": ("calibration", "design")}
    monkeypatch.setattr(agents, "CLAIMS_FOR_LABEL", claims)
    verdict = type("V", (), {"alternative": run.lab["parameter"]})()
    responders = run.responders_for(verdict)
    assert "calibration" in responders and "design" not in responders
    # the control: with no role excluded, the same verdict routes design too
    monkeypatch.setattr(agents, "NOT_RESPONDERS", frozenset())
    assert "design" in run.responders_for(verdict)


def test_the_label_tie_break_is_p0s_order_then_none_and_a_label_leads_none(monkeypatch):
    """B3 (the review of 0f11477): at equal confidence a label claim leads a ``none`` claim.

    The leading claim decides the label written on a pass. With the frozen tie-break the
    label leads and is written; with ``none`` moved first (the control) ``none`` leads and
    is written. The tie-break's head is P0's label order.
    """
    from workflows.p2_multi_agent import workflow as wf

    assert (*wf.P0_ORDER, "none") == agents.LABEL_TIE_BREAK
    from tests.test_p2_agents_harness import FakeTools, _admit_everything, _cfg, _install

    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    _admit_everything(monkeypatch)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    run.findings = {
        "influent": messages.InfluentFinding.model_construct(claim="influent", confidence="high"),
        "data_quality": messages.SensorFinding.model_construct(claim="none", confidence="high"),
    }
    passed = messages.Verdict.model_construct(verdict="pass", round=1, alternative=None)

    def written() -> tuple[str | None, str]:
        run.verdicts, run.verdict, run.verifier_rounds = [passed], {}, 1
        run.abstentions = []
        run.conclude()
        return run.leading()[0], run.classification["label"]

    assert written() == ("influent", "influent")
    # the control: none ranked first leads, and is what a pass writes
    monkeypatch.setattr(agents, "LABEL_TIE_BREAK", ("none", *wf.P0_ORDER))
    assert written() == ("none", "none")


def test_the_role_name_tie_break_routes_a_fail_between_equal_none_claims(monkeypatch):
    """N8 (the review of #46): the role-name tie-break never decides the label, but routes.

    Between two equal ``none`` claims (same label, same confidence) the role's name picks
    the leading role, and the leading role is one of the responders to a round-2 ``fail``.
    The label is ``none`` either way. The control: with ``influent`` leading instead (the
    ``data_quality`` claim one step less confident), the same ``fail`` routes ``influent``.
    """
    from tests.test_p2_agents_harness import FakeTools, _cfg, _install

    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    none = run.lab["none"]

    def findings(dq_confidence: str) -> dict[str, Any]:
        return {
            "influent": messages.InfluentFinding.model_construct(claim=none, confidence="high"),
            "data_quality": messages.SensorFinding.model_construct(
                claim=none, confidence=dq_confidence
            ),
        }

    verdict = type("V", (), {"alternative": run.lab["parameter"]})()
    run.findings = findings("high")
    claim, role, _ = run.leading()
    assert (claim, role) == (none, "data_quality")  # the name breaks the tie
    assert run.responders_for(verdict) == ["data_quality", "calibration"]
    # the control: influent leads, the label is still none, and the route changes
    run.findings = findings("medium")
    claim, role, _ = run.leading()
    assert (claim, role) == (none, "influent")
    assert run.responders_for(verdict) == ["influent", "calibration"]


# ------------------------------- the secondary labels (Q-H4, the lead's "a", 2026-11-05)


def _two_claims(run: Any, second: str | None, second_confidence: str = "high") -> None:
    """A ``sensor`` claim from data quality and, if ``second``, that claim from its role."""
    sensor = messages.SensorFinding.model_construct(claim="sensor", confidence="high", channel="ph")
    run.findings = {"data_quality": sensor}
    if second == "influent":
        run.findings["influent"] = messages.InfluentFinding.model_construct(
            claim="influent", confidence=second_confidence
        )
    elif second is not None:
        run.findings["calibration"] = messages.CalFinding.model_construct(
            claim=second, confidence=second_confidence
        )


def _conclude(run: Any, verdict: str, alternative: str | None = None) -> tuple[str, list[str]]:
    """Conclude on one verdict; the label and the secondary labels written."""
    v = messages.Verdict.model_construct(verdict=verdict, round=1, alternative=alternative)
    run.verdicts, run.verdict, run.verifier_rounds, run.abstentions = [v], {}, 1, []
    if verdict == "abstain":
        run.verdict = {"verdict": "abstain", "reason": "verifier_abstain"}
    run.conclude()
    cls = run.classification
    return cls["label"], list(cls["secondary_labels"])


def _agent_run(monkeypatch) -> Any:
    from tests.test_p2_agents_harness import FakeTools, _admit_everything, _cfg, _install

    fake = FakeTools("B", "B", offsets={"ph": 8.0})
    _install(monkeypatch, fake)
    _admit_everything(monkeypatch)
    run = agents.AgentRun(_cfg())
    run.code_steps()
    return run


def test_on_a_two_fault_admission_the_label_set_is_both_faults(monkeypatch):
    """Q-H4 "a": the other admitted claim is the secondary label.

    The label set then equals a two-fault truth, as the procedural arm's does. The control:
    one claim, no secondary.
    """
    run = _agent_run(monkeypatch)
    _two_claims(run, "influent")
    assert _conclude(run, "pass") == ("sensor", ["influent"])
    assert {"sensor", *run.classification["secondary_labels"]} == {"sensor", "influent"}
    # the state and the report carry it: eval reads the state's final labels
    doc = run.build_state(True)
    assert doc["classification"]["secondary_labels"] == ["influent"]
    assert run.build_report(doc)["secondary_labels"] == ["influent"]
    # the control: a single admitted claim writes no secondary label
    _two_claims(run, None)
    assert _conclude(run, "pass") == ("sensor", [])


def test_secondary_labels_follow_the_label_order_and_need_the_admission(monkeypatch):
    """Two others are written in LABEL_TIE_BREAK order, and only when admitted.

    Their confidence does not order them; a claim the admission rejects is not a secondary
    label (the control: admitted, it is).
    """
    run = _agent_run(monkeypatch)
    _two_claims(run, "influent")
    run.findings["calibration"] = messages.CalFinding.model_construct(
        claim="parameter", confidence="high"
    )
    run.findings["influent"] = messages.InfluentFinding.model_construct(
        claim="influent", confidence="low"
    )
    assert _conclude(run, "pass") == ("sensor", ["influent", "parameter"])
    # the control: with only sensor admitted, the other claims are not secondary labels
    monkeypatch.setattr(
        agents.evidence,
        "admit_agent",
        lambda lab, table, signatures: {"admitted": ["sensor"], "rejected": []},
    )
    assert _conclude(run, "pass") == ("sensor", [])


def test_abstain_and_none_write_no_secondary_labels(monkeypatch):
    """An abstention and `none` write no secondary labels, whatever was claimed.

    The control: the same claims on a pass write one.
    """
    run = _agent_run(monkeypatch)
    _two_claims(run, "influent")
    assert _conclude(run, "abstain") == ("abstain", [])
    assert _conclude(run, "fail", alternative="none") == ("none", [])
    assert _conclude(run, "fail", alternative="parameter") == ("abstain", [])
    assert _conclude(run, "pass") == ("sensor", ["influent"])  # the control
    # `none` is never a secondary label: at equal confidence the label claim leads it (B3)
    # and writes no secondary; when `none` leads (the more confident claim), nothing is
    # written beside it though an admitted `influent` claim stands
    run.findings = {
        "data_quality": messages.SensorFinding.model_construct(claim="none", confidence="high"),
        "influent": messages.InfluentFinding.model_construct(claim="influent", confidence="high"),
    }
    assert _conclude(run, "pass") == ("influent", [])
    run.findings["influent"] = messages.InfluentFinding.model_construct(
        claim="influent", confidence="low"
    )
    assert _conclude(run, "pass") == ("none", [])
