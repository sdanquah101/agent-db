"""The admissible label set of one cell (docs/distinguishability.md §2-§3).

Each label is a hypothesis class: the knobs of the fitted model (or of its prediction)
that the label's explanation needs. The knobs are fitted, from the defaults, to the
tier's visible record over the calibration window: the hold-out is never read, as P0
never reads it. A label is admissible when its AIC is within a margin of the best
class's. The AIC counts 2 per free parameter, and 2 ln N for a class that picks the best
of N candidates (the look-elsewhere correction).

The truth store is read for four things:
- the answer key's labels;
- the injected faults, to give the truth's own class its representable form (a
  parameter change at its onset, an unrecorded delivery on its day) and to flag the
  cells whose truth no class can represent;
- the fitted model's declared extensions, read as the registry reads them;
- nothing else. The data are the visible record.
"""

from __future__ import annotations

import json
import math
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
    "truth_representable",
]

METHOD_VERSION = 2
LABELS = ("none", "sensor", "influent", "state", "parameter", "structural")
REPO = Path(__file__).resolve().parents[1]
P0_CONFIG = REPO / "configs" / "workflows" / "p0.yaml"

# §2.1: the Level-5 shifted parameters, then the four P0 approved most often in the sweep
PARAMETER_SUBSET = ("k_hyd_ch", "K_I_nh3", "Y_ac", "k_m_ac", "k_m_h2", "Y_h2")
EVAL_TIMEOUT_S = 120
BAD_RESIDUAL = 1e3  # a failed or non-finite prediction is a very bad fit, not a crash

# the parameters each parameter fault shifts (sim/faults/schema.py)
_PARAMETER_SHIFTS = {
    "ammonia_inhibition_shift": ("K_I_nh3",),
    "hydrolysis_regime_change": ("k_hyd_ch", "k_hyd_pr", "k_hyd_li"),
}
# fault types whose truth no class here can represent (§2.2): the cell's admissible
# score is null rather than credited
_UNREPRESENTABLE = {
    "feed_mislabelled": "a time-windowed fractionation change",
    "moisture_drift": "a per-day solids change",
    "stagnant_zone": "a stagnant zone",
}

Sim = dict[str, np.ndarray]


def _cfg() -> Any:
    from eval.config import load_eval_config

    return load_eval_config().distinguishability


def _p0() -> dict[str, Any]:
    return yaml.safe_load(P0_CONFIG.read_text(encoding="utf-8"))


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
    n_candidates: int = 1
    converged: bool | None = None
    status: str = ""

    @property
    def search_penalty(self) -> float:
        """2 ln N for a best-of-N search, when the look-elsewhere correction is on."""
        return 2.0 * math.log(self.n_candidates) if _LOOK_ELSEWHERE[0] else 0.0

    @property
    def aic(self) -> float:
        """χ² + 2k + the search penalty."""
        return self.chi2 + 2.0 * self.k + self.search_penalty


_LOOK_ELSEWHERE = [True]


def _noise() -> dict[str, dict[str, float]]:
    raw = yaml.safe_load((REPO / "configs" / "observation" / "sensors.yaml").read_text("utf-8"))
    out = {}
    for name, spec in raw["sensors"].items():
        noise = spec.get("noise") or {}
        out[name] = {"cv": float(noise.get("cv", 0.0)), "sd_abs": float(noise.get("sd_abs", 0.0))}
    return out


def calibration_end(duration_days: float) -> float:
    """The last day the analysis reads: P0's calibration window ends at the hold-out."""
    return float(duration_days) * (1.0 - float(_p0()["windows"]["holdout_fraction"]))


def load_series(sensors_json: Path, t_end: float) -> list[Series]:
    """The tier's calibrated sensors from ``observations/sensors.json``, up to ``t_end``.

    Missing, saturated and flatlined samples are dropped for every class alike (the
    visible record flags them); temperature is left out, as P0 leaves it out; nothing
    after ``t_end`` (the hold-out) is read. The sd is the declared
    ``sqrt((cv v)^2 + sd_abs^2)`` with P0's floors.
    """
    cal = _p0()["calibration"]
    noise = _noise()
    raw = json.loads(sensors_json.read_text(encoding="utf-8"))["sensors"]
    out = []
    for name in cal["channels"]:
        if name not in raw:
            continue
        s = raw[name]
        t = np.asarray(s["sample_t_d"], dtype=float)
        y = np.array([np.nan if v is None else float(v) for v in s["value"]])
        keep = np.isfinite(y) & (t <= t_end + 1e-9)
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
        feed_add: Mapping[tuple[str, int], float] | None = None,
        extensions: Sequence[str] | None = None,
        volume_scale: float = 1.0,
        onset_d: float | None = None,
    ) -> Any:
        """A fitted model with the given variant (construction is arithmetic only)."""
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
        if feed_add:
            log = {k: v.copy() for k, v in log.items()}
            for (fid, day), kg in feed_add.items():
                log[fid][day] += float(kg)
        kwargs = {
            "plant": plant,
            "feed_log": log,
            "extensions": self.extensions if extensions is None else tuple(extensions),
            "horizon_d": self.horizon_d,
        }
        if onset_d is not None:
            from distinguish.segments import ChangePointADM1

            return ChangePointADM1(onset_d=onset_d, **kwargs)
        return FittedADM1(**kwargs)

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


