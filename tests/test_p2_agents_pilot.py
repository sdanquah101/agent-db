"""The agent arm's live pilot driver (``scripts/p2_agents_pilot.py``).

Every test here is offline. The live client is a spy in every test that could reach the
runner's live path: it raises or records, and no network exists for it to reach. The
dry run is shown to build no client (with the mocked live flow as the control, which
builds exactly one, and only after the approval passed); the live flow is driven end to
end on one cell with a mocked client and a faked launch; a cap hit is recorded; a refused
approval, a missing key and a store that already holds the run each stop before any
client. The git-cleanliness rule is tested on its own (``tests/test_p2_live.py``) and
stood down here.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import p2_agents_pilot as pilot
from tests.test_p2_agents_freeze import COMMITTED_AGENT_FROZEN_SHA256
from tests.test_p2_h4_cells import FROZEN
from tools import p2_live
from tools.llm import ScriptedClient

REPO = Path(__file__).resolve().parents[1]
COMMITTED_APPROVAL = REPO / "configs" / "workflows" / "p2_live_approval.yaml"
ONE_CELL = (("S7-01", "B", "B"),)
APPROVED_STORE = Path("/home/user/p2_agents_pilot_store")


def _committed_record() -> dict[str, Any]:
    return yaml.safe_load(COMMITTED_APPROVAL.read_text(encoding="utf-8"))


@pytest.fixture
def no_live_client(monkeypatch):
    """The live client can never be built: both ways to it raise."""

    def never(*a: Any, **k: Any) -> Any:
        raise AssertionError("a live client was built")

    monkeypatch.setattr(p2_live, "p2_live_client", never)
    monkeypatch.setattr("tools.llm.OpenAIResponsesClient.__init__", never)


@pytest.fixture
def client_spy(monkeypatch):
    """The live client replaced by a scripted one; every construction is recorded."""
    events: list[str] = []

    def build(config: Any) -> Any:
        events.append("client")
        return ScriptedClient(lambda p: {"content": [{"type": "text", "text": "ok"}]})

    monkeypatch.setattr(p2_live, "p2_live_client", build)
    monkeypatch.setattr(
        "tools.llm.OpenAIResponsesClient.__init__",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("the real client was built")),
    )
    real = p2_live.require_live_approval

    def approval(*a: Any, **k: Any) -> Any:
        out = real(*a, **k)
        events.append("approval")
        return out

    monkeypatch.setattr(p2_live, "require_live_approval", approval)
    return events


@pytest.fixture
def one_cell(monkeypatch):
    monkeypatch.setattr(pilot, "CELLS", ONE_CELL)
    monkeypatch.setattr(pilot, "REPLICATES", (0,))


@pytest.fixture
def clean_tree(monkeypatch):
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (True, ""))


def _record_for(store: Path, **edits: Any) -> dict[str, Any]:
    """The committed record, re-pointed at a test store (re-digested)."""
    rec = {**_committed_record(), "runs_root": str((store / "runs").resolve()), **edits}
    rec["digest"] = p2_live.approval_digest(rec)
    return rec


@pytest.fixture
def approved_test_store(tmp_path, monkeypatch, clean_tree):
    """A copy of the lead's record naming a temporary store, at a temporary approval path."""
    store = tmp_path / "store"
    path = tmp_path / "p2_live_approval.yaml"
    path.write_text(yaml.safe_dump(_record_for(store)), encoding="utf-8")
    monkeypatch.setattr(p2_live, "APPROVAL_FILE", path)
    monkeypatch.setenv(pilot.KEY_VARIABLE, "sk-not-a-key")
    return store


