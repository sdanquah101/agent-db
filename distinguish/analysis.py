"""The admissible label set of one cell (docs/distinguishability.md, method version 3).

**The null is the calibrated no-fault baseline.** The default-parameter model misfits
even a clean record (the benchmark card, §4.2), so a null at the defaults loses to any
class that rescales a channel. Under `none`, the baseline multipliers are fitted to the
tier's visible record over the calibration window (the hold-out is never read). Every
other class is fitted on top of that same calibrated background.

**Each sensor's χ² is divided by its overdispersion,** the dispersion under the
baseline on the Level-0 cell of the same plant and tier (quasi-likelihood, floor 1).

**A class's score is χ² plus a penalty:** the likelihood-ratio critical value of its k
free parameters at alpha / (number of alternatives), plus 2 ln N for a best-of-N
search. With every class competing at once on noise, `none` is then admissible at least
1 - alpha of the time. A label is admissible when its score is within a margin of the best.

The truth store is read for the answer key's labels, the injected faults, and the
fitted extensions. The injected faults serve two purposes: to give the truth's own class
its representable form (a parameter change at its onset, an unrecorded delivery on its
day), and to flag cells no class can represent. The fitted extensions are read as the
registry reads them. The data are the visible record.
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
from scipy.stats import chi2 as chi2_dist

__all__ = [
    "LABELS",
    "METHOD_VERSION",
    "ClassFit",
    "Series",
    "Simulator",
    "admissible",
    "analyse_pair",
    "calibration_end",
    "chance_rate",
    "class_limited",
    "load_series",
    "truth_representable",
]

METHOD_VERSION = 3
LABELS = ("none", "sensor", "influent", "state", "parameter", "structural")
REPO = Path(__file__).resolve().parents[1]
P0_CONFIG = REPO / "configs" / "workflows" / "p0.yaml"

# the parameter class's generic form: the two parameters the Level-5 faults shift, on top
# of the calibrated baseline (which does not include them)
PARAMETER_EXTRA = ("k_hyd_ch", "K_I_nh3")
EVAL_TIMEOUT_S = 120
BAD_RESIDUAL = 1e3  # a failed or non-finite prediction is a very bad fit, not a crash

# the parameters each parameter fault shifts (sim/faults/schema.py)
_PARAMETER_SHIFTS = {
    "ammonia_inhibition_shift": ("K_I_nh3",),
    "hydrolysis_regime_change": ("k_hyd_ch", "k_hyd_pr", "k_hyd_li"),
}
# fault types whose truth no class here can represent (§2.2): null score, not credited
_UNREPRESENTABLE = {
    "feed_mislabelled": "a time-windowed fractionation change",
    "moisture_drift": "a per-day solids change",
    "stagnant_zone": "a stagnant zone",
}

Sim = dict[str, np.ndarray]
# the penalty's settings, set from configs/eval.yaml at the start of an analysis
_PENALTY: dict[str, Any] = {"alpha": 0.05, "m": 5, "look_elsewhere": True}


def _cfg() -> Any:
    from eval.config import load_eval_config

    return load_eval_config().distinguishability


def _p0() -> dict[str, Any]:
    return yaml.safe_load(P0_CONFIG.read_text(encoding="utf-8"))


def class_penalty(k: int, n_candidates: int) -> float:
    """The likelihood-ratio critical value of ``k`` parameters, plus the search term."""
    lr = float(chi2_dist.ppf(1.0 - _PENALTY["alpha"] / _PENALTY["m"], k)) if k > 0 else 0.0
    search = 2.0 * math.log(n_candidates) if _PENALTY["look_elsewhere"] else 0.0
    return lr + search


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
    def penalty(self) -> float:
        """The class's penalty (``class_penalty``); 0 for the null."""
        return class_penalty(self.k, self.n_candidates)

    @property
    def score(self) -> float:
        """χ² (overdispersion-scaled) plus the penalty."""
        return self.chi2 + self.penalty


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


