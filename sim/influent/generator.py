"""The stochastic influent generator of proposal §6.1.

"A stochastic batch-delivery process: feed identity per delivery (from a small catalogue
per plant), delivery mass, moisture, and a *true* COD fractionation drawn from a
per-feed distribution. Seasonal drift in composition and temperature. Occasional
unrecorded deliveries and mis-logged masses. The generator emits both the hidden true
fractions and the 'routine' assays an operator would see (TS, VS, total COD, TKN/TAN,
alkalinity, pH), with assay noise and lag."

What is generated, per plant, per day of the horizon, from the plant's frozen feed
catalogue (``configs/plants``: identity and delivery pattern), the provisional
fractionation catalogue (``configs/influent/feed_fractionation.yaml``) and the
generator statistics (``configs/influent/generator.yaml``, schema
:class:`GeneratorConfig`; Plant B/C statistics re-derived from the Muscatine daily file
by ``anchor/ingest_muscatine.py`` and ``tests/test_generator.py``):

1. **True fractionation** of every feed, one Dirichlet draw per feed per run
   (:func:`sim.influent.fractionation.draw_true_fractionations`).
2. **Delivery days**: ``continuous`` (every day), ``weekday`` (the listed weekdays, each
   skipped with ``skip_probability``) or ``markov`` (a two-state chain with the
   stationary zero-day fraction and lag-1 persistence of the anchor data; mean run of
   no-delivery days ``1 / (1 - P(0|0))``).
3. **Delivered amount** on delivery days: ``nonzero_median x seasonal(t) x exp(x_t)``
   with ``x_t`` a stationary AR(1) in the log (marginal sd ``log_sigma``, lag-1
   ``lag1``) and ``seasonal(t) = exp(A cos(2 pi (doy(t) - peak) / 365.25))``.
4. **Moisture**: the delivery's total solids ``ts_catalogue x seasonal(t) x exp(y_t)``,
   another AR(1) in the log (the "wetter season" of the Level-3 scenario is the seasonal
   term); VS/TS is the catalogue's.
5. **Unrecorded deliveries**: on any day, with ``unrecorded_probability_per_d``, an
   extra batch (``nonzero_median x exp(sigma z)``) arrives and never enters the log.
6. **Mis-logged masses**: on a logged delivery, with ``mislog_probability``, the logged
   mass is the true mass times ``exp(mislog_log_sigma z)``.
7. **Routine assays** on the feed's schedule (interval, weekdays only or not): TS, VS,
   total COD, TKN, TAN, alkalinity, pH of that day's delivery, each with its assay's
   noise (relative sd, or absolute for pH) and turnaround lag, reported with unit and
   solids basis (:class:`AssayRecord`). TKN is the per-feed one (the intentional inert-N
   mismatch, :mod:`sim.influent.nitrogen`). Alkalinity is the bicarbonate alkalinity of
   the feed's inorganic carbon at its pH (``50 x S_IC x K_a1 / (K_a1 + 10^-pH)`` kg
   CaCO3/m3, ``pK_a1`` the ADM1 base value), a stated proxy for a total-alkalinity
   titration.
8. The **influent series** for :mod:`sim.adm1`: one sample per day, concentrations the
   flow-weighted mix of that day's true deliveries (true fractionation, true moisture,
   derived COD/VS), ``Q`` the true daily volume, **sample-and-hold** (a day's deliveries
   are fed through that day at a constant rate; the hold treatment is the exact one for
   a piecewise-constant input, decision "Solver defaults and influent handling").
   The truth ``N_I`` is the inert-COD-weighted mean over the horizon's mean true recipe.

**Randomness.** One ``numpy.random.default_rng(seed)`` stream per run (CLAUDE.md rule 4),
consumed in this fixed order: the true-fractionation draw (feeds in sorted id order);
then per feed in sorted id order: ``n`` uniforms for delivery days (always consumed,
whatever the model, so the stream layout is independent of the model), ``n`` normals for
the amount AR(1), ``n`` normals for the moisture AR(1), ``n`` uniforms and ``n`` normals
for unrecorded deliveries, ``n`` uniforms and ``n`` normals for mis-logs; then per feed
in sorted id order, per assay in sorted name order, ``n`` normals of assay noise. A
change to a later stage cannot alter an earlier one (tested).

**Hidden truth and the visible record.** :class:`InfluentTruth` is hidden truth (the run
layer writes it to ``runs/<id>/truth/``; nothing here writes anything); the
:class:`OperatorRecord` (the feed log with its omissions and mis-logs, and the assay
records with noise and lag) is what a workflow may see.

**What is assumed.** Every statistic in ``generator.yaml`` carries a source; the
Plant B/C delivery and assay statistics are the Muscatine daily file's, the Plant A
ones are the Tisocco envelopes where they exist and assumed otherwise; assay noise,
lags, mis-log and unrecorded-delivery rates are assumed for every plant and flagged as
such in the file (decisions log, "Influent generator: stochastic structure").
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim.adm1.schema import LIQUID_STATE_NAMES, ADM1Parameters, Influent
from sim.influent.fractionation import TrueFractionations, draw_true_fractionations
from sim.influent.mapping import KG_PER_TONNE, feed_cod_per_m3, feed_concentrations
from sim.influent.nitrogen import feed_tkn, truth_inert_nitrogen
from sim.influent.schema import CODFractionation, FeedFractionation, FeedFractionationCatalogue
from sim.plants.schema import PlantConfig

__all__ = [
    "ASSAY_NAMES",
    "AmountModel",
    "AssayModel",
    "AssayRecord",
    "AssaySchedule",
    "DeliveryModel",
    "FeedGenerator",
    "FeedTruth",
    "GeneratedInfluent",
    "GeneratorConfig",
    "InfluentTruth",
    "LoggingModel",
    "MoistureModel",
    "OperatorRecord",
    "PlantGenerator",
    "bicarbonate_alkalinity",
    "check_generator_against_plant",
    "generate_influent",
    "seasonal_factor",
]

_Frac = Annotated[float, Field(ge=0.0, le=1.0)]
_Pos = Annotated[float, Field(gt=0.0)]
_NonNeg = Annotated[float, Field(ge=0.0)]

DAYS_PER_YEAR = 365.25
KG_CACO3_PER_KMOL_HCO3 = 50.0
"""Equivalent mass of CaCO3 per kmol of bicarbonate charge, kg/kmol (100.09 / 2)."""

AssayName = Literal["ts", "vs", "cod", "tkn", "tan", "alkalinity", "ph"]
ASSAY_NAMES: tuple[str, ...] = ("ts", "vs", "cod", "tkn", "tan", "alkalinity", "ph")
ASSAY_UNITS: dict[str, tuple[str, str]] = {
    "ts": ("kg TS/kg wet", "wet"),
    "vs": ("kg VS/kg TS", "dry"),
    "cod": ("kg COD/m3", "wet"),
    "tkn": ("kmol N/m3", "wet"),
    "tan": ("kmol N/m3", "wet"),
    "alkalinity": ("kg CaCO3/m3", "wet"),
    "ph": ("pH units", "wet"),
}
"""Unit and solids basis of every assay value (CLAUDE.md rule 6)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- configuration


