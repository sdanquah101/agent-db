"""The declared background's driver (docs/decisions.md 2026-09-30, decision 1). Experimenter side.

This script is the *benchmark*, not a workflow. It generates seeded **clean** Level-0
records on every plant with the same harness every cell uses, reads each record the way
a workflow reads it (the run view: the tier's sensors, the feed log, the redacted
manifest), and runs one declared, fixed-size procedure through the registry of each run,
so that every call is budgeted and logged like a workflow's:

1. ``describe_model``, ``feed_loads``, ``simulate`` at the defaults;
2. ``mass_balance`` over ``balance_window_d`` windows inside the calibration window;
3. P0's screening on the objective channels (P0's calibration channels the tier
   carries, P0's declared-noise weights): ``gsa_morris`` at P0's ruled size (4
   trajectories, the mean over the calibration window, ``seeds.morris``) and P0's Morris
   rule (mu* over the largest mu* of that output on any output at least
   ``morris_min_relative``, at most ``subset_max`` kept, at least ``subset_min``); then
   ``fisher_info`` at the defaults on the kept set and P0's identifiability rule
   (relative CRLB at most ``max_relative_crlb``, a null direction drops, at least
   ``subset_min`` stay by rank). Sobol takes its declared fallback (``docs/p0_design.md``
   §4: "skip Sobol and take the Morris subset"), so the band's screening is P0's ladder
   with its middle rung at the fallback; the Fisher-only bottom rung was tried first and
   found degenerate on twenty parameters (every direction null at tier A);
4. ``fit_lsq`` on the approved subset from the defaults (P0's ruled sizes: one start, 40
   evaluations, ``seeds.lsq``), then ``simulate`` at the optimum;
5. the standardised residual ``(observed - predicted) / declared sd`` of every sensor of
   the tier over the calibration window, at the defaults and at the optimum: its mean
   (``mean_z``) and root mean square (``rms_z``), P1's ``sim_summary`` arithmetic.

No data-QC step, no quarantine: every observed sample of the calibration window enters,
so the band is what a record shows *before* any cleaning (a workflow that quarantines
spikes sees a slightly tighter record than the band describes). No assay is requested.
The sizes are fixed, never the measured rate, so the same seeds give the same band on any
machine (rule 4). Nothing under ``truth_store/`` is read by this script: the registry's
privileged side opens it as it does for every workflow, and every number below is a tool
output on the visible record.

Plant A is generated on **both** its declared community states (``adapted``,
``unadapted``) and its band pools them: the band is per plant and tier, and which state
a run is in is not declared to a workflow (ruling B5), so a band per state would leak it.

The band is **per plant and tier only** (rule 1): the seeds are the benchmark's own,
disjoint from the library's; nothing per cell or per scenario enters the configuration.

    python -m scripts.declared_background generate --store <dir>
    python -m scripts.declared_background compute  --store <dir> --part 0/3
    python -m scripts.declared_background publish  --store <dir>
    python -m scripts.declared_background card

``publish`` writes the per-run record under ``reports/background/`` (``runs.jsonl``,
``runs.csv``, each run's visible ``calls.jsonl``), aggregates it into
``configs/background.yaml`` and regenerates the benchmark card's section; a test
regenerates the yaml from the record and compares.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "background"
RECORD_FILE = REPORT_DIR / "runs.jsonl"
CONFIG_FILE = REPO / "configs" / "background.yaml"
CARD_FILE = REPO / "docs" / "benchmark_card.md"
CARD_BEGIN = "<!-- BEGIN GENERATED: declared background -->"
CARD_END = "<!-- END GENERATED: declared background -->"

SCENARIO_ID = "S0-01"
"""The clean Level-0 row; staged on every plant at the plant's horizon."""

SEEDS: tuple[int, ...] = tuple(range(900001, 900011))
"""The background's own base seeds, ten per truth group (the lead's ruling of 2026-09-30,
``docs/decisions.md``): disjoint from every seed of the library (tested). Fixed before any
result of seeds 900004-900010 and never chosen by where a development cell falls."""

FIRST_SEEDS = 3
"""The seeds computed first, whose band is published PROVISIONAL while the rest run."""

PLANT_BASELINES: dict[str, tuple[str | None, ...]] = {
    "A": ("adapted", "unadapted"),
    "B": (None,),
    "C": (None,),
}
"""The declared community states each plant is generated on (None: the plant's default)."""

TIERS: tuple[str, ...] = ("A", "B", "C")

BUDGET = {"simulator_evals": 300, "wall_clock_min": 360.0, "assay_units": 0}
"""The envelope of one background run (the registry enforces it): the procedure's bound is
under 160 evaluations (Morris 84, Fisher at most 8, the fit at most 57, two simulations),
and no assay is ever requested."""

DEV_FIRST: tuple[tuple[str, str | None, str], ...] = (
    ("B", None, "A"),
    ("B", None, "B"),
    ("B", None, "C"),
    ("C", None, "B"),
    ("A", "adapted", "A"),
)
"""The (plant, baseline, tier) combinations the development cells need, computed first."""

MODEL = "adm1_fitted"


@dataclass(frozen=True)
class BackgroundRun:
    """One clean generator run of the background: where it is staged and its seed."""

    plant: str
    baseline: str | None
    tier: str
    seed: int

    @property
    def key(self) -> str:
        """``B-A-900001`` or ``A.adapted-A-900001``: the run's name in the record."""
        stage = self.plant if self.baseline is None else f"{self.plant}.{self.baseline}"
        return f"{stage}-{self.tier}-{self.seed}"

    @property
    def stage(self) -> str:
        """``B``, or ``A.adapted``: the plant and declared state the run is staged on."""
        return self.plant if self.baseline is None else f"{self.plant}.{self.baseline}"

    @property
    def group(self) -> tuple[str, str | None, int]:
        """The (plant, baseline, seed) whose tiers share one truth integration."""
        return (self.plant, self.baseline, self.seed)


