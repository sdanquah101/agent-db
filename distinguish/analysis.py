"""The admissible label set of one cell (docs/distinguishability.md §2-§3).

Each label is a hypothesis class: the knobs of the fitted model (or of its prediction)
that the label's explanation needs, fitted to the tier's visible record from the
defaults. A label is admissible when its AIC is within a margin of the best class's.
The data are the visible record only. The truth store is read for three things: the
answer key's labels, the injected fault types (for the class-limited flag), and the
fitted model's declared extensions, read as the registry reads them.
"""

from __future__ import annotations

import json
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn

import numpy as np
import yaml
from scipy.optimize import least_squares, minimize_scalar

__all__ = [
    "LABELS",
    "METHOD_VERSION",
    "ClassFit",
    "Series",
    "Simulator",
    "admissible",
    "analyse_pair",
    "class_limited",
    "load_series",
]

METHOD_VERSION = 1
LABELS = ("none", "sensor", "influent", "state", "parameter", "structural")
REPO = Path(__file__).resolve().parents[1]
P0_CONFIG = REPO / "configs" / "workflows" / "p0.yaml"

# §2.1: the Level-5 shifted parameters, then the four P0 approved most often in the sweep
PARAMETER_SUBSET = ("k_hyd_ch", "K_I_nh3", "Y_ac", "k_m_ac", "k_m_h2", "Y_h2")
MARGINS = (2.0, 10.0)
EVAL_TIMEOUT_S = 120
# fit sizes: least_squares evaluations (each Jacobian costs k more simulations)
PARAMETER_MAX_NFEV = 6
INFLUENT_MAX_NFEV = 6
SCALAR_MAX_ITER = 10
SENSOR_ONSETS_EVERY_D = 10.0
BAD_RESIDUAL = 1e3  # a failed or non-finite prediction is a very bad fit, not a crash

# fault types whose truth the fitted model's classes cannot represent (§2.2)
_CLASS_LIMITED = {
    "ammonia_inhibition_shift": "a mid-record parameter change",
    "hydrolysis_regime_change": "a mid-record parameter change",
    "feed_mislabelled": "a time-windowed fractionation change",
    "moisture_drift": "a per-day solids change",
    "stagnant_zone": "a stagnant zone",
}

Sim = dict[str, np.ndarray]


@dataclass
class Series:
    """One calibrated sensor of the visible record: its usable samples and their sd."""

    sensor: str
    channel: str
    t: np.ndarray
    y: np.ndarray
    sd: np.ndarray


@dataclass
class ClassFit:
    """The best representative of one hypothesis class on one tier's record."""

    label: str
    chi2: float
    k: int
    knobs: dict[str, Any] = field(default_factory=dict)
    per_sensor: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def aic(self) -> float:
        """χ² + 2k."""
        return self.chi2 + 2.0 * self.k


def _p0_calibration() -> dict[str, Any]:
    return yaml.safe_load(P0_CONFIG.read_text(encoding="utf-8"))["calibration"]


def _noise() -> dict[str, dict[str, float]]:
    raw = yaml.safe_load((REPO / "configs" / "observation" / "sensors.yaml").read_text("utf-8"))
    out = {}
    for name, spec in raw["sensors"].items():
        noise = spec.get("noise") or {}
        out[name] = {"cv": float(noise.get("cv", 0.0)), "sd_abs": float(noise.get("sd_abs", 0.0))}
    return out