def _fake_generate(scenario: Any, tier: Any, *, plant: Any, replicate: int = 0, **kw: Any) -> Any:
    rid = f"run_{scenario.id}_{plant.id}_{tier}_{replicate}"
    (kw["runs_root"] / rid).mkdir(parents=True, exist_ok=True)
    truth = kw["runs_root"].parent / "truth_store" / rid
    truth.mkdir(parents=True, exist_ok=True)
    (truth / "manifest.json").write_text(json.dumps({
        "scenario_id": scenario.id, "plant": plant.id, "tier": tier,
        "seeds": {"replicate": replicate},
    }))  # fmt: skip
    return types.SimpleNamespace(run_id=rid)


def _fake_launch_writing(
    label: str,
    secondary: list[str],
    confidence: float,
    *,
    cap: bool = False,
    calls: list[dict[str, Any]] | None = None,
) -> Any:
    """A launch that leaves a finished run's record, as the arm would, and a model log.

    ``calls``: the model log's lines (each a dict with an ``error``), empty by default.
    """
    from tests.eval_support import minimal_state

    gateways: list[Any] = []

    def launch(script: Any, registry: Any, **kw: Any) -> Any:
        gw = kw["model_gateway"]
        gateways.append(gw)
        out = kw["run_dir"] / "workflows" / "p2"
        out.mkdir(parents=True, exist_ok=True)
        cls = {"label": label, "secondary_labels": secondary, "confidence": confidence}
        state = minimal_state(kw["run_dir"].name, workflow="p2", classification=cls)
        state["final"] = {**state["final"], **cls}
        (out / "state.json").write_text(json.dumps(state))
        if cap:
            report = {"label": "abstain", "secondary_labels": [], "outcome": "abstain",
                      "rule": "abstain:model_cap", "confidence": 0.0,
                      "verdict": {"verdict": "abstain", "reason": "model_cap"},
                      "routing": [{"to": "data_quality"}]}  # fmt: skip
            gw.log_refusal({"model": "x", "messages": []}, "max_requests: 200 reached")
        else:
            report = {"label": label, "secondary_labels": secondary, "outcome": label,
                      "rule": "agents:pass", "confidence": confidence,
                      "verdict": {"verdict": "pass", "reason": "pass"},
                      "routing": [{"to": "data_quality"}]}  # fmt: skip
            (out / "llm_calls.jsonl").write_text(
                "".join(json.dumps(c) + "\n" for c in (calls or []))
            )
        (out / "report.json").write_text(json.dumps(report))
        (kw["run_dir"] / "calls.jsonl").write_text(
            json.dumps({"seq": 0, "name": "simulate", "args_hash": "a", "outcome": "ok"}) + "\n"
        )
        return types.SimpleNamespace(returncode=0, stderr="")

    launch.gateways = gateways  # type: ignore[attr-defined]
    return launch


@pytest.fixture
def faked_runner(monkeypatch):
    from tools import Budget, make_registry, runner

    monkeypatch.setattr("sim.run.harness.generate_run", _fake_generate)
    monkeypatch.setattr(
        runner, "open_registry", lambda *a, **k: make_registry(budget=Budget(10, 5.0, 0), seed=1)
    )

    def install(launch: Any) -> None:
        monkeypatch.setattr(runner, "launch", launch)

    return install


# ------------------------------------------------------------------ the plan and the gates


def test_the_plan_is_the_pilot_the_lead_approved():
    rec = _committed_record()
    plan = pilot.plan()
    assert plan["runs"] == rec["runs"] == pilot.approval_runs() and len(plan["runs"]) == 8
    assert plan["caps_per_run"] == rec["caps"]
    assert plan["frozen_sha256"] == rec["frozen_sha256"] == COMMITTED_AGENT_FROZEN_SHA256
    assert plan["model"] == "gpt-5.6-luna" and plan["arm"] == "agents"
    assert plan["proposer_caps"]["max_usd"] + plan["verifier_caps"]["max_usd"] == 1.0
    assert plan["max_total_usd"] == pilot.max_total_usd() == 8.0
    assert pilot.approved_store() == APPROVED_STORE
    assert REPO not in APPROVED_STORE.parents and APPROVED_STORE != REPO