# ------------------------------------------------------------------ the classes


def _fit_none(simr: Simulator, series: Sequence[Series]) -> ClassFit:
    chi2, per = _chi2(simr.run(("none",), simr.model), series)
    return ClassFit("none", chi2, 0, {}, per, note="the defaults")


def _sensor_candidates(
    s: Series, p: np.ndarray, every_d: float
) -> list[tuple[float, dict[str, Any]]]:
    """Weighted χ² of one sensor under a scale step after each onset, and a linear drift."""
    w = 1.0 / s.sd**2
    out = []
    for onset in np.arange(0.0, float(s.t.max()), every_d):
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


def _fit_sensor(series: Sequence[Series], base: Sim | None, every_d: float) -> ClassFit:
    """One sensor's default prediction rescaled after an onset, or drifting (k = 2).

    The class is the best of every (sensor, onset or drift) candidate, so it pays the
    look-elsewhere penalty for all of them.
    """
    if base is None:
        return ClassFit("sensor", float("inf"), 2, note="the default prediction failed")
    total0, per0 = _chi2(base, series)
    best: ClassFit | None = None
    n = 0
    for s in series:
        p = np.interp(s.t, base["t"], np.asarray(base[s.channel], dtype=float))
        candidates = _sensor_candidates(s, p, every_d)
        n += len(candidates)
        chi2, knobs = min(candidates, key=lambda c: c[0])
        fit = ClassFit(
            "sensor", total0 - per0[s.sensor] + chi2, 2, {"sensor": s.sensor, **knobs},
            {**per0, s.sensor: chi2}, converged=True, status="closed form",
        )  # fmt: skip
        if best is None or fit.chi2 < best.chi2:
            best = fit
    if best is None:
        return ClassFit("sensor", float("inf"), 2)
    best.n_candidates = max(n, 1)
    return best


def _scalar(
    simr: Simulator,
    series: Sequence[Series],
    tag: str,
    bounds: tuple[float, float],
    build: Callable[[float], tuple[Callable[[], Any], dict[str, object]]],
    xatol: float,
    max_iter: int,
) -> tuple[float, float, dict[str, float], bool, str]:
    """A bounded 1-D fit on a log scale: (value, χ², per sensor, converged, status)."""

    def sim_at(u: float) -> Sim | None:
        maker, options = build(float(np.exp(u)))
        return simr.run((tag, round(u, 6)), maker, **options)

    res = minimize_scalar(
        lambda u: _chi2(sim_at(u), series)[0],
        bounds=(np.log(bounds[0]), np.log(bounds[1])),
        method="bounded",
        options={"maxiter": max_iter, "xatol": xatol},
    )
    u = float(res.x)
    chi2, per = _chi2(sim_at(u), series)
    return float(np.exp(u)), chi2, per, bool(res.success), f"{res.message} (nfev {res.nfev})"


def _lsq(
    series: Sequence[Series],
    n: int,
    lower: np.ndarray,
    upper: np.ndarray,
    make: Callable[[np.ndarray], Sim | None],
    max_nfev: int,
) -> tuple[np.ndarray, bool, str]:
    """Bounded least squares on log multipliers from 0 (the defaults), to convergence."""
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
    except Exception as exc:
        return np.zeros(n), False, f"failed: {type(exc).__name__}"
    # status 0 is "max_nfev reached": not converged
    return np.asarray(res.x, dtype=float), bool(res.status > 0), f"{res.message} (nfev {res.nfev})"


def _fit_state(simr: Simulator, series: Sequence[Series], max_iter: int) -> ClassFit:
    """``biomass_scale`` in [0.25, 4] (k = 1)."""
    value, chi2, per, ok, status = _scalar(
        simr, series, "state", (0.25, 4.0),
        lambda v: (simr.model, {"biomass_scale": v}), 0.02, max_iter,
    )  # fmt: skip
    return ClassFit("state", chi2, 1, {"biomass_scale": value}, per, converged=ok, status=status)


def _fit_parameter_constant(simr: Simulator, series: Sequence[Series], nfev: int) -> ClassFit:
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
    u, ok, status = _lsq(series, len(names), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "constant", **dict(zip(names, np.exp(u).tolist(), strict=True))}
    return ClassFit("parameter", chi2, len(names), knobs, per, converged=ok, status=status)