def runs_root(store: Path, run: BackgroundRun) -> Path:
    """The run store of a run: one per Plant A state, one shared by Plants B and C.

    ``<store>/runs`` for Plants B and C, whose run ids differ by plant;
    ``<store>/<stage>/runs`` for each declared state of Plant A.

    A run id is keyed by (scenario, plant, tier, seed, replicate) and NOT by the declared
    community state, so Plant A's two states at one tier and seed would share one run
    directory (and one truth) in a single store, the second generation overwriting the
    first. That happened (found 2026-10-02): every Plant A run of the first computation
    measured the unadapted state under both keys. One store per stage gives each its own
    salt, run ids and truth store (``truth_store_for`` is the store's sibling), and
    :func:`check_index` refuses a collision.
    """
    return store / "runs" if run.baseline is None else store / run.stage / "runs"


def check_index(index: dict[str, str]) -> None:
    """Refuse an index in which two runs of one stage share a run id.

    Raises:
        RuntimeError: Naming the colliding keys.
    """
    seen: dict[tuple[str, str], str] = {}
    by_key = {run.key: run for run in all_runs()}
    for key, rid in index.items():
        stage = by_key[key].stage if key in by_key else key.split("-", 1)[0]
        other = seen.setdefault((stage, rid), key)
        if other != key:
            raise RuntimeError(f"{key} and {other} share run id {rid} in stage {stage}")


def all_runs() -> list[BackgroundRun]:
    """Every background run, the development cells' combinations first."""
    runs = [
        BackgroundRun(plant, baseline, tier, seed)
        for plant, baselines in PLANT_BASELINES.items()
        for baseline in baselines
        for tier in TIERS
        for seed in SEEDS
    ]

    def rank(run: BackgroundRun) -> tuple[int, int, int, str]:
        combo = (run.plant, run.baseline, run.tier)
        first = DEV_FIRST.index(combo) if combo in DEV_FIRST else len(DEV_FIRST)
        late = int(SEEDS.index(run.seed) >= FIRST_SEEDS)
        return (late, first, SEEDS.index(run.seed), run.key)

    return sorted(runs, key=rank)


# ------------------------------------------------------------------ the procedure's settings


def procedure_settings() -> dict[str, Any]:
    """The procedure's every size, window and seed, read from the frozen P0 and P1 files.

    P0's calibration channels, weights, windows, identifiability rule, subset sizes and
    fit sizes (``configs/workflows/p0.yaml``) and P1's balance window
    (``configs/workflows/p1.yaml``): the band is computed with the rules the workflows
    run with, and nothing here is a number of its own.
    """
    from tools.workflow_config import load_p0, load_p1

    p0, p1 = load_p0(), load_p1()
    return {
        "scenario": SCENARIO_ID,
        "seeds": list(SEEDS),
        "plant_a_baselines": list(PLANT_BASELINES["A"]),
        "calibration_start_d": float(p0.windows.calibration_start_d),
        "holdout_fraction": float(p0.windows.holdout_fraction),
        "balance_window_d": float(p1.defaults.balance_window_d),
        "min_relative_sd": float(p0.calibration.min_relative_sd),
        "sd_floor_abs": float(p0.calibration.sd_floor_abs),
        "objective_channels": list(p0.calibration.channels),
        "screening": "P0's ladder, Sobol at its declared fallback: gsa_morris at P0's "
        "ruled size on the objective channels' calibration-window means, P0's Morris "
        "rule (mu* over the largest mu* of that output, on any output, at least "
        "morris_min_relative; at most subset_max kept; at least subset_min), then "
        "fisher_info at the defaults on the kept set with P0's identifiability rule "
        "(relative CRLB at most max_relative_crlb; a null direction drops; at least "
        "subset_min stay by rank)",
        "morris_trajectories": int(p0.gsa.morris_trajectories),
        "morris_min_relative": float(p0.screening.morris_min_relative),
        "morris_seed": int(p0.seeds.morris),
        "gsa_summary": str(p0.gsa.summary),
        "max_relative_crlb": float(p0.identifiability.max_relative_crlb),
        "subset_max": int(p0.screening.morris_keep),
        "subset_min": int(p0.screening.min_subset),
        "fit": "fit_lsq from the defaults on the screened subset",
        "lsq_starts": int(p0.fit.lsq_starts),
        "lsq_max_nfev_per_start": int(p0.fit.lsq_max_nfev_per_start),
        "fit_seed": int(p0.seeds.lsq),
        "budget_simulator_evals": int(BUDGET["simulator_evals"]),
        "budget_wall_clock_min": float(BUDGET["wall_clock_min"]),
    }


def background_scenario(plant_id: str, baseline: str | None):
    """The clean row staged on ``plant_id`` at its horizon, on ``baseline``, with the budget."""
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.matrix import at_plant_horizon

    scenario = at_plant_horizon(
        load_scenario(REPO / "scenarios" / f"{SCENARIO_ID}.yaml"), load_plant_config(plant_id)
    )
    budget = scenario.budget.model_copy(update=dict(BUDGET))
    return scenario.model_copy(update={"baseline": baseline, "budget": budget})


def git_commit() -> str:
    """The repository's commit, marked ``-dirty`` when the tree has changes."""
    from tools.runner import git_commit as _commit

    return _commit()


# ------------------------------------------------------------------ generate


def _index_path(store: Path) -> Path:
    return store / "background" / "index.json"


