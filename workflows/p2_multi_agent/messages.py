"""The typed messages of the agent P2 (``docs/p2_agents_design.md`` §3.3).

Staged into the jail with its package (``tools/sandbox.py``, the lead's option A of
2026-10-26) and imported as ``workflows.p2_multi_agent.messages``. Every string a model may
write is constrained to an enumeration or a pattern: no field of a finding or a verdict is
free text, and :func:`free_text_fields` proves it for every model (the static half of S1).
The label vocabulary is a pattern, not an enum, for the reason recorded on 2026-10-19: rule
1's scanner refuses the bare initial-state label as a string in workflow code.

Rule 1: nothing here reads the truth store; the imports are the standard library and
pydantic (a test pins them).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# -- the typed messages (design note §3.3) ------------------------------------------------
# Every string a model may write is constrained to an enumeration or a pattern: no field of
# a finding or a verdict is free text, and `free_text_fields` proves it for every model. The
# label vocabulary is a pattern, not an enum, for the reason CANDIDATE_PATTERN gives.

LABEL_OR_NONE_PATTERN = r"^(sensor|influent|state|parameter|structural|none)$"
NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,31}$"
"""A sensor, parameter, assay or tool name: an identifier (``K_S_pro``, ``pH``), never prose."""
UNIT_PATTERN = r"^(-|%|[A-Za-z0-9]{1,8}(?: [A-Z][A-Za-z0-9]{0,7})?(?:/[A-Za-z0-9]{1,8})?)$"
"""A unit symbol as a model writes it: ``kg COD/m3``, ``m3/d``, ``-``, ``1/d``, ``sigma``.

The registry's unit strings carry a convention note after the symbol (``kg N/m3 (total
ammoniacal nitrogen, S_IN)``, rule 6); :func:`unit_head` is the symbol a model's unit is
compared with (docs/decisions.md, 2026-10-26).
"""
TOKEN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:+/-]{0,31}$"
"""A value a model may put in a named test's arguments: an identifier or a number as text."""
CONFIDENCE_PATTERN = r"^(low|medium|high)$"
STATUS_PATTERN = r"^(ok|quarantined|excluded|flagged)$"
SENSOR_CLAIM_PATTERN = r"^(sensor|none|refute_sensor|no_claim)$"
INFLUENT_CLAIM_PATTERN = r"^(influent|none|refute_influent|no_claim)$"
CAL_CLAIM_PATTERN = (
    r"^(parameter|state|structural|none|refute_parameter|refute_state|refute_structural"
    r"|no_claim)$"
)
ROUND_TWO_ONLY_CLAIMS = frozenset({"structural"})
"""Claims a calibration finding may carry in round 2 only (design note §3.3, F1)."""
MAX_CHANNELS = 22
"""The observation model's channel count: a bound on the channel-keyed collections (a test
pins it to the channel unit table)."""
MAX_PARAMETERS = 20
"""The fitted model's parameter count: a bound on the parameter-keyed collections (a test
pins it to ``describe_model``'s names)."""
MAX_VALUES = 32
"""A bound on the model-named collections (an evidence item's values and units, a named
test's arguments): more than this is not evidence, it is a dump."""

Name = Annotated[str, Field(pattern=NAME_PATTERN)]
LabelOrNone = Annotated[str, Field(pattern=LABEL_OR_NONE_PATTERN)]
Confidence = Annotated[str, Field(pattern=CONFIDENCE_PATTERN)]
Unit = Annotated[str, Field(pattern=UNIT_PATTERN)]
Day = Annotated[float, Field(description="A day of the run, d")]
DayWindow = Annotated[tuple[float, float], Field(description="(start, end) of a window, d")]
Bounds = Annotated[
    tuple[float, float], Field(description="(lower, upper), in the parameter's unit")
]
Rule = Literal[
    "sensor",
    "early_late",
    "biomass_improves",
    "onset",
    "feed_covariate",
    "change_point",
    "change_point_tied",
    "inhibition",
    "r3",
    "holdout_failed",
]
"""The rules a piece of evidence may rest on: the signatures the pipeline's steps write
(``step_qc`` S1 as ``sensor``, ``step_profile``, the hold-out), by their key. A test pins each
name to a key the code writes."""
Token = Annotated[str, Field(pattern=TOKEN_PATTERN)]
ArgScalar = Token | int | float | bool | None
ArgLevel2 = ArgScalar | list[ArgScalar] | dict[Name, ArgScalar]
ArgLevel1 = ArgScalar | list[ArgLevel2] | dict[Name, ArgLevel2]
ArgValue = ArgScalar | list[ArgLevel1] | dict[Name, ArgLevel1]
"""A named test's argument: tokens and numbers, nested at most three levels below ``args``;
no prose at any depth."""


