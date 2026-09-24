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