def read_index(store: Path) -> dict[str, str]:
    """Run key -> run id of what ``generate`` wrote into ``store``."""
    path = _index_path(store)
    if not path.is_file():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def generate(store: Path, only: Sequence[str] | None = None) -> dict[str, str]:
    """Generate every background run into ``store`` (one truth per plant, baseline, seed)."""
    from sim.plants import load_plant_config
    from sim.run.harness import generate_cells

    index = read_index(store)
    groups: dict[tuple[str, str | None, int], list[BackgroundRun]] = {}
    for run in all_runs():
        if only and run.key not in only:
            continue
        groups.setdefault(run.group, []).append(run)
    for (plant_id, baseline, seed), runs in groups.items():
        todo = [r for r in runs if r.key not in index]
        if not todo:
            continue
        scenario = background_scenario(plant_id, baseline)
        started = time.perf_counter()
        artifacts = generate_cells(
            scenario,
            load_plant_config(plant_id),
            [r.tier for r in todo],
            seed=seed,
            runs_root=runs_root(store, todo[0]),
        )
        for run, art in zip(todo, artifacts, strict=True):
            if not art.truth.solver_success:
                raise RuntimeError(f"{run.key}: the truth did not integrate ({art.truth})")
            if not art.truth.health.sound:
                raise RuntimeError(f"{run.key}: the clean run is not a sound digester")
            index[run.key] = art.run_id
        check_index(index)
        _index_path(store).parent.mkdir(parents=True, exist_ok=True)
        _index_path(store).write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
        print(
            f"generated {plant_id}{'.' + baseline if baseline else ''} seed {seed}: "
            f"{[r.tier for r in todo]} in {time.perf_counter() - started:.0f} s",
            flush=True,
        )
    return index


# ------------------------------------------------------------------ compute


def _round(x: Any) -> float | None:
    """Six significant digits, None for a non-finite value."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.6g}")


class _Series:
    """One sensor with P0's weights (declared noise, floored), calibration window only."""

    def __init__(self, name: str, raw: dict[str, Any], cv: float, sd_abs: float, cal: dict) -> None:
        self.name = name
        self.channel = str(raw["channel"])
        self.unit = str(raw["unit"])
        self.t = np.asarray(raw["sample_t_d"], dtype=float)
        self.value = np.array(
            [np.nan if v is None else float(v) for v in raw["value"]], dtype=float
        )
        finite = self.value[np.isfinite(self.value)]
        scale = float(np.median(np.abs(finite))) if finite.size else 1.0
        floor = max(float(cal["min_relative_sd"]) * scale, float(cal["sd_floor_abs"]))
        sd = np.sqrt((cv * np.abs(np.nan_to_num(self.value))) ** 2 + sd_abs**2)
        self.sd = np.maximum(sd, floor)

    def mask(self, window: tuple[float, float]) -> np.ndarray:
        return np.isfinite(self.value) & (self.t >= window[0]) & (self.t <= window[1])

    def observed(self, window: tuple[float, float]) -> dict[str, Any]:
        keep = (self.t >= window[0]) & (self.t <= window[1])
        return {
            "output": self.channel,
            "t": self.t[keep],
            "value": self.value[keep],
            "sd": self.sd[keep],
            "unit": self.unit,
        }

    def summary(self, sim: Any, window: tuple[float, float]) -> dict[str, Any] | None:
        """``mean_z`` and ``rms_z`` against a ``simulate`` output (P1's ``sim_summary``)."""
        if self.channel not in sim.outputs:
            return None
        m = self.mask(window)
        if int(m.sum()) < 1:
            return None
        t_model = np.asarray(sim.t, dtype=float)
        pred = np.interp(self.t[m], t_model, np.asarray(sim.outputs[self.channel], dtype=float))
        z = (self.value[m] - pred) / self.sd[m]
        return {
            "n": int(m.sum()),
            "mean_z": _round(z.mean()),
            "rms_z": _round(math.sqrt(float(np.mean(z**2)))),
        }