def unit_head(unit: str) -> str:
    """The symbol of a registry unit string: the text before its convention note.

    ``kg N/m3 (total ammoniacal nitrogen, S_IN)`` is ``kg N/m3``; ``m3/d at 0 degC and 1
    atm, water vapour removed`` is ``m3/d``; ``- (multiplier of the BSM2 default 2)`` is
    ``-``. A model writes the symbol (``UNIT_PATTERN``); the harness compares it with the
    registry's through :func:`same_unit`.
    """
    words = unit.strip().split(" ")
    head = words[0]
    if len(words) > 1 and words[1][:1].isupper() and words[1].replace("/", "").isalnum():
        head = f"{head} {words[1]}"
    return head


def same_unit(a: str, b: str) -> bool:
    """Whether two unit strings name the same symbol after :func:`unit_head`."""
    return unit_head(a) == unit_head(b)


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRef(_Msg):
    """One piece of evidence: a label, the rule it rests on, the logged calls and the numbers.

    ``statement`` is not a field: code templates it from these (:func:`statement_for`), so no
    model text reaches ``state.json``. ``units`` carries the symbol of each value's unit
    (rule 6; :func:`unit_head` of the registry's string); a value with no unit is a count or
    a ratio.
    """

    label: LabelOrNone
    rule: Rule
    calls: Annotated[list[int], Field(min_length=1)]
    values: dict[Name, float | int | bool | None] = Field(
        default_factory=dict, max_length=MAX_VALUES
    )
    units: dict[Name, Unit] = Field(default_factory=dict, max_length=MAX_VALUES)

    @model_validator(mode="after")
    def _units_name_values(self) -> EvidenceRef:
        stray = sorted(set(self.units) - set(self.values))
        if stray:
            raise ValueError(f"units for values not given: {stray}")
        if any(i < 0 for i in self.calls):
            raise ValueError("a call index is not negative")
        return self


def statement_for(item: EvidenceRef) -> str:
    """The evidence item's statement, templated by code from its typed fields only."""
    values = ", ".join(
        f"{k}={v}{(' ' + item.units[k]) if k in item.units else ''}"
        for k, v in sorted(item.values.items())
    )
    calls = ", ".join(str(i) for i in item.calls)
    return (
        f"{item.rule}: points to {item.label}"
        + (f" ({values})" if values else "")
        + (f"; calls {calls}")
    )


class SensorFinding(_Msg):
    """Data quality's finding (design note §3.3)."""

    role: Literal["data_quality"] = "data_quality"
    statuses: dict[Name, Annotated[str, Field(pattern=STATUS_PATTERN)]] = Field(
        default_factory=dict, max_length=MAX_CHANNELS
    )
    quarantines: dict[Name, list[DayWindow]] = Field(default_factory=dict, max_length=MAX_CHANNELS)
    claim: Annotated[str, Field(pattern=SENSOR_CLAIM_PATTERN)]
    channel: Name | None = None
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _claim_names_a_channel(self) -> SensorFinding:
        if self.claim == "sensor" and self.channel is None:
            raise ValueError("a sensor claim names its channel")
        for name, windows in self.quarantines.items():
            if any(b < a for a, b in windows):
                raise ValueError(f"{name}: a quarantine window ends before it starts")
        return self


class InfluentFinding(_Msg):
    """The influent role's finding; ``mechanism`` is a report, never a label (§2.3)."""

    role: Literal["influent"] = "influent"
    claim: Annotated[str, Field(pattern=INFLUENT_CLAIM_PATTERN)]
    onset_day: Day | None = Field(default=None, description="The onset day, d")
    feed_id: Name | None = None
    mechanism: Literal["fractionation", "moisture", "unrecorded_delivery", "mislabel", "none"] = (
        "none"
    )
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)