def load_series(
    sensors_json: Path, t_end: float, overdispersion: Mapping[str, float] | None = None
) -> list[Series]:
    """The tier's calibrated sensors from ``observations/sensors.json``, up to ``t_end``.

    Missing, saturated and flatlined samples are dropped for every class alike;
    temperature is left out, as P0 leaves it out; nothing after ``t_end`` is read. The sd
    is the declared ``sqrt((cv v)^2 + sd_abs^2)`` with P0's floors, inflated by
    ``sqrt(overdispersion[sensor])`` when given, so every χ² is overdispersion-scaled.
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
        if overdispersion:
            sd = sd * math.sqrt(max(1.0, float(overdispersion.get(name, 1.0))))
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
        before: np.ndarray | None = None,
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

            return ChangePointADM1(onset_d=onset_d, before=before, **kwargs)
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


# ------------------------------------------------------------------ fitting helpers


def _scalar(
    simr: Simulator,
    series: Sequence[Series],
    tag: Any,
    bounds: tuple[float, float],
    build: Callable[[float], tuple[Callable[[], Any], np.ndarray | None, dict[str, object]]],
    xatol: float,
    max_iter: int,
) -> tuple[float, float, dict[str, float], bool, str]:
    """A bounded 1-D fit on a log scale: (value, χ², per sensor, converged, status)."""

    def sim_at(u: float) -> Sim | None:
        maker, theta, options = build(float(np.exp(u)))
        return simr.run((tag, round(u, 6)), maker, theta, **options)

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
    """Bounded least squares on log multipliers from 0, reporting convergence."""
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


@dataclass
class Baseline:
    """The calibrated no-fault background of one tier: the multipliers and their tag."""

    theta: np.ndarray
    tag: tuple[float, ...]


def _theta_with(
    base: Baseline, names: Sequence[str], values: Sequence[float], probe: Any
) -> np.ndarray:
    theta = base.theta.copy()
    for n, v in zip(names, values, strict=True):
        theta[probe.parameter_names.index(n)] = base.theta[probe.parameter_names.index(n)] * v
    return theta


# ------------------------------------------------------------------ the classes


def _fit_none(
    simr: Simulator, series: Sequence[Series], names: Sequence[str], nfev: int
) -> tuple[ClassFit, Baseline]:
    """The calibrated no-fault baseline: the background multipliers fitted (k shared)."""
    probe = simr.model()
    idx = [probe.parameter_names.index(n) for n in names]

    def make(u: np.ndarray) -> Sim | None:
        theta = probe.defaults.copy()
        theta[idx] = np.exp(u)
        return simr.run(("baseline", tuple(np.round(u, 6))), simr.model, theta)

    lower = np.array([probe.lower[i] for i in idx])
    upper = np.array([probe.upper[i] for i in idx])
    u, ok, status = _lsq(series, len(names), lower, upper, make, nfev)
    theta = probe.defaults.copy()
    theta[idx] = np.exp(u)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "calibrated_baseline", **dict(zip(names, np.exp(u).tolist(), strict=True))}
    base = Baseline(theta, tuple(np.round(u, 6)))
    note = "the calibrated no-fault baseline; its k is shared by every class"
    fit = ClassFit("none", chi2, 0, knobs, per, note=note, converged=ok, status=status)
    return fit, base


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
    """One sensor's baseline prediction rescaled after an onset, or drifting (k = 2)."""
    if base is None:
        return ClassFit("sensor", float("inf"), 2, note="the baseline prediction failed")
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


def _fit_state(simr: Simulator, series: Sequence[Series], b: Baseline, it: int) -> ClassFit:
    """``biomass_scale`` in [0.25, 4] on top of the baseline (k = 1)."""
    value, chi2, per, ok, status = _scalar(
        simr, series, ("state", b.tag), (0.25, 4.0),
        lambda v: (simr.model, b.theta, {"biomass_scale": v}), 0.02, it,
    )  # fmt: skip
    return ClassFit("state", chi2, 1, {"biomass_scale": value}, per, converged=ok, status=status)