def compute_one(
    store: Path,
    run: BackgroundRun,
    run_id: str,
    *,
    root: Path | None = None,
    scenario: Any = None,
) -> dict[str, Any]:
    """The declared procedure on one run, through its registry.

    ``root`` and ``scenario`` default to the background's own; the development-cell
    placement (:func:`dev_cells`) passes a library cell's, with the same budget.
    """
    from sim.observation import load_observation_config
    from sim.plants import declared_geometry, load_plant_config
    from state.run_view import open_run
    from tools import open_registry

    settings = procedure_settings()
    scenario = scenario or background_scenario(run.plant, run.baseline)
    started = time.perf_counter()
    root = root or runs_root(store, run)
    registry = open_registry(run_id, runs_root=root, scenario=scenario)
    view = open_run(root / run_id)
    if manifest_baseline(root, run_id) != (run.baseline or default_baseline(run.plant)):
        raise RuntimeError(f"{run.key}: the stored record is not staged on its declared state")
    manifest = view.manifest
    if str(manifest.plant) != run.plant or str(manifest.tier) != run.tier:
        raise RuntimeError(f"{run.key}: the run's manifest says {manifest.plant}/{manifest.tier}")
    horizon = float(manifest.duration_days)
    cal = (
        float(settings["calibration_start_d"]),
        horizon * (1.0 - float(settings["holdout_fraction"])),
    )
    noise = load_observation_config().sensors
    weights = {
        "min_relative_sd": settings["min_relative_sd"],
        "sd_floor_abs": settings["sd_floor_abs"],
    }
    record = view.sensors()["sensors"]
    series = {
        name: _Series(
            name,
            record[name],
            float(noise[name].noise.cv),
            float(noise[name].noise.sd_abs),
            weights,
        )
        for name in sorted(record)
    }
    objective = [s for name, s in series.items() if name in set(settings["objective_channels"])]

    desc = registry.call("describe_model", model=MODEL)
    loads = registry.call("feed_loads", model=MODEL)
    baseline = registry.call("simulate", model=MODEL)
    at_defaults = {name: s.summary(baseline, cal) for name, s in series.items()}

    # the balance over the calibration window, P1's convention
    width = float(settings["balance_window_d"])
    windows = []
    start = cal[0]
    while start + width <= cal[1] + 1e-9:
        windows.append({"start": start, "end": start + width})
        start += width
    geometry = declared_geometry(load_plant_config(run.plant))
    temp = series.get("temperature")
    t_op = float(geometry.T_op)
    if temp is not None:
        finite = temp.value[temp.mask(cal)]
        if finite.size:
            t_op = float(finite.mean())

    def obs(name: str) -> dict[str, Any] | None:
        s = series.get(name)
        return None if s is None else s.observed(cal)

    balance = registry.call(
        "mass_balance",
        windows=windows,
        t=np.asarray(loads.t),
        q_in_m3_d=np.asarray(loads.q_m3_d),
        cod_in_kg_d=np.asarray(loads.cod_kg_d),
        tkn_in_kg_n_d=np.asarray(loads.tkn_kg_n_d),
        charge_in_keq_d=np.asarray(loads.charge_keq_d),
        gas_flow=obs("gas_flow"),
        ch4_fraction=obs("ch4_fraction"),
        cod_out=obs("cod_total"),
        tan_out=obs("tan"),
        ph=obs("ph"),
        alkalinity=obs("alkalinity"),
        vfa=obs("vfa_total"),
        V_liq_m3=float(geometry.V_liq),
        T_op_K=t_op,
    )
    cod = [w.cod_closure for w in balance.windows if w.cod_closure is not None]
    n_cl = [w.n_closure for w in balance.windows if w.n_closure is not None]
    balance_record = {
        "n_windows": len(balance.windows),
        "n_cod_evaluable": len(cod),
        "n_cod_inadmissible": sum(1 for w in balance.windows if w.cod_admissible is False),
        "cod_closure_windows": [_round(c) for c in cod],
        "cod_closure_mean": _round(np.mean(cod)) if cod else None,
        "n_closure_mean": _round(np.mean(n_cl)) if n_cl else None,
        "charge_drift": _round(balance.charge_drift),
        "charge_consistent": balance.charge_consistent,
        "admissible": bool(balance.admissible),
    }

    # P0's screening (docs/p0_design.md §3.2-3.3), Sobol at its declared fallback: Morris
    # at the ruled size and P0's Morris rule, then Fisher at the defaults on the kept set
    params = list(desc.parameter_names)
    lower = dict(zip(params, np.asarray(desc.lower, dtype=float), strict=True))
    upper = dict(zip(params, np.asarray(desc.upper, dtype=float), strict=True))
    data = [s.observed(cal) for s in objective]
    morris = registry.call(
        "gsa_morris",
        model=MODEL,
        parameters=params,
        outputs=[s.channel for s in objective],
        summary=str(settings["gsa_summary"]),
        window={"start": cal[0], "end": cal[1]},
        n_trajectories=int(settings["morris_trajectories"]),
        seed=int(settings["morris_seed"]),
    )
    scores: dict[str, float] = {}
    for res in morris.results:
        mu = np.asarray(res.mu_star, dtype=float)
        top = float(np.nanmax(mu)) if np.isfinite(mu).any() and np.nanmax(mu) > 0 else 1.0
        for name, v in zip(morris.parameters, mu, strict=True):
            scores[name] = max(scores.get(name, 0.0), float(v) / top if math.isfinite(v) else 0.0)
    ranking = sorted(params, key=lambda n: -scores.get(n, 0.0))
    kept = [n for n in ranking if scores.get(n, 0.0) >= float(settings["morris_min_relative"])]
    kept = kept[: int(settings["subset_max"])]
    if len(kept) < int(settings["subset_min"]):
        kept = ranking[: int(settings["subset_min"])]

    fim = registry.call("fisher_info", model=MODEL, data=data, parameters=kept, at={})
    relative: dict[str, float | None] = {}
    for name, sd in zip(fim.parameters, np.asarray(fim.crlb_sd, dtype=float), strict=True):
        relative[name] = float(sd / (upper[name] - lower[name])) if math.isfinite(sd) else None
    limit = float(settings["max_relative_crlb"])
    ok = [n for n in kept if relative[n] is not None and relative[n] <= limit]
    if len(ok) < int(settings["subset_min"]):
        ok = sorted(kept, key=lambda n: relative[n] if relative[n] is not None else np.inf)[
            : int(settings["subset_min"])
        ]
    approved = [n for n in kept if n in ok]
    dropped = [n for n in kept if n not in ok]

    fit = registry.call(
        "fit_lsq",
        model=MODEL,
        data=data,
        parameters=approved,
        n_starts=int(settings["lsq_starts"]),
        max_nfev_per_start=int(settings["lsq_max_nfev_per_start"]),
        seed=int(settings["fit_seed"]),
    )
    optimum = {n: float(v) for n, v in zip(fit.parameters, np.asarray(fit.theta), strict=True)}
    fitted = registry.call("simulate", model=MODEL, parameters=optimum)
    after_fit = {name: s.summary(fitted, cal) for name, s in series.items()}

    channels = {}
    for name, s in series.items():
        if at_defaults[name] is None or after_fit[name] is None:
            continue
        channels[name] = {
            "channel": s.channel,
            "unit": s.unit,
            "in_objective": name in {o.name for o in objective},
            "n": at_defaults[name]["n"],
            "at_defaults": {k: at_defaults[name][k] for k in ("mean_z", "rms_z")},
            "after_fit": {k: after_fit[name][k] for k in ("mean_z", "rms_z")},
        }
    remaining = registry.remaining()
    return {
        "key": run.key,
        "plant": run.plant,
        "baseline": run.baseline,
        "tier": run.tier,
        "seed": run.seed,
        "run_id": run_id,
        "horizon_d": horizon,
        "calibration_window": [cal[0], cal[1]],
        "balance_window_d": width,
        "sensors": sorted(series),
        "objective": [o.name for o in objective],
        "balance": balance_record,
        "screening": {
            "morris_scores": {n: _round(v) for n, v in scores.items()},
            "morris_ranking": ranking,
            "morris_kept": kept,
            "relative_crlb": {n: _round(v) for n, v in relative.items()},
            "fisher_dropped": dropped,
            "approved": approved,
        },
        "fit": {
            "parameters": list(fit.parameters),
            "optimum": {n: _round(v) for n, v in optimum.items()},
            "chi2": _round(fit.chi2),
            "n_data": int(fit.n_data),
            "at_bound": list(fit.at_bound),
            "converged": bool(fit.converged),
            "message": str(fit.message),
            "n_evaluations": int(fit.n_evaluations),
        },
        "channels": channels,
        "evaluations_used": int(registry.evaluations_used),
        "n_calls": int(remaining.n_calls),
        "wall_s": round(time.perf_counter() - started, 1),
        "git_commit": git_commit(),
    }


