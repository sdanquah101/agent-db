"""P1 — the single constrained agent (proposal §6.5; ``docs/p1_design.md``).

Runs **inside the jail** (``tools.sandbox.launch``) exactly as P0 does: the only things
that resolve here are ``tools`` (the client stub), numpy, scipy, pydantic and the
standard library. It reads its settings and its prompts from ``p1_config.json`` in its
working directory (the runner writes it from ``configs/workflows/p1.yaml``), the run from
``tools.run``, calls every numerical routine through ``tools.call`` (rule 2), and sends
its model turns through ``tools.llm``: the model, its settings, its key, its turn and
token budget, the verbatim log and the token meter all live on the privileged side.

**What the agent decides and what the harness does.** The model chooses which tool to
call next, with which arguments, and when to conclude or abstain (§6.5). The harness
below is plumbing that a language model cannot do through a JSON argument. It turns a
sensor name into the observed series a tool takes (sample times, values, the declared
noise as weights, quarantines applied), and a call index into the prediction or posterior
that call returned. It supplies each stochastic call's seed (``seeds.base`` plus the call
index; rule 4). It restricts data to the calibration window, except for ``validate`` on
the frozen hold-out. And it summarises long arrays in tool results. It also holds the
structured task state (§6.6), which the model fills through three workspace actions
(``set_sensor_status``, ``record_evidence``, ``conclude``), and it refuses an action the
common constraints forbid:
- an evidence item citing no call or a call that did not return;
- an abstention outside the published vocabulary;
- a posterior interval with no converged sampler behind it;
- a bounds change without a justification;
- a flagged sensor left in the objective.
Each refusal is returned to the model as an error and recorded under ``tool_failures``.

The state is written through ``tools.run.write_output`` after every turn, so a run
stopped by the wall clock keeps the state it reached; a run that never concludes is
written with ``completed`` false and counts as a failed run (§6.7 D). Operator notes are
shown to the model as data, marked as such; the state records their day, author and
length, never their text.
"""

from __future__ import annotations

import json
import math
import string
from typing import Any

import numpy as np

import tools

CONFIG_FILE = "p1_config.json"
STATE_FILE = "state.json"
REPORT_FILE = "report.json"
MODEL = "adm1_fitted"
# The `rule` every P1 evidence item carries: P1 has no rule table, so its items are traced
# by their value keys (the configuration's `evidence_keys`, the evaluator's claim sources).
RULE = "p1"

_STATUSES = ("ok", "quarantined", "excluded", "flagged")
_METHODS = ("posterior", "profile", "fisher", "none")


def visible_notes(notes: list[dict[str, Any]], cal_end: float) -> list[dict[str, Any]]:
    """The operator's notes of the calibration window only.

    A note from a hold-out day is part of the hold-out record (the coordinator's ruling of
    2026-09-25, re-review 3). The window is half-open: day ``cal_end`` itself is the
    hold-out's first day.
    """
    return [n for n in notes if float(n.get("day", 0)) < cal_end]


class ActionError(Exception):
    """An action the harness refuses before it reaches the registry."""


# ------------------------------------------------------------------ small helpers