def test_a_refused_approval_or_a_missing_key_builds_no_client(
    tmp_path, monkeypatch, no_live_client
):
    monkeypatch.setattr(p2_live, "_git_clean", lambda p: (True, ""))
    # no record at all
    monkeypatch.setattr(p2_live, "APPROVAL_FILE", tmp_path / "absent" / "p2_live_approval.yaml")
    with pytest.raises(SystemExit, match="no approval record"):
        pilot.run(live=True)
    # a record naming another store than the one it would run in
    store = tmp_path / "store"
    path = tmp_path / "p2_live_approval.yaml"
    path.write_text(yaml.safe_dump(_record_for(tmp_path / "elsewhere")), encoding="utf-8")
    monkeypatch.setattr(p2_live, "APPROVAL_FILE", path)
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    monkeypatch.setenv(pilot.KEY_VARIABLE, "sk-not-a-key")
    with pytest.raises(SystemExit, match="another run store"):
        pilot.run(live=True)
    # a record naming the previous agent freeze
    path.write_text(yaml.safe_dump(_record_for(store, frozen_sha256="b" * 64)), encoding="utf-8")
    with pytest.raises(SystemExit, match="another freeze"):
        pilot.run(live=True)
    # the approval in order, the key missing: refused before any client
    path.write_text(yaml.safe_dump(_record_for(store)), encoding="utf-8")
    monkeypatch.delenv(pilot.KEY_VARIABLE, raising=False)
    with pytest.raises(SystemExit, match=pilot.KEY_VARIABLE):
        pilot.run(live=True)
    assert not (store / "results.jsonl").exists()
    # a live run never takes a --store of its own
    monkeypatch.setenv(pilot.KEY_VARIABLE, "sk-not-a-key")
    with pytest.raises(SystemExit, match="pass no --store"):
        pilot.run(live=True, store=tmp_path / "other")
    with pytest.raises(SystemExit, match="no --part"):
        pilot.main(["run", "--live", "--part", "1/2"])


def test_a_dry_run_refuses_the_approved_store_and_the_repository(tmp_path, no_live_client):
    with pytest.raises(SystemExit, match="scratch store"):
        pilot.run(live=False)
    with pytest.raises(SystemExit, match="never touches the approved store"):
        pilot.run(live=False, store=pilot.approved_store())
    with pytest.raises(SystemExit, match="never touches the approved store"):
        pilot.run(live=False, store=pilot.approved_store() / "runs")
    with pytest.raises(SystemExit, match="outside the repository"):
        pilot._runs(REPO / "runs", live=False)


def test_check_store_fresh_refuses_outputs_or_a_model_log(tmp_path):
    run_dir = tmp_path / "run_x"
    run_dir.mkdir()
    pilot.check_store_fresh(run_dir)  # the control: an empty run directory is fresh
    out = run_dir / "workflows" / "p2"
    out.mkdir(parents=True)
    with pytest.raises(ValueError, match="already holds run_x \\(outputs\\)"):
        pilot.check_store_fresh(run_dir)
    (out / "llm_calls.jsonl").write_text("")
    with pytest.raises(ValueError, match="a model log"):
        pilot.check_store_fresh(run_dir)


def test_scores_are_evals_on_the_outcome():
    truth = ["sensor", "influent"]
    both = pilot.scores("sensor", ["influent"], "sensor", truth)
    assert both == {"label_set": ["influent", "sensor"], "primary_in_truth": True,
                    "attribution_exact": True}  # fmt: skip
    one = pilot.scores("sensor", [], "sensor", truth)
    assert one["primary_in_truth"] and not one["attribution_exact"]
    wide = pilot.scores("sensor", ["influent", "parameter"], "sensor", truth)
    assert wide["primary_in_truth"] and not wide["attribution_exact"]
    none = pilot.scores("none", [], "none", truth)
    assert not none["primary_in_truth"] and not none["attribution_exact"]
    # an abstention or a pending run scores neither, whatever the label says
    for outcome in ("abstain", "pending"):
        assert pilot.scores("sensor", ["influent"], outcome, truth) == {
            "label_set": [], "primary_in_truth": False, "attribution_exact": False
        }  # fmt: skip