class IdentFinding(_Msg):
    """The identifiable subset here, and whether any kinetic update is allowed."""

    role: Literal["identifiability"] = "identifiability"
    subset: list[Name] = Field(default_factory=list, max_length=MAX_PARAMETERS)
    kinetic_update_allowed: bool
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _update_needs_a_subset(self) -> IdentFinding:
        if self.kinetic_update_allowed and not self.subset:
            raise ValueError("a kinetic update needs an identified subset")
        return self


class ParamEstimate(_Msg):
    """A fitted value with its interval, unit (rule 6) and the method that gave the interval."""

    estimate: float
    lower: float | None = None
    upper: float | None = None
    unit: Unit
    method: Literal["posterior", "profile", "fisher", "none"]

    @model_validator(mode="after")
    def _interval_holds(self) -> ParamEstimate:
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("lower above upper")
        if self.method == "none" and (self.lower is not None or self.upper is not None):
            raise ValueError("an interval needs a method")
        return self


class CalFinding(_Msg):
    """Calibration's finding; ``structural`` in round 2 only (:func:`claim_allowed_in_round`).

    ``bounds_narrowed`` is the only bounds change a run may make (Q10): narrowed, never
    widened, checked against the declared box by the harness; its free-text justification
    lives in ``messages.jsonl`` and is redacted from the verifier's view.
    """

    role: Literal["calibration"] = "calibration"
    claim: Annotated[str, Field(pattern=CAL_CLAIM_PATTERN)]
    parameters: dict[Name, ParamEstimate] = Field(default_factory=dict, max_length=MAX_PARAMETERS)
    bounds_narrowed: dict[Name, Bounds] = Field(default_factory=dict, max_length=MAX_PARAMETERS)
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounds_ordered(self) -> CalFinding:
        for name, (lo, hi) in self.bounds_narrowed.items():
            if lo >= hi:
                raise ValueError(f"{name}: an empty bound")
        return self


class AssayPlan(_Msg):
    """The design role's plan: one assay that separates two named causes.

    ``predicted`` is the assay's value under each cause, in ``unit`` (rule 6): the symbol of
    the assay's registry unit, compared through :func:`same_unit` by the harness.
    """

    role: Literal["design"] = "design"
    assay: Name
    day: Day
    unit: Unit
    separates: tuple[LabelOrNone, LabelOrNone]
    predicted: dict[LabelOrNone, float] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _two_causes(self) -> AssayPlan:
        a, b = self.separates
        if a == b:
            raise ValueError("a plan separates two different causes")
        stray = sorted(set(self.predicted) - {a, b})
        if stray:
            raise ValueError(f"predictions for causes not separated: {stray}")
        return self


class HoldoutResult(_Msg):
    """The verifier's hold-out test, typed: what calibration may cite in round 2 (F1)."""

    failed: bool
    call: Annotated[int, Field(ge=0)]


class SeparatingTest(_Msg):
    """The one test a verifier names per round. ``args`` carries no prose.

    Every string in ``args`` is a token (an identifier or a number as text) by type
    (``ArgValue``); the harness also validates ``args`` against the tool's own schema with
    the redacted free-text fields excluded (design note §3.3).
    """

    tool: Name
    args: dict[Name, ArgValue] = Field(default_factory=dict, max_length=MAX_VALUES)


class Verdict(_Msg):
    """The verifier's answer for one round (design note §4): pass, fail or abstain.

    A fail names its alternative and cites at least one piece of evidence (§4, step 4). The
    D-1 check (the hold-out is the verifier's; calibration cites ``holdout``, typed, in
    round 2 and never the hold-out itself) lives in the harness, not here.
    """

    round: Annotated[int, Field(ge=1, le=2)]
    verdict: Literal["pass", "fail", "abstain"]
    holdout: HoldoutResult | None = None
    alternative: LabelOrNone | None = None
    separating_test: SeparatingTest | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> Verdict:
        if self.verdict == "fail" and self.alternative is None:
            raise ValueError("a fail names the alternative")
        if self.verdict == "fail" and not self.evidence:
            raise ValueError("a fail cites its evidence")
        if self.verdict != "fail" and (self.alternative is not None or self.separating_test):
            raise ValueError("only a fail names an alternative or a test")
        return self