def _fit_parameter_extra(
    simr: Simulator, series: Sequence[Series], b: Baseline, nfev: int
) -> ClassFit:
    """A constant change of the Level-5 target parameters on top of the baseline (k = 2)."""
    probe = simr.model()
    names = [n for n in PARAMETER_EXTRA if n in probe.parameter_names]
    idx = [probe.parameter_names.index(n) for n in names]

    def make(u: np.ndarray) -> Sim | None:
        theta = _theta_with(b, names, np.exp(u), probe)
        return simr.run(("parameter", b.tag, tuple(np.round(u, 6))), simr.model, theta)

    lower = np.array([probe.lower[i] for i in idx])
    upper = np.array([probe.upper[i] for i in idx])
    u, ok, status = _lsq(series, len(names), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "constant", **dict(zip(names, np.exp(u).tolist(), strict=True))}
    return ClassFit("parameter", chi2, len(names), knobs, per, converged=ok, status=status)


def _fit_parameter_change_point(
    simr: Simulator, series: Sequence[Series], b: Baseline, names: Sequence[str], onset_d: float,
    nfev: int,
) -> ClassFit:  # fmt: skip
    """The truth's own form: the named parameters change at the known onset (k = len)."""
    probe = simr.model()
    idx = [probe.parameter_names.index(n) for n in names]

    def make(u: np.ndarray) -> Sim | None:
        theta = _theta_with(b, names, np.exp(u), probe)
        key = ("change_point", onset_d, b.tag, tuple(np.round(u, 6)))
        return simr.run(key, lambda: simr.model(onset_d=onset_d, before=b.theta), theta)

    lower = np.array([probe.lower[i] for i in idx])
    upper = np.array([probe.upper[i] for i in idx])
    u, ok, status = _lsq(series, len(names), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "change_point", "onset_d": onset_d}
    knobs.update(dict(zip(names, np.exp(u).tolist(), strict=True)))
    return ClassFit("parameter", chi2, len(names), knobs, per, converged=ok, status=status)


def _fit_influent_constant(
    simr: Simulator, series: Sequence[Series], b: Baseline, nfev: int
) -> ClassFit:
    """A constant scale on each feed's logged mass, in [0.5, 2] (k = number of feeds)."""
    feeds = sorted(simr.feed_log)

    def make(u: np.ndarray) -> Sim | None:
        scale = dict(zip(feeds, np.exp(u).tolist(), strict=True))
        key = ("influent", b.tag, tuple(np.round(u, 6)))
        return simr.run(key, lambda: simr.model(feed_scale=scale), b.theta)

    lower, upper = np.full(len(feeds), 0.5), np.full(len(feeds), 2.0)
    u, ok, status = _lsq(series, len(feeds), lower, upper, make, nfev)
    chi2, per = _chi2(make(u), series)
    knobs = {"form": "constant_scale", **dict(zip(feeds, np.exp(u).tolist(), strict=True))}
    return ClassFit("influent", chi2, len(feeds), knobs, per, converged=ok, status=status)


def _fit_influent_delivery(
    simr: Simulator, series: Sequence[Series], b: Baseline, feed: str, day: int, scale_kg: float,
    it: int,
) -> ClassFit:  # fmt: skip
    """The truth's own form: one unrecorded delivery of free mass on its known day (k = 1)."""
    value, chi2, per, ok, status = _scalar(
        simr, series, ("delivery", feed, day, b.tag), (0.05 * scale_kg, 20.0 * scale_kg),
        lambda kg: ((lambda: simr.model(feed_add={(feed, day): kg})), b.theta, {}), 0.02, it,
    )  # fmt: skip
    knobs = {"form": "unrecorded_delivery", "feed": feed, "day": day, "kg": value}
    return ClassFit("influent", chi2, 1, knobs, per, converged=ok, status=status)


def _fit_structural(simr: Simulator, series: Sequence[Series], b: Baseline, it: int) -> ClassFit:
    """The best of: one fitted extension left out (k = 0), the active volume scaled (k = 1)."""
    fits = []
    for ext in simr.extensions:
        rest = tuple(e for e in simr.extensions if e != ext)
        sim = simr.run(("drop", ext, b.tag), lambda rest=rest: simr.model(extensions=rest), b.theta)
        chi2, per = _chi2(sim, series)
        fits.append(ClassFit("structural", chi2, 0, {"omit_extension": ext}, per, converged=True))
    value, chi2, per, ok, status = _scalar(
        simr, series, ("volume", b.tag), (0.6, 1.4),
        lambda v: ((lambda: simr.model(volume_scale=v)), b.theta, {}), 0.01, it,
    )  # fmt: skip
    fits.append(
        ClassFit("structural", chi2, 1, {"volume_scale": value}, per, converged=ok, status=status)
    )
    best = min(fits, key=lambda c: c.chi2 + class_penalty(c.k, 1))
    best.n_candidates = len(fits)
    return best


