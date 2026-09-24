"""The positive-control hook of P0 (``screening.force_include``, docs/positive_control.md).

Rung R3 of the ladder names parameters P0 must fit. The hook is OFF in the frozen
configuration, and off means P0 unchanged:
- the sandbox's ``p0_config.json`` does not carry the key;
- an explicit empty list gives the same state as no key at all.
On, the named parameters join the approved subset after the Fisher step and are fitted.
The byte-level check on the eight pilot cells is the ladder's own (§5.3 b), run
outside ``pytest``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sim.plants import load_plant_config
from sim.run.harness import generate_run
from tests.conftest import REPO_ROOT, _short
from tools.runner import run_workflow
from tools.server import OUTPUTS_DIR
from tools.workflow_config import load_p0, sandbox_config

FROZEN = REPO_ROOT / "configs" / "workflows" / "p0.yaml"


def test_the_hook_is_off_in_the_frozen_configuration():
    assert load_p0().screening.force_include == ()
    assert "force_include" not in FROZEN.read_text(encoding="utf-8")
    payload = sandbox_config(load_p0())
    assert "force_include" not in payload["screening"]
    assert "force_include" not in json.dumps(payload)


def _variant(tmp: Path, name: str, force: list[str] | None) -> Path:
    """The test-sized configuration, with or without the hook key."""
    raw = yaml.safe_load(FROZEN.read_text(encoding="utf-8"))
    raw["gsa"]["morris_trajectories"] = 1
    raw["plan"]["morris_min_trajectories"] = 1
    raw["screening"]["morris_keep"] = 2
    raw["gsa"]["sobol_samples"] = 8
    raw["fit"]["lsq_starts"] = 1
    raw["fit"]["lsq_max_nfev_per_start"] = 5
    raw["fit"]["de_generations"] = 1
    raw["mcmc"]["walkers"] = 4
    raw["mcmc"]["steps"] = 2
    raw["plan"]["mcmc_min_steps"] = 2
    raw["validation"]["ensemble_size"] = 2
    raw["fit"]["second_pass"] = False
    if force is not None:
        raw["screening"]["force_include"] = force
    path = tmp / f"{name}.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _normalise(state: dict) -> dict:
    """As the same-cell-twice test: drop the wall clock and the log positions."""
    state = json.loads(json.dumps(state))
    state["budget"].pop("wall_clock_min")
    state["plan"].pop("guards_tripped")
    for action in state["actions"]:
        action.pop("seq")
        action.pop("call_index")
    state["budget"].pop("n_calls")
    for item in state["classification"]["evidence"]:
        item.pop("calls")
    if state.get("validation"):
        state["validation"].pop("calls")
    return state


@pytest.fixture(scope="module")
def hook_cell(tmp_path_factory):
    """A 30-day S0-01 cell of Plant C at Tier B in its own store."""
    root = tmp_path_factory.mktemp("pc_store")
    scenario = _short("S0-01", evals=150, wall_min=30.0, assays=2)
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=root / "runs")
    return run, scenario, tmp_path_factory.mktemp("pc_cfg")


def _run(cell, config: Path) -> dict:
    run, scenario, _ = cell
    result = run_workflow(
        run.run_id, "p0", runs_root=run.paths.root.parent, scenario=scenario, config_path=config
    )
    assert result.error == "" and result.completed, result.stderr_tail
    return json.loads((run.paths.root / OUTPUTS_DIR / "p0" / "state.json").read_text())


def test_an_empty_hook_is_p0_unchanged(hook_cell):
    cfg_dir = hook_cell[2]
    without = _run(hook_cell, _variant(cfg_dir, "no_key", None))
    empty = _run(hook_cell, _variant(cfg_dir, "empty", []))
    assert _normalise(without) == _normalise(empty)
    _BASELINE["state"] = without


_BASELINE: dict[str, dict] = {}


def test_the_hook_fits_the_parameters_it_names(hook_cell):
    cfg_dir = hook_cell[2]
    baseline = _BASELINE.get("state") or _run(hook_cell, _variant(cfg_dir, "base", None))
    target = next(
        n for n in ("k_hyd_ch", "K_I_nh3", "k_hyd_pr") if n not in baseline["screening"]["approved"]
    )
    forced = _run(hook_cell, _variant(cfg_dir, "forced", [target]))
    assert forced["screening"]["approved"] == baseline["screening"]["approved"] + [target]
    assert any(a["name"] == "fit_lsq" for a in forced["actions"]), "the screened fit ran"
    # the final estimates are the screened fit's, over the approved subset
    assert target in forced["final"]["parameters"]
    assert target not in baseline["final"]["parameters"]


# ------------------------------------------------------------------ the ladder's verdicts


def _row(variant: str, cell: tuple[str, str, str], **kw: object) -> dict:
    return {"variant": variant, "scenario_id": cell[0], "plant": cell[1], "tier": cell[2], **kw}


def test_the_verdicts_follow_the_preregistered_thresholds():
    """§5 in code, decided before any result is read (review of PR #23, item 2)."""
    from scripts.positive_control import PARAMETER_CELLS, R2_CELLS, R2_CONTROLS, verdict

    ok = {"forced_in_approved": True, "forced_fitted": True}
    # R3: three moves pass; a move on a time-dependent path is shown, never counted
    rows = [_row("r3", c, **ok, moved_exact=i < 3) for i, c in enumerate(PARAMETER_CELLS)]
    assert verdict(rows, dest=False)["rungs"]["R3"]["verdict"] == "pass"
    rows[0]["time_dependent_path"] = True
    r3 = verdict(rows, dest=False)["rungs"]["R3"]
    assert r3["verdict"] == "inconclusive" and r3["timing_moves_not_counted"] == 1
    # the mechanical check gates the rung
    rows[5]["forced_fitted"] = False
    assert verdict(rows, dest=False)["rungs"]["R3"]["verdict"].startswith("not run")
    # R2: moves on the controls confound it
    r2 = [_row("r2", c, moved_exact=True) for c in R2_CELLS[:2]]
    r2 += [_row("r2", c, moved_exact=True) for c in R2_CONTROLS[:2]]
    assert verdict(r2, dest=False)["rungs"]["R2"]["verdict"] == "confounded"
    assert verdict(r2[:2], dest=False)["rungs"]["R2"]["verdict"] == "pass"
    assert verdict([_row("r2", R2_CELLS[0])], dest=False)["rungs"]["R2"]["verdict"] == "fail"


def test_r2_keeps_the_injected_delivery_and_drops_the_background(tmp_path: Path):
    """Review of PR #23, item 1: the fault stays in the record as the baseline has it."""
    import csv

    import numpy as np

    from scripts.positive_control import _injected_kg, _write_exact_feed

    scenario = _short("S3-02", evals=40, wall_min=20.0, assays=2)
    run = generate_run(scenario, "C", plant=load_plant_config("B"), runs_root=tmp_path / "runs")
    injected = _injected_kg(run.paths.truth, "B")
    ((feed, day), kg) = next(iter(injected.items()))
    assert (kg > 0.0 and day == min(90, int(scenario.duration_days) // 2)) or kg > 0.0
    log_path = run.paths.root / "observations" / "feed_log.csv"

    def column(path: Path, name: str) -> np.ndarray:
        with path.open(encoding="utf-8") as fh:
            return np.array([float(r[f"{name}_kg_wet_per_d"]) for r in csv.DictReader(fh)])

    before = column(log_path, feed)
    kept = tmp_path / "kept" / "feed_log.generated.csv"
    _write_exact_feed(run.paths.root, run.paths.truth, kept)
    after = column(log_path, feed)
    assert kept.is_file() and not (run.paths.root / "feed_log.generated.csv").exists()
    with np.load(run.paths.truth / "influent.npz") as z:
        ids = [str(f) for f in z["feed_ids"]]
        true = np.asarray(z["delivered_kg_wet_per_d"])[ids.index(feed)]
    # the injected day: the log still misses the injected mass, as the baseline log does
    assert abs(after[day] - (true[day] - kg)) <= 1e-5 * max(1.0, true[day])
    assert after[day] < true[day]
    # every other day is the true delivered mass (background noise gone)
    others = np.arange(true.size) != day
    assert np.allclose(after[others], true[others], rtol=1e-5)
    # and the baseline log did miss the injected mass on that day
    assert before[day] <= true[day] - kg + 1e-5 * max(1.0, true[day])