# ------------------------------------------------------------------ the dry run (jailed)


def test_a_dry_run_passes_every_check_and_the_run_and_builds_no_client(
    tmp_path, monkeypatch, one_cell, clean_tree, no_live_client
):
    """Every gate and the whole run with the offline scripted model, on a short S7-01 B/B."""
    from scenarios.schema import load_scenario

    def short(sid: str, plant: Any) -> Any:
        s = load_scenario(REPO / "scenarios" / f"{sid}.yaml")
        budget = s.budget.model_copy(update={"simulator_evals": 60, "wall_clock_min": 45.0})
        return s.model_copy(update={"duration_days": 50.0, "budget": budget})

    monkeypatch.setattr(pilot, "scenario_for", short)
    monkeypatch.delenv(pilot.KEY_VARIABLE, raising=False)  # the dry run needs no key
    store = tmp_path / "scratch"
    pilot.run(live=False, store=store)
    rows = [json.loads(x) for x in (store / "results_dry.0.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert (row["cell"], row["replicate"], row["live"]) == ("S7-01 B/B", 0, False)
    assert row["completed"] and row["finished"] and row["decider"] == "offline"
    assert row["outcome"] == "abstain" and row["secondary_labels"] == []  # the offline verifier
    assert row["label_set"] == [] and not row["primary_in_truth"] and not row["attribution_exact"]
    assert row["llm_calls_jsonl"] is False and row["model_id"] is None
    assert row["spend"]["usd"] is None and row["spend"]["requests"] is None
    assert row["cap"] == {"hit": False, "abstained_on_cap": False, "refusals": []}
    assert row["frozen"] == FROZEN["agents"]
    assert row["provenance"]["git_commit"] and row["provenance"]["tools_sha256"]
    assert row["calls_lines"] and len(row["calls_sha256"]) == 64
    assert row["truth"] == ["sensor", "influent"]
    assert json.loads((store / "spent_usd_dry.0.json").read_text()) == {"usd": 0.0}
    run_dir = store / "runs" / row["run_id"]
    assert not (run_dir / "workflows" / "p2" / "llm_calls.jsonl").exists()
    # the report, from the dry run's records, into a temporary report directory
    monkeypatch.setattr(pilot, "REPORT_DIR", tmp_path / "report")
    out = pilot.report(store, live=False)
    assert out["runs"] == 1 and out["abstained"] == 1 and out["cap_hits"] == []
    assert (tmp_path / "report" / "dry_run" / "summary.md").is_file()
    assert (tmp_path / "report" / "dry_run" / "runs" / "S7-01-B-B-r0" / "calls.jsonl").is_file()
    assert not (
        tmp_path / "report" / "dry_run" / "runs" / "S7-01-B-B-r0" / "llm_calls.jsonl"
    ).exists()
    # run again: the cell is settled, nothing runs
    pilot.run(live=False, store=store)
    assert len((store / "results_dry.0.jsonl").read_text().splitlines()) == 1


# ------------------------------------------------------------------ the live flow (mocked)


def test_the_live_flow_end_to_end_on_one_cell_with_a_mocked_client(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner
):
    """The control for the dry run: the live path builds one client, after the approval."""
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    launch = _fake_launch_writing("sensor", ["influent"], 0.5)
    faked_runner(launch)
    pilot.run(live=True)
    # the record as a whole, then this run, were checked before the one client was built
    assert client_spy.count("client") == 1
    assert client_spy.index("client") > client_spy.index("approval")
    assert client_spy[: client_spy.index("client")].count("approval") >= 2
    assert len(launch.gateways) == 1 and isinstance(launch.gateways[0], p2_live.P2AgentGateway)
    assert (launch.gateways[0].max_turns, launch.gateways[0].max_usd) == (240, 1.0)
    rows = [json.loads(x) for x in (store / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert (row["cell"], row["replicate"], row["live"]) == ("S7-01 B/B", 0, True)
    assert row["finished"] and row["decider"] == "live" and row["model_id"] == "gpt-5.6-luna"
    assert (row["label"], row["secondary_labels"], row["confidence"]) == (
        "sensor",
        ["influent"],
        0.5,
    )
    assert row["label_set"] == ["influent", "sensor"]
    assert row["primary_in_truth"] and row["attribution_exact"]
    assert row["cap"]["hit"] is False and row["cap"]["refusals"] == []
    assert row["llm_calls_jsonl"] is True
    assert row["spend"]["usd"] == 0.0 and row["spend"]["requests"] == 0
    assert row["spend"]["attempts"] == 0  # the faked launch sent nothing
    # the meter's rows by role (the faked registry charges one unattributed call)
    assert set(row["spend"]["by_role"]) <= {"unattributed"}
    assert json.loads((store / "spent_usd.json").read_text()) == {"usd": 0.0}
    assert row["frozen"] == FROZEN["agents"]
    # the report
    monkeypatch.setattr(pilot, "REPORT_DIR", tmp_path / "report")
    out = pilot.report(store)
    assert out["attribution_exact"] == "1 of 1 scored" and out["both_faults_named"] == 1
    assert out["usd_total"] == 0.0 and out["cap_hits"] == []
    assert (tmp_path / "report" / "runs" / "S7-01-B-B-r0" / "llm_calls.jsonl").is_file()
    # a second start runs nothing: the cell is settled, and no client is built
    before = list(client_spy)
    pilot.run(live=True)
    assert client_spy.count("client") == before.count("client")


def test_a_cap_hit_stops_the_run_and_is_recorded(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5, cap=True))
    pilot.run(live=True)
    row = json.loads((store / "results.jsonl").read_text().splitlines()[0])
    assert row["outcome"] == "abstain" and row["rule"] == "abstain:model_cap"
    assert row["cap"]["hit"] and row["cap"]["abstained_on_cap"]
    assert row["cap"]["refusals"] and "max_requests" in row["cap"]["refusals"][0]["error"]
    assert row["label_set"] == [] and not row["primary_in_truth"]
    assert row["finished"]  # the run stopped and concluded an abstention: a result
    monkeypatch.setattr(pilot, "REPORT_DIR", tmp_path / "report")
    out = pilot.report(store)
    assert out["cap_hits"] == ["S7-01 B/B r0"] and out["abstained"] == 1
    assert out["primary_in_truth"] == "0 of 0 scored"


def test_a_store_that_already_holds_the_run_is_refused_before_any_client(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner, capsys
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5))
    held = store / "runs" / "run_S7-01_B_B_0" / "workflows" / "p2"
    held.mkdir(parents=True)
    (held / "llm_calls.jsonl").write_text("")
    pilot.run(live=True)
    assert "STOP: S7-01 B/B r0: the store already holds run_S7-01_B_B_0 (a model log)" in (
        capsys.readouterr().out
    )
    assert "client" not in client_spy
    assert not (store / "results.jsonl").exists()


def test_an_unfinished_live_run_stops_the_pilot_and_is_never_rerun(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner, capsys
):
    """A launch that leaves no report: recorded unfinished, the pilot stops, no rerun."""
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)

    def dead(script: Any, registry: Any, **kw: Any) -> Any:
        return types.SimpleNamespace(returncode=1, stderr="killed")

    faked_runner(dead)
    pilot.run(live=True)
    assert client_spy.count("client") == 1
    unfinished = [json.loads(x) for x in (store / "unfinished.jsonl").read_text().splitlines()]
    assert len(unfinished) == 1 and unfinished[0]["status"] == "unfinished_live"
    assert len(unfinished[0]["attempts"]) == 1  # one attempt, no live rerun
    assert not (store / "results.jsonl").exists()
    # a restart is refused on the unfinished record: no second client
    pilot.run(live=True)
    assert client_spy.count("client") == 1
    assert "needs the lead's approval" in capsys.readouterr().out


# ------------------------------------------------------------------ the lead's "B" (12 Nov)

NO_CREDITS = (
    "RateLimitError: Error code: 429 - You have no credits remaining. Add credits to "
    "continue using the API at https://platform.openai.com/settings/organization/billing/."
)
AUTH = "AuthenticationError: Error code: 401 - Incorrect API key provided."
TRANSIENT = "RateLimitError: Error code: 429 - Rate limit reached for requests. Try again in 2s."
OK = {"error": "", "response": {"usage": {"input_tokens": 3, "output_tokens": 300}}}


def _err(text: str) -> dict[str, Any]:
    return {"error": text, "response": None}


class Killed(BaseException):
    """A container restart: the driver dies mid-run, nothing after it is written."""


@pytest.fixture
def two_seeds(monkeypatch):
    monkeypatch.setattr(pilot, "CELLS", ONE_CELL)
    monkeypatch.setattr(pilot, "REPLICATES", (0, 1))


def _model_log(run_dir: Path, calls: list[dict[str, Any]]) -> None:
    out = run_dir / "workflows" / "p2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))


def _interrupted(store: Path, rep: int = 0, attempt: int = 1) -> str:
    """A run the driver started and a restart cut off: a journal start, a partial log."""
    from scripts.p2_rerun import InFlight

    rid = f"run_S7-01_B_B_{rep}"
    _model_log(store / "runs" / rid, [OK, OK])
    InFlight(store / "in_flight.jsonl").start("S7-01 B/B", rep, attempt, rid)
    return rid


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_model_unreachable_reads_the_runs_own_model_log(tmp_path):
    run_dir = tmp_path / "run_x"
    assert pilot.model_unreachable(run_dir) is None  # no log: the offline model
    cases = {
        "no credits, among successes": ([OK, OK, _err(NO_CREDITS)], NO_CREDITS),
        "an auth error": ([_err(AUTH), OK], AUTH),
        "a quota error": ([OK, _err("Error code: 429 - insufficient_quota")], "insufficient"),
        "a permission error": ([_err("PermissionDeniedError: Error code: 403")], "403"),
    }
    for name, (calls, quoted) in cases.items():
        _model_log(run_dir, calls)
        got = pilot.model_unreachable(run_dir)
        assert got is not None and quoted in got, name
    _model_log(run_dir, [_err(TRANSIENT), _err("APIConnectionError: Connection error.")])
    got = pilot.model_unreachable(run_dir)
    assert got and got.startswith("every attempt failed (2 of 2)") and "Connection" in got
    # the controls: successes with one transient failure; a cap refusal only; an empty log
    _model_log(run_dir, [OK, _err(TRANSIENT), OK])
    assert pilot.model_unreachable(run_dir) is None
    _model_log(run_dir, [{"refused": True, "error": "max_requests: 200 reached"}])
    assert pilot.model_unreachable(run_dir) is None
    _model_log(run_dir, [])
    assert pilot.model_unreachable(run_dir) is None


@pytest.mark.parametrize(
    ("calls", "quoted"),
    [
        ([_err(NO_CREDITS)] * 4 + [OK], "You have no credits remaining"),
        ([OK, _err(AUTH)], "Incorrect API key provided"),
        ([_err(TRANSIENT)] * 3, "every attempt failed (3 of 3)"),
    ],
    ids=["no-credits-429", "auth-error", "all-attempts-failed"],
)
def test_an_unreachable_model_is_unfinished_never_scored_and_stops_the_pilot(
    tmp_path, monkeypatch, two_seeds, approved_test_store, client_spy, faked_runner, capsys,
    calls, quoted,
):  # fmt: skip
    """The first start of 11 Nov: every call refused for credits, an abstain scored."""
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    faked_runner(_fake_launch_writing("abstain", [], 0.0, calls=calls))
    pilot.run(live=True)
    out = capsys.readouterr().out
    assert "STOP: S7-01 B/B r0: the model could not be reached: " in out and quoted in out
    assert not (store / "results.jsonl").exists()  # never a result
    (u,) = _rows(store / "unfinished.jsonl")
    assert (u["cell"], u["replicate"], u["status"]) == ("S7-01 B/B", 0, "model_unreachable")
    assert quoted in u["error"] and quoted in u["attempts"][0]["error"]
    assert u["attempts"][0]["failure_reason"] == "model_unreachable"
    assert client_spy.count("client") == 1  # the pilot stopped: r1 never ran
    assert "START S7-01 B/B r1" not in out
    # a restart is refused on the unfinished record: no second client, still no result
    pilot.run(live=True)
    assert "needs the lead's approval" in capsys.readouterr().out
    assert client_spy.count("client") == 1 and not (store / "results.jsonl").exists()


def test_a_run_with_successes_and_one_transient_failure_is_scored(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner
):
    """The control: a transient failure among successful calls is not unreachable."""
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5, calls=[OK, _err(TRANSIENT), OK]))
    pilot.run(live=True)
    (row,) = _rows(store / "results.jsonl")
    assert row["finished"] and row["attribution_exact"] and "unreachable" not in row
    assert not (store / "unfinished.jsonl").exists()