class AssayModel(_Frozen):
    """Noise and turnaround of one routine assay (shared by all plants)."""

    cv: _NonNeg = Field(description="Relative standard deviation of the assay, -")
    sd_abs: _NonNeg = Field(
        default=0.0, description="Absolute standard deviation in the assay's unit (pH), unit"
    )
    lag_d: Annotated[int, Field(ge=0)] = Field(description="Turnaround: report day - sample day, d")
    source: str = Field(default="", description="Where the numbers come from")


class AssaySchedule(_Frozen):
    """When a feed is sampled and which assays are run on the sample."""

    interval_d: Annotated[int, Field(ge=1)] = Field(description="Days between samples, d")
    weekdays_only: bool = Field(description="Skip Saturday and Sunday (lab not staffed)")
    assays: tuple[AssayName, ...] = Field(description="Assays run on each sample")
    source: str = ""

    @model_validator(mode="after")
    def _unique(self) -> AssaySchedule:
        if len(set(self.assays)) != len(self.assays):
            raise ValueError("assays must be unique")
        return self


class DeliveryModel(_Frozen):
    """Which days a feed arrives."""

    model: Literal["continuous", "weekday", "markov"] = Field(
        description=(
            "'continuous': every day; 'weekday': the listed weekdays, each skipped with "
            "skip_probability; 'markov': two-state chain with the given stationary "
            "zero-day fraction and lag-1 persistence"
        )
    )
    days: tuple[Annotated[int, Field(ge=0, le=6)], ...] = Field(
        default=(), description="Weekdays with a delivery (0 = Monday), weekday model"
    )
    skip_probability: _Frac = Field(
        default=0.0, description="Probability a scheduled weekday delivery is skipped, -"
    )
    zero_fraction: _Frac = Field(
        default=0.0, description="Stationary fraction of no-delivery days, markov model, -"
    )
    persistence: _Frac = Field(
        default=0.0,
        description="Lag-1 autocorrelation of the delivery indicator, markov model, -",
    )
    source: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> DeliveryModel:
        if self.model == "weekday":
            if not self.days or len(set(self.days)) != len(self.days):
                raise ValueError("weekday model needs a non-empty set of distinct days")
        elif self.model == "markov":
            if not 0.0 < self.zero_fraction < 1.0:
                raise ValueError("markov model needs 0 < zero_fraction < 1")
            if self.persistence >= 1.0:
                raise ValueError("markov persistence must be < 1")
        return self

    @property
    def expected_zero_fraction(self) -> float:
        """Long-run fraction of days without a delivery, -."""
        if self.model == "continuous":
            return 0.0
        if self.model == "weekday":
            return 1.0 - len(self.days) / 7.0 * (1.0 - self.skip_probability)
        return self.zero_fraction