def _fit_parameter_change_point(
    simr: Simulator, series: Sequence[Series], names: Sequence[str], onset_d: float, nfev: int
) -> ClassFit:
    """The truth's own form: the named parameters change at the known onset (k = len)."""
    probe = simr.model()
    idx = [probe.parameter_names.index(n) for n in names]

    def make(u: np.ndarray) -> Sim | None:
        theta = probe.defaults.copy()
        theta[idx] = np.exp(u)
        key = ("change_point", onset_d, tuple(np.round(u, 6)))
        return simr.run(key, lambda: simr.model(onset_d=onset_d), theta)

    lower = np.array([probe.lower[i] for i in idx])
    upper = np.array([probe.upper[i] for i in idx])
    u, ok, status = _lsq(series, len(names), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "change_point", "onset_d": onset_d}
    knobs.update(dict(zip(names, np.exp(u).tolist(), strict=True)))
    return ClassFit("parameter", chi2, len(names), knobs, per, converged=ok, status=status)


def _fit_influent_constant(simr: Simulator, series: Sequence[Series], nfev: int) -> ClassFit:
    """A constant scale on each feed's logged mass, in [0.5, 2] (k = number of feeds)."""
    feeds = sorted(simr.feed_log)

    def make(u: np.ndarray) -> Sim | None:
        scale = dict(zip(feeds, np.exp(u).tolist(), strict=True))
        key = ("influent", tuple(np.round(u, 6)))
        return simr.run(key, lambda: simr.model(feed_scale=scale))

    lower, upper = np.full(len(feeds), 0.5), np.full(len(feeds), 2.0)
    u, ok, status = _lsq(series, len(feeds), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "constant_scale", **dict(zip(feeds, np.exp(u).tolist(), strict=True))}
    return ClassFit("influent", chi2, len(feeds), knobs, per, converged=ok, status=status)


def _fit_influent_delivery(
    simr: Simulator, series: Sequence[Series], feed: str, day: int, scale_kg: float, it: int
) -> ClassFit:
    """The truth's own form: one unrecorded delivery of free mass on its known day (k = 1)."""
    value, chi2, per, ok, status = _scalar(
        simr, series, f"delivery:{feed}:{day}", (0.05 * scale_kg, 20.0 * scale_kg),
        lambda kg: ((lambda: simr.model(feed_add={(feed, day): kg})), {}), 0.02, it,
    )  # fmt: skip
    knobs = {"form": "unrecorded_delivery", "feed": feed, "day": day, "kg": value}
    return ClassFit("influent", chi2, 1, knobs, per, converged=ok, status=status)


def _fit_structural(simr: Simulator, series: Sequence[Series], max_iter: int) -> ClassFit:
    """The best of: one fitted extension left out (k = 0), the active volume scaled (k = 1)."""
    fits = []
    for ext in simr.extensions:
        rest = tuple(e for e in simr.extensions if e != ext)
        sim = simr.run(("drop", ext), lambda rest=rest: simr.model(extensions=rest))
        chi2, per = _chi2(sim, series)
        fits.append(ClassFit("structural", chi2, 0, {"omit_extension": ext}, per, converged=True))
    value, chi2, per, ok, status = _scalar(
        simr, series, "volume", (0.6, 1.4),
        lambda v: ((lambda: simr.model(volume_scale=v)), {}), 0.01, max_iter,
    )  # fmt: skip
    fits.append(
        ClassFit("structural", chi2, 1, {"volume_scale": value}, per, converged=ok, status=status)
    )
    best = min(fits, key=lambda c: c.chi2 + 2.0 * c.k)
    best.n_candidates = len(fits)
    return best


# ------------------------------------------------------------------ the rule


def admissible(fits: Mapping[str, ClassFit], margin: float) -> list[str]:
    """The labels whose AIC is within ``margin`` of the best class's, in label order."""
    finite = [c.aic for c in fits.values() if np.isfinite(c.aic)]
    if not finite:
        return []
    best = min(finite)
    return [lab for lab in LABELS if lab in fits and fits[lab].aic - best <= margin]