def test_restart_eligible_holds_the_limit_of_one_twice(tmp_path):
    """The journal shows one attempt only, and no restart is recorded: both must hold."""
    from scripts.p2_rerun import InFlight

    store = tmp_path
    one = [{"run_id": "run_a", "attempt": 1}]
    assert pilot.restart_eligible(store, "S7-01 B/B", 0, one)  # the control
    assert not pilot.restart_eligible(store, "S7-01 B/B", 0, [*one, {"run_id": "run_a"}])
    assert not pilot.restart_eligible(store, InFlight.TORN[0], InFlight.TORN[1], one)
    (store / "restarts.jsonl").write_text(
        json.dumps({"cell": "S7-01 B/B", "replicate": 0, "run_id": "run_a"}) + "\n"
    )
    assert not pilot.restart_eligible(store, "S7-01 B/B", 0, one)
    assert pilot.restart_eligible(store, "S7-01 B/B", 1, one)  # another run is unaffected


def test_a_run_cut_off_by_a_restart_is_redone_once_and_scored_on_the_record(
    tmp_path, monkeypatch, two_seeds, approved_test_store, client_spy, faked_runner, capsys
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    rid = _interrupted(store, rep=0)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5, calls=[OK]))
    pilot.run(live=True)
    out = capsys.readouterr().out
    assert f"RESTART S7-01 B/B r0: {rid} set aside" in out
    # the interrupted run set aside whole, under its recorded name, never deleted
    kept = store / "set_aside" / f"{rid}.restart-1"
    assert (kept / "workflows" / "p2" / "llm_calls.jsonl").read_text().count("\n") == 2
    (r,) = pilot.restarts(store)
    assert (r["cell"], r["replicate"], r["run_id"], r["attempt"]) == ("S7-01 B/B", 0, rid, 1)
    assert r["set_aside"] == str(kept) and r["ruling"] == "the lead's B of 12 Nov"
    assert r["time"] and r["usd_charged"] == 1.0 and r["model_calls"] == 2
    # redone once, through every gate (the approval before the one client, a fresh run dir)
    rows = _rows(store / "results.jsonl")
    assert [(x["replicate"], x["attempt"]) for x in rows] == [(0, 2), (1, 1)]
    assert rows[0]["finished"] and rows[0]["restart"] == r and rows[1]["restart"] is None
    assert client_spy.count("client") == 2 and client_spy.index("approval") < client_spy.index(
        "client"
    )
    assert not (store / "unfinished.jsonl").exists()
    # (c) the ledger: the set-aside run at its whole cap, plus the two runs' own spend
    assert json.loads((store / "spent_usd.json").read_text()) == {"usd": 1.0}
    # the report lists the restart
    monkeypatch.setattr(pilot, "REPORT_DIR", tmp_path / "report")
    assert pilot.report(store)["restarts"] == [r]
    assert (
        "Restarted (the lead's B of 12 Nov): S7-01 B/B r0"
        in (tmp_path / "report" / "summary.md").read_text()
    )