class AmountModel(_Frozen):
    """Delivered amount on a delivery day: lognormal AR(1) around a seasonal median."""

    nonzero_median: _Pos = Field(description="Median amount on delivery days, `unit`")
    unit: Literal["m3/d", "t FM/d"] = Field(description="Unit the plant reports this feed in")
    log_sigma: _NonNeg = Field(description="Marginal sd of ln(amount) on delivery days, -")
    lag1: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Lag-1 autocorrelation of ln(amount), -"
    )
    seasonal_amplitude: _NonNeg = Field(
        description="Amplitude A of the seasonal log factor exp(A cos(...)), -"
    )
    seasonal_peak_doy: Annotated[float, Field(ge=0.0, le=366.0)] = Field(
        description="Day of year at which the seasonal factor peaks, d"
    )
    source: str = ""


class MoistureModel(_Frozen):
    """Total solids of a delivery: lognormal AR(1) around the catalogue TS, with a season."""

    ts_log_sigma: _NonNeg = Field(description="Marginal sd of ln(TS) between deliveries, -")
    lag1: Annotated[float, Field(ge=0.0, lt=1.0)] = Field(
        description="Lag-1 autocorrelation of ln(TS), -"
    )
    seasonal_amplitude: _NonNeg = Field(description="Amplitude of the seasonal TS log factor, -")
    seasonal_peak_doy: Annotated[float, Field(ge=0.0, le=366.0)] = Field(
        description="Day of year of the driest deliveries, d"
    )
    source: str = ""


class LoggingModel(_Frozen):
    """How the operator's feed log departs from the truth."""

    unrecorded_probability_per_d: _Frac = Field(
        description="Probability per day of an extra, unlogged delivery, 1/d"
    )
    unrecorded_log_sigma: _NonNeg = Field(
        description="sd of ln(size) of an unrecorded delivery about the nonzero median, -"
    )
    mislog_probability: _Frac = Field(
        description="Probability that a logged delivery's mass is mis-logged, -"
    )
    mislog_log_sigma: _NonNeg = Field(
        description="sd of ln(logged / true) for a mis-logged delivery, -"
    )
    source: str = ""