def default_baseline(plant_id: str) -> str | None:
    """The plant's declared default community state (None for a plant that declares none)."""
    from sim.plants import load_plant_config

    declared = load_plant_config(plant_id).baseline(None)
    return None if declared is None else declared.name


def manifest_baseline(root: Path, run_id: str) -> str | None:
    """The community state the stored run was generated on.

    Experimenter side: the complete manifest, which a workflow never reads.
    """
    from sim.run.layout import RunPaths, truth_store_for

    paths = RunPaths.for_run(run_id, root, truth_store_for(root))
    return json.loads(paths.truth_manifest.read_text(encoding="utf-8")).get("baseline")


def _result_path(store: Path, run: BackgroundRun) -> Path:
    return store / "background" / "results" / f"{run.key}.json"


def compute(store: Path, part: str = "0/1", only: Sequence[str] | None = None) -> None:
    """Run the procedure on every generated run of this part; skip the ones already done."""
    index = read_index(store)
    i, k = (int(x) for x in part.split("/"))
    for n, run in enumerate(all_runs()):
        if n % k != i or (only and run.key not in only):
            continue
        if run.key not in index:
            print(f"SKIP {run.key}: not generated", flush=True)
            continue
        dest = _result_path(store, run)
        if dest.is_file():
            print(f"DONE {run.key}", flush=True)
            continue
        print(f"START {run.key} ({index[run.key]})", flush=True)
        result = compute_one(store, run, index[run.key])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"END {run.key}: {result['evaluations_used']} evaluations in {result['wall_s']:.0f} s; "
            f"fitted {result['fit']['parameters']}; closure "
            f"{result['balance']['cod_closure_mean']}",
            flush=True,
        )


# ------------------------------------------------------------------ aggregate / publish


def _stat(values: Iterable[float | None]) -> dict[str, Any] | None:
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not xs:
        return None
    arr = np.asarray(xs, dtype=float)
    return {
        "n": int(arr.size),
        "mean": _round(arr.mean()),
        "sd": _round(arr.std(ddof=1)) if arr.size > 1 else None,
        "min": _round(arr.min()),
        "max": _round(arr.max()),
    }


def _int_stat(values: Iterable[int]) -> dict[str, Any]:
    xs = [int(v) for v in values]
    return {"n": len(xs), "mean": _round(np.mean(xs)), "min": min(xs), "max": max(xs)}


def worst_window(record: dict[str, Any]) -> float | None:
    """The closure of a run's window with the largest |closure|, sign kept (None: no window).

    The lead's ruling of 2026-09-30 publishes it as its own statistic of the band.
    """
    windows = [float(c) for c in record["balance"]["cod_closure_windows"] if c is not None]
    if not windows:
        return None
    return max(windows, key=abs)


def complete_seeds(records: Sequence[dict[str, Any]]) -> list[int]:
    """The seeds every one of whose declared runs has a record, in declared order."""
    have = {r["key"] for r in records}
    return [s for s in SEEDS if all(run.key in have for run in all_runs() if run.seed == s)]


