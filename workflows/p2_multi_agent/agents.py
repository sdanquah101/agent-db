"""The agent P2's harness (``docs/p2_agents_design.md`` §3 to §5): the roles on P1's loop.

Package code, staged into the jail beside the entry (the lead's option A, 2026-10-26); the
entry ``workflow.py`` dispatches here when its configuration carries an ``agents`` block
(``configs/workflows/p2_agents.yaml``).

**Copied from P1** (``workflows/p1_single_agent/agent.py`` at ``main`` ``8f78881``, the
revision frozen on 2026-09-30, revision 2): the jail stages only this package, so P1 cannot
be imported. What is copied, with the changes named: ``compact``, ``check``,
``estimate_evaluations``, the tool specifications of the registry tools (the same
descriptions and schemas, so the roles see the tools as P1 did), the handlers of those
tools (over the procedural arm's series objects, with the values each call produces kept
with their registry units), the cited-value check, and the loop (``RoleAgent.run``: ask,
execute, answer; no duration guard, since P2 has no wall clock; a grant of evaluations and
assays instead of P1's whole budget; the role's turn budget; the role ends with its one
typed finding instead of ``conclude``).

**What is the agent arm's own.** The procedural arm's code steps run first (QC, the
reference fit, the null table, the signatures: ``docs/p2_agents_design.md`` §2, "kept as
code"), with every decision point at its offline fallback, and are the shared evidence
every role is shown. Then:

* each role's view admits the §3.1 allow-list and nothing else (a call outside it is
  refused in the view and recorded); ``set_sensor_status`` never returns a QC-flagged
  sensor to ``ok`` or the objective (no QC bypass, §5);
* the **projected action log** (§4, step 2): every logged call's index, tool, version,
  typed arguments with every free-text field redacted, outcome, and a compact output cut
  to the configured points; ``stored`` fetches a full output by call index;
* a role ends with one **typed finding** (``messages.py``), checked by code: a claim
  allowed in the round, every evidence item citing calls that returned, every value one a
  cited call produced, with the unit the registry gave it (rule 6; §5 "no fabricated
  values");
* the **coordinator is code** (§3.3, Q7): QC first; then the specialists whose null case
  failed, or all of them when the null stands; the design role when two findings
  conflict; then the verifier. It is the only writer of routing entries;
* **code concludes** (§4, step 6): the verifier's verdict is final; a ``pass`` concludes
  the leading admitted claim, a last-round ``fail`` concludes ``none`` for the alternative
  ``none`` and abstains otherwise, an ``abstain`` abstains. With the verifier off (an
  ablation) the leading admitted claim concludes, ``none`` on a standing null, else
  abstain. The admission is the evidence module's amended rule (``admit_agent``).

No model free text reaches ``state.json`` (§3.3): statements are templated by code, a
sensor's note is templated from its typed status, annotations are code-written; a role's
assessment (its last text) goes to ``messages.jsonl`` only.

Offline (``decider: offline``, the default) the roles are driven by :class:`OfflineModel`,
a scripted responder in this package: one tool use and one typed ``none``/``no_claim``
finding per role, so the arm runs end to end with no model and its floor is a record.
Live, each turn goes through ``tools.llm`` to the privileged gateway, which checks the
role's frozen prompt and tools and the caps.

Rule 1: nothing here reads the truth store; the hold-out is the verifier's only, through
``validate``. Rule 4: every stochastic call is seeded with P0's base plus its call index.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
from pydantic import TypeAdapter, ValidationError

import tools
from workflows.p2_multi_agent import evidence, messages
from workflows.p2_multi_agent import workflow as procedural

MODEL = procedural.MODEL
STATE_FILE = procedural.STATE_FILE
REPORT_FILE = procedural.REPORT_FILE
MESSAGES_FILE = procedural.MESSAGES_FILE
DECISIONS_FILE = procedural.DECISIONS_FILE
ABSTAIN_LABEL = procedural.ABSTAIN_LABEL
RULE = "agents"
"""The rule name the agent arm's classification carries."""

SPECIALISTS: tuple[str, ...] = (
    "data_quality",
    "influent",
    "identifiability",
    "calibration",
    "design",
)
VERIFIER = "verification"
COORDINATOR = "coordination"
ROLES: tuple[str, ...] = (*SPECIALISTS, VERIFIER)
HARNESS_ACTIONS: tuple[str, ...] = ("stored", "emit_finding")
"""The two actions every role holds beside its registry tools (§3.1)."""

REDACTED: dict[str, frozenset[str]] = {
    "set_sensor_status": frozenset({"reason"}),
    "fit_lsq": frozenset({"bounds_justification"}),
    "fit_de": frozenset({"bounds_justification"}),
    "fit_cmaes": frozenset({"bounds_justification"}),
    "bayes_mcmc": frozenset({"bounds_justification"}),
}
"""The free-text arguments the projection always redacts (§4, step 2); any other string
that is not a token is redacted as well."""
REDACTED_MARK = "<redacted>"

CLAIMS_FOR_LABEL: dict[str, tuple[str, ...]] = {
    "sensor": ("data_quality",),
    "influent": ("influent",),
    "initial_state": ("calibration",),
    "parameter": ("calibration",),
    "structural": ("calibration",),
}
"""Which role may claim each label (§3.2)."""

_TOKEN = TypeAdapter(messages.Token)
_NAME = TypeAdapter(messages.Name)


class ActionError(Exception):
    """The harness refused an action (reported to the model, never a crash)."""


# ------------------------------------------------------------------ copied from P1


def _f(x: Any) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _nan(values: list[Any]) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def _round(x: float) -> float | None:
    v = _f(x)
    return None if v is None else float(f"{v:.5g}")


def compact(value: Any, preview: int) -> Any:
    """A tool output made readable: long arrays summarised, floats to five digits (P1's)."""
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
    """Validate a tool input against the JSON-schema subset the tool specs use (P1's).

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


def _ceiling(value: Any, limit: int, name: str) -> int:
    if value is None:
        return int(limit)
    if int(value) > int(limit):
        raise ActionError(f"{name} = {value} exceeds the registry's ceiling of {limit}")
    return int(value)


def estimate_evaluations(name: str, inp: dict[str, Any], ceilings: dict[str, Any]) -> int:
    """The registry's evaluation bound for a sized call, as its cost functions compute it (P1's)."""
    c = ceilings.get(name, {})
    k = len(inp.get("parameters") or [])
    if name == "gsa_morris":
        return _ceiling(inp.get("n_trajectories"), c["n_trajectories"], "n_trajectories") * (k + 1)
    if name == "gsa_sobol":
        n = _ceiling(inp.get("n_samples"), c["n_samples"], "n_samples")
        return n * (2 * k + 2) if inp.get("second_order", True) else n * (k + 2)
    if name == "fisher_info":
        return 2 * k + 1
    if name == "profile_likelihood":
        grid = _ceiling(inp.get("n_grid"), c["n_grid"], "n_grid")
        starts = _ceiling(inp.get("n_starts"), c["n_starts"], "n_starts")
        return grid * starts * int(c["max_nfev_per_start"])
    if name == "fit_lsq":
        return _ceiling(inp.get("n_starts"), c["n_starts"], "n_starts") * _ceiling(
            inp.get("max_nfev_per_start"), c["max_nfev_per_start"], "max_nfev_per_start"
        )
    if name == "fit_de":
        pop = _ceiling(inp.get("popsize"), c["popsize"], "popsize")
        gens = _ceiling(inp.get("max_generations"), c["max_generations"], "max_generations")
        return pop * max(k, 1) * (gens + 1)
    if name == "fit_cmaes":
        return _ceiling(inp.get("max_evaluations"), c["max_evaluations"], "max_evaluations")
    if name == "bayes_mcmc":
        walkers = _ceiling(inp.get("n_walkers"), c["n_walkers"], "n_walkers")
        steps = _ceiling(inp.get("n_steps"), c["n_steps"], "n_steps")
        return walkers * (steps + 1)
    if name == "voi_assay":
        return _ceiling(inp.get("n_outer"), c["n_outer"], "n_outer")
    return 1 if name == "simulate" else 0


def _dump(out: Any) -> Any:
    """A tool output as JSON values (a registry model; a test double offers the same method)."""
    return out.model_dump(mode="json")


def _claim_of(finding: Any) -> str | None:
    """A finding's claim, for the messages that carry one."""
    if isinstance(finding, messages.SensorFinding | messages.InfluentFinding | messages.CalFinding):
        return str(finding.claim)
    return None


# ------------------------------------------------------------------ the record