class FeedGenerator(_Frozen):
    """The generator's statistics for one feed of one plant."""

    delivery: DeliveryModel
    amount: AmountModel
    moisture: MoistureModel
    logging: LoggingModel
    assay_schedule: AssaySchedule


class PlantGenerator(_Frozen):
    """Per-plant generator statistics, keyed by the plant's feed ids."""

    plant_id: Literal["A", "B", "C"]
    feeds: dict[str, FeedGenerator]
    note: str = ""


class GeneratorConfig(_Frozen):
    """``configs/influent/generator.yaml``."""

    version: int
    assays: dict[AssayName, AssayModel] = Field(description="Assay noise and lag, all plants")
    plants: dict[Literal["A", "B", "C"], PlantGenerator]

    @model_validator(mode="after")
    def _complete(self) -> GeneratorConfig:
        missing = set(ASSAY_NAMES) - set(self.assays)
        if missing:
            raise ValueError(f"assay models missing for {sorted(missing)}")
        for pid, gen in self.plants.items():
            if gen.plant_id != pid:
                raise ValueError(f"plants[{pid!r}] declares plant_id {gen.plant_id!r}")
        return self


def check_generator_against_plant(
    gen: PlantGenerator, plant: PlantConfig, catalogue: FeedFractionationCatalogue
) -> None:
    """Raise if the generator statistics contradict the frozen plant contract.

    Same feed set; delivery kind (continuous vs batch) agrees; the expected zero-day
    fraction agrees with the plant's ``zero_days_fraction`` within 0.03; a continuous
    feed's nonzero median equals the plant's median within 3 %; the amount unit is the
    one the plant reports the feed in; every catalogue entry exists.
    """
    if gen.plant_id != plant.id:
        raise ValueError(f"generator is for plant {gen.plant_id!r}, config is {plant.id!r}")
    names = {f.name for f in plant.feeds}
    if set(gen.feeds) != names:
        raise ValueError(f"generator feeds {sorted(gen.feeds)} != plant feeds {sorted(names)}")
    for feed in plant.feeds:
        catalogue.for_stream(feed)
        g = gen.feeds[feed.name]
        continuous = g.delivery.model == "continuous"
        if continuous != (feed.delivery == "continuous"):
            raise ValueError(
                f"{feed.name}: delivery model {g.delivery.model!r} vs {feed.delivery!r}"
            )
        if abs(g.delivery.expected_zero_fraction - feed.zero_days_fraction) > 0.03:
            raise ValueError(
                f"{feed.name}: expected zero-day fraction {g.delivery.expected_zero_fraction:.3f} "
                f"vs plant {feed.zero_days_fraction:.3f}"
            )
        stat = feed.volume_m3_d if feed.volume_m3_d is not None else feed.mass_t_fm_d
        unit = "m3/d" if feed.volume_m3_d is not None else "t FM/d"
        if g.amount.unit != unit:
            raise ValueError(f"{feed.name}: amount unit {g.amount.unit!r}, plant reports {unit!r}")
        if stat is None:
            raise ValueError(f"{feed.name}: plant reports neither volume nor mass")
        if continuous and abs(g.amount.nonzero_median - stat.median) / stat.median > 0.03:
            raise ValueError(
                f"{feed.name}: nonzero median {g.amount.nonzero_median} vs plant median "
                f"{stat.median}"
            )


# ---------------------------------------------------------------------- outputs


class AssayRecord(_Frozen):
    """One routine assay result as the operator receives it (noise and lag applied)."""

    feed_id: str
    assay: AssayName
    sample_day: Annotated[int, Field(ge=0)] = Field(description="Day the sample was taken, d")
    report_day: Annotated[int, Field(ge=0)] = Field(description="Day the result arrived, d")
    value: float = Field(description="Reported value, in `unit`")
    unit: str = Field(description="Unit of `value`")
    basis: Literal["wet", "dry"] = Field(description="Solids basis of `value`")