def test_a_second_interruption_of_the_same_run_is_unfinished_and_stops(
    tmp_path, monkeypatch, two_seeds, approved_test_store, client_spy, faked_runner, capsys
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    _interrupted(store, rep=0)

    def dies(script: Any, registry: Any, **kw: Any) -> Any:
        _model_log(kw["run_dir"], [OK])
        raise Killed  # the container restarts again, during the redo

    faked_runner(dies)
    with pytest.raises(Killed):
        pilot.run(live=True)
    assert len(pilot.restarts(store)) == 1 and client_spy.count("client") == 1
    capsys.readouterr()
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5))
    pilot.run(live=True)
    out = capsys.readouterr().out
    assert "STOP: S7-01 B/B r0 was left unfinished by a stopped pilot" in out
    assert "RESTART" not in out and len(pilot.restarts(store)) == 1  # never redone twice
    (u,) = _rows(store / "unfinished.jsonl")
    assert u["status"] == "unfinished_live" and len(u["attempts"]) == 2
    assert client_spy.count("client") == 1  # no client after the second interruption
    assert not (store / "results.jsonl").exists()


def test_a_finished_run_is_never_redone(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner, capsys
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5))
    pilot.run(live=True)
    assert len(_rows(store / "results.jsonl")) == 1
    capsys.readouterr()
    pilot.run(live=True)
    assert "RESTART" not in capsys.readouterr().out
    assert not (store / "restarts.jsonl").exists() and not (store / "set_aside").exists()
    assert len(_rows(store / "results.jsonl")) == 1 and client_spy.count("client") == 1