def truth_representable(faults: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    """Whether some class can represent the injected faults, and the limits that apply."""
    limits = sorted(
        {_UNREPRESENTABLE[f["type"]] for f in faults if f.get("type") in _UNREPRESENTABLE}
    )
    return not limits, limits


def class_limited(faults: Sequence[Mapping[str, Any]]) -> list[str]:
    """The declared limits (§2.2) that apply to a cell's injected faults."""
    return truth_representable(faults)[1]


def _best_of(label: str, candidates: Sequence[ClassFit]) -> ClassFit:
    """The best of several forms of one class; the choice pays the search penalty."""
    best = min(candidates, key=lambda c: c.chi2 + 2.0 * c.k)
    if len(candidates) > 1:
        best.n_candidates = best.n_candidates * len(candidates)
        best.note = (best.note + f"; best of {len(candidates)} forms").lstrip("; ")
    return best


def _injected_median_kg(plant: str, feed: str) -> float:
    from sim.influent.defaults import load_feed_fractionation, load_generator_config
    from sim.influent.generator import _amount_to_kg

    amount = load_generator_config().plants[plant].feeds[feed].amount
    return _amount_to_kg(amount.nonzero_median, amount.unit, load_feed_fractionation().feeds[feed])


def _fits(
    simr: Simulator,
    series: Sequence[Series],
    classes: Sequence[str],
    faults: Mapping[str, Any],
    plant: str,
    t_end: float,
) -> dict[str, ClassFit]:
    cfg = _cfg()
    fits: dict[str, ClassFit] = {"none": _fit_none(simr, series)}
    base = simr.run(("none",), simr.model)
    for label in LABELS[1:]:
        if label not in classes:
            continue
        if label == "sensor":
            fits[label] = _fit_sensor(series, base, cfg.sensor_onset_every_d)
        elif label == "state":
            fits[label] = _fit_state(simr, series, cfg.scalar_max_iter)
        elif label == "structural":
            fits[label] = _fit_structural(simr, series, cfg.scalar_max_iter)
        elif label == "influent":
            forms = [_fit_influent_constant(simr, series, cfg.lsq_max_nfev)]
            for extra in faults.get("influent", {}).get("unrecorded", []):
                day = int(extra["day"])
                if day <= t_end:  # the truth's own form, when the record can see it
                    median = _injected_median_kg(plant, str(extra["feed_id"]))
                    forms.append(
                        _fit_influent_delivery(
                            simr, series, str(extra["feed_id"]), day, median, cfg.scalar_max_iter
                        )
                    )
            fits[label] = _best_of("influent", forms)
        elif label == "parameter":
            forms = [_fit_parameter_constant(simr, series, cfg.lsq_max_nfev)]
            for fault in faults.get("faults", []):
                names = _PARAMETER_SHIFTS.get(str(fault.get("type")))
                onset = float(fault.get("onset_day", 0.0))
                if names and 0.0 < onset < t_end:
                    forms.append(
                        _fit_parameter_change_point(simr, series, names, onset, cfg.lsq_max_nfev)
                    )
            fits[label] = _best_of("parameter", forms)
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

    cfg = _cfg()
    _LOOK_ELSEWHERE[0] = bool(cfg.look_elsewhere)
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
    t_end = calibration_end(public["duration_days"])
    out = {}
    for run_id, run_dir, truth_dir in runs:
        started, n0 = time.perf_counter(), simr.n_sims
        series = load_series(run_dir / "observations" / "sensors.json", t_end)
        tier = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["tier"]
        faults = json.loads((truth_dir / "faults.json").read_text(encoding="utf-8"))
        fits = _fits(simr, series, classes, faults, public["plant"], t_end)
        truth = [str(x) for x in faults["truth_label"]]
        sets = {
            f"{cfg.margin:g}": admissible(fits, cfg.margin),
            f"{cfg.sensitivity_margin:g}": admissible(fits, cfg.sensitivity_margin),
        }
        primary = sets[f"{cfg.margin:g}"]
        representable, limits = truth_representable(faults.get("faults", []))
        doc = {
            "method_version": METHOD_VERSION,
            "run_id": run_id,
            "scenario_id": faults["scenario_id"],
            "plant": public["plant"],
            "tier": tier,
            "truth_label": truth,
            "calibration_end_d": t_end,
            "n_samples": int(sum(s.t.size for s in series)),
            "sensors": [s.sensor for s in series],
            "margin": cfg.margin,
            "sensitivity_margin": cfg.sensitivity_margin,
            "look_elsewhere": bool(cfg.look_elsewhere),
            "admissible": sets,
            "admissible_set": primary,
            "n_admissible": len(primary),
            "chance_rate": (1.0 / len(primary)) if primary else None,
            "none_admissible": "none" in primary,
            # a multi-label truth passes when any one of its labels is admissible
            "truth_admissible": any(t in primary for t in truth),
            "truth_representable": representable,
            "truth_class_limited": limits,
            "best_label": min(fits.values(), key=lambda c: c.aic).label,
            "classes": {
                lab: {
                    "chi2": _finite(c.chi2),
                    "k": c.k,
                    "n_candidates": c.n_candidates,
                    "search_penalty": c.search_penalty,
                    "aic": _finite(c.aic),
                    "converged": c.converged,
                    "status": c.status,
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
            f"truth={truth} representable={representable} sims={doc['simulations']} "
            f"{doc['wall_s']} s"
        )
    return out