class Grant(_Msg):
    """What the coordinator grants a role for one routing: evaluations and assay units."""

    evaluations: Annotated[int, Field(ge=0)] = 0
    assays: Annotated[int, Field(ge=0)] = 0


class RoutingEntry(_Msg):
    """A coordinator's routing entry: the coordinator (code) is its only writer (N9)."""

    round: Annotated[int, Field(ge=0, le=2)]
    to: Literal[
        "data_quality", "influent", "identifiability", "calibration", "design", "verification"
    ]
    grant: Grant = Field(default_factory=Grant)
    reason: Literal[
        "qc_first",
        "null_failed",
        "null_stands",
        "conflict",
        "verify",
        "separating_test",
        "respond",
        "round_limit",
    ]


FINDINGS: dict[str, type[_Msg]] = {
    "data_quality": SensorFinding,
    "influent": InfluentFinding,
    "identifiability": IdentFinding,
    "calibration": CalFinding,
    "design": AssayPlan,
    "verification": Verdict,
}
"""Each role's one typed message."""

MESSAGE_MODELS: tuple[type[_Msg], ...] = (
    EvidenceRef, SensorFinding, InfluentFinding, IdentFinding, ParamEstimate, CalFinding,
    AssayPlan, HoldoutResult, SeparatingTest, Verdict, Grant, RoutingEntry,
)  # fmt: skip


def claim_allowed_in_round(finding: _Msg, round_: int) -> bool:
    """Whether a finding's claim may be made in ``round_`` (``structural``: round 2 only)."""
    claim = getattr(finding, "claim", None)
    return not (claim in ROUND_TWO_ONLY_CLAIMS and round_ < 2)


def free_text_fields(model: type[BaseModel]) -> list[str]:
    """The fields of ``model`` (and its nested models) a model could write prose into.

    A string with no enumeration or pattern; an untyped node (``Any``: no type, reference,
    alternatives, enumeration or constant); an object open to any value
    (``additionalProperties: true``); an object whose **keys** are unconstrained (a
    ``dict[str, …]``: values typed, keys free, reported as ``[keys]``). The static half of
    the no-free-text guarantee (design note §3.3, S1): a test asserts this is empty for
    every message model, and that a planted plain ``str``, ``Any``, ``list[Any]``,
    ``dict[str, Any]`` and ``dict[str, float]`` are each found.
    """
    found: list[str] = []
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def walk(node: dict[str, Any], where: str) -> None:
        if "$ref" in node:
            walk(defs[node["$ref"].rsplit("/", 1)[1]], where)
            return
        alternatives = [alt for key in ("anyOf", "oneOf", "allOf") for alt in node.get(key, [])]
        for alt in alternatives:
            walk(alt, where)
        if node.get("type") == "string" and not any(
            k in node for k in ("pattern", "enum", "const", "format")
        ):
            found.append(where)
        typed = "type" in node or alternatives or any(k in node for k in ("enum", "const"))
        if not typed:
            found.append(f"{where}[untyped]")
        for name, prop in node.get("properties", {}).items():
            walk(prop, f"{where}.{name}" if where else name)
        for key in ("additionalProperties", "items"):
            if isinstance(node.get(key), dict):
                walk(node[key], f"{where}[{key}]")
            elif node.get(key) is True:
                found.append(f"{where}[{key}]")
        open_keys = node.get("additionalProperties") not in (None, False)  # not extra=forbid
        if open_keys and not any(k in node for k in ("propertyNames", "patternProperties")):
            found.append(f"{where}[keys]")  # values typed, keys free: a dict[str, ...]
        for prop in node.get("patternProperties", {}).values():
            walk(prop, f"{where}[patternProperties]")
        for item in node.get("prefixItems", []):
            walk(item, f"{where}[]")
        if "propertyNames" in node and isinstance(node["propertyNames"], dict):
            walk(node["propertyNames"], f"{where}{{key}}")

    walk(schema, "")
    return sorted(set(found))