# ------------------------------------------------------------------ the rule


def admissible(fits: Mapping[str, ClassFit], margin: float) -> list[str]:
    """The labels whose score is within ``margin`` of the best class's, in label order."""
    finite = [c.score for c in fits.values() if np.isfinite(c.score)]
    if not finite:
        return []
    best = min(finite)
    return [lab for lab in LABELS if lab in fits and fits[lab].score - best <= margin]


def chance_rate(admissible_set: Sequence[str], truth: Sequence[str]) -> float:
    """What a uniform guess over the six labels scores: |A or truth| / 6 (re-review, item 8)."""
    return len(set(admissible_set) | set(truth)) / len(LABELS)


def truth_representable(faults: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    """Whether some class can represent the injected faults, and the limits that apply."""
    limits = sorted(
        {_UNREPRESENTABLE[f["type"]] for f in faults if f.get("type") in _UNREPRESENTABLE}
    )
    return not limits, limits


def class_limited(faults: Sequence[Mapping[str, Any]]) -> list[str]:
    """The declared limits (§2.2) that apply to a cell's injected faults."""
    return truth_representable(faults)[1]


def _best_of(candidates: Sequence[ClassFit]) -> ClassFit:
    """The best of several forms of one class; the choice pays the search penalty."""
    best = min(candidates, key=lambda c: c.score)
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
) -> tuple[dict[str, ClassFit], Baseline]:
    cfg = _cfg()
    none, b = _fit_none(simr, series, cfg.baseline_parameters, cfg.lsq_max_nfev)
    fits: dict[str, ClassFit] = {"none": none}
    base = simr.run(("baseline", b.tag), simr.model, b.theta)
    for label in LABELS[1:]:
        if label not in classes:
            continue
        if label == "sensor":
            fits[label] = _fit_sensor(series, base, cfg.sensor_onset_every_d)
        elif label == "state":
            fits[label] = _fit_state(simr, series, b, cfg.scalar_max_iter)
        elif label == "structural":
            fits[label] = _fit_structural(simr, series, b, cfg.scalar_max_iter)
        elif label == "influent":
            forms = [_fit_influent_constant(simr, series, b, cfg.lsq_max_nfev)]
            for extra in faults.get("influent", {}).get("unrecorded", []):
                day = int(extra["day"])
                if day <= t_end:  # the truth's own form, when the record can see it
                    feed = str(extra["feed_id"])
                    median = _injected_median_kg(plant, feed)
                    forms.append(
                        _fit_influent_delivery(
                            simr, series, b, feed, day, median, cfg.scalar_max_iter
                        )
                    )
            fits[label] = _best_of(forms)
        elif label == "parameter":
            forms = [_fit_parameter_extra(simr, series, b, cfg.lsq_max_nfev)]
            for fault in faults.get("faults", []):
                names = _PARAMETER_SHIFTS.get(str(fault.get("type")))
                onset = float(fault.get("onset_day", 0.0))
                if names and 0.0 < onset < t_end:
                    forms.append(
                        _fit_parameter_change_point(simr, series, b, names, onset, cfg.lsq_max_nfev)
                    )
            fits[label] = _best_of(forms)
    return fits, b