@dataclass(frozen=True)
class FeedTruth:
    """One feed's true delivery history. Hidden truth."""

    feed_id: str
    delivered_kg: np.ndarray
    """True wet mass fed on each day, kg wet/d, including unrecorded deliveries."""
    ts: np.ndarray
    """True total solids of the day's delivery, kg TS/kg wet (catalogue TS where none)."""
    unrecorded_days: tuple[int, ...]
    """Days on which an unrecorded delivery arrived."""
    mislogged_days: tuple[int, ...]
    """Days on which the logged mass differs from the true mass."""


@dataclass(frozen=True)
class InfluentTruth:
    """The hidden truth of one generated run (the run layer writes it to ``runs/<id>/truth/``)."""

    plant_id: str
    seed: int
    n_days: int
    start_doy: int
    """Day of year of day 0, d (sets the phase of the seasonal terms)."""
    fractionations: TrueFractionations
    N_I: float
    """Truth-model inert nitrogen for this run, kmol N/kg COD (see sim.influent.nitrogen)."""
    feeds: dict[str, FeedTruth]
    influent: Influent
    """Daily sample-and-hold ADM1 influent (true fractionation, moisture and flow)."""
    s_ca: np.ndarray
    """Daily dissolved calcium of the influent, kmol/m3 (precipitation extension)."""
    mean_recipe_kg_d: dict[str, float]
    """Mean true wet mass of each feed over the horizon, kg wet/d."""


@dataclass(frozen=True)
class OperatorRecord:
    """What a workflow may see: the feed log and the assay results."""

    plant_id: str
    n_days: int
    feed_log_kg_wet_d: dict[str, np.ndarray]
    """Logged wet mass per feed per day, kg wet/d (mis-logs applied, unrecorded omitted)."""
    assays: tuple[AssayRecord, ...]
    """Assay records ordered by report day, then feed, then assay name."""


@dataclass(frozen=True)
class GeneratedInfluent:
    """Truth and observation of one run, side by side; the run layer separates them."""

    truth: InfluentTruth
    observed: OperatorRecord


# ------------------------------------------------------------------ primitives


def seasonal_factor(
    day: np.ndarray, start_doy: int, amplitude: float, peak_doy: float
) -> np.ndarray:
    """``exp(A cos(2 pi (doy - peak) / 365.25))`` for each day index (day 0 = ``start_doy``)."""
    doy = start_doy + np.asarray(day, dtype=float)
    return np.exp(amplitude * np.cos(2.0 * math.pi * (doy - peak_doy) / DAYS_PER_YEAR))


def _ar1(z: np.ndarray, sigma: float, phi: float) -> np.ndarray:
    """Stationary AR(1) with marginal sd ``sigma`` and lag-1 ``phi`` from N(0,1) draws."""
    x = np.empty_like(z)
    if z.size == 0:
        return x
    x[0] = sigma * z[0]
    innov = sigma * math.sqrt(1.0 - phi * phi)
    for t in range(1, z.size):
        x[t] = phi * x[t - 1] + innov * z[t]
    return x


def _delivery_days(model: DeliveryModel, u: np.ndarray, start_weekday: int) -> np.ndarray:
    """Boolean delivery indicator per day from ``n`` uniforms (all consumed)."""
    n = u.size
    if model.model == "continuous":
        return np.ones(n, dtype=bool)
    if model.model == "weekday":
        weekday = (start_weekday + np.arange(n)) % 7
        scheduled = np.isin(weekday, model.days)
        return scheduled & (u >= model.skip_probability)
    pi0, rho = model.zero_fraction, model.persistence
    p00 = pi0 + rho * (1.0 - pi0)  # P(no delivery | no delivery yesterday)
    p11 = (1.0 - pi0) + rho * pi0  # P(delivery | delivery yesterday)
    out = np.empty(n, dtype=bool)
    out[0] = u[0] >= pi0  # stationary start
    for t in range(1, n):
        out[t] = (u[t] < p11) if out[t - 1] else (u[t] >= p00)
    return out


def bicarbonate_alkalinity(s_ic: float, ph: float, pK_a1: float) -> float:
    """Bicarbonate alkalinity of a feed, kg CaCO3/m3, from its inorganic carbon and pH."""
    k_a = 10.0**-pK_a1
    return KG_CACO3_PER_KMOL_HCO3 * s_ic * k_a / (k_a + 10.0**-ph)


