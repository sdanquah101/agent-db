"""The Q6 (H4) development cells (``docs/p2_agents_design.md`` §7; ``scripts/p2_power.py``).

S7-01 at B/A, B/B and B/C and S7-02 at A/C, two seeds each, run offline by both arms. These
tests pin:

* the cells, seeds and arms are the ones the lead decided (Q6, 2026-10-25);
* each fault of a two-fault truth is a label of the vocabulary, with a role that may
  claim it, and a run's hit is counted on its outcome, never its label alone;
* the cells are reproducible from their seeds: regenerated, each gives the committed
  record's observation fingerprint (exactly on one machine, its sums within a stated
  tolerance on another), and its two seeds differ;
* the frozen check passes for each arm, refuses a moved record (the control), and every
  committed run names the frozen digests and reached no model;
* the agent arm, jailed and offline on a shortened S7-01 B/B, writes the same
  ``calls.jsonl`` and report twice from one seed.

No test reads the truth store: a run's truth label is the scenario file's.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts import p2_power
from scripts.p2_power import (
    H4_ARMS,
    H4_CELLS,
    H4_FINGERPRINT_RTOL,
    H4_REPLICATES,
    calls_digest,
    fingerprint_mismatches,
    h4_frozen,
    h4_jobs,
    h4_summarise,
    observations_digest,
    observations_fingerprint,
)
from tests.test_p2_agents_freeze import (
    COMMITTED_AGENT_CONFIG_SHA256,
    COMMITTED_AGENT_FROZEN_SHA256,
    PROCEDURAL_CONFIG_SHA256,
)
from tests.test_p2_live import COMMITTED_FROZEN_SHA256, _edit_yaml

REPO = Path(__file__).resolve().parents[1]
H4_JSON = REPO / "reports" / "p2_power" / "h4_cells.json"

FROZEN = {
    "procedural": {
        "frozen_record_sha256": COMMITTED_FROZEN_SHA256,
        "config_sha256": PROCEDURAL_CONFIG_SHA256,
    },
    "agents": {
        # frozen_record_sha256(arm) covers both records, p2.yaml's and agents.frozen
        "frozen_record_sha256": COMMITTED_AGENT_FROZEN_SHA256,
        "config_sha256": COMMITTED_AGENT_CONFIG_SHA256,
        # the provenance key a run of the arm carries: agents.frozen alone (PR #45, N4)
        "agents_frozen_sha256": "8a8ab73dba086b06a557b70e196dda57802f9f04e97648ac8d65204fbaf7c951",
    },
}
"""What each arm's record must name: the digests on ``main`` since PR #46."""


def _scenario(sid: str) -> Any:
    from scenarios.schema import load_scenario

    return load_scenario(REPO / "scenarios" / f"{sid}.yaml")


# ------------------------------------------------------------------ the cells


def test_the_h4_cells_are_the_q6_cells_two_seeds_and_both_arms():
    assert H4_CELLS == (
        ("S7-01", "B", "A"),
        ("S7-01", "B", "B"),
        ("S7-01", "B", "C"),
        ("S7-02", "A", "C"),
    )
    assert H4_REPLICATES == (0, 1)
    assert H4_ARMS == {"procedural": None, "agents": REPO / "configs/workflows/p2_agents.yaml"}
    assert len(h4_jobs()) == 16 and len(set(h4_jobs())) == 16
    # S7-02 runs at its defined tier, and on its own plant (the ammonia rows are plant A's)
    s702 = _scenario("S7-02")
    assert (s702.plant, s702.tier) == ("A", "C")
    assert _scenario("S7-01").plant == "B"
    # the development matrix of the power run is left as it is
    assert not set(H4_CELLS) & set(p2_power.CELLS)


def test_each_fault_of_a_two_fault_truth_is_a_label_with_a_claimant():
    """Every truth label of an H4 cell is a label the arms can write, and one a role claims.

    The control: a label outside the vocabulary has no claimant and is not a P0 label.
    """
    from workflows.p2_multi_agent import agents
    from workflows.p2_multi_agent import workflow as wf

    for sid in sorted({c[0] for c in H4_CELLS}):
        truth = list(_scenario(sid).truth_label)
        assert len(truth) == 2, sid  # two simultaneous faults: H4's condition
        for label in truth:
            assert label in wf.P0_ORDER, (sid, label)
            assert agents.CLAIMS_FOR_LABEL.get(label), (sid, label)
            assert label in agents.LABEL_TIE_BREAK
    assert "biological" not in wf.P0_ORDER and not agents.CLAIMS_FOR_LABEL.get("biological")


def _row(**kw: Any) -> dict[str, Any]:
    base = {
        "cell": "S7-01 B/B",
        "replicate": 0,
        "arm": "agents",
        "truth": ["sensor", "influent"],
        "label": "sensor",
        "outcome": "sensor",
        "rule": "r",
        "completed": True,
        "verdict": {"admitted": ["sensor", "influent", "parameter"]},
        "null_table": {"NB": True},
        "evaluations_used": 1,
        "evaluations_total": 2,
        "wall_s": 60.0,
        "observations_sha256": "a",
    }
    return {**base, **kw}