def aggregate(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """The bands, per plant and tier, from the per-run records (Plant A's baselines pooled).

    Raises:
        ValueError: If the runs of one (plant, tier) disagree on the horizon, the window
            or the sensor set, which would make the band a mixture of two records.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in records:
        groups.setdefault((str(rec["plant"]), str(rec["tier"])), []).append(rec)
    bands: dict[str, dict[str, dict[str, Any]]] = {}
    for (plant, tier), runs in sorted(groups.items()):
        horizons = {float(r["horizon_d"]) for r in runs}
        windows = {tuple(r["calibration_window"]) for r in runs}
        widths = {float(r["balance_window_d"]) for r in runs}
        n_windows = {int(r["balance"]["n_windows"]) for r in runs}
        sensors = {tuple(r["sensors"]) for r in runs}
        if len(horizons) != 1 or len(windows) != 1 or len(widths) != 1 or len(n_windows) != 1:
            raise ValueError(f"{plant}/{tier}: the runs disagree on horizon or windows")
        if len(sensors) != 1:
            raise ValueError(f"{plant}/{tier}: the runs disagree on the sensor set")
        evaluable = [int(r["balance"]["n_cod_evaluable"]) for r in runs]
        any_cod = any(e > 0 for e in evaluable)
        charge = [r["balance"]["charge_consistent"] for r in runs]
        charge_known = [c for c in charge if c is not None]
        fitted: dict[str, int] = {}
        for r in runs:
            for name in r["fit"]["parameters"]:
                fitted[name] = fitted.get(name, 0) + 1
        channels = {}
        for name in sensors.pop():
            per = [r["channels"][name] for r in runs if name in r["channels"]]
            if len(per) != len(runs):
                raise ValueError(f"{plant}/{tier}: {name} is missing from a run's channels")
            channels[name] = {
                "channel": per[0]["channel"],
                "unit": per[0]["unit"],
                "in_objective": bool(per[0]["in_objective"]),
                "n_samples": _int_stat(p["n"] for p in per),
                "at_defaults": {
                    "mean_z": _stat(p["at_defaults"]["mean_z"] for p in per),
                    "rms_z": _stat(p["at_defaults"]["rms_z"] for p in per),
                },
                "after_fit": {
                    "mean_z": _stat(p["after_fit"]["mean_z"] for p in per),
                    "rms_z": _stat(p["after_fit"]["rms_z"] for p in per),
                },
            }
        start, end = windows.pop()
        bands.setdefault(plant, {})[tier] = {
            "n_runs": len(runs),
            "horizon_d": horizons.pop(),
            "calibration_window": {"start": float(start), "end": float(end)},
            "balance_window_d": widths.pop(),
            "n_cod_windows": n_windows.pop(),
            "n_cod_evaluable": _int_stat(evaluable) if any_cod else None,
            "n_cod_inadmissible": (
                _int_stat(int(r["balance"]["n_cod_inadmissible"]) for r in runs)
                if any_cod
                else None
            ),
            "cod_closure": _stat(r["balance"]["cod_closure_mean"] for r in runs),
            "cod_closure_windows": _stat(
                c for r in runs for c in r["balance"]["cod_closure_windows"]
            ),
            "cod_closure_worst": _stat(worst_window(r) for r in runs),
            "n_closure": _stat(r["balance"]["n_closure_mean"] for r in runs),
            "charge_drift": _stat(r["balance"]["charge_drift"] for r in runs),
            "charge_consistent_fraction": (
                _round(sum(1 for c in charge_known if c) / len(charge_known))
                if charge_known
                else None
            ),
            "n_fitted": _int_stat(len(r["fit"]["parameters"]) for r in runs),
            "fitted_parameters": dict(sorted(fitted.items())),
            "fit_at_bound_fraction": _round(
                sum(1 for r in runs if r["fit"]["at_bound"]) / len(runs)
            ),
            "channels": channels,
        }
    return bands


def read_record(path: Path = RECORD_FILE) -> list[dict[str, Any]]:
    """The committed per-run record."""
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


CSV_COLUMNS = [
    "key", "plant", "baseline", "tier", "seed", "run_id", "horizon_d", "n_cod_windows",
    "n_cod_evaluable", "n_cod_inadmissible", "cod_closure_mean", "charge_drift",
    "charge_consistent", "fitted", "chi2", "at_bound", "gas_flow_mean_z_defaults",
    "gas_flow_rms_z_defaults", "gas_flow_mean_z_fit", "gas_flow_rms_z_fit",
    "evaluations_used", "n_calls", "wall_s", "git_commit",
]  # fmt: skip


def _csv_row(rec: dict[str, Any]) -> dict[str, Any]:
    gas = rec["channels"].get("gas_flow", {})
    return {
        "key": rec["key"], "plant": rec["plant"], "baseline": rec["baseline"] or "",
        "tier": rec["tier"], "seed": rec["seed"], "run_id": rec["run_id"],
        "horizon_d": rec["horizon_d"], "n_cod_windows": rec["balance"]["n_windows"],
        "n_cod_evaluable": rec["balance"]["n_cod_evaluable"],
        "n_cod_inadmissible": rec["balance"]["n_cod_inadmissible"],
        "cod_closure_mean": rec["balance"]["cod_closure_mean"],
        "charge_drift": rec["balance"]["charge_drift"],
        "charge_consistent": rec["balance"]["charge_consistent"],
        "fitted": "+".join(rec["fit"]["parameters"]), "chi2": rec["fit"]["chi2"],
        "at_bound": "+".join(rec["fit"]["at_bound"]),
        "gas_flow_mean_z_defaults": gas.get("at_defaults", {}).get("mean_z"),
        "gas_flow_rms_z_defaults": gas.get("at_defaults", {}).get("rms_z"),
        "gas_flow_mean_z_fit": gas.get("after_fit", {}).get("mean_z"),
        "gas_flow_rms_z_fit": gas.get("after_fit", {}).get("rms_z"),
        "evaluations_used": rec["evaluations_used"], "n_calls": rec["n_calls"],
        "wall_s": rec["wall_s"], "git_commit": rec["git_commit"],
    }  # fmt: skip


def render_config(bands: dict[str, dict[str, dict[str, Any]]], provenance: dict[str, Any]) -> str:
    """``configs/background.yaml`` as text: a header, the procedure, the provenance, the bands."""
    from tools.config import BackgroundConfig

    payload = {
        "version": 1,
        "procedure": procedure_settings(),
        "provenance": provenance,
        "bands": bands,
    }
    BackgroundConfig.model_validate(payload)  # never write what the loader would refuse
    header = (
        "# The declared background (docs/decisions.md 2026-09-30, decision 1): the null band\n"
        "# of a CLEAN record, per plant and tier, under the tools' own fitted model.\n"
        "# GENERATED by `python -m scripts.declared_background publish` from the per-run\n"
        "# record reports/background/runs.jsonl; do not edit by hand (a test regenerates\n"
        "# it from the record and compares). Schema: tools/config.py::BackgroundConfig.\n"
        "# Served by the registry tool `declared_background` (tools/background.py); read\n"
        "# by P2's verifier and influent role; never by P0 or the frozen P1.\n"
        "#\n"
        "# Keyed by plant and tier ONLY (rule 1): the seeds are the benchmark's own and the\n"
        "# band carries nothing per cell or per scenario. Plant A pools its two declared\n"
        "# community states. Units: the z quantities are multiples of the declared\n"
        "# measurement sd over the calibration window; closures are fractions of the load\n"
        "# fed over a window; counts are counts; windows are days.\n"
    )
    return header + yaml.safe_dump(payload, sort_keys=False, width=100, allow_unicode=True)


def publish(store: Path) -> None:
    """Write the record under ``reports/background/``, the yaml and the card section."""
    index = read_index(store)
    records = []
    for run in all_runs():
        path = _result_path(store, run)
        if path.is_file():
            records.append(json.loads(path.read_text(encoding="utf-8")))
    seeds = complete_seeds(records)
    if not seeds:
        raise SystemExit("no seed has all its runs computed yet")
    # only complete seeds are published: a band is never a mixture of partial seeds
    records = sorted((r for r in records if r["seed"] in seeds), key=lambda r: r["key"])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "calls").mkdir(exist_ok=True)
    with RECORD_FILE.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    with (REPORT_DIR / "runs.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rec in records:
            writer.writerow(_csv_row(rec))
    for rec in records:
        # the visible projection of the run's log: what a workflow's own log would show
        run = next(r for r in all_runs() if r.key == rec["key"])
        src = runs_root(store, run) / index[rec["key"]] / "calls.jsonl"
        shutil.copyfile(src, REPORT_DIR / "calls" / f"{rec['key']}.calls.jsonl")
    bands = aggregate(records)
    provenance = {
        "git_commit": git_commit(),
        "computed": datetime.now(UTC).strftime("%Y-%m-%d"),
        "record": "reports/background/runs.jsonl",
        "n_runs": len(records),
        "evaluations": int(sum(r["evaluations_used"] for r in records)),
        "status": "FINAL" if seeds == list(SEEDS) else "PROVISIONAL",
        "seeds": seeds,
    }
    CONFIG_FILE.write_text(render_config(bands, provenance), encoding="utf-8")
    card()
    done = sorted({(r["plant"], r["tier"]) for r in records})
    print(f"{len(records)} runs -> {CONFIG_FILE.relative_to(REPO)}; bands for {done}")


# ------------------------------------------------------------------ the card


def _fmt(stat: dict[str, Any] | None, digits: int = 3) -> str:
    if stat is None:
        return "n/a"
    return f"{stat['mean']:.{digits}g} [{stat['min']:.{digits}g}, {stat['max']:.{digits}g}]"


def render_card_section(config: Any) -> str:
    """The benchmark card's generated tables from a loaded ``BackgroundConfig``."""
    p = config.provenance
    lines = [
        f"**Status: {p.status}.** {p.n_runs} clean runs, seeds "
        f"{', '.join(str(s) for s in p.seeds)} ({len(p.seeds)} of the declared "
        f"{len(config.procedure.seeds)} per truth group; Plant A pools its two declared "
        "states). The band is the **min-max envelope** over the runs (the lead's ruling of "
        "2026-09-30); the mean beside each envelope is for reading only.",
        "",
        "| plant / tier | runs | COD closure, per-run mean: mean [min, max] | worst window: "
        "mean [min, max] | inadmissible windows [min, max] of n | charge drift [min, max] "
        "| charge-consistent share | parameters fitted (runs) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for plant in sorted(config.bands):
        for tier in sorted(config.bands[plant]):
            b = config.bands[plant][tier]
            bad = (
                "n/a"
                if b.n_cod_inadmissible is None
                else f"[{b.n_cod_inadmissible.min}, {b.n_cod_inadmissible.max}] of "
                f"{b.n_cod_windows}"
            )
            worst = _fmt(None if b.cod_closure_worst is None else b.cod_closure_worst.model_dump())
            fitted = ", ".join(f"{k} ({v})" for k, v in b.fitted_parameters.items())
            share = b.charge_consistent_fraction
            share_text = "n/a" if share is None else f"{share:.2f}"
            closure = _fmt(None if b.cod_closure is None else b.cod_closure.model_dump())
            drift = _fmt(None if b.charge_drift is None else b.charge_drift.model_dump())
            lines.append(
                f"| {plant} / {tier} | {b.n_runs} | {closure} | {worst} | {bad} | {drift} "
                f"| {share_text} | {fitted} |"
            )
    lines += [
        "",
        "Per-channel envelope, **after the screened fit**: `mean_z` [min, max] and `rms_z` "
        "[min, max] over the clean runs (multiples of the declared measurement sd, "
        "calibration window). The same table at the default parameters, and the sd per "
        "statistic, are in `configs/background.yaml`.",
        "",
        "| plant / tier | channel: mean_z [min, max]; rms_z [min, max] |",
        "|---|---|",
    ]
    for plant in sorted(config.bands):
        for tier in sorted(config.bands[plant]):
            b = config.bands[plant][tier]
            cells = []
            for name, ch in b.channels.items():
                mz, rz = ch.after_fit.mean_z, ch.after_fit.rms_z
                cells.append(
                    f"{name}: {mz.mean:+.2f} [{mz.min:+.2f}, {mz.max:+.2f}]; "
                    f"{rz.mean:.2f} [{rz.min:.2f}, {rz.max:.2f}]"
                )
            lines.append(f"| {plant} / {tier} | {'; '.join(cells)} |")
    return "\n".join(lines)


def card() -> None:
    """Regenerate the benchmark card's declared-background tables between the markers."""
    from tools.config import load_background

    text = CARD_FILE.read_text(encoding="utf-8")
    if CARD_BEGIN not in text or CARD_END not in text:
        raise SystemExit(f"{CARD_FILE} has no declared-background markers")
    head, rest = text.split(CARD_BEGIN, 1)
    _, tail = rest.split(CARD_END, 1)
    section = render_card_section(load_background())
    CARD_FILE.write_text(f"{head}{CARD_BEGIN}\n{section}\n{CARD_END}{tail}", encoding="utf-8")


# ------------------------------------------------------------------ the development cells

DEV_CELLS: tuple[tuple[str, str, str], ...] = (
    ("S0-01", "B", "A"),
    ("S0-01", "B", "B"),
    ("S0-01", "B", "C"),
    ("S1-01", "B", "B"),
)
"""The clean development cells of the P2 launch brief (truth `none`). They are NOT inputs
to the band (the lead's ruling of 2026-09-30); they are measured with the same procedure
only to report where each falls relative to the band as published."""

DEV_FILE = REPORT_DIR / "dev_cells.json"


def dev_cells(store: Path) -> list[dict[str, Any]]:
    """Generate each clean development cell at its library seed and run the procedure on it.

    The cell is generated by the harness exactly as the matrix generates it (its own
    scenario, its library seed, the plant's horizon), into ``<store>/dev/runs``, and the
    procedure runs through its own registry with the background's budget. Results are
    cached under ``<store>/dev/results``.
    """
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run
    from sim.run.matrix import at_plant_horizon

    root = store / "dev" / "runs"
    out = []
    for sid, plant_id, tier in DEV_CELLS:
        dest = store / "dev" / "results" / f"{sid}-{plant_id}-{tier}.json"
        if dest.is_file():
            out.append(json.loads(dest.read_text(encoding="utf-8")))
            continue
        plant = load_plant_config(plant_id)
        scenario = at_plant_horizon(load_scenario(REPO / "scenarios" / f"{sid}.yaml"), plant)
        scenario = scenario.model_copy(
            update={"budget": scenario.budget.model_copy(update=dict(BUDGET))}
        )
        art = generate_run(scenario, tier, plant=plant, runs_root=root)
        run = BackgroundRun(plant_id, None, tier, int(scenario.seed))
        print(f"START dev {sid} {plant_id}/{tier} ({art.run_id})", flush=True)
        rec = compute_one(store, run, art.run_id, root=root, scenario=scenario)
        rec["key"] = f"{sid} {plant_id}/{tier}"
        rec["scenario"] = sid
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        out.append(rec)
    return out


def placement(record: dict[str, Any], band: Any) -> list[dict[str, Any]]:
    """Each published statistic of one run against the band of its (plant, tier).

    ``inside`` is ``min <= value <= max``: the min-max envelope exactly as published,
    with no margin (the lead's ruling of 2026-09-30). A statistic the band or the run
    does not have is reported with ``inside`` None.
    """
    rows = []

    def row(statistic: str, value: Any, stat: Any) -> None:
        if value is None or stat is None:
            rows.append({"statistic": statistic, "value": value, "band_min": None,
                         "band_max": None, "inside": None})  # fmt: skip
            return
        lo, hi = float(stat.min), float(stat.max)
        rows.append({"statistic": statistic, "value": float(value), "band_min": lo,
                     "band_max": hi, "inside": bool(lo <= float(value) <= hi)})  # fmt: skip

    b = record["balance"]
    row("cod_closure", b["cod_closure_mean"], band.cod_closure)
    row("cod_closure_worst", worst_window(record), band.cod_closure_worst)
    if band.n_cod_inadmissible is not None and b["n_cod_evaluable"]:
        row("n_cod_inadmissible", b["n_cod_inadmissible"], band.n_cod_inadmissible)
    row("charge_drift", b["charge_drift"], band.charge_drift)
    for name, ch in sorted(record["channels"].items()):
        ref = band.channels.get(name)
        for where in ("at_defaults", "after_fit"):
            for stat in ("mean_z", "rms_z"):
                ref_stat = None if ref is None else getattr(getattr(ref, where), stat)
                row(f"{name}.{where}.{stat}", ch[where][stat], ref_stat)
    return rows


def place(store: Path) -> dict[str, Any]:
    """Where each clean development cell falls relative to the committed band: a finding.

    Reads the committed ``configs/background.yaml`` and nothing derived from the cells;
    writes ``reports/background/dev_cells.json``.
    """
    from tools.config import load_background

    config = load_background()
    cells = []
    for rec in dev_cells(store):
        band = config.band(rec["plant"], rec["tier"])
        rows = placement(rec, band)
        judged = [r for r in rows if r["inside"] is not None]
        cells.append(
            {
                "cell": rec["key"],
                "band_status": config.provenance.status,
                "band_seeds": list(config.provenance.seeds),
                "n_statistics": len(judged),
                "n_outside": sum(1 for r in judged if not r["inside"]),
                "outside": [r["statistic"] for r in judged if not r["inside"]],
                "rows": rows,
                "evaluations_used": rec["evaluations_used"],
            }
        )
    out = {"rule": "min-max envelope as published, no margin (the lead's ruling of "
           "2026-09-30)", "cells": cells}  # fmt: skip
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DEV_FILE.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for c in cells:
        print(f"{c['cell']}: {c['n_outside']} of {c['n_statistics']} outside: {c['outside']}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "action", choices=["generate", "compute", "publish", "card", "list", "place"]
    )
    parser.add_argument("--store", type=Path, default=None, help="root of the background store")
    parser.add_argument("--part", default="0/1", help="i/k: compute every k-th run from the i-th")
    parser.add_argument("--only", action="append", default=None, help="run key (repeatable)")
    args = parser.parse_args(argv)
    if args.action == "list":
        for run in all_runs():
            print(run.key)
        return 0
    if args.action == "card":
        card()
        return 0
    if args.store is None:
        parser.error(f"{args.action} needs --store")
    store = Path(args.store).resolve()
    if REPO in store.parents or store == REPO:
        parser.error("the background store must lie outside the repository")
    if args.action == "generate":
        generate(store, args.only)
    elif args.action == "compute":
        compute(store, args.part, args.only)
    elif args.action == "place":
        place(store)
    else:
        publish(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