def _finite(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def overdispersion_of(doc: Mapping[str, Any]) -> dict[str, float]:
    """Per-sensor dispersion of the calibrated baseline on a Level-0 cell (floor 1)."""
    none = doc["classes"]["none"]
    raw = none.get("chi2_per_sensor_unscaled") or none["chi2_per_sensor"]
    n = doc["n_per_sensor"]
    return {s: max(1.0, float(raw[s]) / max(int(n[s]), 1)) for s in raw if s in n}


def analyse_pair(
    runs: Sequence[tuple[str, Path, Path]],
    *,
    classes: Sequence[str] = LABELS,
    overdispersion: Mapping[str, Mapping[str, float]] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    """Every tier of one (scenario, plant). ``runs`` is (run id, run dir, truth dir).

    ``overdispersion`` maps tier -> sensor -> dispersion, from the Level-0 cell of the same
    plant and tier. When it is None (the Level-0 cells themselves, or when the switch is
    off), each tier's dispersion is taken from its own calibrated baseline: a first
    baseline fit on unscaled data gives it, and the classes are then fitted on the scaled
    data. The tiers share the feed log and the extensions (checked).
    """
    from sim.run.artifacts import read_feed_log

    cfg = _cfg()
    _PENALTY.update(
        alpha=float(cfg.lr_alpha),
        m=int(cfg.n_alternatives),
        look_elsewhere=bool(cfg.look_elsewhere),
    )
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
        tier = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["tier"]
        faults = json.loads((truth_dir / "faults.json").read_text(encoding="utf-8"))
        sensors_json = run_dir / "observations" / "sensors.json"
        raw_series = load_series(sensors_json, t_end)
        n_per_sensor = {s.sensor: int(s.t.size) for s in raw_series}
        if not cfg.overdispersion_from_level0:
            phi: dict[str, float] = {}
            source = "off"
        elif overdispersion is not None and tier in overdispersion:
            phi = dict(overdispersion[tier])
            source = "the Level-0 cell of this plant and tier"
        else:
            unscaled, _ = _fit_none(simr, raw_series, cfg.baseline_parameters, cfg.lsq_max_nfev)
            phi = {
                s: max(1.0, unscaled.per_sensor[s] / max(n_per_sensor[s], 1))
                for s in unscaled.per_sensor
            }
            source = "this cell's own calibrated baseline (a Level-0 cell)"
        series = load_series(sensors_json, t_end, phi)
        fits, _base = _fits(simr, series, classes, faults, public["plant"], t_end)
        truth = [str(x) for x in faults["truth_label"]]
        sets = {
            f"{cfg.margin:g}": admissible(fits, cfg.margin),
            f"{cfg.sensitivity_margin:g}": admissible(fits, cfg.sensitivity_margin),
        }
        primary = sets[f"{cfg.margin:g}"]
        representable, limits = truth_representable(faults.get("faults", []))
        unscaled_none = {
            s: fits["none"].per_sensor.get(s, 0.0) * max(1.0, phi.get(s, 1.0))
            for s in fits["none"].per_sensor
        }
        doc = {
            "method_version": METHOD_VERSION,
            "run_id": run_id,
            "scenario_id": faults["scenario_id"],
            "level": faults.get("level"),
            "plant": public["plant"],
            "tier": tier,
            "truth_label": truth,
            "calibration_end_d": t_end,
            "n_samples": int(sum(n_per_sensor.values())),
            "n_per_sensor": n_per_sensor,
            "sensors": [s.sensor for s in series],
            "overdispersion": phi,
            "overdispersion_source": source,
            "baseline": fits["none"].knobs,
            "margin": cfg.margin,
            "sensitivity_margin": cfg.sensitivity_margin,
            "penalty": {
                "lr_alpha": cfg.lr_alpha,
                "n_alternatives": cfg.n_alternatives,
                "look_elsewhere": bool(cfg.look_elsewhere),
            },
            "admissible": sets,
            "admissible_set": primary,
            "n_admissible": len(primary),
            "chance_rate": chance_rate(primary, truth),
            "none_admissible": "none" in primary,
            # a multi-label truth passes when any one of its labels is admissible
            "truth_admissible": any(t in primary for t in truth),
            "truth_representable": representable,
            "truth_class_limited": limits,
            "best_label": min(fits.values(), key=lambda c: c.score).label,
            "classes": {
                lab: {
                    "chi2": _finite(c.chi2),
                    "k": c.k,
                    "n_candidates": c.n_candidates,
                    "penalty": c.penalty,
                    "score": _finite(c.score),
                    "converged": c.converged,
                    "status": c.status,
                    "knobs": c.knobs,
                    "chi2_per_sensor": c.per_sensor,
                    **({"chi2_per_sensor_unscaled": unscaled_none} if lab == "none" else {}),
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