def test_a_hit_is_one_of_the_two_faults_on_the_outcome_and_an_abstention_is_excluded():
    out = h4_summarise(
        [
            _row(),
            _row(arm="procedural", label="none", outcome="none"),
            _row(replicate=1, label="sensor", outcome="abstain", observations_sha256="b"),
            _row(replicate=1, arm="procedural", observations_sha256="b", verdict={}),
        ]
    )
    rows = {(x["replicate"], x["arm"]): x for x in out["cells"]}
    assert rows[(0, "agents")]["hit"] and rows[(0, "agents")]["truth_admitted"] == [
        "influent",
        "sensor",
    ]
    assert not rows[(0, "procedural")]["hit"]  # none is never a fault's hit
    # an abstaining run is excluded, never read as its label (the label says sensor)
    assert rows[(1, "agents")]["excluded"] and not rows[(1, "agents")]["hit"]
    assert out["arms"]["agents"]["hits"] == "1 of 1 scored"
    assert out["arms"]["agents"]["excluded"]["abstain"] == 1
    assert out["arms"]["agents"]["both_faults_admitted"] == 2
    assert out["arms"]["procedural"]["both_faults_admitted"] == 1
    assert out["descriptive_only"] is True


def test_the_seed_checks_catch_arms_that_saw_different_observations():
    same = h4_summarise([_row(), _row(arm="procedural")])
    assert same["seed_checks"]["S7-01 B/B r0"]["arms_see_the_same_observations"]
    assert not same["seeds_differ_within_a_cell"]["S7-01 B/B"]  # one seed only
    # the control: one arm's observations differ, and the check says so
    other = h4_summarise([_row(), _row(arm="procedural", observations_sha256="z")])
    assert not other["seed_checks"]["S7-01 B/B r0"]["arms_see_the_same_observations"]


def test_the_calls_digest_leaves_out_only_the_clock(tmp_path):
    def write(name: str, lines: list[dict[str, Any]]) -> Path:
        path = tmp_path / name
        path.write_text("".join(json.dumps(x) + "\n" for x in lines))
        return path

    line = {"seq": 1, "name": "simulate", "args_hash": "abc", "outcome": "ok"}
    one = write("a.jsonl", [{**line, "runtime_s": 1.5, "t_utc": "2026-11-03T05:00:00Z"}])
    two = write("b.jsonl", [{**line, "runtime_s": 9.0, "t_utc": "2026-11-04T07:00:00Z"}])
    assert calls_digest(one) == calls_digest(two)
    assert calls_digest(one)[1] == 1
    # the control: a different argument is a different record
    three = write("c.jsonl", [{**line, "args_hash": "abd", "runtime_s": 1.5}])
    assert calls_digest(three) != calls_digest(one)


# ------------------------------------------------------------------ the frozen check


def test_the_frozen_check_passes_for_each_arm_with_the_committed_digests():
    for arm, want in FROZEN.items():
        assert h4_frozen(arm) == want, arm


def test_the_frozen_check_refuses_a_moved_agent_record(tmp_path, monkeypatch):
    dest = tmp_path / "workflows"
    shutil.copytree(REPO / "configs" / "workflows", dest)
    moved = dest / "p2_agents.yaml"
    _edit_yaml(moved, lambda r: r["agents"]["frozen"].update(rules_sha256="0" * 64))
    monkeypatch.setitem(p2_power.H4_ARMS, "agents", moved)
    with pytest.raises(ValueError):
        h4_frozen("agents")
    # the control: the unedited copy passes
    shutil.copy(REPO / "configs" / "workflows" / "p2_agents.yaml", moved)
    assert h4_frozen("agents") == FROZEN["agents"]


# ------------------------------------------------------------------ the committed record


def _committed() -> dict[str, Any]:
    return json.loads(H4_JSON.read_text(encoding="utf-8"))


def test_every_committed_run_passed_the_frozen_check_offline_and_reached_no_model():
    out = _committed()
    rows = out["cells"]
    assert sorted((x["cell"], x["replicate"], x["arm"]) for x in rows) == sorted(
        (p2_power.key(c), r, a) for c, r, a in h4_jobs()
    )
    assert not out["unfinished"]
    for x in rows:
        assert x["frozen"] == FROZEN[x["arm"]], (x["cell"], x["replicate"], x["arm"])
        assert x["decider"] == "offline" and x["llm_turns"] is None
        assert x["calls_lines"] and len(x["calls_sha256"]) == 64
        if x["arm"] == "agents":
            assert x["routing"] and x["routing"][0] == "data_quality"
    assert all(v["arms_see_the_same_observations"] for v in out["seed_checks"].values())
    assert all(out["seeds_differ_within_a_cell"].values())