def load_series(sensors_json: Path) -> list[Series]:
    """The tier's calibrated sensors from ``observations/sensors.json``.

    Missing, saturated and flatlined samples are dropped for every class alike (the
    visible record flags them). Temperature is left out, as P0 leaves it out. The sd is
    the declared ``sqrt((cv v)^2 + sd_abs^2)`` with P0's floors.
    """
    cal = _p0_calibration()
    noise = _noise()
    raw = json.loads(sensors_json.read_text(encoding="utf-8"))["sensors"]
    out = []
    for name in cal["channels"]:
        if name not in raw:
            continue
        s = raw[name]
        t = np.asarray(s["sample_t_d"], dtype=float)
        y = np.array([np.nan if v is None else float(v) for v in s["value"]])
        keep = np.isfinite(y)
        for flag in ("flatlined", "saturated"):
            if flag in s:
                keep &= ~np.asarray(s[flag], dtype=bool)
        if not keep.any():
            continue
        t, y = t[keep], y[keep]
        n = noise[name]
        scale = float(np.median(np.abs(y)))
        floor = max(float(cal["min_relative_sd"]) * scale, float(cal["sd_floor_abs"]))
        sd = np.maximum(np.sqrt((n["cv"] * np.abs(y)) ** 2 + n["sd_abs"] ** 2), floor)
        out.append(Series(name, str(s["channel"]), t, y, sd))
    return out


def _residuals(sim: Sim, series: Sequence[Series]) -> tuple[np.ndarray, dict[str, float]]:
    parts, per = [], {}
    for s in series:
        p = np.interp(s.t, sim["t"], np.asarray(sim[s.channel], dtype=float))
        r = (s.y - p) / s.sd
        r = np.where(np.isfinite(r), r, BAD_RESIDUAL)
        parts.append(r)
        per[s.sensor] = float(r @ r)
    return (np.concatenate(parts) if parts else np.zeros(0)), per


def _chi2(sim: Sim | None, series: Sequence[Series]) -> tuple[float, dict[str, float]]:
    if sim is None:
        return float("inf"), {}
    r, per = _residuals(sim, series)
    return float(r @ r), per


class _Timeout(Exception):
    pass


def _alarm(_signum: int, _frame: FrameType | None) -> NoReturn:
    raise _Timeout


class Simulator:
    """The fitted model of one (scenario, plant): its feed log and extensions, and a cache."""

    def __init__(
        self,
        plant_id: str,
        feed_log: Mapping[str, np.ndarray],
        extensions: Sequence[str],
        horizon_d: float,
    ) -> None:
        """Hold what every variant of the model is built from."""
        from sim.plants import load_plant_config

        self.plant = load_plant_config(plant_id)
        self.feed_log = {k: np.asarray(v, dtype=float) for k, v in feed_log.items()}
        self.extensions = tuple(extensions)
        self.horizon_d = float(horizon_d)
        self.n_sims = 0
        self.timeouts = 0
        self._cache: dict[Any, Sim | None] = {}

    def model(
        self,
        *,
        feed_scale: Mapping[str, float] | None = None,
        extensions: Sequence[str] | None = None,
        volume_scale: float = 1.0,
    ) -> Any:
        """A ``FittedADM1`` with the given variant (construction is arithmetic only)."""
        from tools.fitted import FittedADM1

        plant = self.plant
        if volume_scale != 1.0:
            geometry = plant.geometry.model_copy(
                update={"V_liq_declared": plant.geometry.V_liq_declared * float(volume_scale)}
            )
            plant = plant.model_copy(update={"geometry": geometry})
        log = self.feed_log
        if feed_scale:
            log = {k: v * float(feed_scale.get(k, 1.0)) for k, v in log.items()}
        return FittedADM1(
            plant=plant,
            feed_log=log,
            extensions=self.extensions if extensions is None else tuple(extensions),
            horizon_d=self.horizon_d,
        )

    def run(
        self,
        key: Any,
        build: Callable[[], Any],
        theta: np.ndarray | None = None,
        **options: object,
    ) -> Sim | None:
        """One simulation (cached by ``key``), or None on a solver failure or a timeout."""
        if key in self._cache:
            return self._cache[key]
        model = build()
        th = model.defaults.copy() if theta is None else theta
        self.n_sims += 1
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(EVAL_TIMEOUT_S)
        result: Sim | None
        try:
            out = model.evaluate(th, **options)
            ok, _ = model.last_status()
            result = {"t": np.asarray(model.t, dtype=float), **out} if ok else None
        except _Timeout:
            self.timeouts += 1
            result = None
        except Exception:
            result = None
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        self._cache[key] = result
        return result


