"""The privileged side: the registry of a generated run.

This is the module that reads what a workflow may not: the truth store's index (which
scenario a run is, hence its budget), the complete manifest (the observation seed the
registry's own seed is derived from), ``faults.json`` (the Level-8 directive),
``parameters.json`` (the extensions the fitted model carries) and ``channels.npz`` (what
requested assays are sampled from). None of it leaves this process: the workflow, in its
own process (:mod:`tools.sandbox`), sees the registry's answers only.

The registry's seed is ``SeedSequence([observation seed, key("registry")])`` -- a keyed
child of one of the run's five streams (:mod:`sim.run.seeds` is frozen with G1 and gains no
sixth stream), so two registries of one run draw the same assay noise and the same Level-8
pattern (rule 4), and two runs draw different ones.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from scenarios.schema import Scenario, load_scenario
from sim.plants import load_plant_config
from sim.run.artifacts import read_feed_log
from sim.run.layout import INDEX_FILE, RUNS_ROOT, RunPaths, truth_store_for
from sim.run.manifest import RunManifest
from tools.assays import AssayServer
from tools.fitted import FittedADM1
from tools.impl import SPECS
from tools.registry import Budget, Registry, ToolFailure, stream_key

__all__ = ["open_registry", "registry_seed"]

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def registry_seed(observation_seed: int) -> int:
    """The registry's seed for a run, a keyed child of the run's observation stream."""
    seq = np.random.SeedSequence([int(observation_seed), stream_key("registry")])
    return int(seq.generate_state(1, dtype=np.uint32)[0])


def _scenario_of(run_id: str, truth_store: Path, scenarios_dir: Path) -> Scenario:
    index = truth_store / INDEX_FILE
    if not index.is_file():
        raise FileNotFoundError(f"{index} does not exist; the run's cell is unknown")
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("run_id") == run_id:
            return load_scenario(scenarios_dir / f"{entry['scenario_id']}.yaml")
    raise KeyError(f"run {run_id!r} is not in {index}")


def open_registry(
    run_id: str,
    *,
    runs_root: Path = RUNS_ROOT,
    truth_store: Path | None = None,
    scenario: Scenario | None = None,
    scenarios_dir: Path = SCENARIOS_DIR,
    clock: Callable[[], float] = time.monotonic,
) -> Registry:
    """Open the registry of a generated run.

    Args:
        run_id: The opaque run id.
        runs_root: Root of the run store.
        truth_store: Root of the truth store (default: the sibling of ``runs_root``).
        scenario: The run's scenario, if the caller already holds it; otherwise it is
            looked up through the truth-side index.
        scenarios_dir: Where the scenario files live.
        clock: The wall clock the budget is enforced against.

    Returns:
        The registry, with ``adm1_fitted`` registered, the assay channel attached, the
        Level-8 directive loaded and both logs open in append mode.
    """
    store = truth_store_for(runs_root) if truth_store is None else Path(truth_store)
    paths = RunPaths.for_run(run_id, runs_root, store)
    if not paths.truth_manifest.is_file():
        raise FileNotFoundError(f"{paths.truth_manifest} does not exist")
    manifest = RunManifest.read(paths.truth_manifest)
    if scenario is None:
        scenario = _scenario_of(run_id, store, scenarios_dir)
    faults = json.loads(paths.truth_faults.read_text(encoding="utf-8"))
    directives = [ToolFailure(str(t), float(p)) for t, p in faults["workflow"]["tool_failure"]]
    parameters = json.loads(paths.truth_parameters.read_text(encoding="utf-8"))
    fitted_extensions = tuple(parameters["fitted_extensions"])

    plant = load_plant_config(manifest.plant)
    feed_log = read_feed_log(paths.feed_log)
    model = FittedADM1(
        plant=plant,
        feed_log=feed_log,
        extensions=fitted_extensions,
        horizon_d=float(manifest.duration_days),
    )
    seed = registry_seed(int(manifest.seeds["observation"]))
    assays = AssayServer.from_truth_store(paths.truth, seed=seed)
    return Registry(
        specs=SPECS,
        budget=Budget.of(scenario.budget),
        seed=seed,
        run_dir=paths.root,
        truth_log_dir=paths.truth,
        tool_failures=directives,
        models={"adm1_fitted": model},
        assay_server=assays,
        clock=clock,
    )