def test_each_cell_regenerates_from_its_seed_to_the_committed_observations(tmp_path):
    """Each cell is reproducible from its seed, and its two seeds differ.

    A generated run is machine-bound to the last bits (``tests/test_p0_freeze.py``), so the
    committed record is matched through its numeric fingerprint: a fresh store (a new
    salt, so new run ids) gives each committed run's counts, flags and text exactly and
    its sums within ``H4_FINGERPRINT_RTOL``. The control: the other seed's fingerprint is
    outside it. Exact byte identity is checked on one machine: the committed runs (both
    arms of each seed, generated in two stores) and the test below.
    """
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon

    committed = {
        (x["cell"], x["replicate"]): x["observations_fingerprint"] for x in _committed()["cells"]
    }
    for cell in H4_CELLS:
        sid, plant_id, tier = cell
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(_scenario(sid), plant)
        for rep in H4_REPLICATES:
            root = tmp_path / f"{sid}-{plant_id}-{tier}-r{rep}" / "runs"
            art = generate_run(scenario, tier, plant=plant, replicate=rep, runs_root=root)
            got = observations_fingerprint(root / art.run_id)
            want = committed[(p2_power.key(cell), rep)]
            assert not fingerprint_mismatches(got, want), (cell, rep)
            other = committed[(p2_power.key(cell), 1 - rep)]
            assert fingerprint_mismatches(got, other), (cell, rep)  # the control


def test_one_seed_generates_byte_identical_observations_on_one_machine(tmp_path):
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon

    plant = load_plant_config("B")
    scenario = at_plant_horizon(_scenario("S7-01"), plant)
    digests = []
    for name, rep in (("one", 0), ("two", 0), ("other", 1)):
        root = tmp_path / name / "runs"
        art = generate_run(scenario, "B", plant=plant, replicate=rep, runs_root=root)
        digests.append(observations_digest(root / art.run_id))
    assert digests[0] == digests[1]
    assert digests[2] != digests[0]  # the control: the other seed


def test_the_fingerprint_comparison_holds_floats_to_the_tolerance_and_the_rest_exactly():
    want = {"sensors": {"ph": {"n": 3, "sum": 21.0, "unit": "pH units"}}}
    near = {
        "sensors": {"ph": {"n": 3, "sum": 21.0 * (1 + H4_FINGERPRINT_RTOL / 2), "unit": "pH units"}}
    }
    assert not fingerprint_mismatches(near, want)
    far = {
        "sensors": {"ph": {"n": 3, "sum": 21.0 * (1 + 2 * H4_FINGERPRINT_RTOL), "unit": "pH units"}}
    }
    assert fingerprint_mismatches(far, want)
    assert fingerprint_mismatches(
        {"sensors": {"ph": {"n": 4, "sum": 21.0, "unit": "pH units"}}}, want
    )
    assert fingerprint_mismatches({"sensors": {}}, want)


# ------------------------------------------------------------------ the jailed arm


def _short_s701() -> Any:
    s = _scenario("S7-01")
    budget = s.budget.model_copy(update={"simulator_evals": 60, "wall_clock_min": 45.0})
    # past the pH drift's onset (day 45); the feed fault (day 60) is outside this horizon
    return s.model_copy(update={"duration_days": 50.0, "budget": budget})


@pytest.fixture(scope="module")
def jailed_twice(tmp_path_factory):
    """The agent arm jailed and offline on a shortened S7-01 B/B, twice from one seed."""
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from tools.runner import run_workflow

    s = _short_s701()
    out = []
    for k in (1, 2):
        root = tmp_path_factory.mktemp(f"h4short{k}") / "runs"
        art = generate_run(s, "B", plant=load_plant_config("B"), replicate=0, runs_root=root)
        result = run_workflow(
            art.run_id, "p2", runs_root=root, scenario=s, config_path=H4_ARMS["agents"]
        )
        out.append((root / art.run_id, result))
    return out


def _report_without_ids(run_dir: Path) -> dict[str, Any]:
    report = json.loads((run_dir / "workflows" / "p2" / "report.json").read_text())
    text = json.dumps(report, sort_keys=True).replace(run_dir.name, "<run>")
    return json.loads(text)


def test_the_jailed_agent_arm_is_reproducible_from_its_seed(jailed_twice):
    (one, r1), (two, r2) = jailed_twice
    assert one.name != two.name  # two stores, two salts
    assert r1.completed and r2.completed
    assert observations_digest(one) == observations_digest(two)
    assert calls_digest(one / "calls.jsonl") == calls_digest(two / "calls.jsonl")
    assert _report_without_ids(one) == _report_without_ids(two)
    report = _report_without_ids(one)
    assert report["arm"] == "agents" and report["routing"][0]["to"] == "data_quality"
    for run_dir in (one, two):
        summary = json.loads((run_dir / "workflows" / "p2" / "summary.json").read_text())
        assert summary["decider"] == "offline" and summary["llm_turns"] is None
        assert summary["model_id"] is None