class Recorder:
    """Every tool call, by role, with the outputs and the values each call produced.

    ``produced[index][key]`` holds ``(value, unit, sensor)`` triples: what an evidence
    item may cite under ``key`` from that call, with the unit the registry gave the value
    (rule 6) and the sensor it concerns (``None`` for a value no single sensor owns).
    """

    def __init__(self) -> None:
        """Start empty."""
        self.actions: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.refusals: list[dict[str, str]] = []
        self.by_role: dict[str, dict[str, float]] = {}
        self.outputs: dict[int, Any] = {}
        self.produced: dict[int, dict[str, list[tuple[Any, str, str | None]]]] = {}
        self.evals_charged = 0

    @staticmethod
    def next_index() -> int:
        """The registry's call count: the index the next call will carry."""
        return int(tools.remaining().n_calls)

    def call(self, role: str, step: str, name: str, **args: Any) -> tuple[Any, int]:
        """Call a tool, record it under the role, and re-raise its error after recording."""
        before = tools.remaining()
        index = int(before.n_calls)
        record: dict[str, Any] = {
            "step": f"{role}.{step}",
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
            record["outcome"], record["detail"] = "budget_exceeded", str(exc)[:300]
            raise
        except tools.ToolError as exc:
            record["outcome"], record["detail"] = "error", str(exc)[:300]
            raise
        finally:
            logged = tools.last_call() or {}
            record["version"] = str(logged.get("version", ""))
            record["args_hash"] = str(logged.get("args_hash", ""))
            record["seq"] = logged.get("seq")
            self.actions.append(record)
            after = tools.remaining()
            use = self.by_role.setdefault(
                role, {"evaluations": 0, "wall_clock_s": 0.0, "assay_units": 0, "calls": 0}
            )
            spent = int(before.simulator_evals) - int(after.simulator_evals)
            use["evaluations"] += spent
            use["wall_clock_s"] += 60.0 * (
                float(before.wall_clock_min) - float(after.wall_clock_min)
            )
            use["assay_units"] += int(before.assay_units) - int(after.assay_units)
            use["calls"] += 1
            self.evals_charged += spent
        return out, index

    def failure(
        self,
        role: str,
        step: str,
        name: str,
        kind: str,
        message: str,
        fallback: str,
        index: int | None,
    ) -> None:
        """Record a tool that did not deliver, or an action the harness refused."""
        self.failures.append(
            {
                "step": f"{role}.{step}",
                "name": name,
                "call_index": index,
                "kind": kind,
                "message": message[:300],
                "fallback": fallback,
            }
        )

    def ok_index(self, index: int) -> dict[str, Any] | None:
        """The action record of a call that returned, by call index; None otherwise."""
        for a in self.actions:
            if a["call_index"] == index and a["outcome"] == "ok":
                return a
        return None

    def produce(
        self, index: int, key: str, value: Any, unit: str, sensor: str | None = None
    ) -> None:
        """Record a value a call produced under ``key``, with its unit and its sensor."""
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        self.produced.setdefault(index, {}).setdefault(key, []).append((value, unit, sensor))


class RoleView:
    """One role's view of the registry: its allow-list (§3.1), then the registry."""

    def __init__(self, role: str, allowed: list[str], rec: Recorder) -> None:
        """Set up."""
        self.role = role
        self.allowed = frozenset(allowed)
        self.rec = rec

    def call(self, step: str, name: str, **args: Any) -> tuple[Any, int]:
        """Call ``name`` if the role holds it; refuse and record otherwise.

        Raises:
            ActionError: The tool is not on the role's list (nothing was called).
        """
        if name not in self.allowed:
            self.rec.refusals.append({"role": self.role, "step": step, "name": name})
            self.rec.failure(
                self.role,
                step,
                f"p2.{self.role}.refused",
                "error",
                f"{name} is not on the {self.role} role's list",
                "not called",
                None,
            )
            raise ActionError(f"{name} is not on the {self.role} role's list")
        return self.rec.call(self.role, step, name, **args)


# ------------------------------------------------------------------ the projection


def is_token(value: Any) -> bool:
    """Whether a string is a token (an identifier or a number as text), never prose."""
    try:
        _TOKEN.validate_python(value)
    except ValidationError:
        return False
    return isinstance(value, str)


def redact(name: str, args: Any) -> Any:
    """The typed arguments of a call with every free-text field redacted (§4, step 2).

    The declared free-text fields of ``name`` (:data:`REDACTED`) are always redacted; any
    other string that is not a token is redacted too, at any depth. Numbers, booleans,
    tokens and identifiers pass.
    """
    declared = REDACTED.get(name, frozenset())

    def walk(x: Any, key: str | None) -> Any:
        if key is not None and key in declared:
            return REDACTED_MARK
        if isinstance(x, str):
            return x if is_token(x) else REDACTED_MARK
        if isinstance(x, dict):
            return {str(k): walk(v, str(k)) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [walk(v, None) for v in x]
        return x

    return walk(args, None)


def cut_points(value: Any, max_points: int) -> Any:
    """An output with every flat numeric array cut to at most ``max_points`` points."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, dict):
        return {str(k): cut_points(v, max_points) for k, v in value.items()}
    if isinstance(value, list | tuple):
        flat = all(isinstance(v, int | float) or v is None for v in value)
        if flat and len(value) > max_points:
            stride = max(1, math.ceil(len(value) / max_points))
            return [compact(v, max_points) for v in list(value)[::stride]]
        return [cut_points(v, max_points) for v in value]
    return value


def project(
    rec: Recorder, args_by_index: dict[int, dict[str, Any]], max_points: int, preview: int
) -> list[dict[str, Any]]:
    """The projected action log: what the verifier (and every role) is shown of the calls."""
    out = []
    for a in rec.actions:
        index = int(a["call_index"])
        entry = {
            "call_index": index,
            "role": a["step"].split(".", 1)[0],
            "tool": a["name"],
            "version": a["version"],
            "args": redact(a["name"], args_by_index.get(index, {})),
            "outcome": a["outcome"],
        }
        if index in rec.outputs:
            entry["output"] = compact(cut_points(rec.outputs[index], max_points), preview)
        out.append(entry)
    return out


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
_STATUSES = ("ok", "quarantined", "excluded", "flagged")


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


_PARAMS = _d(_STRS, "Calibratable parameter names")
_SENSORS = _d(_STRS, "Sensor names whose calibration data to use (default: the objective)")


def registry_tool_specs() -> dict[str, dict[str, Any]]:
    """The registry tools as P1 specifies them, by name (the same text, the same schemas)."""
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
            "Rule-based quality checks per sensor over the calibration window: unit and "
            "timestamp checks, flatlines, spikes, drift, and missingness during high-load "
            "event windows. No evaluation.",
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
            "COD and N closure over consecutive windows of the calibration window, and the "
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
            "input). A flagged or excluded sensor never enters the objective, and a sensor "
            "the quality checks flagged is never set ok.",
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
            "declared_background",
            "The plant's declared background at this tier: the published envelope of the "
            "reference calibration's statistics on clean records, with its procedure. No "
            "evaluation.",
            {},
            (),
        ),
        (
            "validate",
            "The one test of a stored prediction on the frozen hold-out window: metrics "
            "per objective channel. The verifier's tool only; the result's call index is "
            "what a verdict's holdout field cites.",
            {"prediction": _d(_INT, "Call index of a simulate")},
            ("prediction",),
        ),
    ]
    return {
        name: {"name": name, "description": desc, "input_schema": _obj(desc, props, req)}
        for name, desc, props, req in specs
    }


def role_tool_specs(role: str, allowed: list[str]) -> list[dict[str, Any]]:
    """The tools a role is offered: its registry tools, ``stored`` and its ``emit_finding``.

    ``emit_finding``'s schema is the role's typed message (``messages.FINDINGS``), so the
    model is shown exactly the fields code will check.
    """
    registry = registry_tool_specs()
    unknown = sorted(set(allowed) - set(registry))
    if unknown:
        raise ValueError(f"{role}: no specification for {unknown}")
    specs = [registry[name] for name in registry if name in allowed]
    specs.append(
        {
            "name": "stored",
            "description": "Fetch the full stored output of an earlier call by call index.",
            "input_schema": _obj("stored", {"call_index": _INT}, ("call_index",)),
        }
    )
    model = messages.FINDINGS[role]
    schema = model.model_json_schema()
    specs.append(
        {
            "name": "emit_finding",
            "description": (
                f"Your one typed finding ({model.__name__}); it ends your turns. Every "
                "evidence item cites call indices of this run and carries numbers those "
                "calls returned, with their unit symbols."
            ),
            "input_schema": {
                "type": "object",
                "description": f"{model.__name__}",
                "properties": {"finding": schema},
                "required": ["finding"],
                "additionalProperties": False,
            },
        }
    )
    return specs


# ------------------------------------------------------------------ the workspace


def _mask(s: Any, window: tuple[float, float]) -> np.ndarray:
    """Samples of a procedural series inside ``[start, end)`` (the hold-out's first instant out)."""
    return (s.t >= window[0]) & (s.t < window[1])


class Workspace:
    """The run as the roles work on it, over the procedural arm's state.

    Holds the procedural ``Workflow`` (its series, model interface, reference fit, null
    table and signatures), the stored results of the roles' calls, and the handlers of
    the tools the roles may call. Every handler returns what the model reads: a compact
    result, the call index, and the budget left.
    """

    def __init__(self, base: Any, cfg: dict[str, Any], rec: Recorder) -> None:
        """Set up over the procedural state."""
        self.base = base
        self.cfg = cfg
        self.rec = rec
        self.agents_cfg = cfg["agents"]
        self.preview = int(self.agents_cfg["projection"]["preview"])
        self.max_points = int(self.agents_cfg["projection"]["max_points"])
        self.lab: dict[str, str] = dict(base.lab)
        self.labels = sorted(set(self.lab.values()))
        self.series = base.series
        self.cal, self.holdout = base.cal, base.holdout
        self.manifest = base.manifest
        self.params: list[str] = list(base.model.get("parameters", []))
        self.lower: dict[str, float] = dict(base.model.get("lower", {}))
        self.upper: dict[str, float] = dict(base.model.get("upper", {}))
        self.units: dict[str, str] = dict(base.model.get("units", {}))
        self.outputs: list[str] = sorted(
            set(base.baseline.outputs) if base.baseline is not None else set()
        )
        self.feed_log = base.feed_log
        self.feed_assays = tools.run.feed_assays()
        self.notes = tools.run.operator_notes()
        self.sims: dict[int, Any] = {}
        self.sim_params: dict[int, dict[str, float]] = {}
        self.fits: dict[int, Any] = {}
        self.fit_bounds: dict[int, dict[str, tuple[float, float]]] = {}
        self.posteriors: dict[int, Any] = {}
        self.fishers: dict[int, Any] = {}
        self.profiles: dict[int, Any] = {}
        self.args_by_index: dict[int, dict[str, Any]] = {}
        self.validation: dict[str, Any] | None = None
        self.assay_checks: list[dict[str, Any]] = []
        self.bounds_narrowed: dict[str, tuple[float, float]] = {}
        self.sensor_reason_lengths: dict[str, int] = {}
        if base.baseline is not None and base.baseline_index is not None:
            self.sims[int(base.baseline_index)] = base.baseline
            self.sim_params[int(base.baseline_index)] = {}
        if base.reference_prediction is not None and base.prediction_index is not None:
            self.sims[int(base.prediction_index)] = base.reference_prediction
            self.sim_params[int(base.prediction_index)] = dict(base.reference_optimum)

    # -- data ----------------------------------------------------------------------------
    def sensor(self, name: Any) -> Any:
        """A sensor by name.

        Raises:
            ActionError: If the tier carries no such sensor.
        """
        if not isinstance(name, str) or name not in self.series:
            raise ActionError(f"no sensor {name!r} at this tier; sensors: {sorted(self.series)}")
        return self.series[name]

    def objective(self) -> list[Any]:
        """The sensors currently in the calibration objective."""
        return [s for s in self.series.values() if s.in_objective]

    def n_observed(self, s: Any, window: tuple[float, float]) -> int:
        """Samples with a value inside ``window``."""
        return int(np.sum(np.isfinite(s.value) & _mask(s, window)))

    def observed(self, s: Any, window: tuple[float, float]) -> dict[str, Any]:
        """An ``ObservedSeries`` payload on ``[start, end)``, quarantines applied."""
        keep = _mask(s, window)
        return {
            "output": s.channel,
            "t": s.t[keep],
            "value": s.value[keep],
            "sd": s.sd[keep],
            "unit": s.unit,
        }

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
        out = [self.observed(s, self.cal) for s in chosen if self.n_observed(s, self.cal) >= 2]
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
        """Rule 4: P0's declared base plus the call index the next call will carry."""
        return int(self.cfg["p0"]["seeds"]["base"]) + Recorder.next_index()

    def stored_result(self, table: dict[int, Any], index: Any, what: str) -> Any:
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
            "assay_units_left": int(rem.assay_units),
        }

    def unit_of_sensor(self, name: str) -> str:
        """The registry's unit of a sensor's observed quantity."""
        return str(self.series[name].unit)

    # -- the handlers --------------------------------------------------------------------
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
            "fit_lsq": self.t_fit,
            "fit_de": self.t_fit,
            "fit_cmaes": self.t_fit,
            "bayes_mcmc": self.t_mcmc,
            "residual_diag": self.t_residual,
            "request_assay": self.t_assay,
            "voi_assay": self.t_voi,
            "set_sensor_status": self.t_status,
            "declared_background": self.t_background,
            "validate": self.t_validate,
        }

    def _out(self, index: int | None, result: Any) -> dict[str, Any]:
        if index is not None:
            self.rec.outputs[index] = result
        out: dict[str, Any] = {}
        if index is not None:
            out["call_index"] = index
        out["result"] = compact(result, self.preview)
        out["budget"] = self.budget()
        return out

    def _call(self, view: RoleView, name: str, inp: dict[str, Any], **args: Any) -> tuple[Any, int]:
        out, index = view.call(name, name, **args)
        self.args_by_index[index] = dict(inp)
        return out, index

    def t_inspect(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """Part of the calibration window's record (no registry call)."""
        start = max(float(inp.get("start_d", self.cal[0])), self.cal[0])
        end = min(float(inp.get("end_d", self.cal[1])), self.cal[1])
        limit = max(min(int(inp.get("max_points", 60)), self.max_points), 1)
        what = inp["what"]
        if what == "sensor":
            s = self.sensor(inp.get("name"))
            keep = _mask(s, (start, end))
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

    def t_describe(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The model interface (a registry call)."""
        out, index = self._call(view, "describe_model", inp, model=MODEL)
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

    def t_feed_loads(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The declared loads (a registry call)."""
        out, index = self._call(view, "feed_loads", inp, model=MODEL)
        return self._out(index, _dump(out))

    def event_windows(self, quantile: float | None) -> list[dict[str, float]]:
        """Runs of days whose declared COD load exceeds its ``quantile``."""
        if quantile is None:
            return []
        if not 0.0 < float(quantile) < 1.0:
            raise ActionError("event_load_quantile must lie in (0, 1)")
        loads = self.base.loads
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

    def t_qc(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """Quality checks on the calibration window (the hold-out is not the roles' to read)."""
        names = inp.get("sensors") or sorted(self.series)
        chosen = [self.sensor(n) for n in names]
        q = inp.get("event_load_quantile", self.cfg["p0"]["qc"].get("event_load_quantile"))
        windows = self.event_windows(q)
        payload = []
        for s in chosen:
            m = _mask(s, self.cal)
            payload.append({"name": s.name, "t": s.t[m], "value": s.value[m], "unit": s.unit})
        out, index = self._call(view, "data_qc", inp, series=payload, event_windows=windows)
        for r in out.results:
            if r.name in self.series:
                bound = self.series[r.name].drift_bound
                self.rec.produce(
                    index, "declared_bound", bound, self.unit_of_sensor(r.name), r.name
                )
            self.rec.produce(index, "slope_per_d", _f(r.drift_slope_per_d), "-", r.name)
            self.rec.produce(index, "signal_to_noise", _f(r.drift_signal_to_noise), "-", r.name)
            self.rec.produce(index, "event_missing_ratio", _f(r.event_missing_ratio), "-", r.name)
            for seg in r.flatlines:
                self.rec.produce(index, "start_d", float(seg.start), "d", r.name)
                self.rec.produce(index, "end_d", float(seg.end), "d", r.name)
        return self._out(index, _dump(out))

    def t_balance(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """COD, N and charge closure over the calibration window."""
        end_d = self.cal[1]
        default = min(float(self.cfg["p0"]["mass_balance"]["window_d"]), end_d - self.cal[0])
        width = float(inp.get("window_d", default))
        if not 1.0 <= width <= end_d:
            raise ActionError(f"window_d must lie in [1, {end_d:g}] d (the calibration window)")
        windows, start = [], self.cal[0]
        while start + width <= end_d + 1e-9:
            windows.append({"start": start, "end": start + width})
            start += width
        loads = self.base.loads
        geometry = self.cfg["plant_geometry"][str(self.manifest["plant"])]
        temp = self.series.get("temperature")
        t_op = float(geometry["T_op_K"])
        if temp is not None and np.isfinite(temp.value[_mask(temp, self.cal)]).any():
            t_op = float(np.nanmean(temp.value[_mask(temp, self.cal)]))
        lt = np.asarray(loads.t, dtype=float)
        lk = lt < end_d

        def obs(name: str) -> dict[str, Any] | None:
            s = self.series.get(name)
            return None if s is None else self.observed(s, self.cal)

        out, index = self._call(
            view,
            "mass_balance",
            inp,
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
        n_inadmissible = sum(1 for w in out.windows if w.cod_admissible is False)
        closure_mean = _f(np.mean(cod)) if cod else None
        self.rec.produce(index, "n_inadmissible", n_inadmissible, "-")
        self.rec.produce(index, "cod_closure_mean", closure_mean, "-")
        self.rec.produce(index, "charge_drift", _f(out.charge_drift), "-")
        result = _dump(out)
        result["summary"] = {
            "n_inadmissible": n_inadmissible,
            "cod_closure_mean": closure_mean,
            "charge_drift": _f(out.charge_drift),
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

    def sim_summary(self, sim: Any, index: int) -> dict[str, Any]:
        """Per observed sensor on the calibration window: the standardised misfit."""
        t_model = np.asarray(sim.t, dtype=float)
        out: dict[str, Any] = {}
        for s in self.series.values():
            if s.channel not in sim.outputs:
                continue
            m = _mask(s, self.cal) & np.isfinite(s.value)
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
            self.rec.produce(index, "mean_z", _f(z.mean()), "-", s.name)
            self.rec.produce(index, "rms_z", _f(math.sqrt(float(np.mean(z**2)))), "-", s.name)
            self.rec.produce(index, "mean_predicted", _f(pred.mean()), s.unit, s.name)
            self.rec.produce(index, "mean_observed", _f(s.value[m].mean()), s.unit, s.name)
        return out

    def t_simulate(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """One evaluation; stored under its call index."""
        args: dict[str, Any] = {
            "model": MODEL,
            "parameters": self._multipliers(inp.get("parameters"), "parameters"),
        }
        if inp.get("biomass_scale") is not None:
            if float(inp["biomass_scale"]) <= 0:
                raise ActionError("biomass_scale must be positive")
            args["biomass_scale"] = float(inp["biomass_scale"])
        out, index = self._call(view, "simulate", inp, **args)
        self.sims[index] = out
        self.sim_params[index] = dict(args["parameters"])
        return self._out(
            index,
            {
                "success": out.success,
                "message": out.message,
                "n_evaluations": out.n_evaluations,
                "by_sensor": self.sim_summary(out, index),
            },
        )

    def _outputs(self, value: Any) -> list[str]:
        outs = list(value or [s.channel for s in self.objective()])
        bad = [o for o in outs if o not in self.outputs]
        if bad or not outs:
            raise ActionError(f"unknown output channel(s) {bad}; outputs: {self.outputs}")
        return outs

    def t_morris(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
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
        out, index = self._call(view, "gsa_morris", inp, **args)
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
        for r in out.results:
            for v in r.mu_star:
                self.rec.produce(index, "mu_star", _f(v), "-", None)
        return self._out(index, result)

    def t_sobol(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
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
        out, index = self._call(view, "gsa_sobol", inp, **args)
        names = list(out.parameters)
        by_output: dict[str, Any] = {}
        for r in out.results:
            entry: dict[str, Any] = {
                "ranking": list(r.ranking),
                "S1": dict(zip(names, r.S1, strict=True)),
                "ST": dict(zip(names, r.ST, strict=True)),
                "ST_conf": dict(zip(names, r.ST_conf, strict=True)),
            }
            by_output[r.output] = entry
            for v in r.ST:
                self.rec.produce(index, "ST", _f(v), "-", None)
        return self._out(index, {"by_output": by_output, "n_evaluations": out.n_evaluations})

    def fisher_interval(self, name: str, estimate: float, sd: Any) -> list[float] | None:
        """``estimate +/- z sd`` clipped to the bounds; None for a non-finite sd."""
        sd_f = _f(sd)
        if sd_f is None or name not in self.lower:
            return None
        z = float(self.cfg["p0"]["uncertainty"]["z"])
        return [
            max(self.lower[name], estimate - z * sd_f),
            min(self.upper[name], estimate + z * sd_f),
        ]

    def t_fisher(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """Fisher information on the calibration data."""
        self.check_parameters(inp["parameters"])
        at = self._multipliers(inp.get("at"), "at")
        out, index = self._call(
            view,
            "fisher_info",
            inp,
            model=MODEL,
            data=self.data(inp.get("sensors")),
            parameters=list(inp["parameters"]),
            at=at,
        )
        self.fishers[index] = out
        rel: dict[str, float | None] = {}
        for n, sd in zip(out.parameters, out.crlb_sd, strict=True):
            width = self.upper[n] - self.lower[n]
            rel[n] = _f(float(sd) / width) if width > 0 else None
            self.rec.produce(index, "crlb_sd", _f(sd), self.units.get(n, "-"), None)
            self.rec.produce(index, "crlb_sd_over_bound_width", rel[n], "-", None)
        result = _dump(out)
        result.pop("fim", None)
        result["crlb_sd"] = dict(zip(out.parameters, out.crlb_sd, strict=True))
        result["crlb_sd_over_bound_width"] = rel
        result["interval_90_at_point"] = {
            n: self.fisher_interval(n, at.get(n, 1.0), sd)
            for n, sd in zip(out.parameters, out.crlb_sd, strict=True)
        }
        return self._out(index, result)

    def t_profile(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
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
        out, index = self._call(view, "profile_likelihood", inp, **args)
        self.profiles[index] = out
        lo, hi = out.interval
        self.rec.produce(index, "profile_lower", _f(lo), self.units.get(out.parameter, "-"))
        self.rec.produce(index, "profile_upper", _f(hi), self.units.get(out.parameter, "-"))
        return self._out(index, _dump(out))

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
                # narrowed only, inside the declared box and inside any earlier narrowing
                # of this run (Q10: never widened)
                p_lo, p_hi = self.bounds_narrowed.get(n, (self.lower[n], self.upper[n]))
                if not p_lo <= lo < hi <= p_hi:
                    raise ActionError(
                        f"bounds of {n} must be [lower, upper] inside [{p_lo}, {p_hi}]"
                    )
                bounds[n] = (lo, hi)
            args["bounds"] = bounds
            self.bounds_narrowed.update(bounds)
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

    def t_fit(self, view: RoleView, inp: dict[str, Any], name: str = "fit_lsq") -> dict[str, Any]:
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
        out, index = self._call(view, name, inp, **args)
        self.fits[index] = out
        self.fit_bounds[index] = dict(args.get("bounds") or {})
        names = list(out.parameters)
        sd = list(out.sd) if out.sd is not None else [None] * len(names)
        for n, t, d in zip(names, out.theta, sd, strict=True):
            unit = self.units.get(n, "-")
            self.rec.produce(index, "theta", _f(t), unit, None)
            iv = self.fisher_interval(n, float(t), d)
            if iv is not None:
                self.rec.produce(index, "interval_lower", iv[0], unit, None)
                self.rec.produce(index, "interval_upper", iv[1], unit, None)
        self.rec.produce(index, "chi2", _f(out.chi2), "-", None)
        return self._out(index, self.fit_result(out))

    def t_mcmc(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The sampler; stored under its call index."""
        inp = dict(inp)
        if inp.get("from_fit") is not None:
            fit = self.stored_result(self.fits, inp.pop("from_fit"), "fit")
            start = {n: float(v) for n, v in zip(fit.parameters, fit.theta, strict=True)}
            start.update(inp.get("start") or {})
            inp["start"] = {n: v for n, v in start.items() if n in inp["parameters"]}
        args = self._fit_args(inp)
        for key in ("likelihood", "n_walkers", "n_steps"):
            if key in inp:
                args[key] = inp[key]
        out, index = self._call(view, "bayes_mcmc", inp, **args)
        self.posteriors[index] = out
        names = list(out.parameters)
        q = {k: list(v) for k, v in dict(out.quantiles).items()}
        for i, n in enumerate(names):
            unit = self.units.get(n, "-")
            self.rec.produce(index, "mean", _f(list(out.mean)[i]), unit, None)
            if "q05" in q and "q95" in q:
                self.rec.produce(index, "q05", _f(q["q05"][i]), unit, None)
                self.rec.produce(index, "q95", _f(q["q95"][i]), unit, None)
        result = {
            "converged": out.converged,
            "mean": dict(zip(names, out.mean, strict=True)),
            "sd": dict(zip(names, out.sd, strict=True)),
            "quantiles": {k: dict(zip(names, v, strict=True)) for k, v in q.items()},
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
        loads = self.base.loads
        t_all = np.asarray(loads.t, dtype=float)
        keep = t_all < self.cal[1]
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
        if temp is not None and (np.isfinite(temp.value) & _mask(temp, self.cal)).sum() >= 4:
            m = np.isfinite(temp.value) & _mask(temp, self.cal)
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
        split = self.cal[0] + float(self.cfg["p0"]["attribution"]["transient_d"])

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

    def t_residual(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """Residual structure of one sensor against a stored prediction."""
        s = self.sensor(inp["sensor"])
        sim = self.stored_result(self.sims, inp["prediction"], "simulate")
        if s.channel not in sim.outputs:
            raise ActionError(f"{s.name} observes {s.channel}, which the model does not output")
        m = _mask(s, self.cal) & np.isfinite(s.value)
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
        out, index = self._call(view, "residual_diag", inp, **args)
        for key in ("bias_z", "rmse_z", "step_z", "early_bias_z", "late_bias_z"):
            self.rec.produce(index, key, stats[key], "-", s.name)
        self.rec.produce(index, "step_day", stats["step_day"], "d", s.name)
        result = _dump(out)
        result["standardised"] = {**stats, "prediction_call_index": int(inp["prediction"])}
        return self._out(index, result)

    def t_assay(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """A requested assay (never on a hold-out day)."""
        day = float(inp["day"])
        if not self.cal[0] <= day < self.cal[1]:
            raise ActionError(f"an assay day must lie in the calibration window {list(self.cal)}")
        sim = None
        if inp.get("prediction") is not None:
            sim = self.stored_result(self.sims, inp["prediction"], "simulate")
        out, index = self._call(view, "request_assay", inp, assay=inp["assay"], day=day)
        result = _dump(out)
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
            self.rec.produce(index, "value", float(res.value), str(res.unit), None)
            self.rec.produce(index, "disagreement_z", _f(z), "-", None)
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

    def t_voi(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """Expected information gain of the assays, from a stored posterior."""
        post = self.stored_result(self.posteriors, inp["posterior"], "bayes_mcmc")
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
        out, index = self._call(view, "voi_assay", inp, **args)
        for r in out.results:
            self.rec.produce(index, "eig_per_unit", _f(r.eig_per_unit), "-", None)
        return self._out(index, _dump(out))

    def t_status(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The data-quality role's judgement of one sensor: no QC bypass (§5)."""
        s = self.sensor(inp["sensor"])
        status = inp["status"]
        in_obj = bool(inp["in_objective"])
        if status in ("flagged", "excluded") and in_obj:
            raise ActionError(f"a {status} sensor never enters the objective")
        if s.flags and (status == "ok" or in_obj):
            raise ActionError(
                f"{s.name} failed a quality check ({sorted(s.flags)}): it is never set ok and "
                "never enters the objective"
            )
        if in_obj and s.channel not in self.outputs:
            raise ActionError(f"{s.name} observes nothing the model outputs")
        windows = [(float(a), float(b)) for a, b in inp.get("quarantine") or []]
        for start, end in windows:
            if end < start:
                raise ActionError(f"quarantine window [{start}, {end}] is reversed")
            if end > self.cal[1]:
                raise ActionError(
                    f"quarantine window [{start}, {end}] reaches into the hold-out "
                    f"window (after {self.cal[1]:g} d), which is not yours to edit"
                )
        for start, end in windows:
            inside = (s.t >= start) & (s.t <= end)
            s.value = np.where(inside, np.nan, s.value)
            s.quarantined.append([float(start), float(end)])
        s.status, s.in_objective = status, in_obj
        # the reason is free text: it is logged with the call's arguments (messages.jsonl,
        # the redacted projection) and never reaches state.json; its length is the record
        self.sensor_reason_lengths[s.name] = len(str(inp.get("reason", "")))
        return {
            "sensor": s.name,
            "status": s.status,
            "in_objective": s.in_objective,
            "quarantined_windows": [list(w) for w in s.quarantined],
            "objective_now": [x.name for x in self.objective()],
        }

    def t_background(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The declared background band (a registry call)."""
        out, index = self._call(
            view,
            "declared_background",
            inp,
            plant=str(self.manifest["plant"]),
            tier=str(self.manifest["tier"]),
        )
        return self._out(index, _dump(out))

    def t_validate(self, view: RoleView, inp: dict[str, Any]) -> dict[str, Any]:
        """The hold-out test of a stored prediction (the verifier's tool only, §3.1)."""
        sim = self.stored_result(self.sims, inp["prediction"], "simulate")
        observed = [
            {"output": s.channel, "t": s.t, "value": s.raw, "sd": s.sd, "unit": s.unit}
            for s in self.objective()
            if s.channel in sim.outputs
            and int(np.sum(np.isfinite(s.raw) & (s.t >= self.holdout[0]))) >= 1
        ]
        if not observed:
            raise ActionError("no objective sensor has a hold-out sample")
        t_model = np.asarray(sim.t, dtype=float)
        predicted = {
            o["output"]: np.asarray(sim.outputs[o["output"]], dtype=float) for o in observed
        }
        out, index = self._call(
            view,
            "validate",
            inp,
            observed=observed,
            t=t_model,
            predicted=predicted,
            holdout={"start": self.holdout[0], "end": self.holdout[1]},
        )
        names = {s.channel: s.name for s in self.objective()}
        band = (self.base.band or {}).get("channels", {})
        failed = 0
        metrics: dict[str, Any] = {}
        for m in out.results:
            name = names.get(m.output)
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
            self.rec.produce(
                index, "rmse", _f(m.rmse), self.unit_of_sensor(name) if name else "-", name
            )
            self.rec.produce(
                index, "bias", _f(m.bias), self.unit_of_sensor(name) if name else "-", name
            )
            limit = (band.get(name) or {}).get("after_fit", {}).get("rms_z", {}).get("max")
            rms_z = None
            if name is not None and _f(m.rmse) is not None:
                s = self.series[name]
                sd = float(np.nanmedian(s.sd)) if np.isfinite(s.sd).any() else None
                rms_z = _f(float(m.rmse) / sd) if sd else None
            if limit is not None and rms_z is not None and rms_z > float(limit):
                failed += 1
        holdout_failed = failed >= int(self.cfg["holdout"]["min_channels_failed"])
        self.rec.produce(index, "holdout_failed", bool(holdout_failed), "-", None)
        self.rec.produce(index, "n_channels_failed", failed, "-", None)
        self.validation = {
            "holdout": [self.holdout[0], self.holdout[1]],
            "ensemble": bool(out.ensemble),
            "ensemble_size": 0,
            "metrics": metrics,
            "constraint_violations": int(sum(int(m.constraint_violations) for m in out.results)),
            "calls": [index],
        }
        result = _dump(out)
        result["holdout_failed"] = bool(holdout_failed)
        result["n_channels_failed"] = failed
        return self._out(index, result)

    def stored(self, inp: dict[str, Any]) -> dict[str, Any]:
        """A full stored output by call index (a harness action, no registry call)."""
        index = inp.get("call_index")
        if not isinstance(index, int) or index not in self.rec.outputs:
            raise ActionError(
                f"no stored output with call_index {index!r}; have {sorted(self.rec.outputs)}"
            )
        return {"call_index": index, "result": compact(self.rec.outputs[index], self.max_points)}


# ------------------------------------------------------------------ findings


def check_finding(ws: Workspace, role: str, payload: Any, round_: int) -> Any:
    """A role's typed finding, checked by code; the model instance when it passes.

    Refused: a payload that is not the role's message; a claim not allowed in the round
    (``structural`` in round 1); an evidence item citing a call that did not return; a
    value no cited call produced under that name (numbers to the five digits shown,
    strings exactly); a unit that is not the registry's for that value; a quantity whose
    registry unit is not ``-`` cited without its unit (rule 6); a sensor claim on a sensor
    the tier does not carry; a bounds narrowing the run did not make; a verdict whose
    alternative the amended rule does not admit; a verdict's hold-out citing a call that
    is not a ``validate`` of this run.

    Raises:
        ActionError: Naming the first refusal.
    """
    model = messages.FINDINGS[role]
    try:
        finding = model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise ActionError(f"finding: {where}: {first.get('msg')}") from exc
    if not messages.claim_allowed_in_round(finding, round_):
        raise ActionError(f"finding: claim {finding.claim!r} is a round-2 claim")
    for i, item in enumerate(finding.evidence):
        missing = [c for c in item.calls if ws.rec.ok_index(c) is None]
        if missing:
            raise ActionError(
                f"evidence[{i}]: call index(es) {missing} name no call of this run that returned"
            )
        for key, value in item.values.items():
            entries = [e for c in item.calls for e in ws.rec.produced.get(c, {}).get(key, [])]
            if not entries:
                raise ActionError(
                    f"evidence[{i}]: no cited call produced `{key}`; cite the call it rests on"
                )
            matched = [(v, unit) for v, unit, _ in entries if _same_value(v, value)]
            if not matched:
                shown = sorted(
                    {
                        _round(float(v)) if not isinstance(v, bool | str) else v
                        for v, _, _ in entries
                    },
                    key=str,
                )[:8]
                raise ActionError(
                    f"evidence[{i}]: `{key}` = {value!r} is not what the cited calls produced "
                    f"({shown})"
                )
            units = {unit for _, unit in matched}
            given = item.units.get(key)
            if given is None:
                if units - {"-"}:
                    raise ActionError(
                        f"evidence[{i}]: `{key}` is a quantity in {sorted(units)}; give its unit"
                    )
            elif not any(messages.same_unit(given, u) for u in units):
                raise ActionError(
                    f"evidence[{i}]: `{key}` has unit {given!r}; the registry gives {sorted(units)}"
                )
    if role == "data_quality":
        for name in (*finding.statuses, *finding.quarantines):
            if name not in ws.series:
                raise ActionError(f"finding: no sensor {name!r} at this tier")
        if finding.channel is not None and finding.channel not in ws.series:
            raise ActionError(f"finding: no sensor {finding.channel!r} at this tier")
    if role == "calibration":
        for name in (*finding.parameters, *finding.bounds_narrowed):
            if name not in ws.params:
                raise ActionError(f"finding: unknown parameter {name!r}")
        for name, (lo, hi) in finding.bounds_narrowed.items():
            made = ws.bounds_narrowed.get(name)
            if made is None or abs(made[0] - lo) > 1e-9 or abs(made[1] - hi) > 1e-9:
                raise ActionError(
                    f"finding: bounds of {name} were not narrowed to [{lo}, {hi}] by a fit of "
                    "this run"
                )
    if role == "design" and finding.assay not in ws.cfg.get("assay_catalogue", {}):
        raise ActionError(f"finding: no requestable assay {finding.assay!r}")
    if role == VERIFIER:
        if finding.holdout is not None:
            rec = ws.rec.ok_index(finding.holdout.call)
            if rec is None or rec["name"] != "validate":
                raise ActionError("verdict: holdout.call names no validate call of this run")
            produced = [
                v
                for v, _, _ in ws.rec.produced.get(finding.holdout.call, {}).get(
                    "holdout_failed", []
                )
            ]
            if produced and bool(produced[0]) != finding.holdout.failed:
                raise ActionError("verdict: holdout.failed is not what the validate call found")
        if finding.verdict == "fail":
            if not evidence.admissible_alternative(
                finding.alternative, ws.lab, ws.base.table, ws.base.signatures
            ):
                raise ActionError(
                    f"verdict: the alternative {finding.alternative!r} is not admitted by the "
                    "evidence"
                )
            # D-1: a fail against a non-structural label whose only evidence is a passed hold-out
            non_structural = finding.alternative not in (ws.lab["structural"], ws.lab["none"])
            only_holdout = all(
                ws.rec.ok_index(c) is not None and ws.rec.ok_index(c)["name"] == "validate"
                for item in finding.evidence
                for c in item.calls
            )
            if (
                non_structural
                and only_holdout
                and finding.holdout is not None
                and not finding.holdout.failed
            ):
                raise ActionError(
                    "verdict: a passed hold-out is not evidence against a non-structural cause "
                    "(D-1)"
                )
    return finding


def _same_value(produced: Any, value: Any) -> bool:
    if isinstance(produced, bool) or isinstance(value, bool):
        return produced is value
    if isinstance(produced, str) or isinstance(value, str):
        return produced == value
    if produced is None or value is None:
        return produced is value
    a, b = float(produced), float(value)
    return abs(a - b) <= 1e-3 * max(abs(a), abs(b)) + 1e-9


def evidence_items(finding: Any) -> list[dict[str, Any]]:
    """A finding's evidence as ``state.json`` items, statements templated by code."""
    return [
        {
            "rule": item.rule,
            "label": item.label,
            "statement": messages.statement_for(item),
            "values": {
                k: (v if isinstance(v, bool | str) or v is None else _f(v))
                for k, v in item.values.items()
            },
            "calls": list(item.calls),
        }
        for item in finding.evidence
    ]


# ------------------------------------------------------------------ the role agent


def _assistant_blocks(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


class RoleAgent:
    """One role's turns on P1's loop: ask, execute, answer, until its finding or its budget."""

    def __init__(
        self,
        role: str,
        ws: Workspace,
        respond: Any,
        *,
        round_: int,
        grant: dict[str, int],
        brief: dict[str, Any],
        turns: int,
    ) -> None:
        """Set up one routing of ``role``."""
        self.role = role
        self.ws = ws
        self.respond = respond
        self.round = round_
        self.grant = dict(grant)
        self.turns = int(turns)
        allowed = list(ws.agents_cfg["roles"][role]["tools"])
        self.view = RoleView(role, allowed, ws.rec)
        self.specs = role_tool_specs(role, allowed)
        self.system = str(ws.agents_cfg["prompts"][role])
        self.messages: list[dict[str, Any]] = [
            {"role": "user", "content": json.dumps(brief, sort_keys=True, default=str)}
        ]
        self.finding: Any = None
        self.assessment = ""
        self.stop_reason = ""
        self.state = {"turns": 0, "tool_uses": 0, "refused": 0}
        self.spent = {"evaluations": 0, "assays": 0}

    def guard_grant(self, name: str, inp: dict[str, Any]) -> None:
        """Refuse a call whose evaluation bound or assay cost exceeds the grant.

        Raises:
            ActionError: Naming the bound and the grant.
        """
        bound = estimate_evaluations(name, inp, self.ws.cfg.get("tool_size_ceilings", {}))
        left = int(self.grant.get("evaluations", 0)) - self.spent["evaluations"]
        if bound > left:
            raise ActionError(
                f"{name}: a bound of {bound} evaluations exceeds the grant's {left} left"
            )
        if name == "request_assay":
            price = int(
                self.ws.cfg.get("assay_catalogue", {})
                .get(str(inp.get("assay")), {})
                .get("unit_cost", 1)
            )
            if price > int(self.grant.get("assays", 0)) - self.spent["assays"]:
                raise ActionError(
                    f"request_assay: {price} unit(s) exceed the grant's assay units left"
                )

    def execute(self, block: dict[str, Any]) -> dict[str, Any]:
        """One tool use -> its tool_result block."""
        name = str(block.get("name"))
        inp = block.get("input") or {}
        self.state["tool_uses"] += 1
        spec = next((s for s in self.specs if s["name"] == name), None)
        try:
            if spec is None:
                if name in registry_tool_specs():
                    self.view.call(name, name)  # a registry tool off the list: the view refuses
                raise ActionError(f"no tool {name!r} for the {self.role} role")
            check(inp, spec["input_schema"], name)
            if name == "emit_finding":
                self.finding = check_finding(self.ws, self.role, inp["finding"], self.round)
                return self._result(block, {"accepted": True}, False)
            if name == "stored":
                return self._result(block, self.ws.stored(inp), False)
            self.guard_grant(name, inp)
            before = tools.remaining()
            handler = self.ws.handlers()[name]
            payload = (
                handler(self.view, inp, name)
                if name in ("fit_lsq", "fit_de", "fit_cmaes")
                else handler(self.view, inp)
            )
            after = tools.remaining()
            self.spent["evaluations"] += int(before.simulator_evals) - int(after.simulator_evals)
            self.spent["assays"] += int(before.assay_units) - int(after.assay_units)
            return self._result(block, payload, False)
        except ActionError as exc:
            return self.refuse(block, str(exc))
        except tools.BudgetExceededError as exc:
            index = self.ws.rec.actions[-1]["call_index"] if self.ws.rec.actions else None
            self.ws.rec.failure(
                self.role, name, name, "budget_exceeded", str(exc), "nothing ran", index
            )
            return self._result(
                block, {"error": f"budget refusal: {exc}", "budget": self.ws.budget()}, True
            )
        except tools.ToolError as exc:
            index = self.ws.rec.actions[-1]["call_index"] if self.ws.rec.actions else None
            self.ws.rec.failure(
                self.role, name, name, "error", str(exc), "reported to the role", index
            )
            return self._result(block, {"error": f"tool error: {exc}"}, True)

    def refuse(self, block: dict[str, Any], reason: str) -> dict[str, Any]:
        """Refuse one tool use: recorded under ``tool_failures``, returned as an error."""
        name = str(block.get("name"))
        self.state["refused"] += 1
        self.ws.rec.failure(
            self.role,
            name,
            f"p2.{self.role}.{name}",
            "error",
            reason,
            "refused by the harness",
            None,
        )
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

    def run(self) -> Any:
        """The loop; the role's finding, or None when its turns ended without one."""
        while self.finding is None:
            if self.state["turns"] >= self.turns:
                self.stop_reason = f"{self.turns} turns used without a finding"
                break
            try:
                reply = self.respond(
                    {"system": self.system, "messages": self.messages, "tools": self.specs}
                )
            except tools.BudgetExceededError as exc:
                self.stop_reason = f"model budget: {exc}"
                raise procedural.ModelCapReached(str(exc)) from exc
            except tools.ToolError as exc:
                self.stop_reason = f"model error: {exc}"
                break
            self.state["turns"] += 1
            response = reply["response"]
            content = list(response.get("content") or [])
            self.messages.append({"role": "assistant", "content": _assistant_blocks(content)})
            texts = [str(b.get("text", "")) for b in content if b.get("type") == "text"]
            if texts:
                self.assessment = "\n".join(texts)[:4000]
            if response.get("stop_reason") == "refusal":
                self.stop_reason = "the model refused"
                break
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses:
                self.messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "HARNESS: continue by calling a tool; your turns end "
                                "with `emit_finding`.",
                            }
                        ],
                    }
                )
                continue
            results = []
            for b in uses:
                if self.finding is not None:
                    results.append(self.refuse(b, "the finding is emitted; nothing runs after it"))
                else:
                    results.append(self.execute(b))
            self.messages.append({"role": "user", "content": results})
        if self.finding is not None:
            self.stop_reason = "finding emitted"
        return self.finding


# ------------------------------------------------------------------ the offline responder


class OfflineModel:
    """The scripted responder of the offline arm: one tool use, then one typed finding.

    No model is reachable offline; this stands in its place so the arm runs end to end
    and its floor is a record. Each role calls one tool of its list and emits a ``none``
    or ``no_claim`` finding citing that call (or an empty one where no value is produced).
    """

    def __init__(self, role: str) -> None:
        """Set up for ``role``."""
        self.role = role
        self.turn = 0

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        """The next reply, read off the request's history."""
        self.turn += 1
        history = request["messages"]
        last = history[-1]["content"] if history else ""
        result = None
        if isinstance(last, list):
            for block in last:
                if block.get("type") == "tool_result" and not block.get("is_error"):
                    result = json.loads(block["content"])
        if self.turn == 1:
            name, inp = self.first_call()
            block = {"type": "tool_use", "id": f"{self.role}-1", "name": name, "input": inp}
        else:
            block = {
                "type": "tool_use",
                "id": f"{self.role}-{self.turn}",
                "name": "emit_finding",
                "input": {"finding": self.finding(result)},
            }
        response = {"content": [block], "stop_reason": "tool_use", "usage": {}}
        return {"response": response, "status": {}}

    def first_call(self) -> tuple[str, dict[str, Any]]:
        """The one tool use of the role."""
        return {
            "data_quality": ("data_qc", {}),
            "influent": ("mass_balance", {}),
            "identifiability": ("describe_model", {}),
            "calibration": ("simulate", {}),
            "design": ("stored", {"call_index": 0}),
            VERIFIER: ("declared_background", {}),
        }[self.role]

    def finding(self, result: dict[str, Any] | None) -> dict[str, Any]:
        """The role's typed ``none`` / ``no_claim`` finding, citing the call when it returned."""
        cited: list[dict[str, Any]] = []
        if result is not None and "call_index" in result:
            cited = [
                {
                    "label": "none",
                    "rule": "sensor",
                    "calls": [int(result["call_index"])],
                    "values": {},
                    "units": {},
                }
            ]
        if self.role == "data_quality":
            return {"claim": "no_claim", "confidence": "low", "evidence": cited}
        if self.role == "influent":
            return {"claim": "no_claim", "confidence": "low", "evidence": cited}
        if self.role == "identifiability":
            return {"subset": [], "kinetic_update_allowed": False, "evidence": cited}
        if self.role == "calibration":
            return {"claim": "no_claim", "confidence": "low", "evidence": cited}
        if self.role == "design":
            return {
                "assay": "none",
                "day": 0.0,
                "unit": "-",
                "separates": ["sensor", "none"],
                "predicted": {},
                "evidence": [],
            }
        return {"round": 1, "verdict": "abstain", "evidence": cited}


# ------------------------------------------------------------------ the coordinator


class Coordinator:
    """Code routes (§3.3, Q7); the only writer of routing entries. It never writes a finding."""

    def __init__(self, run: AgentRun) -> None:
        """Set up over the run."""
        self.run = run
        self.entries: list[dict[str, Any]] = []

    def route(self, round_: int, to: str, reason: str, grant: dict[str, int]) -> dict[str, Any]:
        """One routing entry, typed (``messages.RoutingEntry``), logged."""
        entry = messages.RoutingEntry(
            round=round_, to=to, reason=reason, grant=messages.Grant(**grant)
        )
        doc = entry.model_dump(mode="json")
        self.entries.append(doc)
        self.run.log.send("decision", COORDINATOR, to, f"route.{round_}", doc)
        return doc

    def specialists_for(self) -> list[str]:
        """The specialists of this stage: those whose null case failed, or all when it stands."""
        on = self.run.on
        table = self.run.base.table
        ordered = [r for r in ("influent", "identifiability", "calibration") if on.get(r, True)]
        if not table or not table.get("null_rejected"):
            return ordered
        wanted: list[str] = []
        if table.get("NB") and on.get("influent", True):
            wanted.append("influent")
        if (table.get("NM") or table.get("NS")) and on.get("calibration", True):
            if on.get("identifiability", True):
                wanted.append("identifiability")
            wanted.append("calibration")
        return wanted or ordered

    def grant_for(self, roles: list[str], role: str) -> dict[str, int]:
        """An equal share of the evaluations left for the roles of this stage; assays to design."""
        rem = tools.remaining()
        share = int(rem.simulator_evals) // max(len(roles), 1)
        assays = int(rem.assay_units) if role == "design" else 0
        return {"evaluations": max(share, 0), "assays": assays}

    def conflict(self, findings: dict[str, Any]) -> tuple[str, str] | None:
        """Two findings claiming different causes, if any (the design role's trigger)."""
        claims = {r: _claim_of(f) for r, f in findings.items() if _claim_of(f) in self.run.labels}
        distinct = sorted(set(claims.values()))
        if len(distinct) >= 2:
            return distinct[0], distinct[1]
        return None


# ------------------------------------------------------------------ the run


class AgentRun:
    """One run of the agent P2: the code steps, then the roles under the coordinator, then code."""

    def __init__(self, cfg: dict[str, Any], responder: Any = None) -> None:
        """Set up; ``responder(role) -> respond(request)`` (offline: :class:`OfflineModel`)."""
        self.cfg = cfg
        self.agents_cfg = cfg["agents"]
        self.base = procedural.Workflow(cfg, procedural.offline_responder)
        self.log = self.base.log
        self.rec = Recorder()
        self.on = dict(cfg["ablation"]["roles"])
        self.switch = cfg["ablation"]
        self.lab = self.base.lab
        self.labels = sorted(set(self.lab.values()))
        self.responder = responder or (
            (lambda role: OfflineModel(role))
            if cfg.get("decider") != "live"
            else (lambda role: tools.llm)
        )
        self.ws: Workspace | None = None
        self.coordinator = Coordinator(self)
        self.findings: dict[str, Any] = {}
        self.verdicts: list[Any] = []
        self.assessments: dict[str, str] = {}
        self.role_runs: list[dict[str, Any]] = []
        self.classification: dict[str, Any] = {}
        self.abstentions: list[str] = []
        self.codes: list[str] = []
        self.annotations: list[str] = []
        self.verdict: dict[str, Any] = {}
        self.completed = False
        self.evidence: list[dict[str, Any]] = []

    # -- the stages ----------------------------------------------------------------------
    def code_steps(self) -> None:
        """The procedural arm's evidence: QC, the reference fit, the null table, the signatures."""
        b = self.base
        b.step_read()
        b.step_qc()
        b.step_reference()
        b.step_null()
        if b.reference is not None and b.placement:
            b.step_screen()
            b.intervals_from_fit()
            b.step_mcmc()
            b.step_residuals()
            b.step_state_test()
            b.step_profile()
        # the procedural recorder's actions are the code steps': kept in the record too
        self.rec.actions.extend(b.rec.actions)
        self.rec.failures.extend(b.rec.failures)
        for role, use in b.rec.by_role.items():
            self.rec.by_role[f"code.{role}"] = dict(use)
        self.ws = Workspace(b, self.cfg, self.rec)

    def brief(self, role: str, round_: int, grant: dict[str, int], turns: int) -> dict[str, Any]:
        """What a role is shown at its first turn: the typed state and the projected log."""
        ws = self.ws
        assert ws is not None
        b = self.base
        findings = {r: f.model_dump(mode="json") for r, f in self.findings.items()}
        verdicts = [v.model_dump(mode="json") for v in self.verdicts]
        brief: dict[str, Any] = {
            "role": role,
            "round": round_,
            "plant": str(ws.manifest["plant"]),
            "tier": str(ws.manifest["tier"]),
            "calibration_window": list(ws.cal),
            "sensors": {
                n: {
                    "channel": s.channel,
                    "unit": s.unit,
                    "status": s.status,
                    "flags": list(s.flags),
                    "in_objective": bool(s.in_objective),
                }
                for n, s in ws.series.items()
            },
            "model": {
                "parameters": ws.params,
                "lower": ws.lower,
                "upper": ws.upper,
                "units": ws.units,
                "outputs": ws.outputs,
            },
            "null_table": b.table,
            "placement": dict(b.placement),
            "signatures": json.loads(procedural.to_json(b.signatures)),
            "findings": findings,
            "verdicts": verdicts,
            "projected_log": project(self.rec, ws.args_by_index, ws.max_points, ws.preview),
            "grant": grant,
            "turns": turns,
            "labels": self.labels,
        }
        if role in ("data_quality", "influent"):
            brief["operator_notes"] = [
                {"day": n.get("day"), "author": n.get("author"), "text": n.get("text")}
                for n in ws.notes
            ]
            brief["feed_log_days"] = {n: int(np.asarray(v).size) for n, v in ws.feed_log.items()}
        if role == "design":
            brief["assay_catalogue"] = self.cfg.get("assay_catalogue", {})
        return brief

    def run_role(self, role: str, round_: int, reason: str, roles: list[str]) -> Any:
        """One routing of ``role``: the coordinator's entry, the role's turns, its finding."""
        ws = self.ws
        assert ws is not None
        grant = self.coordinator.grant_for(roles, role)
        self.coordinator.route(round_, role, reason, grant)
        turns = int(self.agents_cfg["roles"][role]["turns"])
        agent = RoleAgent(
            role,
            ws,
            self.responder(role),
            round_=round_,
            grant=grant,
            brief=self.brief(role, round_, grant, turns),
            turns=turns,
        )
        finding = agent.run()
        self.role_runs.append(
            {
                "role": role,
                "round": round_,
                "turns": agent.state["turns"],
                "tool_uses": agent.state["tool_uses"],
                "refused": agent.state["refused"],
                "stop": agent.stop_reason,
                "spent": dict(agent.spent),
            }
        )
        if agent.assessment:
            self.assessments[f"{role}.{round_}"] = agent.assessment
            self.log.send(
                "proposal", role, COORDINATOR, f"assessment.{round_}", {"text": agent.assessment}
            )
        if finding is not None:
            kind = "verdict" if role == VERIFIER else "finding"
            self.log.send(
                kind, role, COORDINATOR, f"{kind}.{round_}", finding.model_dump(mode="json")
            )
            if role == VERIFIER:
                self.verdicts.append(finding)
            else:
                self.findings[role] = finding
        else:
            self.annotations.append(f"{role} (round {round_}): no finding: {agent.stop_reason}")
        return finding

    def run(self) -> None:
        """The run: the code steps, QC first, the specialists, design on conflict, the verifier."""
        try:
            self.code_steps()
            round_ = 1
            if self.on.get("data_quality", True):
                self.run_role("data_quality", round_, "qc_first", ["data_quality"])
            table = self.base.table
            reason = "null_failed" if table and table.get("null_rejected") else "null_stands"
            roles = self.coordinator.specialists_for()
            for role in roles:
                self.run_role(role, round_, reason, roles)
            if self.on.get("design", True) and self.coordinator.conflict(self.findings):
                self.run_role("design", round_, "conflict", ["design"])
            if self.switch.get("verifier", True):
                self.run_role(VERIFIER, round_, "verify", [VERIFIER])
        except procedural.ModelCapReached as exc:
            self.codes.append("model_cap")
            self.annotations.append(f"model cap reached: {str(exc)[:200]}")
            self.verdict = {"verdict": "abstain", "reason": "model_cap"}
        except tools.BudgetExceededError as exc:
            self.codes.append("budget")
            self.annotations.append(f"budget refused: {str(exc)[:200]}")
            self.verdict = {"verdict": "abstain", "reason": "budget"}
        self.conclude()
        self.completed = True
        self.write(completed=True)

    # -- the conclusion (§4, step 6) -----------------------------------------------------
    def leading(self) -> tuple[str | None, str | None, list[str]]:
        """The leading admitted claim, its role, and every admitted label."""
        b = self.base
        if b.table is None and not b.signatures:
            return None, None, []
        admitted = evidence.admit_agent(self.lab, b.table, b.signatures)["admitted"]
        order = {"high": 0, "medium": 1, "low": 2}
        candidates = []
        for role, f in self.findings.items():
            claim = _claim_of(f)
            if claim is None or claim not in self.labels:
                continue
            if claim != self.lab["none"] and claim not in admitted:
                continue
            key = next((k for k, v in self.lab.items() if v == claim), "none")
            if claim != self.lab["none"] and role not in CLAIMS_FOR_LABEL.get(key, ()):
                continue
            candidates.append(
                (
                    order.get(f.confidence, 3),
                    procedural.P0_ORDER.index(
                        next((k for k, v in self.lab.items() if v == claim), "none")
                    )
                    if claim != self.lab["none"]
                    else len(procedural.P0_ORDER),
                    role,
                    claim,
                )
            )
        if not candidates:
            return None, None, admitted
        candidates.sort()
        _, _, role, claim = candidates[0]
        return claim, role, admitted

    def conclude(self) -> None:
        """Code writes the label (§4, step 6; the verifier's verdict is final)."""
        lab = self.lab
        claim, role, admitted = self.leading()
        table = self.base.table
        null_stands = not (table and table.get("null_rejected"))
        verdict = self.verdicts[-1] if self.verdicts else None
        reason = ""
        if self.verdict.get("verdict") == "abstain":
            label, rule = ABSTAIN_LABEL, f"abstain:{self.verdict['reason']}"
        elif verdict is None:
            if claim is not None:
                label, rule = claim, "verifier_off:leading_claim"
            elif null_stands:
                label, rule = lab["none"], "verifier_off:null_stands"
            else:
                label, rule = ABSTAIN_LABEL, "abstain:no_admitted_claim"
            if not self.switch.get("verifier", True):
                reason = "verifier_off"
            self.verdict = {
                "verdict": "abstain" if label == ABSTAIN_LABEL else "pass",
                "reason": reason or rule.split(":")[-1],
            }
        elif verdict.verdict == "pass":
            if claim is not None:
                label, rule = claim, f"{RULE}:pass"
            else:
                label, rule = lab["none"], f"{RULE}:pass:none"
            self.verdict = {"verdict": "pass", "reason": "pass"}
        elif verdict.verdict == "fail":
            if verdict.alternative == lab["none"]:
                label, rule = lab["none"], f"{RULE}:fail:none"
                self.verdict = {"verdict": "fail", "reason": "alternative_none"}
            else:
                label, rule = ABSTAIN_LABEL, "abstain:verifier_fail"
                self.verdict = {"verdict": "abstain", "reason": "verifier_fail"}
        else:
            label, rule = ABSTAIN_LABEL, "abstain:verifier_abstain"
            self.verdict = {"verdict": "abstain", "reason": "verifier_abstain"}
        attr = self.cfg["p0"]["attribution"]
        if label == ABSTAIN_LABEL:
            conf = 0.0
            self.abstentions += ["kinetic_attribution", "parameter_values", "structural_adequacy"]
        elif label == lab["none"]:
            conf = float(attr["confidence"]["none"])
        else:
            conf = float(attr["confidence"]["single"])
        flag = None
        if label == lab["sensor"] and isinstance(self.findings.get(role), messages.SensorFinding):
            flag = self.findings[role].channel
        if label in (lab["sensor"], lab["influent"], lab["structural"]):
            self.abstentions.append("kinetic_attribution")
        if label == lab["structural"]:
            self.abstentions.append("parameter_values")
        self.evidence = [item for f in self.findings.values() for item in evidence_items(f)]
        for v in self.verdicts:
            self.evidence.extend(evidence_items(v))
        vocab = set(self.cfg.get("abstentions", {}))
        self.abstentions = sorted({a for a in self.abstentions if not vocab or a in vocab})
        self.verdict.update(
            {
                "label": label,
                "admitted": admitted,
                "leading_role": role,
                "rounds": len(self.verdicts),
            }
        )
        self.classification = {
            "label": label,
            "secondary_labels": [],
            "confidence": conf,
            "rule": rule,
            "evidence": self.evidence,
            "flag_sensor": flag,
            "scale_factor": {},
            "revise_influent_mapping": label == lab["influent"],
            "recommend_structural_review": label == lab["structural"],
            "kinetic_update": label in (lab["parameter"], lab["none"])
            and self.verdict["verdict"] != "abstain",
        }

    # -- the record ----------------------------------------------------------------------
    def build_state(self, completed: bool) -> dict[str, Any]:
        """The shared task state (§6.6) for the agent arm: no model free text in it."""
        ws = self.ws
        b = self.base
        rem = tools.remaining()
        cls = self.classification or {
            "label": ABSTAIN_LABEL,
            "secondary_labels": [],
            "confidence": 0.0,
            "rule": "pending",
            "evidence": [],
            "flag_sensor": None,
            "scale_factor": {},
            "revise_influent_mapping": False,
            "recommend_structural_review": False,
            "kinetic_update": False,
        }
        dq = {
            name: {
                "status": s.status,
                "flags": list(s.flags),
                "missing_fraction": _f(s.missing_fraction),
                "quarantined_windows": [list(w) for w in s.quarantined],
                "in_objective": bool(s.in_objective),
                # templated from the typed status: the role's reason is free text and
                # stays in messages.jsonl (§3.3)
                "notes": f"status {s.status} set by code"
                if ws is None or name not in ws.sensor_reason_lengths
                else f"status {s.status} set by data_quality (reason of "
                f"{ws.sensor_reason_lengths[name]} chars, logged)",
            }
            for name, s in b.series.items()
        }
        balance = {}
        if b.reference is not None:
            balance = {
                k: v for k, v in b.reference["balance"].items() if k != "cod_closure_windows"
            }
        parameters: dict[str, Any] = {}
        method = "none"
        cal = self.findings.get("calibration")
        ident = self.findings.get("identifiability")
        if isinstance(cal, messages.CalFinding) and cls["label"] != ABSTAIN_LABEL:
            for name, est in cal.parameters.items():
                parameters[name] = {
                    "estimate": est.estimate,
                    "lower": est.lower,
                    "upper": est.upper,
                    "method": est.method,
                    "unit": est.unit,
                    "at_bound": bool(
                        name in ws.lower
                        and min(est.estimate - ws.lower[name], ws.upper[name] - est.estimate)
                        <= 0.01 * (ws.upper[name] - ws.lower[name])
                    ),
                }
                if est.method != "none":
                    method = est.method
        return {
            "schema_version": "1.0",
            "workflow": str(self.cfg["workflow"]),
            "workflow_version": str(self.cfg["workflow_version"]),
            "run_id": str(b.manifest["run_id"]),
            "plant": b.plant,
            "tier": b.tier,
            "duration_days": b.T,
            "calibration_window": [b.cal[0], b.cal[1]],
            "holdout_window": [b.holdout[0], b.holdout[1]],
            "candidate_model": MODEL,
            "model_parameters": list(b.model.get("parameters", [])),
            "calibrated_outputs": [s.channel for s in b.series.values() if s.in_objective],
            "data_quality": dq,
            "mass_balance": balance,
            "classification": cls,
            "screening": {
                "declared": list(b.model.get("parameters", [])),
                "approved": list(ident.subset) if ident is not None else [],
                **{
                    k: v
                    for k, v in b.screening.items()
                    if k
                    in ("morris_ranking", "morris_kept", "fisher_dropped", "fisher_relative_crlb")
                },
            },
            "residuals": {
                r["channel"]: {k: v for k, v in r.items() if k not in ("call_index", "channel")}
                for r in b.residuals.values()
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
            "validation": ws.validation if ws is not None else None,
            "assay_checks": list(ws.assay_checks) if ws is not None else [],
            "abstentions": sorted(set(self.abstentions)),
            "final": {
                "label": cls["label"],
                "secondary_labels": cls["secondary_labels"],
                "confidence": cls["confidence"],
                "parameters": parameters,
                "interval_method": method,
                "abstentions": sorted(set(self.abstentions)),
                "completed": bool(completed),
            },
            "plan": {
                "sizes": {
                    **dict(b.plan.sizes),
                    "model_turns": sum(int(r["turns"]) for r in self.role_runs),
                    "tool_uses": sum(int(r["tool_uses"]) for r in self.role_runs),
                    "refused_actions": sum(int(r["refused"]) for r in self.role_runs),
                },
                "fallbacks": list(b.plan.fallbacks) + list(self.codes),
                "guards_tripped": list(b.plan.guards),
                "eval_seconds_assumed": float(self.cfg["p0"]["plan"]["eval_seconds_assumed"]),
                "steps_completed": list(b.plan.completed)
                + [f"{r['role']}.{r['round']}" for r in self.role_runs],
                "steps_skipped": dict(b.plan.skipped),
            },
            "notes_seen": list(b.notes),
            "annotations": [
                f"decider: {self.cfg['decider']}",
                f"arm: agents ({self.cfg['workflow_version']})",
                f"ablation: {json.dumps(self.switch, sort_keys=True)}",
                f"codes: {sorted(set(self.codes))}",
                *([procedural.UNLIMITED_NOTE] if b.unlimited else []),
                *b.annotations,
                *self.annotations,
            ],
        }

    def build_report(self, doc: dict[str, Any]) -> dict[str, Any]:
        """The human-readable report: the label, the null table, the findings and the routing."""
        cls = doc["classification"]
        return {
            "workflow": doc["workflow"],
            "arm": "agents",
            "run_id": doc["run_id"],
            "label": cls["label"],
            "outcome": procedural.outcome(
                self.verdict, bool(doc["final"]["completed"]), cls["label"]
            ),
            "confidence": cls["confidence"],
            "rule": cls["rule"],
            "abstentions": doc["abstentions"],
            "null_table": self.base.table,
            "signatures": json.loads(procedural.to_json(self.base.signatures)),
            "verdict": self.verdict,
            "findings": {r: f.model_dump(mode="json") for r, f in self.findings.items()},
            "verdicts": [v.model_dump(mode="json") for v in self.verdicts],
            "routing": list(self.coordinator.entries),
            "role_runs": list(self.role_runs),
            "by_role": {
                role: {**use, "wall_clock_s": None} if self.base.unlimited else use
                for role, use in self.rec.by_role.items()
            },
            "refusals": self.rec.refusals,
            "completed": doc["final"]["completed"],
        }

    def write(self, *, completed: bool) -> None:
        """Write the task state, the report, the messages and the code steps' decisions."""
        doc = self.build_state(completed)
        tools.run.write_output(STATE_FILE, json.dumps(doc, indent=1, sort_keys=True))
        tools.run.write_output(REPORT_FILE, json.dumps(self.build_report(doc), indent=1))
        tools.run.write_output(MESSAGES_FILE, self.log.lines())
        # the code steps' decision records (every point at its offline fallback) are part
        # of the arm's record too
        tools.run.write_output(
            DECISIONS_FILE,
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.base.decider.records),
        )


def main(cfg: dict[str, Any]) -> int:
    """Run the agent arm on the run the registry serves (the entry dispatches here)."""
    run = AgentRun(cfg)
    try:
        run.run()
    except Exception as exc:
        run.annotations.append(f"stopped: {type(exc).__name__}: {str(exc)[:200]}")
        try:
            run.write(completed=False)
        finally:
            raise
    return 0