def _amount_to_kg(amount: float, unit: str, spec: FeedFractionation) -> float:
    return amount * spec.density if unit == "m3/d" else amount * KG_PER_TONNE


# ------------------------------------------------------------------- generator


def generate_influent(
    plant: PlantConfig,
    catalogue: FeedFractionationCatalogue,
    config: GeneratorConfig,
    params: ADM1Parameters,
    seed: int,
    n_days: int,
    start_doy: int = 1,
    start_weekday: int = 0,
) -> GeneratedInfluent:
    """Generate one run's influent truth and operator record for a plant.

    Args:
        plant: The frozen plant configuration (feed identity and delivery pattern).
        catalogue: The feed-fractionation catalogue.
        config: Generator statistics (``configs/influent/generator.yaml``).
        params: ADM1 parameters; only ``N_aa`` (assay TKN) and ``pK_a_co2_base``
            (alkalinity proxy) are read.
        seed: Seed of the run's single ``default_rng`` stream.
        n_days: Horizon, d (one influent sample per day).
        start_doy: Day of year of day 0 (seasonal phase), d.
        start_weekday: Weekday of day 0 (0 = Monday).

    Returns:
        The hidden truth and the visible record.

    Raises:
        ValueError: If the generator statistics contradict the plant contract, or the
            horizon is empty.
    """
    if n_days < 1:
        raise ValueError("n_days must be positive")
    gen = config.plants[plant.id]
    check_generator_against_plant(gen, plant, catalogue)
    rng = np.random.default_rng(seed)
    feed_ids = sorted(f.name for f in plant.feeds)

    # 1. true fractionation (same stream head as sample_true_fractionations)
    truth_frac = draw_true_fractionations(catalogue, feed_ids, rng, seed)

    day = np.arange(n_days)
    feeds_truth: dict[str, FeedTruth] = {}
    logged: dict[str, np.ndarray] = {}
    # 2-6. deliveries, amounts, moisture, unrecorded deliveries, mis-logs
    for fid in feed_ids:
        g = gen.feeds[fid]
        spec = catalogue.feeds[fid]
        u_days = rng.uniform(size=n_days)
        z_amount = rng.standard_normal(n_days)
        z_ts = rng.standard_normal(n_days)
        u_unrec = rng.uniform(size=n_days)
        z_unrec = rng.standard_normal(n_days)
        u_mislog = rng.uniform(size=n_days)
        z_mislog = rng.standard_normal(n_days)

        delivered = _delivery_days(g.delivery, u_days, start_weekday)
        season_amt = seasonal_factor(
            day, start_doy, g.amount.seasonal_amplitude, g.amount.seasonal_peak_doy
        )
        amount = (
            g.amount.nonzero_median
            * season_amt
            * np.exp(_ar1(z_amount, g.amount.log_sigma, g.amount.lag1))
        )
        true_kg = np.where(delivered, _amount_to_kg(1.0, g.amount.unit, spec) * amount, 0.0)
        season_ts = seasonal_factor(
            day, start_doy, g.moisture.seasonal_amplitude, g.moisture.seasonal_peak_doy
        )
        ts = spec.ts * season_ts * np.exp(_ar1(z_ts, g.moisture.ts_log_sigma, g.moisture.lag1))
        ts = np.minimum(ts, 1.0)

        unrecorded = u_unrec < g.logging.unrecorded_probability_per_d
        extra_kg = _amount_to_kg(g.amount.nonzero_median, g.amount.unit, spec) * np.exp(
            g.logging.unrecorded_log_sigma * z_unrec
        )
        log_kg = true_kg.copy()  # the log before mis-logs: recorded deliveries only
        true_kg = true_kg + np.where(unrecorded, extra_kg, 0.0)
        mislogged = (log_kg > 0.0) & (u_mislog < g.logging.mislog_probability)
        log_kg = np.where(mislogged, log_kg * np.exp(g.logging.mislog_log_sigma * z_mislog), log_kg)

        feeds_truth[fid] = FeedTruth(
            feed_id=fid,
            delivered_kg=true_kg,
            ts=ts,
            unrecorded_days=tuple(int(t) for t in np.flatnonzero(unrecorded)),
            mislogged_days=tuple(int(t) for t in np.flatnonzero(mislogged)),
        )
        logged[fid] = log_kg

    # 7. assays
    n_aa = params.stoichiometry.N_aa
    pk_a1 = params.physchem.pK_a_co2_base
    records: list[AssayRecord] = []
    for fid in feed_ids:
        g = gen.feeds[fid]
        spec = catalogue.feeds[fid]
        frac = truth_frac[fid]
        ft = feeds_truth[fid]
        sched = g.assay_schedule
        weekday = (start_weekday + day) % 7
        sampled = (day % sched.interval_d == 0) & (ft.delivered_kg > 0.0)
        if sched.weekdays_only:
            sampled &= weekday < 5
        for assay in sorted(sched.assays):
            z = rng.standard_normal(n_days)
            model = config.assays[assay]
            unit, basis = ASSAY_UNITS[assay]
            for t in np.flatnonzero(sampled):
                true_value = _true_assay(assay, spec, frac, float(ft.ts[t]), n_aa, pk_a1)
                noisy = true_value * (1.0 + model.cv * z[t]) + model.sd_abs * z[t]
                records.append(
                    AssayRecord(
                        feed_id=fid,
                        assay=assay,
                        sample_day=int(t),
                        report_day=int(t) + model.lag_d,
                        value=float(noisy),
                        unit=unit,
                        basis=basis,
                    )
                )
    records.sort(key=lambda r: (r.report_day, r.feed_id, r.assay))

    # 8. the influent series (true deliveries, sample-and-hold per day)
    conc = np.zeros((n_days, len(LIQUID_STATE_NAMES)))
    q = np.zeros(n_days)
    s_ca = np.zeros(n_days)
    for fid in feed_ids:
        spec = catalogue.feeds[fid]
        ft = feeds_truth[fid]
        qk = ft.delivered_kg / spec.density
        for t in np.flatnonzero(qk > 0.0):
            c = feed_concentrations(spec, truth_frac[fid], float(ft.ts[t]))
            conc[t] += qk[t] * c
            s_ca[t] += qk[t] * spec.s_ca
        q += qk
    fed = q > 0.0
    conc[fed] /= q[fed, None]
    s_ca[fed] /= q[fed]
    influent = Influent(t=day.astype(float), concentrations=conc, q=q, interpolation="hold")

    mean_recipe = {fid: float(feeds_truth[fid].delivered_kg.mean()) for fid in feed_ids}
    n_i = truth_inert_nitrogen(catalogue, mean_recipe, truth_frac.fractionations)

    truth = InfluentTruth(
        plant_id=plant.id,
        seed=int(seed),
        n_days=int(n_days),
        start_doy=int(start_doy),
        fractionations=truth_frac,
        N_I=n_i,
        feeds=feeds_truth,
        influent=influent,
        s_ca=s_ca,
        mean_recipe_kg_d=mean_recipe,
    )
    observed = OperatorRecord(
        plant_id=plant.id, n_days=int(n_days), feed_log_kg_wet_d=logged, assays=tuple(records)
    )
    return GeneratedInfluent(truth=truth, observed=observed)


def _true_assay(
    assay: str,
    spec: FeedFractionation,
    frac: CODFractionation,
    ts: float,
    n_aa: float,
    pk_a1: float,
) -> float:
    """The true value of one assay on a delivery with total solids ``ts``."""
    if assay == "ts":
        return ts
    if assay == "vs":
        return spec.vs_of_ts
    if assay == "cod":
        return feed_cod_per_m3(spec, frac, ts)
    if assay == "tkn":
        return feed_tkn(spec, n_aa, frac, ts)
    if assay == "tan":
        return spec.tan
    if assay == "alkalinity":
        return bicarbonate_alkalinity(spec.s_ic, spec.ph, pk_a1)
    if assay == "ph":
        return spec.ph
    raise ValueError(f"unknown assay {assay!r}")