def _fit_none(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    chi2, per = _chi2(simr.run(("none",), simr.model), series)
    return ClassFit("none", chi2, 0, {}, per, note="the defaults")


def _sensor_candidates(s: Series, p: np.ndarray) -> list[tuple[float, dict[str, Any]]]:
    """Weighted χ² of one sensor under a scale step after each onset, and a linear drift."""
    w = 1.0 / s.sd**2
    out = []
    for onset in np.arange(0.0, float(s.t.max()), SENSOR_ONSETS_EVERY_D):
        m = s.t >= onset
        den = float(np.sum(w[m] * p[m] ** 2))
        if den <= 0.0:
            continue
        a = float(np.sum(w[m] * p[m] * (s.y[m] - p[m])) / den)
        q = p.copy()
        q[m] = p[m] * (1.0 + a)
        chi2 = float(np.sum(w * (s.y - q) ** 2))
        out.append((chi2, {"kind": "scale_step", "onset_d": float(onset), "a": a}))
    design = np.column_stack([np.ones_like(s.t), s.t])
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(design * sw[:, None], (s.y - p) * sw, rcond=None)
    q = p + design @ coef
    chi2 = float(np.sum(w * (s.y - q) ** 2))
    out.append((chi2, {"kind": "drift", "b0": float(coef[0]), "b1_per_d": float(coef[1])}))
    return out


def _fit_sensor(simr: Simulator, series: Sequence[Series], base: Sim | None) -> ClassFit:
    """One sensor's default prediction rescaled after an onset, or drifting (k = 2)."""
    if base is None:
        return ClassFit("sensor", float("inf"), 2, note="the default prediction failed")
    total0, per0 = _chi2(base, series)
    best: ClassFit | None = None
    for s in series:
        p = np.interp(s.t, base["t"], np.asarray(base[s.channel], dtype=float))
        chi2, knobs = min(_sensor_candidates(s, p), key=lambda c: c[0])
        fit = ClassFit(
            "sensor",
            total0 - per0[s.sensor] + chi2,
            2,
            {"sensor": s.sensor, **knobs},
            {**per0, s.sensor: chi2},
        )
        if best is None or fit.chi2 < best.chi2:
            best = fit
    return best if best is not None else ClassFit("sensor", float("inf"), 2)


def _scalar(
    simr: Simulator,
    series: Sequence[Series],
    tag: str,
    bounds: tuple[float, float],
    build: Callable[[float], tuple[Callable[[], Any], dict[str, object]]],
    xatol: float,
) -> tuple[float, float, dict[str, float]]:
    """A bounded one-dimensional fit on a log scale; returns (value, χ², per sensor)."""

    def sim_at(u: float) -> Sim | None:
        maker, options = build(float(np.exp(u)))
        return simr.run((tag, round(u, 6)), maker, **options)

    res = minimize_scalar(
        lambda u: _chi2(sim_at(u), series)[0],
        bounds=(np.log(bounds[0]), np.log(bounds[1])),
        method="bounded",
        options={"maxiter": SCALAR_MAX_ITER, "xatol": xatol},
    )
    u = float(res.x)
    chi2, per = _chi2(sim_at(u), series)
    return float(np.exp(u)), chi2, per


def _fit_state(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    """``biomass_scale`` in [0.25, 4] (k = 1)."""
    value, chi2, per = _scalar(
        simr, series, "state", (0.25, 4.0), lambda v: (simr.model, {"biomass_scale": v}), 0.02
    )
    return ClassFit("state", chi2, 1, {"biomass_scale": value}, per)


def _lsq(
    series: Sequence[Series],
    n: int,
    lower: np.ndarray,
    upper: np.ndarray,
    make: Callable[[np.ndarray], Sim | None],
    max_nfev: int,
) -> np.ndarray:
    """Bounded least squares on log multipliers, started at 0 (the defaults)."""
    n_res = sum(s.t.size for s in series)

    def resid(u: np.ndarray) -> np.ndarray:
        sim = make(u)
        return np.full(n_res, BAD_RESIDUAL) if sim is None else _residuals(sim, series)[0]

    try:
        res = least_squares(
            resid,
            np.zeros(n),
            bounds=(np.log(lower), np.log(upper)),
            diff_step=0.05,
            max_nfev=max_nfev,
        )
    except Exception:
        return np.zeros(n)
    return np.asarray(res.x, dtype=float)


def _fit_parameter(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    """A constant multiplier on the six parameters of §2.1 (k = 6)."""
    probe = simr.model()
    names = [n for n in PARAMETER_SUBSET if n in probe.parameter_names]
    idx = [probe.parameter_names.index(n) for n in names]

    def make(u: np.ndarray) -> Sim | None:
        theta = probe.defaults.copy()
        theta[idx] = np.exp(u)
        return simr.run(("parameter", tuple(np.round(u, 6))), simr.model, theta)

    lower = np.array([probe.lower[i] for i in idx])
    upper = np.array([probe.upper[i] for i in idx])
    u = _lsq(series, len(names), lower, upper, make, PARAMETER_MAX_NFEV)
    chi2, per = _chi2(make(u), series)
    knobs = dict(zip(names, np.exp(u).tolist(), strict=True))
    return ClassFit("parameter", chi2, len(names), knobs, per)


def _fit_influent(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    """A constant scale on each feed's logged mass, in [0.5, 2] (k = number of feeds)."""
    feeds = sorted(simr.feed_log)

    def make(u: np.ndarray) -> Sim | None:
        scale = dict(zip(feeds, np.exp(u).tolist(), strict=True))
        key = ("influent", tuple(np.round(u, 6)))
        return simr.run(key, lambda: simr.model(feed_scale=scale))

    lower, upper = np.full(len(feeds), 0.5), np.full(len(feeds), 2.0)
    u = _lsq(series, len(feeds), lower, upper, make, INFLUENT_MAX_NFEV)
    chi2, per = _chi2(make(u), series)
    knobs = dict(zip(feeds, np.exp(u).tolist(), strict=True))
    return ClassFit("influent", chi2, len(feeds), knobs, per)


def _fit_structural(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    """The best of: one fitted extension left out (k = 0), the active volume scaled (k = 1)."""
    fits = []
    for ext in simr.extensions:
        rest = tuple(e for e in simr.extensions if e != ext)
        sim = simr.run(("drop", ext), lambda rest=rest: simr.model(extensions=rest))
        chi2, per = _chi2(sim, series)
        fits.append(ClassFit("structural", chi2, 0, {"omit_extension": ext}, per))
    value, chi2, per = _scalar(
        simr,
        series,
        "volume",
        (0.6, 1.4),
        lambda v: ((lambda: simr.model(volume_scale=v)), {}),
        0.01,
    )
    fits.append(ClassFit("structural", chi2, 1, {"volume_scale": value}, per))
    return min(fits, key=lambda c: c.aic)


def admissible(fits: Mapping[str, ClassFit], margin: float) -> list[str]:
    """The labels whose AIC is within ``margin`` of the best class's, in label order."""
    finite = [c.aic for c in fits.values() if np.isfinite(c.aic)]
    if not finite:
        return []
    best = min(finite)
    return [lab for lab in LABELS if lab in fits and fits[lab].aic - best <= margin]


def class_limited(faults: Sequence[Mapping[str, Any]]) -> list[str]:
    """The declared limits (§2.2) that apply to a cell's injected faults."""
    return sorted({_CLASS_LIMITED[f["type"]] for f in faults if f.get("type") in _CLASS_LIMITED})


def _fits(simr: Simulator, series: Sequence[Series], classes: Sequence[str]) -> dict:
    fits: dict[str, ClassFit] = {"none": _fit_none(simr, series)}
    base = simr.run(("none",), simr.model)
    steps: dict[str, Callable[[], ClassFit]] = {
        "sensor": lambda: _fit_sensor(simr, series, base),
        "state": lambda: _fit_state(simr, series),
        "structural": lambda: _fit_structural(simr, series),
        "influent": lambda: _fit_influent(simr, series),
        "parameter": lambda: _fit_parameter(simr, series),
    }
    for label in LABELS[1:]:
        if label in classes:
            fits[label] = steps[label]()
    return fits


def _finite(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def analyse_pair(
    runs: Sequence[tuple[str, Path, Path]],
    *,
    classes: Sequence[str] = LABELS,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    """Every tier of one (scenario, plant). ``runs`` is (run id, run dir, truth dir).

    The tiers share the feed log and the fitted extensions (checked), so a simulation that
    needs no fit (the defaults, an extension left out) is shared. The fits are per tier.
    Returns run id -> the ``admissible.json`` document.
    """
    from sim.run.artifacts import read_feed_log

    first = runs[0]
    public = json.loads((first[1] / "manifest.json").read_text(encoding="utf-8"))
    feed = (first[1] / "observations" / "feed_log.csv").read_bytes()
    params = json.loads((first[2] / "parameters.json").read_text(encoding="utf-8"))
    for _, run_dir, truth_dir in runs[1:]:
        if (run_dir / "observations" / "feed_log.csv").read_bytes() != feed:
            raise ValueError(f"{run_dir}: the tiers of a pair do not share the feed log")
        other = json.loads((truth_dir / "parameters.json").read_text(encoding="utf-8"))
        if other["fitted_extensions"] != params["fitted_extensions"]:
            raise ValueError(f"{truth_dir}: the tiers of a pair differ in extensions")
    simr = Simulator(
        public["plant"],
        read_feed_log(first[1] / "observations" / "feed_log.csv"),
        params["fitted_extensions"],
        public["duration_days"],
    )
    out = {}
    for run_id, run_dir, truth_dir in runs:
        started, n0 = time.perf_counter(), simr.n_sims
        series = load_series(run_dir / "observations" / "sensors.json")
        tier = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["tier"]
        faults = json.loads((truth_dir / "faults.json").read_text(encoding="utf-8"))
        fits = _fits(simr, series, classes)
        truth = [str(x) for x in faults["truth_label"]]
        sets = {f"{m:g}": admissible(fits, m) for m in MARGINS}
        primary = sets[f"{MARGINS[0]:g}"]
        doc = {
            "method_version": METHOD_VERSION,
            "run_id": run_id,
            "scenario_id": faults["scenario_id"],
            "plant": public["plant"],
            "tier": tier,
            "truth_label": truth,
            "n_samples": int(sum(s.t.size for s in series)),
            "sensors": [s.sensor for s in series],
            "margins": list(MARGINS),
            "admissible": sets,
            "admissible_set": primary,
            "truth_admissible": any(t in primary for t in truth),
            "truth_class_limited": class_limited(faults.get("faults", [])),
            "best_label": min(fits.values(), key=lambda c: c.aic).label,
            "classes": {
                lab: {
                    "chi2": _finite(c.chi2),
                    "k": c.k,
                    "aic": _finite(c.aic),
                    "knobs": c.knobs,
                    "chi2_per_sensor": c.per_sensor,
                    "note": c.note,
                }
                for lab, c in fits.items()
            },
            "simulations": simr.n_sims - n0,
            "timeouts_total": simr.timeouts,
            "wall_s": round(time.perf_counter() - started, 1),
        }
        out[run_id] = doc
        log(
            f"{faults['scenario_id']} {public['plant']}/{tier} {run_id}: A={primary} "
            f"truth={truth} sims={doc['simulations']} {doc['wall_s']} s"
        )
    return out
