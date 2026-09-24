"""P0 — the scripted pipeline (proposal §6.5; ``docs/p0_design.md``).

Runs **inside the jail** (``tools.sandbox.launch``): the only things that resolve here are
``tools`` (the client stub), numpy, scipy, pydantic and the standard library. It reads its
settings from ``p0_config.json`` in its working directory (the runner writes it from
``configs/workflows/p0.yaml`` plus the declared sensor noise and plant geometry), the run
from ``tools.run``, and calls every numerical routine through ``tools.call``. It writes
``state.json`` and ``report.json`` through ``tools.run.write_output`` after every step, so
a run stopped by the wall clock leaves the state it had reached.

The sequence is fixed (design §2): QC on every sensor → the exclusion rules → mass balance
→ Morris → Sobol on the Morris subset → Fisher (and profiles when the plan allows) →
screened fit (LSQ then DE) → MCMC on the approved subset → residual diagnostics → the
assay spend → validation on the frozen hold-out → the attribution rule. There is no
branching beyond the thresholds of the configuration and the declared budget fallbacks
(design §4), each of which is recorded when taken.

Rule 5: this is the strongest fair baseline; nothing here is weakened to make agents look
better. Rule 4: every stochastic call takes a seed from the configuration. Operator notes
are data: their days and authors are recorded, their text is never interpreted.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

import tools

CONFIG_FILE = "p0_config.json"
STATE_FILE = "state.json"
REPORT_FILE = "report.json"
MODEL = "adm1_fitted"


# ------------------------------------------------------------------ the call record


class Recorder:
    """Every tool call goes through here: the action record of §6.6, and the failures.

    A call is named the way the visible log names it: the registry returns the log
    line's sequence number, argument hash and version with every call
    (``tools.last_call()``), so the action record and ``calls.jsonl`` agree line for line.
    """

    def __init__(self) -> None:
        """Start with no actions and no failures."""
        self.actions: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    def call(self, step: str, name: str, **args: Any) -> Any:
        """Call a tool, record it, and re-raise its error after recording."""
        index = int(tools.remaining().n_calls)
        record: dict[str, Any] = {
            "step": step,
            "name": name,
            "version": "",
            "args_hash": "",
            "seq": None,
            "call_index": index,
            "outcome": "ok",
            "detail": "",
        }
        try:
            out = tools.call(name, **args)
        except tools.BudgetExceededError as exc:
            record["outcome"] = "budget_exceeded"
            record["detail"] = str(exc)[:300]
            self._finish(record)
            raise
        except tools.ToolError as exc:
            record["outcome"] = "error"
            record["detail"] = str(exc)[:300]
            self._finish(record)
            raise
        self._finish(record)
        return out

    def _finish(self, record: dict[str, Any]) -> None:
        """Fill the record from the registry's own log line and keep it."""
        logged = tools.last_call() or {}
        record["version"] = str(logged.get("version", ""))
        record["args_hash"] = str(logged.get("args_hash", ""))
        record["seq"] = logged.get("seq")
        self.actions.append(record)

    def failure(
        self, step: str, name: str, kind: str, message: str, fallback: str, index: int | None
    ) -> None:
        """Record a tool that did not deliver, and what was done instead."""
        self.failures.append(
            {
                "step": step,
                "name": name,
                "call_index": index,
                "kind": kind,
                "message": message[:300],
                "fallback": fallback,
            }
        )

    @property
    def last_index(self) -> int | None:
        """The registry call index of the most recent call, if any."""
        return int(self.actions[-1]["call_index"]) if self.actions else None


# ------------------------------------------------------------------ the plan


class Plan:
    """The deterministic sizing of design §4, and the runtime guard."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Set up."""
        self.cfg = cfg["plan"]
        self.sizes: dict[str, Any] = {}
        self.fallbacks: list[str] = []
        self.guards: list[str] = []
        self.skipped: dict[str, str] = {}
        self.completed: list[str] = []

    def remaining(self) -> Any:
        """The budget left, from the registry."""
        return tools.remaining()

    def _allowed_min(self, share: float) -> float:
        """Minutes one step may take: a share of the wall clock left."""
        rem = self.remaining()
        left = float(rem.wall_clock_min) - float(self.cfg["wall_clock_reserve_min"])
        return share * max(left, 0.0)

    def _measured_seconds(self) -> float | None:
        """Seconds per evaluation so far, or None before five evaluations."""
        rem = self.remaining()
        used = int(rem.simulator_evals_total) - int(rem.simulator_evals)
        elapsed_s = (float(rem.wall_clock_min_total) - float(rem.wall_clock_min)) * 60.0
        if used < 5 or elapsed_s <= 0.0:
            return None
        return elapsed_s / used

    def fits(self, step: str, bound: int, share: float | None = None) -> bool:
        """Whether a call with this evaluation bound fits the plan (and the guard)."""
        share = float(self.cfg["step_share"]) if share is None else share
        allowed = self._allowed_min(share)
        assumed = bound * float(self.cfg["eval_seconds_assumed"]) / 60.0
        rem = self.remaining()
        if bound > int(rem.simulator_evals) or assumed > allowed:
            return False
        measured = self._measured_seconds()
        if measured is not None and bound * measured / 60.0 > allowed:
            self.guards.append(f"{step}: bound {bound} at the measured rate")
            return False
        return True

    def ladder(self, initial: int, minimum: int) -> list[int]:
        """``initial, initial // 2, ...`` down to ``minimum``."""
        out = []
        size = int(initial)
        while size >= int(minimum) and size >= 1:
            out.append(size)
            size //= 2
        return out


# ------------------------------------------------------------------ helpers