def test_the_ledger_counts_a_set_aside_run_and_the_ceiling_never_resets(
    tmp_path, monkeypatch, one_cell, approved_test_store, client_spy, faked_runner, capsys
):
    """One run approved (USD 1.00 in all): its set-aside attempt leaves no room for a redo."""
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    assert pilot.max_total_usd() == 1.0
    _interrupted(store, rep=0)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5))
    pilot.run(live=True)
    out = capsys.readouterr().out
    assert "RESTART S7-01 B/B r0" in out
    assert "STOP: USD 1.000 spent; one more run could pass 1.00" in out
    assert json.loads((store / "spent_usd.json").read_text()) == {"usd": 1.0}
    assert "client" not in client_spy and not (store / "results.jsonl").exists()


def test_every_gate_applies_to_a_redo_and_a_refusal_sets_nothing_aside(
    tmp_path, monkeypatch, two_seeds, approved_test_store, client_spy, faked_runner, capsys
):
    store = approved_test_store
    monkeypatch.setattr(pilot, "approved_store", lambda: store)
    rid = _interrupted(store, rep=0)
    faked_runner(_fake_launch_writing("sensor", ["influent"], 0.5))

    def thawed(arm: str) -> Any:
        raise ValueError("the agent freeze does not hold")

    monkeypatch.setattr(pilot, "h4_frozen", thawed)
    pilot.run(live=True)
    assert "STOP: S7-01 B/B r0 refused before any run: the agent freeze" in capsys.readouterr().out
    # nothing set aside, the redo not spent, no client: the interrupted run still waits
    assert (store / "runs" / rid / "workflows" / "p2" / "llm_calls.jsonl").is_file()
    assert not (store / "set_aside").exists() and pilot.restarts(store) == []
    assert "client" not in client_spy and not (store / "spent_usd.json").exists()