def _f(x: Any) -> float | None:
    """A JSON-safe float (None for non-finite or missing)."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _nan(values: list[Any]) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def _round(x: float) -> float | None:
    v = _f(x)
    return None if v is None else float(f"{v:.5g}")


def compact(value: Any, preview: int) -> Any:
    """A tool output made readable: long arrays summarised, floats to five digits."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, dict):
        return {str(k): compact(v, preview) for k, v in value.items()}
    if isinstance(value, list | tuple):
        flat = all(isinstance(v, int | float) or v is None for v in value)
        if flat and len(value) > preview:
            arr = _nan(list(value))
            finite = arr[np.isfinite(arr)]
            head = [_round(v) if v is not None else None for v in value[: preview // 2]]
            tail = [_round(v) if v is not None else None for v in value[-(preview // 2) :]]
            return {
                "n": len(value),
                "n_missing": int(arr.size - finite.size),
                "min": _round(finite.min()) if finite.size else None,
                "max": _round(finite.max()) if finite.size else None,
                "mean": _round(finite.mean()) if finite.size else None,
                "first": head,
                "last": tail,
            }
        return [compact(v, preview) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str | int):
        return value
    if isinstance(value, float):
        return _round(value)
    return value


def check(value: Any, schema: dict[str, Any], where: str = "input") -> None:
    """Validate a tool input against the small JSON-schema subset the tool specs use.

    Raises:
        ActionError: On the first mismatch, naming where it is.
    """
    kinds = schema.get("type")
    if isinstance(kinds, str):
        kinds = [kinds]
    if kinds:
        ok = False
        for kind in kinds:
            if (
                (kind == "null" and value is None)
                or (kind == "object" and isinstance(value, dict))
                or (kind == "array" and isinstance(value, list))
                or (kind == "string" and isinstance(value, str))
                or (kind == "boolean" and isinstance(value, bool))
                or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
                or (
                    kind == "number"
                    and isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                )
            ):
                ok = True
        if not ok:
            raise ActionError(f"{where}: expected {' or '.join(kinds)}, got {value!r:.80}")
    if "enum" in schema and value not in schema["enum"]:
        raise ActionError(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ActionError(f"{where}: missing required field {key!r}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                raise ActionError(f"{where}: unknown field(s) {extra}")
        extra_schema = schema.get("additionalProperties")
        for key, item in value.items():
            if key in props:
                check(item, props[key], f"{where}.{key}")
            elif isinstance(extra_schema, dict):
                check(item, extra_schema, f"{where}.{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise ActionError(f"{where}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ActionError(f"{where}: at most {schema['maxItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                check(item, schema["items"], f"{where}[{i}]")


# ------------------------------------------------------------------ the call record


class Recorder:
    """Every registry call goes through here: the action record of §6.6, and the failures.

    As P0's: each call is named the way the visible log names it (``tools.last_call()``),
    so the action record and ``calls.jsonl`` agree line for line.
    """

    def __init__(self) -> None:
        """Start with no actions and no failures."""
        self.actions: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    @staticmethod
    def next_index() -> int:
        """The registry call index the next call will carry."""
        return int(tools.remaining().n_calls)

    def call(self, step: str, name: str, **args: Any) -> tuple[Any, int]:
        """Call a tool, record it; return its output and call index; re-raise its error."""
        index = self.next_index()
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
        return out, index

    def _finish(self, record: dict[str, Any]) -> None:
        logged = tools.last_call() or {}
        record["version"] = str(logged.get("version", ""))
        record["args_hash"] = str(logged.get("args_hash", ""))
        record["seq"] = logged.get("seq")
        self.actions.append(record)

    def failure(
        self, step: str, name: str, kind: str, message: str, fallback: str, index: int | None
    ) -> None:
        """Record a tool or an action that did not deliver, and what happened instead."""
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

    def ok_index(self, index: int) -> dict[str, Any] | None:
        """The action of a call index, if that call returned ``ok``."""
        for a in self.actions:
            if a["call_index"] == index and a["outcome"] == "ok":
                return a
        return None


# ------------------------------------------------------------------ the record


class Series:
    """One sensor as the harness serves it: times, values (NaN missing), weights, status."""

    def __init__(
        self, name: str, raw: dict[str, Any], noise: dict[str, Any], cal: dict, cal_end: float
    ) -> None:
        """Set up from the run view's record and the declared noise.

        Every statistic is taken from the calibration window ``t < cal_end`` only, so that
        no hold-out value reaches a weight, a z-score or a fit (the re-review of 1624e4d, 1).
        """
        self.name = name
        self.channel = str(raw["channel"])
        self.unit = str(raw["unit"])
        self.t = np.asarray(raw["sample_t_d"], dtype=float)
        self.raw = _nan(list(raw["value"]))
        self.value = self.raw.copy()
        self.noise = {k: _f(v) for k, v in noise.items()}
        cv = float(noise.get("cv") or 0.0)
        sd_abs = float(noise.get("sd_abs") or 0.0)
        in_cal = self.raw[(self.t < cal_end) & np.isfinite(self.raw)]
        scale = float(np.median(np.abs(in_cal))) if in_cal.size else 1.0
        floor = max(float(cal["min_relative_sd"]) * scale, float(cal["sd_floor_abs"]))
        sd = np.sqrt((cv * np.abs(np.nan_to_num(self.raw))) ** 2 + sd_abs**2)
        self.sd = np.maximum(sd, floor)
        self.status = "ok"
        self.in_objective = True
        self.flags: list[str] = []
        self.quarantined: list[tuple[float, float]] = []
        self.reason = ""

    def missing_fraction(self) -> float | None:
        """Fraction of the record's samples without a value."""
        return float(np.mean(~np.isfinite(self.raw))) if self.raw.size else None

    def mask(self, window: tuple[float, float] | None) -> np.ndarray:
        """Samples inside the half-open ``[start, end)`` (all when None).

        Half-open so that a sample at exactly the calibration window's end, the hold-out's
        first instant, is never shown to the agent (the re-review of 1624e4d, 1).
        """
        if window is None:
            return np.ones(self.t.shape, dtype=bool)
        return (self.t >= window[0]) & (self.t < window[1])

    def recorded(self) -> dict[str, Any]:
        """The whole record as recorded, no quarantine applied (what validation scores)."""
        return {
            "output": self.channel,
            "t": self.t,
            "value": self.raw,
            "sd": self.sd,
            "unit": self.unit,
        }

    def observed(self, window: tuple[float, float] | None) -> dict[str, Any]:
        """An ``ObservedSeries`` payload restricted to ``window``, quarantines applied."""
        keep = self.mask(window)
        return {
            "output": self.channel,
            "t": self.t[keep],
            "value": self.value[keep],
            "sd": self.sd[keep],
            "unit": self.unit,
        }

    def n_observed(self, window: tuple[float, float] | None) -> int:
        """Samples with a value inside ``window``."""
        return int(np.sum(np.isfinite(self.value) & self.mask(window)))

    def quarantine(self, start: float, end: float) -> None:
        """Drop every sample inside ``[start, end]`` from what tools are given."""
        inside = (self.t >= start) & (self.t <= end)
        self.value = np.where(inside, np.nan, self.value)
        self.quarantined.append((float(start), float(end)))


# ------------------------------------------------------------------ tool specifications

_NUM = {"type": "number"}
_INT = {"type": "integer"}
_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_STRS = {"type": "array", "items": _STR}
_MULT = {"type": "object", "additionalProperties": _NUM}
_WINDOWS = {
    "type": "array",
    "items": {"type": "array", "items": _NUM, "minItems": 2, "maxItems": 2},
}


def _obj(desc: str, props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "description": desc,
        "properties": props,
        "required": list(required),
        "additionalProperties": False,
    }


def _d(schema: dict[str, Any], desc: str) -> dict[str, Any]:
    return {**schema, "description": desc}


_SENSORS = _d(_STRS, "Sensor names (default: the sensors currently in the objective)")
_PARAMS = _d({"type": "array", "items": _STR, "minItems": 1}, "Model parameter names (multipliers)")


def tool_specs() -> list[dict[str, Any]]:
    """Every tool the agent may use: name, description and input schema."""
    fit_common = {
        "parameters": _PARAMS,
        "sensors": _SENSORS,
        "start": _d(_MULT, "Start point, parameter -> multiplier (default: the defaults)"),
        "bounds": _d(
            {"type": "object", "additionalProperties": {"type": "array", "items": _NUM}},
            "Parameter -> [lower, upper] inside the declared bounds; needs bounds_justification",
        ),
        "bounds_justification": _d(_STR, "Why the declared bounds are narrowed"),
    }
    specs = [
        (
            "inspect_record",
            "Read part of the calibration window's record: one sensor's samples, the feed "
            "log, or the feed assays. No registry call and no budget.",
            {
                "what": {"type": "string", "enum": ["sensor", "feed_log", "feed_assays"]},
                "name": _d(_STR, "Sensor name (what = sensor) or feed name (optional filter)"),
                "start_d": _NUM,
                "end_d": _NUM,
                "max_points": _INT,
            },
            ("what",),
        ),
        (
            "describe_model",
            "The fitted model's interface: parameters with defaults, bounds and units; "
            "output channels with units. No evaluation.",
            {},
            (),
        ),
        (
            "feed_loads",
            "The daily COD, TKN, TAN and charge loads the feed log implies through the "
            "declared catalogue. No evaluation.",
            {},
            (),
        ),
        (
            "data_qc",
            "Rule-based quality checks per sensor over the whole record: unit and timestamp "
            "checks, flatlines, spikes, drift, and missingness during high-load event "
            "windows. No evaluation.",
            {
                "sensors": _d(_STRS, "Sensor names (default: every sensor)"),
                "event_load_quantile": _d(
                    {"type": ["number", "null"]},
                    "Days above this quantile of the declared COD load are the event "
                    "windows (default from the configuration; null for none)",
                ),
            },
            (),
        ),
        (
            "mass_balance",
            "COD and N closure over consecutive windows of the whole record, and the "
            "consistency of the implied charge balance. No evaluation.",
            {"window_d": _d(_NUM, "Window width, d (default from the configuration)")},
            (),
        ),
        (
            "simulate",
            "One evaluation of the fitted model over the whole record at the given "
            "multipliers (default 1.0). Returns a summary per observed sensor on the "
            "calibration window; its call index names the prediction for residual_diag, "
            "validate and request_assay.",
            {
                "parameters": _d(_MULT, "Parameter -> multiplier; others stay at 1.0"),
                "biomass_scale": _d(_NUM, "Multiplier on every initial biomass state"),
            },
            (),
        ),
        (
            "gsa_morris",
            "Morris elementary-effects screening on the calibration window. Cost "
            "n_trajectories x (k + 1) evaluations.",
            {
                "parameters": _PARAMS,
                "outputs": _d(_STRS, "Model output channels (default: the objective's)"),
                "summary": {"type": "string", "enum": ["mean", "final", "max", "min"]},
                "n_trajectories": _INT,
            },
            ("parameters",),
        ),
        (
            "gsa_sobol",
            "Variance-based Sobol indices (first, total and optionally second order) on "
            "the calibration window. Cost n_samples x (2k + 2) evaluations with second "
            "order; n_samples a power of two.",
            {
                "parameters": _PARAMS,
                "outputs": _d(_STRS, "Model output channels (default: the objective's)"),
                "summary": {"type": "string", "enum": ["mean", "final", "max", "min"]},
                "n_samples": _INT,
                "second_order": _BOOL,
            },
            ("parameters",),
        ),
        (
            "fisher_info",
            "Fisher information of the named sensors' calibration data about the "
            "parameters at a point: conditioning, correlations, null directions and "
            "Cramer-Rao bounds. Costs about 2k + 1 evaluations.",
            {"parameters": _PARAMS, "sensors": _SENSORS, "at": _d(_MULT, "Point (default 1.0)")},
            ("parameters",),
        ),
        (
            "profile_likelihood",
            "Profile likelihood of one parameter with the others refitted: practical "
            "identifiability. Cost up to n_grid x n_starts x the fitter's evaluations.",
            {
                "parameters": _PARAMS,
                "profile": _d(_STR, "The profiled parameter (one of parameters)"),
                "sensors": _SENSORS,
                "center": _d(_MULT, "Centre of the grid (default 1.0)"),
                "n_grid": _INT,
                "n_starts": _INT,
            },
            ("parameters", "profile"),
        ),
        (
            "fit_lsq",
            "Constrained multistart least squares on the calibration window. Cost at most "
            "n_starts x max_nfev_per_start evaluations.",
            {**fit_common, "n_starts": _INT, "max_nfev_per_start": _INT},
            ("parameters",),
        ),
        (
            "fit_de",
            "Differential evolution on the calibration window. Cost about popsize x k x "
            "(max_generations + 1) evaluations.",
            {**fit_common, "popsize": _INT, "max_generations": _INT},
            ("parameters",),
        ),
        (
            "fit_cmaes",
            "CMA-ES on the calibration window. Cost at most max_evaluations.",
            {**fit_common, "max_evaluations": _INT},
            ("parameters",),
        ),
        (
            "bayes_mcmc",
            "Reduced-parameter MCMC on the calibration window (uniform prior on the bounds). "
            "Cost n_walkers x n_steps evaluations. Report its intervals only if converged.",
            {
                **fit_common,
                "from_fit": _d(_INT, "Call index of a fit whose optimum is the start"),
                "likelihood": {"type": "string", "enum": ["gaussian", "ar1", "heteroscedastic"]},
                "n_walkers": _INT,
                "n_steps": _INT,
            },
            ("parameters",),
        ),
        (
            "residual_diag",
            "Residual structure of one sensor against a prediction on the calibration "
            "window: bias, serial structure, trend, and structure by load, time, feed batch, "
            "feed fraction and temperature. The result adds the standardised summary "
            "(bias_z, rmse_z, step_z, step_day, early_bias_z, late_bias_z). No evaluation.",
            {
                "sensor": _STR,
                "prediction": _d(_INT, "Call index of a simulate"),
                "n_bins": _INT,
            },
            ("sensor", "prediction"),
        ),
        (
            "request_assay",
            "Request a laboratory assay on a day inside the calibration window, at its "
            "declared cost in assay units and its turnaround. With a prediction, the result "
            "adds the predicted value and the disagreement in sd units (disagreement_z).",
            {
                "assay": _STR,
                "day": _NUM,
                "prediction": _d(_INT, "Call index of a simulate to compare with"),
            },
            ("assay", "day"),
        ),
        (
            "voi_assay",
            "Expected information gain of each requestable assay on a day, from the draws "
            "of a sampler call. Costs evaluations (n_outer).",
            {
                "posterior": _d(_INT, "Call index of a bayes_mcmc"),
                "day": _NUM,
                "assays": _STRS,
                "n_outer": _INT,
                "n_inner": _INT,
            },
            ("posterior", "day"),
        ),
        (
            "set_sensor_status",
            "Record your judgement of one sensor: status, whether it enters the objective, "
            "and windows to quarantine (their samples are dropped from every later tool "
            "input). A flagged or excluded sensor never enters the objective.",
            {
                "sensor": _STR,
                "status": {"type": "string", "enum": list(_STATUSES)},
                "in_objective": _BOOL,
                "quarantine": _d(_WINDOWS, "[[start_d, end_d], ...]"),
                "reason": _STR,
            },
            ("sensor", "status", "in_objective", "reason"),
        ),
        (
            "record_evidence",
            "Record one piece of evidence for the classification: the label it points to, "
            "a statement, numbers under published evidence value keys (plus, optionally, "
            "`sensor` or `channel` naming what they concern), and the call indices those "
            "numbers rest on.",
            {
                "label": _STR,
                "statement": _STR,
                "values": {
                    "type": "object",
                    "additionalProperties": {"type": ["number", "string", "boolean", "null"]},
                },
                "calls": {"type": "array", "items": _INT, "minItems": 1},
            },
            ("label", "statement", "values", "calls"),
        ),
        (
            "conclude",
            "Your final, structured conclusion. Ends the run. Parameter estimates are "
            "multipliers with an interval and the method that produced it. Name your final "
            "prediction (a simulate call) or a predictive ensemble (several simulate calls): "
            "after the conclusion is fixed, the harness validates it once on the frozen "
            "hold-out window, and you do not see the result.",
            {
                "prediction": _d(_INT, "Call index of the simulate that is your final prediction"),
                "ensemble": _d(
                    {"type": "array", "items": _INT, "minItems": 2},
                    "Call indices of simulates forming a predictive ensemble",
                ),
                "label": _STR,
                "secondary_labels": _STRS,
                "confidence": _NUM,
                "flag_sensor": {"type": ["string", "null"]},
                "scale_factor": _d(_MULT, "Sensor -> estimated scale factor"),
                "revise_influent_mapping": _BOOL,
                "recommend_structural_review": _BOOL,
                "kinetic_update": _BOOL,
                "approved_parameters": _d(_STRS, "The subset you judged identifiable"),
                "parameters": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "estimate": _NUM,
                            "lower": {"type": ["number", "null"]},
                            "upper": {"type": ["number", "null"]},
                            "method": {"type": "string", "enum": list(_METHODS)},
                        },
                        "required": ["estimate", "lower", "upper", "method"],
                        "additionalProperties": False,
                    },
                },
                "interval_method": {"type": "string", "enum": list(_METHODS)},
                "abstentions": _STRS,
                "summary": _d(_STR, "Two or three sentences for the human report"),
            },
            (
                "label",
                "secondary_labels",
                "confidence",
                "kinetic_update",
                "parameters",
                "interval_method",
                "abstentions",
            ),
        ),
    ]
    return [
        {"name": name, "description": desc, "input_schema": _obj(desc, props, req)}
        for name, desc, props, req in specs
    ]


# ------------------------------------------------------------------ the workspace


class Workspace:
    """The run as the agent works on it: the record, the results, the task state."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Read the run and the model's interface (one ``describe_model`` call)."""
        self.cfg = cfg
        self.lab: dict[str, str] = dict(cfg["labels"])
        self.labels = sorted(set(self.lab.values()))
        self.vocabulary: dict[str, str] = dict(cfg.get("abstentions", {}))
        self.evidence_keys: dict[str, list[str]] = {
            k: list(v) for k, v in cfg["evidence_keys"].items()
        }
        self.preview = int(cfg["loop"]["array_preview"])
        self.rec = Recorder()
        self.manifest = tools.run.manifest()
        self.T = float(self.manifest["duration_days"])
        w = cfg["windows"]
        cal_end = self.T * (1.0 - float(w["holdout_fraction"]))
        self.cal = (float(w["calibration_start_d"]), float(cal_end))
        self.holdout = (float(cal_end), self.T)
        noise = cfg.get("sensor_noise", {})
        record = tools.run.sensors()["sensors"]
        self.series: dict[str, Series] = {
            name: Series(name, record[name], noise.get(name, {}), cfg["calibration"], self.cal[1])
            for name in sorted(record)
        }
        self.feed_log = tools.run.feed_log()
        self.feed_assays = tools.run.feed_assays()
        self._all_notes = tools.run.operator_notes()
        self.notes = visible_notes(self._all_notes, self.cal[1])
        desc, _ = self.rec.call("read", "describe_model", model=MODEL)
        self.params = list(desc.parameter_names)
        self.lower = {n: float(v) for n, v in zip(desc.parameter_names, desc.lower, strict=True)}
        self.upper = {n: float(v) for n, v in zip(desc.parameter_names, desc.upper, strict=True)}
        self.defaults = {
            n: float(v) for n, v in zip(desc.parameter_names, desc.defaults, strict=True)
        }
        self.units = dict(desc.parameter_units)
        self.outputs = list(desc.output_names)
        self.output_units = dict(desc.output_units)
        # the objective starts as every sensor observing a model output, temperature aside
        # (no calibratable parameter moves it)
        for s in self.series.values():
            s.in_objective = s.channel in self.outputs and s.channel != "temperature"
            if s.n_observed(self.cal) < 2:
                s.in_objective = False
        self.loads: Any = None
        self.sims: dict[int, Any] = {}
        self.fits: dict[int, Any] = {}
        self.posteriors: dict[int, Any] = {}
        self.fishers: dict[int, Any] = {}
        self.fisher_at: dict[int, dict[str, float]] = {}
        self.sim_params: dict[int, dict[str, float]] = {}
        self.profiles: dict[int, Any] = {}
        # the evidence values each call produced, by call index and evidence key: an
        # evidence item may cite only these (§6.5: no fabricated values)
        self.produced: dict[int, dict[str, list[Any]]] = {}
        self.residuals: dict[str, dict[str, Any]] = {}
        self.balance: dict[str, Any] = {}
        self.screening: dict[str, Any] = {"declared": list(self.params)}
        self.validation: dict[str, Any] | None = None
        self.assay_checks: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.steps: list[str] = []
        self.annotations: list[str] = []
        self.final: dict[str, Any] | None = None

    # -- data ----------------------------------------------------------------------------
    def sensor(self, name: Any) -> Series:
        """A sensor by name.

        Raises:
            ActionError: If the tier carries no such sensor.
        """
        if not isinstance(name, str) or name not in self.series:
            raise ActionError(f"no sensor {name!r} at this tier; sensors: {sorted(self.series)}")
        return self.series[name]

    def objective(self) -> list[Series]:
        """The sensors currently in the calibration objective."""
        return [s for s in self.series.values() if s.in_objective]

    def data(self, names: list[str] | None) -> list[dict[str, Any]]:
        """Observed series (calibration window) of the named sensors, or of the objective.

        Raises:
            ActionError: If a named sensor is unknown, flagged or excluded, or none has data.
        """
        chosen = self.objective() if not names else [self.sensor(n) for n in names]
        for s in chosen:
            if s.status in ("flagged", "excluded"):
                raise ActionError(
                    f"{s.name} is {s.status}; a flagged or excluded sensor is not fitted"
                )
            if s.channel not in self.outputs:
                raise ActionError(f"{s.name} observes {s.channel}, which the model does not output")
        out = [s.observed(self.cal) for s in chosen if s.n_observed(self.cal) >= 2]
        if not out:
            raise ActionError("no sensor with observed samples in the calibration window")
        return out

    def check_parameters(self, names: list[str]) -> None:
        """Every name is a calibratable parameter.

        Raises:
            ActionError: Otherwise.
        """
        unknown = [n for n in names if n not in self.params]
        if unknown:
            raise ActionError(f"unknown parameter(s) {unknown}; see describe_model")

    def seed(self) -> int:
        """Rule 4: the declared base plus the call index the next call will carry."""
        return int(self.cfg["seeds"]["base"]) + Recorder.next_index()

    def need_loads(self, step: str) -> Any:
        """The feed loads, calling ``feed_loads`` once if no call has been made yet."""
        if self.loads is None:
            self.loads, _ = self.rec.call(step, "feed_loads", model=MODEL)
        return self.loads

    def stored(self, table: dict[int, Any], index: Any, what: str) -> Any:
        """A stored result by call index.

        Raises:
            ActionError: If no successful call of that kind has that index.
        """
        if not isinstance(index, int) or index not in table:
            raise ActionError(f"no {what} result with call_index {index!r}; have {sorted(table)}")
        return table[index]

    def budget(self) -> dict[str, Any]:
        """What is left of the registry's envelope."""
        rem = tools.remaining()
        return {
            "simulator_evals_left": int(rem.simulator_evals),
            "wall_clock_min_left": round(float(rem.wall_clock_min), 1),
            "assay_units_left": int(rem.assay_units),
        }

    # -- the record, as text -----------------------------------------------------------
    def sensors_text(self) -> str:
        """One line per sensor for the task prompt (calibration window only)."""
        lines = []
        for s in self.series.values():
            m = s.mask(self.cal)
            vals = s.value[m]
            fin = vals[np.isfinite(vals)]
            cadence = float(np.median(np.diff(s.t))) if s.t.size > 1 else float("nan")
            stats = (
                f"min {_round(fin.min())}, median {_round(np.median(fin))}, max {_round(fin.max())}"
                if fin.size
                else "no values"
            )
            lines.append(
                f"- `{s.name}` -> `{s.channel}` [{s.unit}]: {int(m.sum())} samples every "
                f"~{_round(cadence)} d, {int(m.sum()) - fin.size} missing; {stats}; noise "
                f"{json.dumps({k: v for k, v in s.noise.items() if v is not None})}; "
                f"{'in' if s.in_objective else 'not in'} the objective"
            )
        return "\n".join(lines)

    def feeds_text(self) -> str:
        """The feed log, per feed, for the task prompt (calibration window only)."""
        lines = []
        n_cal = math.ceil(self.cal[1])  # days 0 .. n_cal - 1, all < cal_end
        for name in sorted(self.feed_log):
            x = np.asarray(self.feed_log[name], dtype=float)[:n_cal]
            lines.append(
                f"- `{name}`: {int(np.sum(x > 0))} of {x.size} days fed; mean "
                f"{_round(np.nanmean(x)) if x.size else None} kg wet/d, max "
                f"{_round(np.nanmax(x)) if x.size else None}"
            )
        return "\n".join(lines) or "(no feed log)"

    def assays_text(self) -> str:
        """Counts of the feed assays in the calibration window, by feed and assay."""
        counts: dict[str, int] = {}
        for a in self.feed_assays:
            if float(a.get("sample_day_d", 0)) < self.cal[1]:
                key = f"{a.get('feed_id')}:{a.get('assay')} [{a.get('unit')}, {a.get('basis')}]"
                counts[key] = counts.get(key, 0) + 1
        return ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())) or "none"

    def notes_text(self) -> str:
        """The operator's notes as quoted data."""
        if not self.notes:
            return "(none)"
        return "\n".join(
            f"- day {n.get('day')}, {n.get('author', '')}: <note>{n.get('text', '')}</note>"
            for n in self.notes
        )

    def model_text(self) -> str:
        """The model's interface for the task prompt."""
        rows = [
            f"- `{n}`: default {_round(self.defaults[n])}, bounds "
            f"[{_round(self.lower[n])}, {_round(self.upper[n])}], {self.units.get(n, '')}"
            for n in self.params
        ]
        outs = ", ".join(f"`{o}` [{self.output_units.get(o, '')}]" for o in self.outputs)
        assays = "\n".join(
            f"- `{name}`: measures `{a['channel']}`, {a['unit_cost']} assay unit(s), reported "
            f"{a['turnaround_d']:g} d after the sample day"
            for name, a in sorted(self.cfg.get("assay_catalogue", {}).items())
        )
        return (
            "Parameters (multipliers):\n"
            + "\n".join(rows)
            + "\n\nOutputs: "
            + outs
            + "\n\nRequestable assays (`request_assay`):\n"
            + (assays or "(none)")
        )

    # -- tool handlers -----------------------------------------------------------------
    def run_tool(self, name: str, inp: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one tool use; the result is what the model reads.

        Raises:
            ActionError: The harness refused the action.
            tools.ToolError: The registry refused or the tool failed.
        """
        handler = self.handlers().get(name)
        if handler is None:
            raise ActionError(f"no tool {name!r}")
        return handler(inp)

    def handlers(self) -> dict[str, Any]:
        """Tool name -> handler."""
        return {
            "inspect_record": self.t_inspect,
            "describe_model": self.t_describe,
            "feed_loads": self.t_feed_loads,
            "data_qc": self.t_qc,
            "mass_balance": self.t_balance,
            "simulate": self.t_simulate,
            "gsa_morris": self.t_morris,
            "gsa_sobol": self.t_sobol,
            "fisher_info": self.t_fisher,
            "profile_likelihood": self.t_profile,
            "bayes_mcmc": self.t_mcmc,
            "residual_diag": self.t_residual,
            "request_assay": self.t_assay,
            "voi_assay": self.t_voi,
            "set_sensor_status": self.t_status,
            "record_evidence": self.t_evidence,
        }

    def produce(self, index: int, key: str, value: Any, sensor: str | None = None) -> None:
        """Record a value a call produced under an evidence key, and the sensor it concerns.

        ``sensor`` is None for a value no single sensor owns (a balance, an assay).
        """
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        self.produced.setdefault(index, {}).setdefault(key, []).append((value, sensor))

    def _out(self, index: int | None, result: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if index is not None:
            out["call_index"] = index
        out["result"] = compact(result, self.preview)
        out["budget"] = self.budget()
        return out

    def t_inspect(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Part of the calibration window's record."""
        start = max(float(inp.get("start_d", self.cal[0])), self.cal[0])
        end = min(float(inp.get("end_d", self.cal[1])), self.cal[1])
        limit = min(int(inp.get("max_points", 60)), int(self.cfg["loop"]["max_points_shown"]))
        limit = max(limit, 1)
        what = inp["what"]
        if what == "sensor":
            s = self.sensor(inp.get("name"))
            keep = s.mask((start, end))
            t, v = s.t[keep], s.value[keep]
            stride = max(1, math.ceil(t.size / limit))
            return {
                "sensor": s.name,
                "unit": s.unit,
                "window": [start, end],
                "stride": stride,
                "t": [_round(x) for x in t[::stride]],
                "value": [_round(x) for x in v[::stride]],
            }
        if what == "feed_log":
            names = [inp["name"]] if inp.get("name") else sorted(self.feed_log)
            out = {}
            for n in names:
                if n not in self.feed_log:
                    raise ActionError(f"no feed {n!r}; feeds: {sorted(self.feed_log)}")
                x = np.asarray(self.feed_log[n], dtype=float)
                days = np.arange(x.size, dtype=float)
                keep = (days >= start) & (days < end)
                stride = max(1, math.ceil(int(keep.sum()) / limit))
                out[n] = {
                    "day": [int(d) for d in days[keep][::stride]],
                    "kg_wet_d": [_round(v) for v in x[keep][::stride]],
                }
            return {"window": [start, end], "feeds": out}
        rows = [
            a
            for a in self.feed_assays
            if start <= float(a.get("sample_day_d", 0)) < end
            and (not inp.get("name") or a.get("feed_id") == inp.get("name"))
        ]
        stride = max(1, math.ceil(len(rows) / limit))
        return {"window": [start, end], "n": len(rows), "stride": stride, "rows": rows[::stride]}

    def t_describe(self, inp: dict[str, Any]) -> dict[str, Any]:
        """The model interface (a registry call)."""
        out, index = self.rec.call("describe_model", "describe_model", model=MODEL)
        params = {
            n: {
                "default": _round(d),
                "lower": _round(lo),
                "upper": _round(hi),
                "unit": out.parameter_units.get(n, ""),
            }
            for n, d, lo, hi in zip(
                out.parameter_names, out.defaults, out.lower, out.upper, strict=True
            )
        }
        return self._out(index, {"parameters": params, "outputs": dict(out.output_units)})

    def t_feed_loads(self, inp: dict[str, Any]) -> dict[str, Any]:
        """The declared loads (a registry call)."""
        out, index = self.rec.call("feed_loads", "feed_loads", model=MODEL)
        self.loads = out
        return self._out(index, out.model_dump(mode="json"))

    def event_windows(self, quantile: float | None, step: str) -> list[dict[str, float]]:
        """Runs of days whose declared COD load exceeds its ``quantile``."""
        if quantile is None:
            return []
        if not 0.0 < float(quantile) < 1.0:
            raise ActionError("event_load_quantile must lie in (0, 1)")
        loads = self.need_loads(step)
        t_all = np.asarray(loads.t, dtype=float)
        keep = t_all < self.cal[1]
        load = np.asarray(loads.cod_kg_d, dtype=float)[keep]
        t = t_all[keep]
        if not load.size:
            return []
        high = load > np.quantile(load, float(quantile))
        windows, i = [], 0
        while i < high.size:
            if high[i]:
                j = i
                while j + 1 < high.size and high[j + 1]:
                    j += 1
                end = min(float(t[j]) + 1.0, self.cal[1])
                if end > float(t[i]):
                    windows.append({"start": float(t[i]), "end": end})
                i = j + 1
            else:
                i += 1
        return windows

    def t_qc(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Quality checks on the calibration window.

        The hold-out record is not the agent's to read (the coordinator's ruling of
        2026-09-25); P0's QC reads the whole record.
        """
        names = inp.get("sensors") or sorted(self.series)
        chosen = [self.sensor(n) for n in names]
        q = inp.get("event_load_quantile", self.cfg["defaults"]["event_load_quantile"])
        windows = self.event_windows(q, "data_qc")
        payload = []
        for s in chosen:
            m = s.mask(self.cal)
            payload.append({"name": s.name, "t": s.t[m], "value": s.value[m], "unit": s.unit})
        out, index = self.rec.call("data_qc", "data_qc", series=payload, event_windows=windows)
        for r in out.results:
            if r.name in self.series:
                self.series[r.name].flags = list(r.flags)
                self.produce(
                    index, "declared_bound", self.series[r.name].noise.get("drift_bound"), r.name
                )
            self.produce(index, "slope_per_d", _f(r.drift_slope_per_d), r.name)
            self.produce(index, "signal_to_noise", _f(r.drift_signal_to_noise), r.name)
            self.produce(index, "event_missing_ratio", _f(r.event_missing_ratio), r.name)
            for seg in r.flatlines:
                self.produce(index, "start_d", float(seg.start), r.name)
                self.produce(index, "end_d", float(seg.end), r.name)
        return self._out(index, out.model_dump(mode="json"))

    def t_balance(self, inp: dict[str, Any]) -> dict[str, Any]:
        """COD, N and charge closure over the calibration window.

        The coordinator's ruling of 2026-09-25; P0's balance reads the whole record.
        """
        end_d = self.cal[1]
        # the declared default, capped to the calibration window on a short record
        default = min(float(self.cfg["defaults"]["balance_window_d"]), end_d - self.cal[0])
        width = float(inp.get("window_d", default))
        if not 1.0 <= width <= end_d:
            raise ActionError(f"window_d must lie in [1, {end_d:g}] d (the calibration window)")
        windows, start = [], self.cal[0]
        while start + width <= end_d + 1e-9:
            windows.append({"start": start, "end": start + width})
            start += width
        loads = self.need_loads("mass_balance")
        geometry = self.cfg["plant_geometry"][str(self.manifest["plant"])]
        temp = self.series.get("temperature")
        t_op = float(geometry["T_op_K"])
        if temp is not None and np.isfinite(temp.value[temp.mask(self.cal)]).any():
            t_op = float(np.nanmean(temp.value[temp.mask(self.cal)]))
        lt = np.asarray(loads.t, dtype=float)
        lk = lt < end_d

        def obs(name: str) -> dict[str, Any] | None:
            s = self.series.get(name)
            return None if s is None else s.observed(self.cal)

        out, index = self.rec.call(
            "mass_balance",
            "mass_balance",
            windows=windows,
            t=lt[lk],
            q_in_m3_d=np.asarray(loads.q_m3_d)[lk],
            cod_in_kg_d=np.asarray(loads.cod_kg_d)[lk],
            tkn_in_kg_n_d=np.asarray(loads.tkn_kg_n_d)[lk],
            charge_in_keq_d=np.asarray(loads.charge_keq_d)[lk],
            gas_flow=obs("gas_flow"),
            ch4_fraction=obs("ch4_fraction"),
            cod_out=obs("cod_total"),
            tan_out=obs("tan"),
            ph=obs("ph"),
            alkalinity=obs("alkalinity"),
            vfa=obs("vfa_total"),
            V_liq_m3=float(geometry["V_liq_m3"]),
            T_op_K=t_op,
        )
        cod = [w.cod_closure for w in out.windows if w.cod_closure is not None]
        ncl = [w.n_closure for w in out.windows if w.n_closure is not None]
        self.balance = {
            "n_windows": len(out.windows),
            "n_cod_evaluable": len(cod),
            "n_cod_inadmissible": sum(1 for w in out.windows if w.cod_admissible is False),
            "cod_closure_mean": _f(np.mean(cod)) if cod else None,
            "n_closure_mean": _f(np.mean(ncl)) if ncl else None,
            "charge_drift": _f(out.charge_drift),
            "charge_consistent": out.charge_consistent,
            "admissible": bool(out.admissible),
        }
        for key in ("n_inadmissible", "cod_closure_mean", "charge_drift"):
            source = "n_cod_inadmissible" if key == "n_inadmissible" else key
            self.produce(index, key, self.balance[source])
        result = out.model_dump(mode="json")
        result["summary"] = {
            "n_inadmissible": self.balance["n_cod_inadmissible"],
            "cod_closure_mean": self.balance["cod_closure_mean"],
            "charge_drift": self.balance["charge_drift"],
        }
        return self._out(index, result)

    def _multipliers(self, value: Any, what: str) -> dict[str, float]:
        mult = dict(value or {})
        self.check_parameters(list(mult))
        for n, v in mult.items():
            if not self.lower[n] <= float(v) <= self.upper[n]:
                raise ActionError(
                    f"{what}: {n}={v} lies outside its bounds [{self.lower[n]}, {self.upper[n]}]"
                )
        return {n: float(v) for n, v in mult.items()}

    def sim_summary(self, sim: Any) -> dict[str, Any]:
        """Per observed sensor on the calibration window: the standardised misfit."""
        t_model = np.asarray(sim.t, dtype=float)
        out: dict[str, Any] = {}
        for s in self.series.values():
            if s.channel not in sim.outputs:
                continue
            m = s.mask(self.cal) & np.isfinite(s.value)
            if m.sum() < 1:
                continue
            pred = np.interp(s.t[m], t_model, np.asarray(sim.outputs[s.channel], dtype=float))
            z = (s.value[m] - pred) / s.sd[m]
            out[s.name] = {
                "n": int(m.sum()),
                "mean_predicted": _round(pred.mean()),
                "mean_observed": _round(s.value[m].mean()),
                "mean_z": _round(z.mean()),
                "rms_z": _round(math.sqrt(float(np.mean(z**2)))),
            }
        return out

    def t_simulate(self, inp: dict[str, Any]) -> dict[str, Any]:
        """One evaluation; stored under its call index."""
        args: dict[str, Any] = {
            "model": MODEL,
            "parameters": self._multipliers(inp.get("parameters"), "parameters"),
        }
        if inp.get("biomass_scale") is not None:
            if float(inp["biomass_scale"]) <= 0:
                raise ActionError("biomass_scale must be positive")
            args["biomass_scale"] = float(inp["biomass_scale"])
        out, index = self.rec.call("simulate", "simulate", **args)
        self.sims[index] = out
        self.sim_params[index] = dict(args["parameters"])
        return self._out(
            index,
            {
                "success": out.success,
                "message": out.message,
                "n_evaluations": out.n_evaluations,
                "by_sensor": self.sim_summary(out),
            },
        )

    def _outputs(self, value: Any) -> list[str]:
        outs = list(value or [s.channel for s in self.objective()])
        bad = [o for o in outs if o not in self.outputs]
        if bad or not outs:
            raise ActionError(f"unknown output channel(s) {bad}; outputs: {self.outputs}")
        return outs

    def t_morris(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Morris screening on the calibration window."""
        self.check_parameters(inp["parameters"])
        args: dict[str, Any] = {
            "model": MODEL,
            "parameters": list(inp["parameters"]),
            "outputs": self._outputs(inp.get("outputs")),
            "window": {"start": self.cal[0], "end": self.cal[1]},
            "seed": self.seed(),
        }
        for key in ("summary", "n_trajectories"):
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call("gsa_morris", "gsa_morris", **args)
        norm: dict[str, float] = {}
        for r in out.results:
            mu = np.asarray(r.mu_star, dtype=float)
            top = float(np.nanmax(mu)) if mu.size and np.nanmax(mu) > 0 else 1.0
            for n, v in zip(out.parameters, mu, strict=True):
                norm[n] = max(norm.get(n, 0.0), float(v) / top)
        self.screening["morris_ranking"] = sorted(norm, key=lambda n: -norm[n])
        result = {
            "by_output": {
                r.output: {
                    "ranking": list(r.ranking),
                    "mu_star": dict(zip(out.parameters, r.mu_star, strict=True)),
                    "sigma": dict(zip(out.parameters, r.sigma, strict=True)),
                }
                for r in out.results
            },
            "n_evaluations": out.n_evaluations,
        }
        return self._out(index, result)

    def t_sobol(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Sobol indices on the calibration window."""
        self.check_parameters(inp["parameters"])
        args: dict[str, Any] = {
            "model": MODEL,
            "parameters": list(inp["parameters"]),
            "outputs": self._outputs(inp.get("outputs")),
            "window": {"start": self.cal[0], "end": self.cal[1]},
            "seed": self.seed(),
        }
        for key in ("summary", "n_samples", "second_order"):
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call("gsa_sobol", "gsa_sobol", **args)
        names = list(out.parameters)
        total: dict[str, float] = {}
        by_output: dict[str, Any] = {}
        for r in out.results:
            for n, v in zip(names, r.ST, strict=True):
                if _f(v) is not None:
                    total[n] = max(total.get(n, 0.0), float(v))
            entry: dict[str, Any] = {
                "ranking": list(r.ranking),
                "S1": dict(zip(names, r.S1, strict=True)),
                "ST": dict(zip(names, r.ST, strict=True)),
                "ST_conf": dict(zip(names, r.ST_conf, strict=True)),
            }
            if r.S2 is not None:
                s2 = np.asarray(r.S2, dtype=float)
                entry["S2"] = {
                    f"{names[i]}*{names[j]}": s2[i, j]
                    for i in range(len(names))
                    for j in range(i + 1, len(names))
                }
            by_output[r.output] = entry
        if total:
            self.screening["sobol_total_order"] = total
        return self._out(index, {"by_output": by_output, "n_evaluations": out.n_evaluations})

    def t_fisher(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Fisher information on the calibration data."""
        self.check_parameters(inp["parameters"])
        out, index = self.rec.call(
            "fisher_info",
            "fisher_info",
            model=MODEL,
            data=self.data(inp.get("sensors")),
            parameters=list(inp["parameters"]),
            at=self._multipliers(inp.get("at"), "at"),
        )
        self.fishers[index] = out
        at = self._multipliers(inp.get("at"), "at")
        self.fisher_at[index] = at
        rel: dict[str, float | None] = {}
        for n, sd in zip(out.parameters, out.crlb_sd, strict=True):
            width = self.upper[n] - self.lower[n]
            rel[n] = _f(float(sd) / width) if width > 0 else None
        self.screening["fisher_relative_crlb"] = rel
        result = out.model_dump(mode="json")
        result.pop("fim", None)
        result["crlb_sd"] = dict(zip(out.parameters, out.crlb_sd, strict=True))
        result["crlb_sd_over_bound_width"] = rel
        result["interval_90_at_point"] = {
            n: self.fisher_interval(n, at.get(n, 1.0), sd)
            for n, sd in zip(out.parameters, out.crlb_sd, strict=True)
        }
        return self._out(index, result)

    def t_profile(self, inp: dict[str, Any]) -> dict[str, Any]:
        """A profile likelihood."""
        self.check_parameters(inp["parameters"])
        args: dict[str, Any] = {
            "model": MODEL,
            "data": self.data(inp.get("sensors")),
            "parameters": list(inp["parameters"]),
            "profile": inp["profile"],
            "center": self._multipliers(inp.get("center"), "center"),
            "seed": self.seed(),
        }
        for key in ("n_grid", "n_starts"):
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call("profile_likelihood", "profile_likelihood", **args)
        self.profiles[index] = out
        self.screening.setdefault("profiled", {})[out.parameter] = bool(out.identifiable)
        return self._out(index, out.model_dump(mode="json"))

    def _fit_args(self, inp: dict[str, Any]) -> dict[str, Any]:
        self.check_parameters(inp["parameters"])
        args: dict[str, Any] = {
            "model": MODEL,
            "data": self.data(inp.get("sensors")),
            "parameters": list(inp["parameters"]),
            "start": self._multipliers(inp.get("start"), "start"),
            "seed": self.seed(),
        }
        if inp.get("bounds"):
            if not str(inp.get("bounds_justification") or "").strip():
                raise ActionError("a bounds change needs a bounds_justification")
            bounds = {}
            for n, pair in dict(inp["bounds"]).items():
                self.check_parameters([n])
                lo, hi = (float(pair[0]), float(pair[1])) if len(pair) == 2 else (0.0, 0.0)
                if not self.lower[n] <= lo < hi <= self.upper[n]:
                    raise ActionError(
                        f"bounds of {n} must be [lower, upper] inside "
                        f"[{self.lower[n]}, {self.upper[n]}]"
                    )
                bounds[n] = (lo, hi)
            args["bounds"] = bounds
            self.annotations.append(
                f"bounds narrowed ({sorted(bounds)}): {inp['bounds_justification']}"[:300]
            )
        return args

    def fit_result(self, out: Any) -> dict[str, Any]:
        """A fitter's output, by parameter."""
        names = list(out.parameters)
        sd = list(out.sd) if out.sd is not None else [None] * len(names)
        return {
            "fisher_interval_90": {
                n: self.fisher_interval(n, float(t), d)
                for n, t, d in zip(names, out.theta, sd, strict=True)
            },
            "method": out.method,
            "theta": dict(zip(names, out.theta, strict=True)),
            "sd": dict(zip(names, sd, strict=True)),
            "at_bound": list(out.at_bound),
            "chi2": out.chi2,
            "n_data": out.n_data,
            "converged": out.converged,
            "message": out.message,
            "n_evaluations": out.n_evaluations,
        }

    def fit(self, name: str, inp: dict[str, Any]) -> dict[str, Any]:
        """Run the named fitter on the calibration data."""
        args = self._fit_args(inp)
        sizes = {
            "fit_lsq": ("n_starts", "max_nfev_per_start"),
            "fit_de": ("popsize", "max_generations"),
            "fit_cmaes": ("max_evaluations",),
        }[name]
        for key in sizes:
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call(name, name, **args)
        self.fits[index] = out
        return self._out(index, self.fit_result(out))

    def t_mcmc(self, inp: dict[str, Any]) -> dict[str, Any]:
        """The sampler; stored under its call index."""
        inp = dict(inp)
        if inp.get("from_fit") is not None:
            fit = self.stored(self.fits, inp.pop("from_fit"), "fit")
            start = {n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)}
            start.update(inp.get("start") or {})
            inp["start"] = {n: v for n, v in start.items() if n in inp["parameters"]}
        args = self._fit_args(inp)
        for key in ("likelihood", "n_walkers", "n_steps"):
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call("bayes_mcmc", "bayes_mcmc", **args)
        self.posteriors[index] = out
        names = list(out.parameters)
        result = {
            "converged": out.converged,
            "mean": dict(zip(names, out.mean, strict=True)),
            "sd": dict(zip(names, out.sd, strict=True)),
            "quantiles": {
                q: dict(zip(names, v, strict=True)) for q, v in dict(out.quantiles).items()
            },
            "rhat": dict(zip(names, out.rhat, strict=True)),
            "ess": dict(zip(names, out.ess, strict=True)),
            "acceptance_fraction": out.acceptance_fraction,
            "n_walkers": out.n_walkers,
            "n_steps": out.n_steps,
            "n_evaluations": out.n_evaluations,
            "warning": out.warning,
        }
        return self._out(index, result)

    def covariates(self) -> list[dict[str, Any]]:
        """Load, time, feed batch, feed fractions and temperature, as residual covariates."""
        loads = self.need_loads("residual_diag")
        t_all = np.asarray(loads.t, dtype=float)
        keep = t_all < self.cal[1]  # the calibration window only, as every other input
        t = t_all[keep]
        feeds = sorted(self.feed_log)
        cov: list[dict[str, Any]] = [
            {"name": "load", "t": t, "value": np.asarray(loads.cod_kg_d, dtype=float)[keep]},
            {"name": "time", "t": t, "value": t},
        ]
        if feeds:
            masses = np.stack([np.asarray(self.feed_log[f], dtype=float) for f in feeds], axis=1)
            n = min(masses.shape[0], t_all.size)
            masses, tt = masses[:n][keep[:n]], t_all[:n][keep[:n]]
            total = masses.sum(axis=1)
            dominant = np.argmax(masses, axis=1).astype(float)
            cov.append({"name": "feed_batch", "t": tt, "value": dominant, "categorical": True})
            for i, f in enumerate(feeds):
                frac = np.where(total > 0, masses[:, i] / np.where(total > 0, total, 1.0), 0.0)
                cov.append({"name": f"feed_{f}", "t": tt, "value": frac})
        temp = self.series.get("temperature")
        if temp is not None and (np.isfinite(temp.value) & temp.mask(self.cal)).sum() >= 4:
            m = np.isfinite(temp.value) & temp.mask(self.cal)
            cov.append({"name": "temperature", "t": temp.t[m], "value": temp.value[m]})
        return cov

    def standardised(self, t: np.ndarray, z: np.ndarray) -> dict[str, Any]:
        """Bias, RMS, the best step in time and the early/late bias of standardised residuals."""
        n = int(z.size)
        spread = float(z.std(ddof=1)) if n > 1 else 0.0
        se = spread / math.sqrt(n) if spread > 0 else 1.0 / math.sqrt(max(n, 1))
        best_z, best_day = 0.0, None
        for cut in range(4, n - 4):
            a, b = z[:cut], z[cut:]
            pooled = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
            if pooled > 0:
                dz = abs(float(a.mean() - b.mean())) / pooled
                if dz > best_z:
                    best_z, best_day = dz, float(t[cut])
        split = self.cal[0] + float(self.cfg["defaults"]["transient_d"])

        def bias(x: np.ndarray) -> float | None:
            if x.size < 3:
                return None
            s_e = float(x.std(ddof=1)) / math.sqrt(x.size)
            return _f(float(x.mean()) / s_e) if s_e > 0 else None

        return {
            "n": n,
            "bias_z": _f(float(z.mean()) / se),
            "rmse_z": _f(math.sqrt(float(np.mean(z**2)))),
            "step_z": _f(best_z) if best_day is not None else None,
            "step_day": best_day,
            "early_bias_z": bias(z[t <= split]),
            "late_bias_z": bias(z[t > split]),
        }

    def t_residual(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Residual structure of one sensor against a stored prediction."""
        s = self.sensor(inp["sensor"])
        sim = self.stored(self.sims, inp["prediction"], "simulate")
        if s.channel not in sim.outputs:
            raise ActionError(f"{s.name} observes {s.channel}, which the model does not output")
        m = s.mask(self.cal) & np.isfinite(s.value)
        if m.sum() < 4:
            raise ActionError(f"{s.name} has fewer than 4 samples in the calibration window")
        t = s.t[m]
        pred = np.interp(
            t, np.asarray(sim.t, dtype=float), np.asarray(sim.outputs[s.channel], dtype=float)
        )
        r = s.value[m] - pred
        stats = self.standardised(t, r / s.sd[m])
        args: dict[str, Any] = {"t": t, "residual": r, "covariates": self.covariates()}
        if "n_bins" in inp:
            args["n_bins"] = inp["n_bins"]
        out, index = self.rec.call("residual_diag", "residual_diag", **args)
        structured = {c.name: _f(c.eta_squared) or 0.0 for c in out.covariates if c.structured}
        summary = {
            **stats,
            "serially_structured": bool(out.serially_structured),
            "lag1_autocorrelation": _f(out.lag1_autocorrelation) or 0.0,
            "trend_slope_per_d": _f(out.trend_slope_per_d) or 0.0,
            "most_explanatory": out.most_explanatory,
            "covariate_eta2": structured,
        }
        if summary["bias_z"] is not None and summary["rmse_z"] is not None:
            self.residuals[s.channel] = summary
        for key in ("bias_z", "rmse_z", "step_z", "step_day", "early_bias_z", "late_bias_z"):
            self.produce(index, key, stats[key], s.name)
        self.produce(index, "most_explanatory", out.most_explanatory, s.name)
        result = out.model_dump(mode="json")
        result["standardised"] = {**stats, "prediction_call_index": int(inp["prediction"])}
        return self._out(index, result)

    def t_assay(self, inp: dict[str, Any]) -> dict[str, Any]:
        """A requested assay (never on a hold-out day)."""
        day = float(inp["day"])
        if not self.cal[0] <= day < self.cal[1]:
            raise ActionError(f"an assay day must lie in the calibration window {list(self.cal)}")
        sim = None
        if inp.get("prediction") is not None:
            sim = self.stored(self.sims, inp["prediction"], "simulate")
        out, index = self.rec.call("request_assay", "request_assay", assay=inp["assay"], day=day)
        self.produce(index, "assay", out.assay)
        result = out.model_dump(mode="json")
        for res, row in zip(out.results, result["results"], strict=True):
            pred = z = None
            if sim is not None and res.channel in sim.outputs:
                pred = float(
                    np.interp(
                        day,
                        np.asarray(sim.t, dtype=float),
                        np.asarray(sim.outputs[res.channel], dtype=float),
                    )
                )
                z = (float(res.value) - pred) / float(res.sd) if float(res.sd) > 0 else None
            row["predicted"] = _f(pred)
            row["disagreement_z"] = _f(z)
            self.produce(index, "disagreement_z", _f(z))
            self.assay_checks.append(
                {
                    "assay": out.assay,
                    "channel": res.channel,
                    "sample_day": day,
                    "report_day": float(out.report_day),
                    "value": float(res.value),
                    "unit": res.unit,
                    "sd": float(res.sd),
                    "predicted": _f(pred),
                    "z": _f(z),
                }
            )
        return self._out(index, result)

    def t_voi(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Expected information gain of the assays, from a stored posterior."""
        post = self.stored(self.posteriors, inp["posterior"], "bayes_mcmc")
        day = float(inp["day"])
        if not self.cal[0] <= day < self.cal[1]:
            raise ActionError(f"an assay day must lie in the calibration window {list(self.cal)}")
        args: dict[str, Any] = {
            "model": MODEL,
            "samples": np.asarray(post.samples, dtype=float),
            "parameters": list(post.parameters),
            "day": day,
            "seed": self.seed(),
        }
        for key in ("assays", "n_outer", "n_inner"):
            if key in inp:
                args[key] = inp[key]
        out, index = self.rec.call("voi_assay", "voi_assay", **args)
        return self._out(index, out.model_dump(mode="json"))

    def validate_final(self) -> None:
        """Validate the concluded prediction once on the frozen hold-out (the review of #26, 1).

        Called by the harness after ``conclude`` is accepted, never by the model: the
        agent cannot choose among predictions by their hold-out score, as P0, which
        validates once at the end, cannot. The result goes into the state only.
        """
        final = self.final or {}
        indices = list(final.get("validate_calls") or [])
        if not indices:
            self.annotations.append("no final prediction named: no validation")
            return
        sims = [self.sims[i] for i in indices]
        observed = [
            s.recorded()
            for s in self.objective()
            if s.channel in sims[0].outputs and s.n_observed(self.holdout) >= 1
        ]
        if not observed:
            self.annotations.append("no objective sensor has a hold-out sample: no validation")
            return
        t_model = np.asarray(sims[0].t, dtype=float)
        if len(sims) >= 2:
            predicted = {
                o["output"]: np.stack(
                    [np.asarray(s.outputs[o["output"]], dtype=float) for s in sims]
                )
                for o in observed
            }
        else:
            predicted = {
                o["output"]: np.asarray(sims[0].outputs[o["output"]], dtype=float) for o in observed
            }
        try:
            out, index = self.rec.call(
                "validate",
                "validate",
                observed=observed,
                t=t_model,
                predicted=predicted,
                holdout={"start": self.holdout[0], "end": self.holdout[1]},
            )
        except tools.ToolError as exc:
            index = self.rec.actions[-1]["call_index"] if self.rec.actions else None
            self.rec.failure("validate", "validate", "error", str(exc), "no validation", index)
            return
        metrics, violations = {}, 0
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
            "ensemble_size": len(sims) if out.ensemble else 0,
            "metrics": metrics,
            "constraint_violations": violations,
            "calls": [index],
        }
        self.steps.append("validate")

    def t_status(self, inp: dict[str, Any]) -> dict[str, Any]:
        """The agent's judgement of one sensor."""
        s = self.sensor(inp["sensor"])
        status = inp["status"]
        in_obj = bool(inp["in_objective"])
        if status in ("flagged", "excluded") and in_obj:
            raise ActionError(f"a {status} sensor never enters the objective")
        if in_obj and s.channel not in self.outputs:
            raise ActionError(f"{s.name} observes nothing the model outputs")
        windows = [(float(a), float(b)) for a, b in inp.get("quarantine") or []]
        for start, end in windows:
            if end < start:
                raise ActionError(f"quarantine window [{start}, {end}] is reversed")
            if end > self.cal[1]:
                # the hold-out's record is what the forecast is scored against; it is not
                # the agent's to edit (found on the first live cell, 2026-09-25)
                raise ActionError(
                    f"quarantine window [{start}, {end}] reaches into the hold-out window "
                    f"(after {self.cal[1]:g} d), which is not yours to edit"
                )
        for start, end in windows:
            s.quarantine(start, end)
        s.status, s.in_objective = status, in_obj
        s.reason = str(inp["reason"])[:300]
        return {
            "sensor": s.name,
            "status": s.status,
            "in_objective": s.in_objective,
            "quarantined_windows": [list(w) for w in s.quarantined],
            "objective_now": [x.name for x in self.objective()],
        }

    def t_evidence(self, inp: dict[str, Any]) -> dict[str, Any]:
        """One evidence item, checked for form (the evaluator checks its sources)."""
        if inp["label"] not in self.labels:
            raise ActionError(f"label must be one of {self.labels}")
        values = dict(inp["values"])
        unknown = sorted(set(values) - set(self.evidence_keys) - {"sensor", "channel"})
        if unknown:
            raise ActionError(
                f"unknown value key(s) {unknown}; use the published evidence keys "
                "(and optionally `sensor` or `channel` to name what they concern)"
            )
        if not set(values) & set(self.evidence_keys):
            raise ActionError("an evidence item carries at least one published value key")
        calls = [int(i) for i in inp["calls"]]
        missing = [i for i in calls if self.rec.ok_index(i) is None]
        if missing:
            raise ActionError(f"call index(es) {missing} name no call of this run that returned")
        for key in ("sensor", "channel"):
            if key in values:
                known = set(self.series) if key == "sensor" else set(self.outputs)
                if values[key] not in known:
                    raise ActionError(f"{key} {values[key]!r} is not one of {sorted(known)}")
        tagged: set[str] | None = None
        if "sensor" in values:
            tagged = {str(values["sensor"])}
        if "channel" in values:
            by_channel = {n for n, x in self.series.items() if x.channel == values["channel"]}
            tagged = by_channel if tagged is None else tagged & by_channel
            if not tagged:
                raise ActionError(
                    f"the sensor and channel tags disagree, or no sensor observes "
                    f"{values['channel']!r}"
                )
        for key in sorted(set(values) & set(self.evidence_keys)):
            self.check_value(key, values[key], calls, tagged)
        item = {
            "rule": RULE,
            "label": inp["label"],
            "statement": str(inp["statement"])[:500],
            "values": {
                k: (_f(v) if isinstance(v, int | float) and not isinstance(v, bool) else v)
                for k, v in values.items()
            },
            "calls": calls,
        }
        self.evidence.append(item)
        return {"evidence_id": len(self.evidence) - 1, "n_evidence": len(self.evidence)}

    def check_value(
        self, key: str, value: Any, calls: list[int], sensors: set[str] | None = None
    ) -> None:
        """A cited value must be one the cited calls produced (§6.5: no fabricated values).

        Numbers match to the five significant digits the agent is shown; strings exactly.
        With a ``sensor`` (or ``channel``) tag on the item, a per-sensor value must be one
        the call produced *for that sensor* (the coordinator's re-review of PR #26, 3).

        Raises:
            ActionError: If no cited call produced that value under that key.
        """
        entries = [e for i in calls for e in self.produced.get(i, {}).get(key, [])]
        if sensors is not None:
            entries = [(v, who) for v, who in entries if who is None or who in sensors]
        produced = [v for v, _ in entries]
        if not produced:
            where = "" if sensors is None else f" for {sorted(sensors)}"
            raise ActionError(
                f"no cited call produced a `{key}`{where}; cite the call the number rests on"
            )
        numeric = [v for v in produced if not isinstance(v, str)]
        if numeric:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ActionError(f"`{key}` is a number; got {value!r:.40}")
            if not any(
                abs(float(value) - float(v)) <= 1e-3 * max(abs(float(v)), abs(float(value))) + 1e-9
                for v in numeric
            ):
                shown = sorted({_round(float(v)) for v in numeric})[:8]
                raise ActionError(
                    f"`{key}` = {value!r} is not what the cited calls produced ({shown})"
                )
            return
        if value not in produced:
            raise ActionError(f"`{key}` = {value!r:.40} is not what the cited calls produced")

    def fisher_interval(self, name: str, estimate: float, sd: Any) -> list[float] | None:
        """``estimate +/- z sd`` clipped to the bounds; None for a non-finite sd."""
        sd_f = _f(sd)
        if sd_f is None or name not in self.lower:
            return None
        z = float(self.cfg["uncertainty"]["z"])
        return [
            max(self.lower[name], estimate - z * sd_f),
            min(self.upper[name], estimate + z * sd_f),
        ]

    def _close(self, a: float, b: float) -> bool:
        tol = float(self.cfg["uncertainty"]["rel_tolerance"])
        return abs(a - b) <= tol * max(abs(a), abs(b)) + 1e-9

    def interval_sources(self, name: str, method: str) -> list[tuple[list[float], Any, Any]]:
        """Every (estimates, lower, upper) a successful call produced for ``name`` by ``method``.

        The coordinator's re-review of PR #26, item 1:

        - posterior: a converged sampler's mean or median, and its q05-q95;
        - profile: the grid point of least chi2, and the profile's closed interval;
        - fisher: a fit's optimum +/- z sd (its covariance is the Fisher information at
          the optimum, P0's intervals) or a Fisher call's point +/- z CRLB sd, clipped to
          the bounds, where that sd is finite;
        - fisher from a Fisher call: only at a point this run estimated (a fit optimum or
          a converged sampler's mean or median);
        - none: an estimate a call of this run estimated (a fit's optimum, a converged
          sampler's mean or median), with no interval; never a simulate input or the
          default.
        """
        out: list[tuple[list[float], Any, Any]] = []
        if method == "posterior":
            for post in self.posteriors.values():
                if post.converged and name in post.parameters:
                    i = list(post.parameters).index(name)
                    q = {k: list(v) for k, v in dict(post.quantiles).items()}
                    ests = [float(list(post.mean)[i])]
                    if "q50" in q:
                        ests.append(float(q["q50"][i]))
                    if "q05" in q and "q95" in q:
                        out.append((ests, float(q["q05"][i]), float(q["q95"][i])))
        elif method == "profile":
            for pr in self.profiles.values():
                lo, hi = pr.interval
                if pr.parameter == name and lo is not None and hi is not None:
                    chi2 = np.asarray(pr.chi2, dtype=float)
                    grid = np.asarray(pr.grid, dtype=float)
                    best = float(grid[int(np.nanargmin(chi2))]) if chi2.size else float(lo)
                    out.append(([best], float(lo), float(hi)))
        elif method == "fisher":
            for fit in self.fits.values():
                if fit.converged and fit.sd is not None and name in fit.parameters:
                    i = list(fit.parameters).index(name)
                    theta = float(list(fit.theta)[i])
                    iv = self.fisher_interval(name, theta, list(fit.sd)[i])
                    if iv is not None:
                        out.append(([theta], iv[0], iv[1]))
            optima = self.estimated_optima()
            for index, fisher in self.fishers.items():
                if name in fisher.parameters:
                    i = list(fisher.parameters).index(name)
                    at = self.fisher_at.get(index, {})
                    full = {p: float(at.get(p, 1.0)) for p in fisher.parameters}
                    point = full[name]
                    # a Fisher call's interval backs an estimate only when ALL its
                    # coordinates are an optimum this run estimated, never a point the
                    # agent chose (the re-reviews of e4fc44a, 2 and 1624e4d, 2)
                    if not any(
                        all(p in o and self._close(v, o[p]) for p, v in full.items())
                        for o in optima
                    ):
                        continue
                    iv = self.fisher_interval(name, point, list(fisher.crlb_sd)[i])
                    if iv is not None:
                        out.append(([point], iv[0], iv[1]))
        else:
            estimated = self.estimated_points(name)
            if estimated:
                out.append((estimated, None, None))
        return out

    def estimated_optima(self) -> list[dict[str, float]]:
        """Every whole point an estimator of this run returned, parameter -> value.

        A converged fit's optimum, and a converged sampler's mean and its median. A fit
        that did not converge returns its start, not an estimate (the re-review of
        1624e4d, 2); a simulate's input and the default are never estimates.
        """
        out: list[dict[str, float]] = []
        for fit in self.fits.values():
            if fit.converged:
                out.append({n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)})
        for post in self.posteriors.values():
            if post.converged:
                names = list(post.parameters)
                out.append({n: float(v) for n, v in zip(names, post.mean, strict=True)})
                q50 = dict(post.quantiles).get("q50")
                if q50 is not None:
                    out.append({n: float(v) for n, v in zip(names, q50, strict=True)})
        return out

    def estimated_points(self, name: str) -> list[float]:
        """The values an estimator of this run returned for ``name`` (see estimated_optima)."""
        return [o[name] for o in self.estimated_optima() if name in o]

    def interval_problem(self, name: str, e: float, lo: Any, hi: Any, method: str) -> str | None:
        """Why an estimate and its interval are not what a call of this run produced."""
        sources = self.interval_sources(name, method)
        if not sources:
            return (
                f"{name}: no successful call of this run produced a {method} interval for it "
                "(posterior: a converged sampler; profile: a closed profile; fisher: a fit "
                "or a Fisher call with a finite sd)"
            )
        for ests, s_lo, s_hi in sources:
            if not any(self._close(e, x) for x in ests):
                continue
            if s_lo is None and lo is None and hi is None:
                return None
            if (
                s_lo is not None
                and lo is not None
                and hi is not None
                and self._close(float(lo), s_lo)
                and self._close(float(hi), s_hi)
            ):
                return None
        shown = [
            [_round(x) for x in ests[:3]] + ([] if s_lo is None else [[_round(s_lo), _round(s_hi)]])
            for ests, s_lo, s_hi in sources[:4]
        ]
        return (
            f"{name}: estimate {e} with interval [{lo}, {hi}] is not what a {method} call of "
            f"this run produced (estimates and intervals produced: {shown})"
        )

    def conclude(self, inp: dict[str, Any]) -> dict[str, Any]:
        """Validate the final conclusion and hold it.

        Raises:
            ActionError: On any field the contract refuses; nothing is held then.
        """
        problems: list[str] = []
        label = inp["label"]
        if label not in self.labels:
            problems.append(f"label must be one of {self.labels}")
        secondary = list(inp.get("secondary_labels") or [])
        bad = [x for x in secondary if x not in self.labels or x == label]
        if bad:
            problems.append(f"secondary labels {bad} are unknown or repeat the label")
        if secondary and (label == self.lab["none"] or self.lab["none"] in secondary):
            problems.append("`none` never stands beside another label")
        conf = float(inp["confidence"])
        if not 0.0 <= conf <= 1.0:
            problems.append("confidence must lie in [0, 1]")
        flag = inp.get("flag_sensor")
        if flag is not None and flag not in self.series:
            problems.append(f"flag_sensor {flag!r} is not a sensor of this tier")
        scale = dict(inp.get("scale_factor") or {})
        if any(k not in self.series for k in scale):
            problems.append("scale_factor keys must be sensor names")
        abst = list(dict.fromkeys(inp.get("abstentions") or []))
        unknown = [a for a in abst if a not in self.vocabulary]
        if unknown:
            problems.append(f"abstention(s) {unknown} are not in the published vocabulary")
        params: dict[str, dict[str, Any]] = {}
        for name, est in dict(inp.get("parameters") or {}).items():
            if name not in self.params:
                problems.append(f"unknown parameter {name!r}")
                continue
            e, lo, hi = float(est["estimate"]), _f(est.get("lower")), _f(est.get("upper"))
            method = est["method"]
            if not self.lower[name] <= e <= self.upper[name]:
                problems.append(f"{name}: estimate outside the declared bounds")
            if (lo is None) != (hi is None) or (lo is not None and not lo <= e <= hi):
                problems.append(f"{name}: an interval is [lower, upper] around the estimate")
            problem = self.interval_problem(name, e, lo, hi, method)
            if problem is not None:
                problems.append(problem)
            if method != "none" and lo is None:
                problems.append(f"{name}: method {method} needs an interval")
            span = self.upper[name] - self.lower[name]
            params[name] = {
                "estimate": e,
                "lower": lo,
                "upper": hi,
                "method": method,
                "at_bound": bool(min(e - self.lower[name], self.upper[name] - e) <= 0.01 * span),
                "unit": self.units.get(name, ""),
            }
        interval = inp["interval_method"]
        if interval != "none" and not any(p["method"] == interval for p in params.values()):
            problems.append(f"interval_method {interval}: no estimate carries that method")
        indices = list(inp.get("ensemble") or [])
        if not indices and inp.get("prediction") is not None:
            indices = [inp["prediction"]]
        bad_sims = [i for i in indices if i not in self.sims]
        if bad_sims:
            problems.append(f"prediction/ensemble {bad_sims} name no simulate call of this run")
        if problems:
            raise ActionError("; ".join(problems))
        approved = [n for n in (inp.get("approved_parameters") or list(params)) if n in self.params]
        self.screening["approved"] = approved
        self.final = {
            "classification": {
                "label": label,
                "secondary_labels": secondary,
                "confidence": conf,
                "rule": RULE,
                "flag_sensor": flag,
                "scale_factor": {k: float(v) for k, v in scale.items()},
                "revise_influent_mapping": bool(inp.get("revise_influent_mapping", False)),
                "recommend_structural_review": bool(inp.get("recommend_structural_review", False)),
                "kinetic_update": bool(inp["kinetic_update"]),
            },
            "parameters": params,
            "interval_method": interval,
            "abstentions": abst,
            "validate_calls": indices,
        }
        if inp.get("summary"):
            self.annotations.append(f"agent summary: {str(inp['summary'])[:800]}")
        return {"concluded": True}

    # -- the state -----------------------------------------------------------------------
    def build_state(self, loop: dict[str, Any], completed: bool) -> dict[str, Any]:
        """The task state as JSON (``state.task_state.TaskState``)."""
        rem = tools.remaining()
        final = self.final
        if final is not None:
            cls = {**final["classification"], "evidence": list(self.evidence)}
        else:
            cls = {
                "label": self.lab["none"],
                "secondary_labels": [],
                "confidence": 0.0,
                "rule": "unconcluded",
                "evidence": list(self.evidence),
                "flag_sensor": None,
                "scale_factor": {},
                "revise_influent_mapping": False,
                "recommend_structural_review": False,
                "kinetic_update": False,
            }
        abst = list(final["abstentions"]) if final else []
        dq = {
            name: {
                "status": s.status,
                "flags": list(s.flags),
                "missing_fraction": _f(s.missing_fraction()),
                "quarantined_windows": [list(w) for w in s.quarantined],
                "in_objective": bool(s.in_objective),
                "notes": s.reason,
            }
            for name, s in self.series.items()
        }
        screening = {**self.screening}
        screening.setdefault("approved", [])
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
            "model_parameters": list(self.params),
            "calibrated_outputs": [s.channel for s in self.objective()],
            "data_quality": dq,
            "mass_balance": dict(self.balance),
            "classification": cls,
            "screening": screening,
            "residuals": dict(self.residuals),
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
            "assay_checks": list(self.assay_checks),
            "abstentions": abst,
            "final": {
                "label": cls["label"],
                "secondary_labels": cls["secondary_labels"],
                "confidence": cls["confidence"],
                "parameters": dict(final["parameters"]) if final else {},
                "interval_method": final["interval_method"] if final else "none",
                "abstentions": abst,
                "completed": bool(completed),
            },
            "plan": {
                "sizes": {
                    "model_turns": int(loop["turns"]),
                    "tool_uses": int(loop["tool_uses"]),
                    "refused_actions": int(loop["refused"]),
                },
                "fallbacks": [],
                "guards_tripped": list(loop["guards"]),
                "eval_seconds_assumed": None,
                "steps_completed": list(self.steps),
                "steps_skipped": {},
            },
            "notes_seen": [
                {
                    "day": int(n.get("day", 0)),
                    "author": str(n.get("author", "")),
                    "length": len(str(n.get("text", ""))),
                }
                for n in self.notes
            ],
            "annotations": list(self.annotations),
        }


# ------------------------------------------------------------------ the loop


def _assistant_blocks(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The response's blocks as request input: the fields the API reads, values unchanged."""
    keep = {
        "text": ("type", "text"),
        "tool_use": ("type", "id", "name", "input"),
        "thinking": ("type", "thinking", "signature"),
        "redacted_thinking": ("type", "data"),
    }
    out = []
    for block in content:
        fields = keep.get(str(block.get("type")))
        if fields is None:
            continue
        out.append({k: block[k] for k in fields if k in block and block[k] is not None})
    return out


class Agent:
    """The model loop over the workspace."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Read the run and build the prompts."""
        self.cfg = cfg
        self.loop_cfg = cfg["loop"]
        self.ws = Workspace(cfg)
        self.specs = tool_specs()
        self.system = cfg["prompts"]["system"]
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": self.task_text()}]
        self.state = {"turns": 0, "tool_uses": 0, "refused": 0, "guards": []}
        self.grace: int | None = None
        self.stop_reason = ""

    def task_text(self) -> str:
        """The task prompt, filled from the visible record."""
        ws = self.ws
        geometry = self.cfg["plant_geometry"][str(ws.manifest["plant"])]
        budget = ws.budget()
        fields = {
            "plant": ws.manifest["plant"],
            "tier": ws.manifest["tier"],
            "duration_days": f"{ws.T:g}",
            "volume_m3": f"{float(geometry['V_liq_m3']):g}",
            "t_op_k": f"{float(geometry['T_op_K']):g}",
            "calibration_window": f"[{ws.cal[0]:g}, {ws.cal[1]:g}]",
            "holdout_window": f"[{ws.holdout[0]:g}, {ws.holdout[1]:g}]",
            "sensors": ws.sensors_text(),
            "feeds": ws.feeds_text(),
            "feed_assays": ws.assays_text(),
            "notes": ws.notes_text(),
            "model": ws.model_text(),
            "budget": (
                f"{budget['simulator_evals_left']} simulator evaluations, "
                f"wall-clock minutes (wall_clock_min_left={budget['wall_clock_min_left']}), "
                f"{budget['assay_units_left']} assay units."
            ),
            "max_turns": self.loop_cfg["max_turns"],
            "max_tool_calls": self.loop_cfg["max_tool_calls"],
            "labels": ", ".join(f"`{x}`" for x in ws.labels),
            "abstentions": "\n".join(f"- `{k}`: {v}" for k, v in sorted(ws.vocabulary.items())),
            "evidence_keys": "\n".join(
                f"- `{k}`: {', '.join(v)}" for k, v in sorted(ws.evidence_keys.items())
            ),
        }
        return string.Template(self.cfg["prompts"]["task"]).substitute(fields)

    def write(self, completed: bool) -> None:
        """Write the state and the report through the registry."""
        state = self.ws.build_state(self.state, completed)
        tools.run.write_output(STATE_FILE, json.dumps(state, indent=1, sort_keys=True))
        report = {
            "workflow": state["workflow"],
            "label": state["final"]["label"],
            "secondary_labels": state["final"]["secondary_labels"],
            "confidence": state["final"]["confidence"],
            "completed": completed,
            "stop": self.stop_reason,
            "abstentions": state["final"]["abstentions"],
            "parameters": state["final"]["parameters"],
            "validation": state["validation"],
            "annotations": state["annotations"],
            "tool_failures": state["tool_failures"],
        }
        tools.run.write_output(REPORT_FILE, json.dumps(report, indent=1))

    def notices(self) -> list[str]:
        """What the harness tells the model about its limits this turn."""
        out = []
        lc = self.loop_cfg
        rem = tools.remaining()
        left_uses = int(lc["max_tool_calls"]) - self.state["tool_uses"]
        left_turns = int(lc["max_turns"]) - self.state["turns"]
        urgent = (
            float(rem.wall_clock_min) < float(lc["wall_clock_reserve_min"])
            or left_uses <= 3
            or left_turns <= int(lc["conclude_grace_turns"]) + 1
        )
        if urgent:
            if self.grace is None:
                self.grace = int(lc["conclude_grace_turns"])
                self.state["guards"].append(
                    f"conclude notice at turn {self.state['turns']}: "
                    f"{float(rem.wall_clock_min):.1f} min, {left_uses} tool uses, "
                    f"{left_turns} turns left"
                )
            out.append(
                "HARNESS: limits nearly reached (wall-clock minutes left: "
                f"wall_clock_min_left={float(rem.wall_clock_min):.1f}; {left_uses} tool uses, "
                f"{left_turns} turns left). Call `conclude` now; the run stops unconcluded "
                f"after {self.grace} more turn(s)."
            )
        return out

    def execute(self, block: dict[str, Any]) -> dict[str, Any]:
        """One tool use -> its tool_result block."""
        name = str(block.get("name"))
        inp = block.get("input") or {}
        self.state["tool_uses"] += 1
        spec = next((s for s in self.specs if s["name"] == name), None)
        try:
            if spec is None:
                raise ActionError(f"no tool {name!r}")
            if (
                self.state["tool_uses"] > int(self.loop_cfg["max_tool_calls"])
                and name != "conclude"
            ):
                raise ActionError("the tool-use cap is reached; only `conclude` is accepted")
            check(inp, spec["input_schema"], name)
            if name == "conclude":
                payload: dict[str, Any] = self.ws.conclude(inp)
            elif name in ("fit_lsq", "fit_de", "fit_cmaes"):
                payload = self.ws.fit(name, inp)
            else:
                payload = self.ws.run_tool(name, inp)
            self.ws.steps.append(name)
            return self._result(block, payload, False)
        except ActionError as exc:
            return self.refuse(block, str(exc))
        except tools.BudgetExceededError as exc:
            index = self.ws.rec.actions[-1]["call_index"] if self.ws.rec.actions else None
            self.ws.rec.failure(name, name, "budget_exceeded", str(exc), "nothing ran", index)
            return self._result(
                block, {"error": f"budget refusal: {exc}", "budget": self.ws.budget()}, True
            )
        except tools.ToolError as exc:
            index = self.ws.rec.actions[-1]["call_index"] if self.ws.rec.actions else None
            self.ws.rec.failure(name, name, "error", str(exc), "reported to the agent", index)
            return self._result(block, {"error": f"tool error: {exc}"}, True)

    def refuse(self, block: dict[str, Any], reason: str) -> dict[str, Any]:
        """Refuse one tool use: recorded under ``tool_failures``, returned as an error."""
        name = str(block.get("name"))
        self.state["refused"] += 1
        self.ws.rec.failure(name, f"p1.{name}", "error", reason, "refused by the harness", None)
        return self._result(block, {"error": f"refused: {reason}"}, True)

    @staticmethod
    def _result(block: dict[str, Any], payload: dict[str, Any], error: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.get("id"),
            "content": json.dumps(payload, sort_keys=True, default=str),
        }
        if error:
            out["is_error"] = True
        return out

    def run(self) -> int:
        """The loop: ask, execute, answer, until ``conclude`` or a limit."""
        self.write(completed=False)
        while True:
            if self.grace is not None and self.grace < 0:
                self.stop_reason = "stopped: limits reached without a conclusion"
                break
            try:
                reply = tools.llm(
                    {"system": self.system, "messages": self.messages, "tools": self.specs}
                )
            except tools.BudgetExceededError as exc:
                self.stop_reason = f"model budget: {exc}"
                break
            except tools.ToolError as exc:
                self.stop_reason = f"model error: {exc}"
                break
            self.state["turns"] += 1
            response = reply["response"]
            content = list(response.get("content") or [])
            self.messages.append({"role": "assistant", "content": _assistant_blocks(content)})
            if response.get("stop_reason") == "refusal":
                self.stop_reason = "the model refused"
                break
            uses = [b for b in content if b.get("type") == "tool_use"]
            if self.grace is not None:
                self.grace -= 1
            if not uses:
                text = "HARNESS: continue by calling a tool; the run ends only with `conclude`."
                self.messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}, *self._notice_blocks()],
                    }
                )
                if self.grace is None:
                    self.grace = int(self.loop_cfg["conclude_grace_turns"])
                    self.state["guards"].append(f"no tool use at turn {self.state['turns']}")
                self.write(completed=False)
                continue
            results = []
            for b in uses:
                if self.ws.final is not None:
                    # the conclusion ends the run: a later tool use of the same turn is refused
                    results.append(self.refuse(b, "the run is concluded; nothing runs after it"))
                else:
                    results.append(self.execute(b))
            if self.ws.final is not None:
                self.stop_reason = "concluded"
                self.ws.validate_final()
                self.write(completed=True)
                return 0
            self.messages.append({"role": "user", "content": [*results, *self._notice_blocks()]})
            self.write(completed=False)
        self.ws.annotations.append(f"run ended: {self.stop_reason}")
        self.write(completed=False)
        return 0

    def _notice_blocks(self) -> list[dict[str, Any]]:
        return [{"type": "text", "text": n} for n in self.notices()]


def main() -> int:
    """Read the configuration, run the agent, write the state."""
    with open(CONFIG_FILE, encoding="utf-8") as fh:
        cfg = json.load(fh)
    return Agent(cfg).run()


if __name__ == "__main__":
    raise SystemExit(main())