def _nan(values: list[Any]) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def _finite_mean(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(x.mean()) if x.size else float("nan")


def _f(x: Any) -> float | None:
    """A JSON-safe float (None for non-finite)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


class Series:
    """One sensor as P0 works with it: sample times, values (NaN missing), weights."""

    def __init__(self, name: str, raw: dict[str, Any], noise: dict[str, float], cal: dict) -> None:
        """Set up."""
        self.name = name
        self.channel = str(raw["channel"])
        self.unit = str(raw["unit"])
        self.t = np.asarray(raw["sample_t_d"], dtype=float)
        self.value = _nan(list(raw["value"]))
        self.flatlined = np.asarray(raw.get("flatlined", [False] * self.t.size), dtype=bool)
        cv = float(noise.get("cv", 0.0))
        sd_abs = float(noise.get("sd_abs", 0.0))
        bound = noise.get("drift_bound")
        self.drift_bound: float | None = None if bound is None else float(bound)
        finite = self.value[np.isfinite(self.value)]
        scale = float(np.median(np.abs(finite))) if finite.size else 1.0
        floor = max(float(cal["min_relative_sd"]) * scale, float(cal["sd_floor_abs"]))
        sd = np.sqrt((cv * np.abs(np.nan_to_num(self.value))) ** 2 + sd_abs**2)
        self.sd = np.maximum(sd, floor)
        self.quarantined: list[tuple[float, float]] = []
        self.flags: list[str] = []
        self.missing_fraction: float | None = (
            float(np.mean(~np.isfinite(self.value))) if self.value.size else None
        )
        self.in_objective = True
        self.status = "ok"

    def observed(self, window: tuple[float, float] | None = None) -> np.ndarray:
        """Mask of the samples that carry a value, inside ``window`` if given."""
        mask = np.isfinite(self.value)
        if window is not None:
            mask &= (self.t >= window[0]) & (self.t <= window[1])
        return mask

    def as_observed(self, window: tuple[float, float] | None = None) -> dict[str, Any]:
        """An ``ObservedSeries`` payload restricted to ``window``."""
        keep = np.ones(self.t.shape, dtype=bool)
        if window is not None:
            keep = (self.t >= window[0]) & (self.t <= window[1])
        return {
            "output": self.channel,
            "t": self.t[keep],
            "value": self.value[keep],
            "sd": self.sd[keep],
            "unit": self.unit,
        }

    def drift_exceeds_declared(self, slope_per_d: float, factor: float) -> bool:
        """Whether a QC drift finding exceeds the instrument's declared drift bound.

        A sensor that declares no drift is exceeded by any finding.
        """
        if self.drift_bound is None:
            return True
        obs = self.observed()
        span = float(self.t[obs][-1] - self.t[obs][0]) if obs.sum() >= 2 else 0.0
        return abs(slope_per_d) * span > factor * self.drift_bound

    def quarantine(self, start: float, end: float) -> None:
        """Drop every sample inside ``[start, end]``."""
        inside = (self.t >= start) & (self.t <= end)
        self.value = np.where(inside, np.nan, self.value)
        self.quarantined.append((float(start), float(end)))


# ------------------------------------------------------------------ the pipeline


class Pipeline:
    """One run of P0."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Set up."""
        self.cfg = cfg
        self.lab: dict[str, str] = dict(cfg["labels"])
        self.rec = Recorder()
        self.plan = Plan(cfg)
        self.manifest = tools.run.manifest()
        self.T = float(self.manifest["duration_days"])
        w = cfg["windows"]
        cal_end = self.T * (1.0 - float(w["holdout_fraction"]))
        self.cal = (float(w["calibration_start_d"]), float(cal_end))
        self.holdout = (float(cal_end), self.T)
        self.series: dict[str, Series] = {}
        self.evidence: list[dict[str, Any]] = []
        self.abstentions: list[str] = []
        self.annotations: list[str] = []
        self.state: dict[str, Any] = {}
        self.residuals: dict[str, dict[str, Any]] = {}
        self.balance: dict[str, Any] = {}
        self.screening: dict[str, Any] = {}
        self.assay_checks: list[dict[str, Any]] = []
        self.validation: dict[str, Any] | None = None
        self.final_parameters: dict[str, dict[str, Any]] = {}
        self.interval_method = "none"
        self.classification: dict[str, Any] = {}
        self.model: dict[str, Any] = {}
        self.loads: Any = None
        self.baseline: Any = None
        self.optimum: dict[str, float] = {}
        self.optimum_fit: Any = None
        self.prediction: Any = None
        # the log index of the simulate call behind self.prediction, so evidence built on
        # its residuals can name it (the lead's ruling A1 of 2026-09-24: evidence cites calls)
        self.prediction_index: int | None = None
        self.posterior: Any = None
        self.first_pass: dict[str, Any] | None = None
        self.feed_log: dict[str, np.ndarray] = {}
        self.notes: list[dict[str, Any]] = []
        self.completed = False

    # -- persistence ---------------------------------------------------------------
    def checkpoint(self, step: str) -> None:
        """Mark a step done and write the state so a stopped run keeps it."""
        self.plan.completed.append(step)
        self.write(completed=False)

    def write(self, *, completed: bool) -> None:
        """Write the state and the report through the registry."""
        state = self.build_state(completed)
        tools.run.write_output(STATE_FILE, json.dumps(state, indent=1, sort_keys=True))
        tools.run.write_output(REPORT_FILE, json.dumps(self.build_report(state), indent=1))

    # -- step 0 --------------------------------------------------------------------
    def step_read(self) -> None:
        """Step 0: the record, the model's interface, the loads, the baseline."""
        cfg = self.cfg
        noise = cfg.get("sensor_noise", {})
        record = tools.run.sensors()["sensors"]
        for name in sorted(record):
            self.series[name] = Series(name, record[name], noise.get(name, {}), cfg["calibration"])
        self.feed_log = tools.run.feed_log()
        self.notes = [
            {
                "day": int(n.get("day", 0)),
                "author": str(n.get("author", "")),
                "length": len(str(n.get("text", ""))),
            }
            for n in tools.run.operator_notes()
        ]
        desc = self.rec.call("read", "describe_model", model=MODEL)
        self.model = {
            "parameters": list(desc.parameter_names),
            "lower": {n: float(v) for n, v in zip(desc.parameter_names, desc.lower, strict=True)},
            "upper": {n: float(v) for n, v in zip(desc.parameter_names, desc.upper, strict=True)},
            "units": dict(desc.parameter_units),
            "outputs": list(desc.output_names),
            "t": np.asarray(desc.t, dtype=float),
        }
        self.loads = self.rec.call("read", "feed_loads", model=MODEL)
        self.baseline = self.rec.call("read", "simulate", model=MODEL)
        self.baseline_index = self.rec.last_index
        self.checkpoint("read")

    # -- step 1 --------------------------------------------------------------------
    def event_windows(self) -> list[dict[str, float]]:
        """Days of high declared COD load, as the QC tool's event windows."""
        load = np.asarray(self.loads.cod_kg_d, dtype=float)
        t = np.asarray(self.loads.t, dtype=float)
        q = float(self.cfg["qc"]["event_load_quantile"])
        high = load > np.quantile(load, q)
        windows = []
        i = 0
        while i < high.size:
            if high[i]:
                j = i
                while j + 1 < high.size and high[j + 1]:
                    j += 1
                windows.append({"start": float(t[i]), "end": float(t[j]) + 1.0})
                i = j + 1
            else:
                i += 1
        return windows

    def step_qc(self) -> None:
        """Step 1: QC on every sensor and the exclusion rules (design §3.1)."""
        qc = self.cfg["qc"]
        payload = [
            {"name": s.name, "t": s.t, "value": s.value, "unit": s.unit}
            for s in self.series.values()
        ]
        out = self.rec.call("qc", "data_qc", series=payload, event_windows=self.event_windows())
        index = self.rec.last_index
        by_name = {r.name: r for r in out.results}
        cal_channels = set(self.cfg["calibration"]["channels"])
        for name, s in self.series.items():
            r = by_name[name]
            s.flags = list(r.flags)
            s.missing_fraction = float(r.missing_fraction)
            for seg in r.flatlines:
                s.quarantine(float(seg.start), float(seg.end))
                if float(seg.end) - float(seg.start) >= float(qc["flatline_flag_d"]):
                    s.status = "flagged"
                    self.abstentions.append(f"{name}_claims")
                    self.evidence.append(
                        _ev(
                            "R1a",
                            self.lab["sensor"],
                            f"{name} flatlined for {seg.end - seg.start:.0f} d",
                            {"sensor": name, "start_d": float(seg.start), "end_d": float(seg.end)},
                            [index],
                        )
                    )
            if s.quarantined and s.status == "ok":
                s.status = "quarantined"
            spikes = np.asarray(r.spikes, dtype=float)
            if spikes.size:
                drop = np.isin(s.t, spikes)
                s.value = np.where(drop, np.nan, s.value)
            if r.drift_flag and s.drift_exceeds_declared(
                float(r.drift_slope_per_d or 0.0), float(qc["drift_bound_factor"])
            ):
                s.status = "flagged"
                s.in_objective = False
                self.evidence.append(
                    _ev(
                        "R1a",
                        self.lab["sensor"],
                        f"{name} drifts ({r.drift_slope_per_d:.3g} unit/d) beyond its "
                        "declared drift bound",
                        {
                            "sensor": name,
                            "slope_per_d": _f(r.drift_slope_per_d),
                            "signal_to_noise": _f(r.drift_signal_to_noise),
                            "declared_bound": _f(s.drift_bound),
                        },
                        [index],
                    )
                )
            elif r.drift_flag:
                s.flags.append("drift_within_declared_bound")
            if r.informative_missingness:
                self.abstentions.append("missing_transient")
                self.evidence.append(
                    _ev(
                        "R5",
                        self.lab["initial_state"],
                        f"{name} is missing preferentially in event windows",
                        {"sensor": name, "event_missing_ratio": _f(r.event_missing_ratio)},
                        [index],
                    )
                )
            if name not in cal_channels:
                s.in_objective = False
            if int(s.observed(self.cal).sum()) < int(qc["min_samples"]):
                s.in_objective = False
                if s.status == "ok":
                    s.status = "excluded"
            if s.status == "flagged":
                s.in_objective = s.in_objective and not r.drift_flag
        self.abstentions = sorted(set(self.abstentions))
        self.checkpoint("qc")

    @property
    def calibrated(self) -> list[Series]:
        """The sensors in the calibration objective."""
        return [s for s in self.series.values() if s.in_objective]

    def calibration_data(self, exclude: set[str] | None = None) -> list[dict[str, Any]]:
        """The observed series of the objective, calibration window only."""
        return [
            s.as_observed(self.cal) for s in self.calibrated if not exclude or s.name not in exclude
        ]

    # -- step 2 --------------------------------------------------------------------
    def step_balance(self) -> None:
        """Step 2: COD, N and charge closure over fixed windows."""
        mb = self.cfg["mass_balance"]
        width = float(mb["window_d"])
        windows = []
        start = 0.0
        while start + width <= self.T + 1e-9:
            windows.append({"start": start, "end": start + width})
            start += width
        if not windows:
            windows.append({"start": 0.0, "end": self.T})
        geometry = self.cfg["plant_geometry"][str(self.manifest["plant"])]
        temp = self.series.get("temperature")
        t_op = _finite_mean(temp.value) if temp is not None else float(geometry["T_op_K"])
        if not math.isfinite(t_op):
            t_op = float(geometry["T_op_K"])

        def obs(name: str) -> dict[str, Any] | None:
            s = self.series.get(name)
            return None if s is None else s.as_observed()

        out = self.rec.call(
            "balance",
            "mass_balance",
            windows=windows,
            t=np.asarray(self.loads.t),
            q_in_m3_d=np.asarray(self.loads.q_m3_d),
            cod_in_kg_d=np.asarray(self.loads.cod_kg_d),
            tkn_in_kg_n_d=np.asarray(self.loads.tkn_kg_n_d),
            charge_in_keq_d=np.asarray(self.loads.charge_keq_d),
            gas_flow=obs("gas_flow"),
            ch4_fraction=obs("ch4_fraction"),
            cod_out=obs("cod_total"),
            tan_out=obs("tan"),
            ph=obs("ph"),
            alkalinity=obs("alkalinity"),
            vfa=obs("vfa_total"),
            V_liq_m3=float(geometry["V_liq_m3"]),
            T_op_K=float(t_op),
        )
        index = self.rec.last_index
        cod = [w.cod_closure for w in out.windows if w.cod_closure is not None]
        bad = [w for w in out.windows if w.cod_admissible is False]
        self.balance = {
            "n_windows": len(out.windows),
            "n_cod_evaluable": len(cod),
            "n_cod_inadmissible": len(bad),
            "cod_closure_mean": _f(np.mean(cod)) if cod else None,
            "n_closure_mean": _f(
                np.mean([w.n_closure for w in out.windows if w.n_closure is not None])
            )
            if any(w.n_closure is not None for w in out.windows)
            else None,
            "charge_drift": _f(out.charge_drift),
            "charge_consistent": out.charge_consistent,
            "admissible": bool(out.admissible),
            "call_index": index,
        }
        if len(bad) >= int(self.cfg["attribution"]["balance_windows_min"]):
            self.evidence.append(
                _ev(
                    "R2",
                    self.lab["influent"],
                    f"COD balance inadmissible in {len(bad)} windows",
                    {
                        "n_inadmissible": len(bad),
                        "cod_closure_mean": self.balance["cod_closure_mean"],
                    },
                    [index],
                )
            )
        if out.charge_consistent is False:
            self.evidence.append(
                _ev(
                    "balance",
                    self.lab["sensor"],
                    "the implied strong-ion difference drifts across windows",
                    {"charge_drift": _f(out.charge_drift)},
                    [index],
                )
            )
        self.checkpoint("balance")

    # -- steps 3-5 -----------------------------------------------------------------
    def _outputs(self) -> list[str]:
        """The model outputs the objective observes."""
        return [s.channel for s in self.calibrated]

    def step_screen(self) -> None:
        """Steps 3-5: Morris, Sobol on the Morris subset, Fisher at the defaults."""
        cfg, scr, gsa = self.cfg, self.cfg["screening"], self.cfg["gsa"]
        params = list(self.model["parameters"])
        outputs = self._outputs()
        window = {"start": self.cal[0], "end": self.cal[1]}
        k = len(params)
        self.screening = {"declared": params}
        # Morris
        ranking: list[str] = []
        kept: list[str] = []
        scores: dict[str, float] = {}
        for r in self.plan.ladder(
            int(gsa["morris_trajectories"]), int(cfg["plan"]["morris_min_trajectories"])
        ):
            bound = r * (k + 1)
            if not self.plan.fits("morris", bound):
                self.plan.fallbacks.append(f"morris: {r} trajectories do not fit")
                continue
            try:
                out = self.rec.call(
                    "morris",
                    "gsa_morris",
                    model=MODEL,
                    parameters=params,
                    outputs=outputs,
                    summary=str(gsa["summary"]),
                    window=window,
                    n_trajectories=r,
                    seed=int(cfg["seeds"]["morris"]),
                )
            except tools.BudgetExceededError as exc:
                self.plan.fallbacks.append(f"morris: {r} trajectories refused ({exc})"[:160])
                continue
            self.plan.sizes["morris_trajectories"] = r
            for res in out.results:
                mu = np.asarray(res.mu_star, dtype=float)
                top = float(np.nanmax(mu)) if np.isfinite(mu).any() and np.nanmax(mu) > 0 else 1.0
                for name, v in zip(out.parameters, mu, strict=True):
                    scores[name] = max(
                        scores.get(name, 0.0), float(v) / top if math.isfinite(v) else 0.0
                    )
            ranking = sorted(params, key=lambda n: -scores.get(n, 0.0))
            kept = [n for n in ranking if scores.get(n, 0.0) >= float(scr["morris_min_relative"])]
            kept = kept[: int(scr["morris_keep"])]
            break
        if not ranking:
            # the declared fallback: Fisher screening at the defaults
            self.plan.fallbacks.append("morris: replaced by Fisher screening at the defaults")
            self.plan.sizes["morris_trajectories"] = 0
            fim = self._fisher(params, at={}, step="morris_fallback")
            if fim is not None:
                rel = self._relative_crlb(fim)
                ranking = sorted(
                    params, key=lambda n: rel.get(n) if rel.get(n) is not None else np.inf
                )
                kept = ranking[: int(scr["morris_keep"])]
            else:
                ranking = params
                kept = params[: int(scr["morris_keep"])]
        if len(kept) < int(scr["min_subset"]):
            kept = ranking[: int(scr["min_subset"])]
        self.screening.update(
            {
                "morris_ranking": ranking,
                "morris_kept": kept,
                "morris_scores": {n: _f(v) for n, v in scores.items()},
            }
        )
        self.checkpoint("morris")

        # Sobol
        sobol_kept = list(kept)
        total: dict[str, float] = {}
        interactions: list[tuple[str, str, float]] = []
        ks = len(kept)
        ran = False
        if ks >= 2:
            for n_samples in self.plan.ladder(
                int(gsa["sobol_samples"]), int(cfg["plan"]["sobol_min_samples"])
            ):
                bound = n_samples * (2 * ks + 2)
                if not self.plan.fits("sobol", bound):
                    self.plan.fallbacks.append(f"sobol: N={n_samples} does not fit")
                    continue
                try:
                    out = self.rec.call(
                        "sobol",
                        "gsa_sobol",
                        model=MODEL,
                        parameters=kept,
                        outputs=outputs,
                        summary=str(gsa["summary"]),
                        window=window,
                        n_samples=n_samples,
                        second_order=True,
                        seed=int(cfg["seeds"]["sobol"]),
                    )
                except tools.BudgetExceededError as exc:
                    self.plan.fallbacks.append(f"sobol: N={n_samples} refused ({exc})"[:160])
                    continue
                ran = True
                self.plan.sizes["sobol_samples"] = n_samples
                for res in out.results:
                    st = np.asarray(res.ST, dtype=float)
                    for name, v in zip(out.parameters, st, strict=True):
                        total[name] = max(
                            total.get(name, 0.0), float(v) if math.isfinite(v) else 0.0
                        )
                    if res.S2 is not None:
                        s2 = np.asarray(res.S2, dtype=float)
                        for i in range(ks):
                            for j in range(i + 1, ks):
                                if math.isfinite(s2[i, j]):
                                    interactions.append(
                                        (out.parameters[i], out.parameters[j], float(s2[i, j]))
                                    )
                order = sorted(kept, key=lambda n: -total.get(n, 0.0))
                sobol_kept = [
                    n for n in order if total.get(n, 0.0) >= float(scr["sobol_min_total"])
                ]
                if len(sobol_kept) < int(scr["min_subset"]):
                    sobol_kept = order[: int(scr["min_subset"])]
                break
        if not ran:
            self.plan.sizes["sobol_samples"] = 0
            self.plan.skipped["sobol"] = (
                "skipped: the Morris subset stands" if ks >= 2 else "one parameter only"
            )
        interactions.sort(key=lambda x: -abs(x[2]))
        self.screening.update(
            {
                "sobol_kept": sobol_kept,
                "sobol_total_order": {n: _f(v) for n, v in total.items()},
                "sobol_interactions": [(a, b, _f(v)) for a, b, v in interactions[:6]],
            }
        )
        self.checkpoint("sobol")

        # Fisher at the defaults
        approved = list(sobol_kept)
        dropped: list[str] = []
        rel: dict[str, float | None] = {}
        fim = self._fisher(sobol_kept, at={}, step="fisher")
        if fim is not None:
            rel = self._relative_crlb(fim)
            limit = float(cfg["identifiability"]["max_relative_crlb"])
            ok = [n for n in sobol_kept if rel.get(n) is not None and rel[n] <= limit]
            dropped = [n for n in sobol_kept if n not in ok]
            if len(ok) < int(scr["min_subset"]):
                ok = sorted(
                    sobol_kept, key=lambda n: rel.get(n) if rel.get(n) is not None else np.inf
                )[: int(scr["min_subset"])]
                dropped = [n for n in sobol_kept if n not in ok]
            approved = [n for n in sobol_kept if n in ok]
        self.screening.update(
            {
                "fisher_dropped": dropped,
                "fisher_relative_crlb": {n: _f(v) for n, v in rel.items()},
                "profiled": {},
                "approved": approved,
            }
        )
        self.checkpoint("fisher")

    def _fisher(self, params: list[str], at: dict[str, float], step: str) -> Any:
        """``fisher_info`` on ``params`` at ``at``, or None when the plan refuses it."""
        if not params:
            return None
        bound = 2 * len(params)
        if not self.plan.fits(step, bound):
            self.plan.fallbacks.append(f"{step}: {bound} evaluations do not fit")
            return None
        try:
            return self.rec.call(
                step,
                "fisher_info",
                model=MODEL,
                data=self.calibration_data(),
                parameters=params,
                at=at,
            )
        except tools.ToolError as exc:
            self.rec.failure(
                step, "fisher_info", "error", str(exc), "subset unchanged", self.rec.last_index
            )
            return None

    def _relative_crlb(self, fim: Any) -> dict[str, float | None]:
        """CRLB sd over the bound width, per parameter (None on a null direction)."""
        out: dict[str, float | None] = {}
        for name, sd in zip(fim.parameters, np.asarray(fim.crlb_sd, dtype=float), strict=True):
            width = self.model["upper"][name] - self.model["lower"][name]
            out[name] = float(sd / width) if math.isfinite(sd) else None
        return out

    # -- step 6 --------------------------------------------------------------------
    def _fit(
        self, params: list[str], start: dict[str, float], exclude: set[str] | None, tag: str
    ) -> Any:
        """LSQ then DE on ``params`` with the plan's sizes; the lower chi-square wins."""
        cfg, fit, seeds_cfg = self.cfg, self.cfg["fit"], self.cfg["seeds"]
        k = len(params)
        data = self.calibration_data(exclude)
        best = None
        nfev = int(fit["lsq_max_nfev_per_start"])
        for starts in self.plan.ladder(int(fit["lsq_starts"]), 1):
            bound = starts * (nfev + 2 * k + 1) + 2 * k
            if not self.plan.fits(f"{tag}lsq", bound):
                self.plan.fallbacks.append(f"{tag}lsq: {starts} starts do not fit")
                continue
            try:
                best = self.rec.call(
                    f"{tag}lsq",
                    "fit_lsq",
                    model=MODEL,
                    data=data,
                    parameters=params,
                    start=start,
                    n_starts=starts,
                    max_nfev_per_start=nfev,
                    seed=int(seeds_cfg["lsq"]),
                )
            except tools.BudgetExceededError as exc:
                self.plan.fallbacks.append(f"{tag}lsq: {starts} starts refused ({exc})"[:160])
                continue
            except tools.ToolError as exc:
                self.rec.failure(
                    f"{tag}lsq", "fit_lsq", "error", str(exc), "DE alone", self.rec.last_index
                )
                break
            self.plan.sizes[f"{tag}lsq_starts"] = starts
            break
        de = None
        popsize = int(fit["de_popsize"])
        for gens in self.plan.ladder(
            int(fit["de_generations"]), int(cfg["plan"]["de_min_generations"])
        ):
            bound = (gens + 1) * popsize * k + 2 * k
            if not self.plan.fits(f"{tag}de", bound):
                self.plan.fallbacks.append(f"{tag}de: {gens} generations do not fit")
                continue
            try:
                de = self.rec.call(
                    f"{tag}de",
                    "fit_de",
                    model=MODEL,
                    data=data,
                    parameters=params,
                    start=start,
                    popsize=popsize,
                    max_generations=gens,
                    seed=int(seeds_cfg["de"]),
                )
            except tools.BudgetExceededError as exc:
                self.plan.fallbacks.append(f"{tag}de: {gens} generations refused ({exc})"[:160])
                continue
            except tools.ToolError as exc:
                self.rec.failure(
                    f"{tag}de", "fit_de", "error", str(exc), "LSQ alone", self.rec.last_index
                )
                break
            self.plan.sizes[f"{tag}de_generations"] = gens
            break
        if de is None:
            self.plan.skipped[f"{tag}de"] = "skipped"
        if best is None or (de is not None and float(de.chi2) < float(best.chi2)):
            best = de
        return best

    def step_fit(self) -> None:
        """Step 6: the screened fit and the point prediction at its optimum."""
        params = list(self.screening["approved"])
        fit = self._fit(params, {}, None, "")
        if fit is None:
            self.plan.skipped["fit"] = "no fitter fitted the plan: the defaults stand"
            self.optimum = {}
            self.prediction = self.baseline
            self.prediction_index = self.baseline_index
        else:
            self.optimum_fit = fit
            self.optimum = {n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)}
            self.prediction = self.rec.call(
                "predict", "simulate", model=MODEL, parameters=self.optimum
            )
            self.prediction_index = self.rec.last_index
        self.checkpoint("fit")

    def _intervals_from_fit(self, fit: Any) -> None:
        """Fisher intervals from the fit's Jacobian covariance."""
        z = float(self.cfg["uncertainty"]["z"])
        self.final_parameters = {}
        if fit is None:
            return
        sd = None if fit.sd is None else np.asarray(fit.sd, dtype=float)
        for i, name in enumerate(fit.parameters):
            est = float(fit.theta[i])
            lo = hi = None
            if sd is not None and math.isfinite(sd[i]):
                # clipped to the admissible range: an interval is a statement about
                # where the parameter can be, and it cannot be outside its bounds
                lo = max(est - z * float(sd[i]), self.model["lower"][name])
                hi = min(est + z * float(sd[i]), self.model["upper"][name])
            self.final_parameters[name] = {
                "estimate": est,
                "lower": _f(lo),
                "upper": _f(hi),
                "method": "fisher" if lo is not None else "none",
                "at_bound": name in fit.at_bound,
                "unit": str(self.model["units"].get(name, "")),
            }
        self.interval_method = "fisher" if sd is not None else "none"

    def step_profiles(self) -> None:
        """Profiles while the plan allows (design §4), worst-conditioned first."""
        ident, plan = self.cfg["identifiability"], self.cfg["plan"]
        fit = self.optimum_fit
        if fit is None:
            return
        params = list(fit.parameters)
        rel = self.screening.get("fisher_relative_crlb", {})
        order = sorted(params, key=lambda n: -(rel.get(n) if rel.get(n) is not None else np.inf))
        n_grid, n_starts = int(ident["profile_grid"]), int(ident["profile_starts"])
        expected = n_grid * n_starts * int(plan["profile_evals_per_point"])
        for name in order:
            if len(params) < 2:
                break
            if not self.plan.fits("profile", expected, float(plan["profile_share"])):
                self.plan.skipped["profiles"] = "the plan does not allow a profile"
                break
            try:
                out = self.rec.call(
                    "profile",
                    "profile_likelihood",
                    model=MODEL,
                    data=self.calibration_data(),
                    parameters=params,
                    profile=name,
                    center=self.optimum,
                    n_grid=n_grid,
                    n_starts=n_starts,
                    seed=int(self.cfg["seeds"]["profile"]),
                )
            except tools.BudgetExceededError as exc:
                self.plan.fallbacks.append(f"profile {name}: refused ({exc})"[:160])
                self.plan.skipped["profiles"] = "refused by the registry"
                break
            except tools.ToolError as exc:
                self.rec.failure(
                    "profile",
                    "profile_likelihood",
                    "error",
                    str(exc),
                    "Fisher interval stands",
                    self.rec.last_index,
                )
                break
            self.screening["profiled"][name] = bool(out.identifiable)
            lo, hi = out.interval
            entry = self.final_parameters.get(name)
            if entry is not None and lo is not None and hi is not None:
                entry.update({"lower": float(lo), "upper": float(hi), "method": "profile"})
                self.interval_method = "profile"
        if self.screening.get("profiled"):
            self.checkpoint("profiles")

    # -- step 7 --------------------------------------------------------------------
    def step_mcmc(self) -> None:
        """Step 7: the posterior on the approved subset, or the Level-8 fallback."""
        cfg, mc = self.cfg, self.cfg["mcmc"]
        fit = self.optimum_fit
        if fit is None:
            self.plan.skipped["mcmc"] = "no optimum to start from"
            self.abstentions.append("posterior_intervals")
            return
        params = list(fit.parameters)
        k = len(params)
        walkers = max(int(mc["walkers"]), 2 * k + (2 * k) % 2)
        out = None
        for steps in self.plan.ladder(int(mc["steps"]), int(cfg["plan"]["mcmc_min_steps"])):
            bound = walkers * (steps + 1)
            if not self.plan.fits("mcmc", bound):
                self.plan.fallbacks.append(f"mcmc: {steps} steps do not fit")
                continue
            try:
                out = self.rec.call(
                    "mcmc",
                    "bayes_mcmc",
                    model=MODEL,
                    data=self.calibration_data(),
                    parameters=params,
                    start=self.optimum,
                    likelihood=str(mc["likelihood"]),
                    n_walkers=walkers,
                    n_steps=steps,
                    seed=int(cfg["seeds"]["mcmc"]),
                )
            except tools.BudgetExceededError as exc:
                self.plan.fallbacks.append(f"mcmc: {steps} steps refused ({exc})"[:160])
                continue
            except tools.ToolError as exc:
                self.rec.failure(
                    "mcmc",
                    "bayes_mcmc",
                    "error",
                    str(exc),
                    "Fisher intervals stand",
                    self.rec.last_index,
                )
                break
            self.plan.sizes["mcmc_steps"] = steps
            self.plan.sizes["mcmc_walkers"] = walkers
            break
        if out is None:
            if "mcmc_steps" not in self.plan.sizes:
                self.plan.skipped["mcmc"] = "skipped: no size fitted the plan"
            self.abstentions.append("posterior_intervals")
            return
        if not out.converged:
            # the Level-8 rule: a non-converged sampler is a failed tool; the posterior is
            # not reported, the Fisher (or profile) intervals stand, no retry
            self.rec.failure(
                "mcmc",
                "bayes_mcmc",
                "not_converged",
                f"R-hat max {float(np.nanmax(out.rhat)):.3g}, "
                f"ESS min {float(np.nanmin(out.ess)):.3g}; {out.warning}",
                "posterior not reported; Fisher/profile intervals stand",
                self.rec.last_index,
            )
            self.abstentions.append("posterior_intervals")
            self.checkpoint("mcmc")
            return
        self.posterior = out
        q05, q95 = (
            np.asarray(out.quantiles["q05"], dtype=float),
            np.asarray(out.quantiles["q95"], dtype=float),
        )
        for i, name in enumerate(out.parameters):
            entry = self.final_parameters.get(name)
            if entry is not None:
                entry.update(
                    {"lower": float(q05[i]), "upper": float(q95[i]), "method": "posterior"}
                )
        self.interval_method = "posterior"
        self.checkpoint("mcmc")

    # -- step 8 --------------------------------------------------------------------
    def _residual(
        self, s: Series, window: tuple[float, float]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Times, residuals and sds of one series inside ``window``."""
        t_model = np.asarray(self.prediction.t, dtype=float)
        pred = np.asarray(self.prediction.outputs[s.channel], dtype=float)
        mask = s.observed(window)
        t = s.t[mask]
        r = s.value[mask] - np.interp(t, t_model, pred)
        return t, r, s.sd[mask]

    def _covariates(self) -> list[dict[str, Any]]:
        """Load, time, feed batch, feed fractions and temperature as covariates."""
        t = np.asarray(self.loads.t, dtype=float)
        feeds = sorted(self.feed_log)
        masses = (
            np.stack([np.asarray(self.feed_log[f], dtype=float) for f in feeds], axis=1)
            if feeds
            else np.zeros((t.size, 0))
        )
        total = masses.sum(axis=1)
        cov = [
            {"name": "load", "t": t, "value": np.asarray(self.loads.cod_kg_d, dtype=float)},
            {"name": "time", "t": t, "value": t},
        ]
        if feeds:
            dominant = np.argmax(masses, axis=1).astype(float)
            cov.append({"name": "feed_batch", "t": t, "value": dominant, "categorical": True})
            for i, f in enumerate(feeds):
                frac = np.where(total > 0, masses[:, i] / np.where(total > 0, total, 1.0), 0.0)
                cov.append({"name": f"feed_{f}", "t": t, "value": frac})
        temp = self.series.get("temperature")
        if temp is not None and temp.observed().sum() >= 4:
            m = temp.observed()
            cov.append({"name": "temperature", "t": temp.t[m], "value": temp.value[m]})
        return cov

    def step_residuals(self) -> None:
        """Step 8: residual structure per calibrated output."""
        attr = self.cfg["attribution"]
        covariates = self._covariates()
        self.residuals = {}
        for s in self.calibrated:
            t, r, sd = self._residual(s, self.cal)
            if r.size < 4:
                continue
            z = r / sd
            n = int(z.size)
            se = (
                float(z.std(ddof=1) / math.sqrt(n))
                if n > 1 and z.std(ddof=1) > 0
                else 1.0 / math.sqrt(n)
            )
            summary: dict[str, Any] = {
                "n": n,
                "bias_z": _f(z.mean() / se),
                "rmse_z": _f(math.sqrt(float(np.mean(z**2)))),
            }
            # the best before/after split in time
            best_z, best_day = 0.0, None
            min_side = 4
            for cut in range(min_side, n - min_side):
                a, b = z[:cut], z[cut:]
                pooled = (
                    math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
                    if a.size > 1 and b.size > 1
                    else 0.0
                )
                if pooled > 0:
                    dz = abs(float(a.mean() - b.mean())) / pooled
                    if dz > best_z:
                        best_z, best_day = dz, float(t[cut])
            summary["step_z"] = _f(best_z) if best_day is not None else None
            summary["step_day"] = best_day
            early = z[t <= self.cal[0] + float(attr["transient_d"])]
            late = z[t > self.cal[0] + float(attr["transient_d"])]

            def _bias(x: np.ndarray) -> float | None:
                if x.size < 3:
                    return None
                s_e = x.std(ddof=1) / math.sqrt(x.size)
                return _f(x.mean() / s_e) if s_e > 0 else None

            summary["early_bias_z"] = _bias(early)
            summary["late_bias_z"] = _bias(late)
            try:
                out = self.rec.call(
                    "residuals", "residual_diag", t=t, residual=r, covariates=covariates
                )
            except tools.ToolError as exc:
                self.rec.failure(
                    "residuals",
                    "residual_diag",
                    "error",
                    str(exc),
                    "time statistics only",
                    self.rec.last_index,
                )
                summary.update(
                    {
                        "serially_structured": False,
                        "lag1_autocorrelation": 0.0,
                        "trend_slope_per_d": 0.0,
                        "most_explanatory": None,
                        "covariate_eta2": {},
                    }
                )
            else:
                summary.update(
                    {
                        "serially_structured": bool(out.serially_structured),
                        "lag1_autocorrelation": _f(out.lag1_autocorrelation) or 0.0,
                        "trend_slope_per_d": _f(out.trend_slope_per_d) or 0.0,
                        "most_explanatory": out.most_explanatory,
                        "covariate_eta2": {
                            c.name: (_f(c.eta_squared) or 0.0)
                            for c in out.covariates
                            if c.structured
                        },
                        "call_index": self.rec.last_index,
                    }
                )
            self.residuals[s.channel] = summary
        self.checkpoint("residuals")

    # -- the sensor second pass ------------------------------------------------------
    def single_offender(self) -> str | None:
        """R1b: exactly one calibrated channel off while the others are clean."""
        return single_offender(self.cfg, self.residuals, bool(self.balance.get("admissible", True)))

    def step_second_pass(self) -> None:
        """Refit without the one channel the sensor rule flagged (design §3.4)."""
        if not self.cfg["fit"]["second_pass"] or self.optimum_fit is None:
            return
        channel = self.single_offender()
        if channel is None:
            return
        sensor = next((s.name for s in self.calibrated if s.channel == channel), None)
        if sensor is None:
            return
        self.evidence.append(
            _ev(
                "R1b",
                self.lab["sensor"],
                f"{sensor} is the one channel the fitted model does not explain",
                {
                    "sensor": sensor,
                    "bias_z": self.residuals[channel].get("bias_z"),
                    "step_z": self.residuals[channel].get("step_z"),
                    "step_day": self.residuals[channel].get("step_day"),
                },
                [self.prediction_index, self.residuals[channel].get("call_index")],
            )
        )
        self.series[sensor].status = "flagged"
        self.series[sensor].in_objective = False
        self.first_pass = {"optimum": dict(self.optimum), "chi2": _f(self.optimum_fit.chi2)}
        fit = self._fit(list(self.optimum_fit.parameters), self.optimum, None, "second_")
        if fit is None:
            self.plan.skipped["second_pass"] = (
                "the plan does not allow the second fit; the first stands, provisional"
            )
            self.annotations.append("parameters are provisional: fitted through a flagged channel")
            return
        self.optimum_fit = fit
        self.optimum = {n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)}
        self.prediction = self.rec.call(
            "second_predict", "simulate", model=MODEL, parameters=self.optimum
        )
        self.prediction_index = self.rec.last_index
        self.plan.sizes["second_pass"] = True
        self.checkpoint("second_pass")

    def scale_factor(self, sensor: str) -> float | None:
        """Median observed over predicted after the step, for a flagged sensor."""
        s = self.series[sensor]
        t, r, _ = self._residual(s, self.cal)
        pred = np.interp(
            t,
            np.asarray(self.prediction.t, dtype=float),
            np.asarray(self.prediction.outputs[s.channel], dtype=float),
        )
        obs = r + pred
        day = self.residuals.get(s.channel, {}).get("step_day")
        after = t >= day if day is not None else np.ones(t.shape, dtype=bool)
        ok = after & (pred > 0)
        return _f(np.median(obs[ok] / pred[ok])) if ok.sum() >= 3 else None

    # -- step 9 --------------------------------------------------------------------
    def step_assays(self) -> None:
        """Step 9: the declared assay spend at the day of the largest residual."""
        cfg = self.cfg["assays"]
        primary = next(
            (s for s in self.calibrated if s.name == self.cfg["calibration"]["primary_channel"]),
            None,
        )
        if primary is None:
            primary = next(iter(self.calibrated), None)
        if primary is None:
            return
        t, r, sd = self._residual(primary, self.cal)
        if r.size == 0:
            return
        day = float(t[int(np.argmax(np.abs(r / sd)))])
        requests = 0
        prefs = list(cfg["preference"])
        while requests < int(cfg["max_requests"]) and prefs:
            units = int(tools.remaining().assay_units)
            if units <= 0:
                break
            assay = prefs.pop(0)
            try:
                out = self.rec.call("assay", "request_assay", assay=assay, day=day)
            except tools.BudgetExceededError:
                continue
            except tools.ToolError as exc:
                self.rec.failure(
                    "assay", "request_assay", "error", str(exc), "no assay", self.rec.last_index
                )
                continue
            requests += 1
            t_model = np.asarray(self.prediction.t, dtype=float)
            for res in out.results:
                pred = None
                if res.channel in self.prediction.outputs:
                    pred = float(
                        np.interp(
                            day,
                            t_model,
                            np.asarray(self.prediction.outputs[res.channel], dtype=float),
                        )
                    )
                z = (
                    (float(res.value) - pred) / float(res.sd)
                    if pred is not None and res.sd > 0
                    else None
                )
                self.assay_checks.append(
                    {
                        "assay": assay,
                        "channel": res.channel,
                        "sample_day": day,
                        "report_day": float(out.report_day),
                        "value": float(res.value),
                        "unit": res.unit,
                        "sd": float(res.sd),
                        "predicted": _f(pred),
                        "z": _f(z),
                        "disagrees": bool(z is not None and abs(z) >= float(cfg["disagreement_z"])),
                        "call_index": self.rec.last_index,
                    }
                )
        if self.assay_checks:
            self.checkpoint("assays")

    # -- step 10 -------------------------------------------------------------------
    def step_validate(self) -> None:
        """Step 10: hold-out validation with the predictive ensemble."""
        vcfg, plan, seeds_cfg = self.cfg["validation"], self.cfg["plan"], self.cfg["seeds"]
        observed = [s.as_observed() for s in self.calibrated if s.observed(self.holdout).sum() >= 1]
        if not observed:
            self.plan.skipped["validate"] = "no observed sample in the hold-out window"
            return
        t_model = np.asarray(self.prediction.t, dtype=float)
        predicted = {
            s["output"]: np.asarray(self.prediction.outputs[s["output"]], dtype=float)
            for s in observed
        }
        ensemble_rows: list[dict[str, np.ndarray]] = []
        n_draws = 0
        fit = self.optimum_fit
        if fit is not None:
            draws = None
            if self.posterior is not None:
                samples = np.asarray(self.posterior.samples, dtype=float)
                names = list(self.posterior.parameters)
            elif fit.covariance is not None:
                names = list(fit.parameters)
                cov = np.asarray(fit.covariance, dtype=float)
                rng = np.random.default_rng(int(seeds_cfg["ensemble"]))
                samples = (
                    rng.multivariate_normal(
                        np.asarray(fit.theta, dtype=float), cov, size=64, method="cholesky"
                    )
                    if np.all(np.isfinite(cov))
                    else None
                )
                if samples is not None:
                    lower = np.array([self.model["lower"][n] for n in names])
                    upper = np.array([self.model["upper"][n] for n in names])
                    samples = np.clip(samples, lower, upper)
            else:
                samples, names = None, []
            if samples is not None and samples.shape[0] >= 2:
                for size in self.plan.ladder(int(vcfg["ensemble_size"]), int(plan["ensemble_min"])):
                    if self.plan.fits("ensemble", size):
                        pick = np.linspace(0, samples.shape[0] - 1, size).astype(int)
                        draws = samples[pick]
                        break
                    self.plan.fallbacks.append(f"ensemble: {size} draws do not fit")
            if draws is not None:
                for row in draws:
                    try:
                        sim = self.rec.call(
                            "ensemble",
                            "simulate",
                            model=MODEL,
                            parameters={n: float(v) for n, v in zip(names, row, strict=True)},
                        )
                    except tools.ToolError as exc:
                        self.rec.failure(
                            "ensemble",
                            "simulate",
                            "error",
                            str(exc),
                            "fewer draws",
                            self.rec.last_index,
                        )
                        break
                    ensemble_rows.append(
                        {k: np.asarray(v, dtype=float) for k, v in sim.outputs.items()}
                    )
                n_draws = len(ensemble_rows)
        if n_draws >= 2:
            predicted = {ch: np.stack([row[ch] for row in ensemble_rows]) for ch in predicted}
        try:
            out = self.rec.call(
                "validate",
                "validate",
                observed=observed,
                t=t_model,
                predicted=predicted,
                holdout={"start": self.holdout[0], "end": self.holdout[1]},
            )
        except tools.ToolError as exc:
            self.rec.failure(
                "validate", "validate", "error", str(exc), "no validation", self.rec.last_index
            )
            return
        metrics = {}
        violations = 0
        for m in out.results:
            metrics[m.output] = {
                "n": float(m.n),
                "mae": _f(m.mae),
                "rmse": _f(m.rmse),
                "nrmse": _f(m.nrmse),
                "bias": _f(m.bias),
                "coverage_50": _f(m.coverage.get("50")),
                "coverage_90": _f(m.coverage.get("90")),
                "interval_score_90": _f(m.interval_score.get("90")),
                "crps": _f(m.crps),
            }
            violations += int(m.constraint_violations)
        self.validation = {
            "holdout": [self.holdout[0], self.holdout[1]],
            "ensemble": bool(out.ensemble),
            "ensemble_size": n_draws if out.ensemble else 0,
            "metrics": metrics,
            "constraint_violations": violations,
            "calls": [self.rec.last_index],
        }
        self.checkpoint("validate")

    # -- step 11 -------------------------------------------------------------------
    def step_attribute(self) -> None:
        """Step 11: the attribution rule (design §3.7) and the abstentions."""
        flagged = [s.name for s in self.series.values() if s.status == "flagged"]
        primary = self.cfg["calibration"]["primary_channel"]
        channel_of = {s.name: s.channel for s in self.series.values()}
        verdict = classify(
            self.cfg,
            self.lab,
            residuals=self.residuals,
            balance=self.balance,
            flagged=flagged,
            channel_of=channel_of,
            primary_channel=channel_of.get(primary),
            abstentions=list(self.abstentions),
            at_bound=any(e.get("at_bound") for e in self.final_parameters.values()),
            prediction_call=self.prediction_index,
        )
        scale: dict[str, float] = {}
        for name in verdict["flagged"]:
            if name == "gas_flow" and self.prediction is not None:
                f = self.scale_factor(name)
                if f is not None:
                    scale[name] = f
        self.evidence.extend(verdict["evidence"])
        self.abstentions = list(verdict["abstentions"])
        self.classification = {
            **verdict["classification"],
            "evidence": self.evidence,
            "scale_factor": scale,
        }
        rules = verdict["rules"]
        self.annotations.append(f"rules fired: {rules}" if rules else "no rule fired: none")
        self.checkpoint("attribute")

    # -- the state and the report ----------------------------------------------------
    def build_state(self, completed: bool) -> dict[str, Any]:
        """The task state as JSON (``state.task_state.TaskState``)."""
        rem = tools.remaining()
        dq = {}
        for name, s in self.series.items():
            dq[name] = {
                "status": s.status,
                "flags": list(s.flags),
                "missing_fraction": _f(s.missing_fraction),
                "quarantined_windows": [list(w) for w in s.quarantined],
                "in_objective": bool(s.in_objective),
                "notes": "",
            }
        cls = self.classification or {
            "label": self.lab["none"],
            "secondary_labels": [],
            "confidence": 0.0,
            "rule": "pending",
            "evidence": self.evidence,
            "flag_sensor": None,
            "scale_factor": {},
            "revise_influent_mapping": False,
            "recommend_structural_review": False,
            "kinetic_update": False,
        }
        scr = self.screening or {"declared": list(self.model.get("parameters", [])), "approved": []}
        scr = {k: v for k, v in scr.items() if k != "morris_scores"}
        return {
            "schema_version": "1.0",
            "workflow": str(self.cfg["workflow"]),
            "workflow_version": str(self.cfg["workflow_version"]),
            "run_id": str(self.manifest["run_id"]),
            "plant": str(self.manifest["plant"]),
            "tier": str(self.manifest["tier"]),
            "duration_days": self.T,
            "calibration_window": [self.cal[0], self.cal[1]],
            "holdout_window": [self.holdout[0], self.holdout[1]],
            "candidate_model": MODEL,
            "model_parameters": list(self.model.get("parameters", [])),
            "calibrated_outputs": [s.channel for s in self.calibrated],
            "data_quality": dq,
            "mass_balance": {k: v for k, v in self.balance.items() if k != "call_index"},
            "classification": cls,
            "screening": {
                **{"declared": scr.get("declared", []), "approved": scr.get("approved", [])},
                **scr,
            },
            "residuals": {
                ch: {k: v for k, v in r.items() if k != "call_index"}
                for ch, r in self.residuals.items()
            },
            "actions": list(self.rec.actions),
            "tool_failures": list(self.rec.failures),
            "budget": {
                "simulator_evals": int(rem.simulator_evals),
                "simulator_evals_total": int(rem.simulator_evals_total),
                "simulator_evals_used": int(rem.simulator_evals_total) - int(rem.simulator_evals),
                "wall_clock_min": float(rem.wall_clock_min),
                "wall_clock_min_total": float(rem.wall_clock_min_total),
                "assay_units": int(rem.assay_units),
                "assay_units_total": int(rem.assay_units_total),
                "assay_units_used": int(rem.assay_units_total) - int(rem.assay_units),
                "n_calls": int(rem.n_calls),
            },
            "validation": self.validation,
            "assay_checks": [
                {k: v for k, v in a.items() if k != "call_index"} for a in self.assay_checks
            ],
            "abstentions": sorted(set(self.abstentions)),
            "final": {
                "label": cls["label"],
                "secondary_labels": cls["secondary_labels"],
                "confidence": cls["confidence"],
                "parameters": self.final_parameters,
                "interval_method": self.interval_method,
                "abstentions": sorted(set(self.abstentions)),
                "completed": bool(completed),
            },
            "plan": {
                "sizes": dict(self.plan.sizes),
                "fallbacks": list(self.plan.fallbacks),
                "guards_tripped": list(self.plan.guards),
                "eval_seconds_assumed": float(self.cfg["plan"]["eval_seconds_assumed"]),
                "steps_completed": list(self.plan.completed),
                "steps_skipped": dict(self.plan.skipped),
            },
            "notes_seen": list(self.notes),
            "annotations": list(self.annotations),
        }

    def build_report(self, state: dict[str, Any]) -> dict[str, Any]:
        """The human-readable report of the same conclusions."""
        cls = state["classification"]
        lines = [
            f"Plant {state['plant']}, tier {state['tier']}, {state['duration_days']:.0f} d record; "
            f"calibration on [{state['calibration_window'][0]:.0f}, "
            f"{state['calibration_window'][1]:.0f}] d, "
            f"hold-out [{state['holdout_window'][0]:.0f}, {state['holdout_window'][1]:.0f}] d.",
            f"Final label: {cls['label']} (rule {cls['rule']}, confidence {cls['confidence']:.2f})"
            + (f"; also {cls['secondary_labels']}" if cls["secondary_labels"] else "")
            + ".",
        ]
        if cls.get("flag_sensor"):
            lines.append(
                f"Sensor flagged: {cls['flag_sensor']}"
                + (f"; scale factor {cls['scale_factor']}" if cls["scale_factor"] else "")
                + "."
            )
        lines.append(
            f"Approved parameter subset: {state['screening'].get('approved', [])} "
            f"(Morris kept {state['screening'].get('morris_kept', [])}, "
            f"Sobol kept {state['screening'].get('sobol_kept', [])}, "
            f"Fisher dropped {state['screening'].get('fisher_dropped', [])})."
        )
        for name, p in state["final"]["parameters"].items():
            lines.append(
                f"  {name} = {p['estimate']:.3f} [{p['lower']}, {p['upper']}] "
                f"({p['method']}){' at bound' if p['at_bound'] else ''}"
            )
        if state["tool_failures"]:
            lines.append(
                "Tool failures: "
                + "; ".join(
                    f"{f['name']} ({f['kind']}): {f['fallback']}" for f in state["tool_failures"]
                )
            )
        if state["abstentions"]:
            lines.append(f"Abstains on: {state['abstentions']}.")
        if state["validation"]:
            lines.append(
                f"Validation on the hold-out (ensemble={state['validation']['ensemble']}): "
                + ", ".join(
                    f"{ch} nRMSE {m['nrmse']}" for ch, m in state["validation"]["metrics"].items()
                )
                + "."
            )
        lines.append(
            f"Budget: {state['budget']['simulator_evals_used']}/"
            f"{state['budget']['simulator_evals_total']} evaluations, "
            f"{state['budget']['assay_units_used']}/"
            f"{state['budget']['assay_units_total']} assay units."
        )
        lines.append(
            f"Operator notes seen: {len(state['notes_seen'])} (recorded as data; not interpreted)."
        )
        return {
            "workflow": state["workflow"],
            "run_id": state["run_id"],
            "label": cls["label"],
            "confidence": cls["confidence"],
            "abstentions": state["abstentions"],
            "lines": lines,
            "evidence": [e["statement"] for e in cls["evidence"]],
            "completed": state["final"]["completed"],
        }

    # -- the run -------------------------------------------------------------------
    def run(self) -> None:
        """The fixed sequence."""
        self.step_read()
        self.step_qc()
        self.step_balance()
        self.step_screen()
        self.step_fit()
        self._intervals_from_fit(self.optimum_fit)
        self.step_profiles()
        self.step_mcmc()
        self.step_residuals()
        self.step_second_pass()
        if self.plan.sizes.get("second_pass"):
            self._intervals_from_fit(self.optimum_fit)
            self.step_residuals()
        self.step_assays()
        self.step_validate()
        self.step_attribute()
        self.completed = True
        self.write(completed=True)


def single_offender(
    cfg: dict[str, Any], residuals: dict[str, dict[str, Any]], admissible: bool
) -> str | None:
    """R1b (design §3.7): the one channel off while every other one is clean, else None."""
    attr = cfg["attribution"]
    off, clean = [], []
    for ch, r in residuals.items():
        bias = abs(r.get("bias_z") or 0.0)
        step = r.get("step_z") or 0.0
        if bias >= float(attr["sensor_bias_z"]) or step >= float(attr["sensor_step_z"]):
            off.append(ch)
        elif bias <= float(attr["clean_bias_z"]) and not r.get("serially_structured", False):
            clean.append(ch)
    if len(off) == 1 and len(clean) == len(residuals) - 1 and admissible:
        return off[0]
    return None


def classify(
    cfg: dict[str, Any],
    lab: dict[str, str],
    *,
    residuals: dict[str, dict[str, Any]],
    balance: dict[str, Any],
    flagged: list[str],
    channel_of: dict[str, str],
    primary_channel: str | None,
    abstentions: list[str],
    at_bound: bool,
    prediction_call: int | None = None,
) -> dict[str, Any]:
    """The attribution rule of design §3.7 on collected evidence: pure, so it is testable.

    Args:
        cfg: The P0 configuration.
        lab: The label vocabulary (``cfg["labels"]``).
        residuals: Per-channel residual summaries (``ResidualSummary`` fields).
        balance: The mass-balance summary.
        flagged: Sensors QC already flagged (R1a).
        channel_of: Sensor name -> model output.
        primary_channel: The primary channel's model output.
        abstentions: Abstentions collected so far.
        at_bound: Whether any fitted parameter sits at a bound.
        prediction_call: The log index of the simulate call whose prediction the
            residuals are taken against; every residual-derived evidence item names it
            and the residual_diag call of each channel it rests on (ruling A1).

    Returns:
        ``classification`` (without evidence and scale factors), ``evidence`` (new
        items), ``abstentions`` (complete), ``flagged`` (complete), ``rules``.
    """
    attr = cfg["attribution"]
    fired: list[tuple[str, str]] = []
    evidence: list[dict[str, Any]] = []
    flagged = list(flagged)
    abstentions = list(abstentions)
    sensor_of = {ch: name for name, ch in channel_of.items()}

    def _cited(*channels: str | None) -> list[Any]:
        """The prediction and the residual_diag call of each channel (evidence cites calls)."""
        return [prediction_call] + [
            residuals.get(ch, {}).get("call_index") for ch in channels if ch is not None
        ]

    # R1: a flagged sensor (QC), the single offender (post-fit), or the charge check
    offender = single_offender(cfg, residuals, bool(balance.get("admissible", True)))
    if offender is not None and offender not in [channel_of.get(n) for n in flagged]:
        sensor = sensor_of.get(offender)
        if sensor is not None:
            flagged.append(sensor)
            evidence.append(
                _ev(
                    "R1b",
                    lab["sensor"],
                    f"{sensor} is the one channel the fitted model does not explain",
                    {
                        "sensor": sensor,
                        "bias_z": residuals[offender].get("bias_z"),
                        "step_z": residuals[offender].get("step_z"),
                    },
                    _cited(offender),
                )
            )
    # the lead's ruling B(b) of 2026-09-21: a charge inconsistency is sensor evidence only
    # when the pH residual is the single offending channel (it was R1c on its own, and it
    # fired on the plants' background on 8 of 10 pilot cells)
    ph_channel = channel_of.get("ph")
    if (
        balance.get("charge_consistent") is False
        and ph_channel is not None
        and offender == ph_channel
        and "ph" in flagged
    ):
        evidence.append(
            _ev(
                "R1b",
                lab["sensor"],
                "the charge balance also disagrees with the reported pH",
                {"charge_drift": balance.get("charge_drift")},
                [balance.get("call_index"), *_cited(offender)],
            )
        )
    if flagged:
        fired.append(("R1", lab["sensor"]))

    # R2: the influent
    primary_res = residuals.get(primary_channel, {}) if primary_channel else {}
    feed_eta = [v for k, v in primary_res.get("covariate_eta2", {}).items() if k.startswith("feed")]
    feed_structured = str(primary_res.get("most_explanatory") or "").startswith("feed") and max(
        feed_eta or [0.0]
    ) >= float(attr["feed_eta2_min"])
    if (
        int(balance.get("n_cod_inadmissible", 0)) >= int(attr["balance_windows_min"])
        or feed_structured
    ):
        fired.append(("R2", lab["influent"]))
        if feed_structured:
            evidence.append(
                _ev(
                    "R2",
                    lab["influent"],
                    "the primary residual is structured by the feed batch",
                    {"most_explanatory": primary_res.get("most_explanatory")},
                    _cited(primary_channel),
                )
            )

    # R5: the initial transient only. The QC informative-missingness path was dropped by
    # the lead's ruling B(a) of 2026-09-21 (it fired on 9 of 10 pilot cells: the
    # observation model's conditional missingness is the plant's, not a fault); the QC
    # finding is still recorded and still abstains on `missing_transient`.
    early = primary_res.get("early_bias_z")
    late = primary_res.get("late_bias_z")
    transient_only = (
        early is not None
        and late is not None
        and abs(early) >= float(attr["state_bias_z"])
        and abs(late) <= float(attr["clean_bias_z"])
    )
    if transient_only:
        fired.append(("R5", lab["initial_state"]))
        if transient_only:
            evidence.append(
                _ev(
                    "R5",
                    lab["initial_state"],
                    "the primary residual is biased in the initial window only",
                    {"early_bias_z": early, "late_bias_z": late},
                    _cited(primary_channel),
                )
            )

    # R4: a common change point across channels
    steps = [
        (ch, r["step_day"], r["step_z"])
        for ch, r in residuals.items()
        if r.get("step_z") is not None
        and r["step_z"] >= float(attr["parameter_step_z"])
        and r.get("step_day") is not None
    ]
    common = False
    if len(steps) >= int(attr["parameter_channels_min"]):
        days = sorted(d for _, d, _ in steps)
        tol = float(attr["step_day_tolerance_d"])
        for day in days:
            if sum(1 for d in days if abs(d - day) <= tol) >= int(attr["parameter_channels_min"]):
                common = True
                break
    if common and balance.get("admissible", True) and not feed_structured:
        fired.append(("R4", lab["parameter"]))
        evidence.append(
            _ev(
                "R4",
                lab["parameter"],
                "a common change point in the residuals of several channels",
                {ch: d for ch, d, _ in steps},
                _cited(*(ch for ch, _, _ in steps)),
            )
        )

    # R3: persistent structure after the fit
    structured = [
        ch
        for ch, r in residuals.items()
        if (r.get("rmse_z") or 0.0) >= float(attr["structural_rmse_z_min"])
        and r.get("serially_structured")
        and (r.get("most_explanatory") in ("load", "time") or at_bound)
    ]
    if len(structured) >= int(attr["structural_channels_min"]) and not common:
        fired.append(("R3", lab["structural"]))
        evidence.append(
            _ev(
                "R3",
                lab["structural"],
                "residuals stay structured by load or time after the fit",
                {ch: residuals[ch].get("rmse_z") for ch in structured},
                _cited(*structured),
            )
        )
        abstentions += ["parameter_values", "kinetic_attribution"]
        abstentions += [f"{ch}_budget" for ch in structured]
        if "alkalinity_total" in structured:
            abstentions.append("inorganic_carbon_balance")

    labels = [label for _, label in fired]
    if fired:
        rule, label = fired[0]
        secondary = [x for x in labels[1:] if x != label]
        conf = (
            attr["confidence"]["single"]
            if len(set(labels)) == 1
            else attr["confidence"]["multiple"]
        )
    else:
        rule, label, secondary, conf = "R6", lab["none"], [], attr["confidence"]["none"]
    if label in (lab["sensor"], lab["influent"], lab["structural"]):
        abstentions.append("kinetic_attribution")
    return {
        "classification": {
            "label": label,
            "secondary_labels": secondary,
            "confidence": float(conf),
            "rule": rule,
            "flag_sensor": flagged[0] if flagged else None,
            "revise_influent_mapping": lab["influent"] in labels,
            "recommend_structural_review": lab["structural"] in labels,
            "kinetic_update": label in (lab["parameter"], lab["none"]),
        },
        "evidence": evidence,
        "abstentions": sorted(set(abstentions)),
        "flagged": flagged,
        "rules": [r for r, _ in fired],
    }


def _ev(
    rule: str, label: str, statement: str, values: dict[str, Any], calls: list[Any]
) -> dict[str, Any]:
    return {
        "rule": rule,
        "label": label,
        "statement": statement,
        "values": {
            k: (v if isinstance(v, str | bool) or v is None else _f(v)) for k, v in values.items()
        },
        "calls": [int(c) for c in calls if c is not None],
    }


def main() -> int:
    """Run P0 on the run the registry serves."""
    with open(CONFIG_FILE, encoding="utf-8") as fh:
        cfg = json.load(fh)
    pipeline = Pipeline(cfg)
    try:
        pipeline.run()
    except Exception as exc:
        pipeline.annotations.append(f"stopped: {type(exc).__name__}: {str(exc)[:200]}")
        try:
            pipeline.write(completed=False)
        finally:
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
