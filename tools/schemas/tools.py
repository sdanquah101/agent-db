"""Input and output models of every tool in the registry (proposal §6.2).

Each tool's numerical ceilings live in ``configs/tools/``; an input field that a workflow
may set (``n_trajectories``, ``n_starts``, ...) is optional here and, when given, must not
exceed the config's ceiling -- the registry checks that. ``seed`` is required on every
stochastic tool (CLAUDE.md rule 4).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from tools.schemas.base import Array, ObservedSeries, ToolInput, ToolOutput, Window

_PosInt = Annotated[int, Field(gt=0)]
_NonNegInt = Annotated[int, Field(ge=0)]
_Frac = Annotated[float, Field(ge=0.0, le=1.0)]


# ------------------------------------------------------------------ the model


class DescribeModelInput(ToolInput):
    """Which registered model to describe."""

    model: str = Field(default="adm1_fitted", description="Registered model name")


class DescribeModelOutput(ToolOutput):
    """A model's interface: parameters, defaults, bounds, outputs and units."""

    model: str
    parameter_names: tuple[str, ...]
    defaults: Array = Field(description="Default parameter vector, in `parameter_units`")
    lower: Array = Field(description="Lower bounds, in `parameter_units`")
    upper: Array = Field(description="Upper bounds, in `parameter_units`")
    parameter_units: dict[str, str] = Field(description="Unit of every parameter (rule 6)")
    output_names: tuple[str, ...]
    output_units: dict[str, str] = Field(description="Unit of every output (rule 6)")
    t: Array = Field(description="Output time grid, d")
    description: str = Field(default="", description="What the model is, in words")


class SimulateInput(ToolInput):
    """One evaluation of a registered model. Costs one simulator evaluation."""

    model: str = Field(default="adm1_fitted")
    parameters: dict[str, float] = Field(
        default_factory=dict,
        description="Parameter overrides by name (missing = default), in parameter units",
    )
    initial_state: dict[str, float] | None = Field(
        default=None,
        description="Initial-state overrides by state name, in state units (fitted ADM1 only)",
    )
    biomass_scale: float | None = Field(
        default=None,
        description="Multiplier applied to every biomass state of the burn-in state, - "
        "(the Level-4 unknown; fitted ADM1 only)",
    )
    t_end: float | None = Field(default=None, description="Stop the record at this day, d")


class SimulateOutput(ToolOutput):
    """A model's outputs on its time grid, with units."""

    model: str
    t: Array = Field(description="Output times, d")
    outputs: dict[str, Array] = Field(description="Output name -> series on t")
    units: dict[str, str]
    success: bool
    message: str = ""
    n_evaluations: int = Field(description="Simulator evaluations this call was charged")


class FeedLoadsInput(ToolInput):
    """Daily COD, N and charge loads of the operator's feed log through the declared catalogue."""

    model: str = Field(default="adm1_fitted")


class FeedLoadsOutput(ToolOutput):
    """What the declared catalogue says the logged feed delivered, per day."""

    t: Array = Field(description="Day, d")
    q_m3_d: Array = Field(description="Total feed flow, m3/d")
    cod_kg_d: Array = Field(description="Total COD load, kg COD/d")
    tkn_kg_n_d: Array = Field(description="Total Kjeldahl N load, kg N/d")
    tan_kg_n_d: Array = Field(description="Ammoniacal N load, kg N/d")
    charge_keq_d: Array = Field(description="Strong-ion difference load (cations - anions), keq/d")
    units: dict[str, str]


# ------------------------------------------------------------------ data_qc


class QCSeries(ToolInput):
    """One series to check."""

    name: str
    t: Array = Field(description="Sample times, d")
    value: Array = Field(description="Values; NaN where missing")
    unit: str = Field(default="", description="Declared unit; empty is a QC finding")


class DataQCInput(ToolInput):
    """Series to check and, optionally, windows of process events for the missingness test."""

    series: tuple[QCSeries, ...] = Field(min_length=1)
    event_windows: tuple[Window, ...] = Field(
        default=(), description="Windows in which the process was under stress, d"
    )
    flatline_min_samples: _PosInt | None = None
    spike_mad_multiplier: float | None = Field(default=None, gt=0.0)


class Segment(ToolOutput):
    """A closed interval of one series, d."""

    start: float
    end: float
    n_samples: int


class SeriesQC(ToolOutput):
    """Findings on one series."""

    name: str
    unit_declared: bool
    timestamps_monotone: bool
    n_samples: int
    n_missing: int
    missing_fraction: _Frac
    longest_gap_d: float = Field(description="Longest run of missing samples, d")
    flatlines: tuple[Segment, ...]
    spikes: Array = Field(description="Times of spike samples, d")
    drift_slope_per_d: float | None = Field(
        description="Robust trend slope, unit/d; None if too few"
    )
    drift_signal_to_noise: float | None
    drift_flag: bool
    event_missing_ratio: float | None = Field(
        description="Missing rate inside event windows over outside; None without events"
    )
    informative_missingness: bool
    flags: tuple[str, ...] = Field(description="Every finding raised, as short codes")


class DataQCOutput(ToolOutput):
    """Rule-based QC verdicts, one per series."""

    results: tuple[SeriesQC, ...]
    flagged: tuple[str, ...] = Field(description="Names of series with at least one finding")


# ------------------------------------------------------------------ mass_balance


class MassBalanceInput(ToolInput):
    """Loads in, gas and effluent out, per window."""

    windows: tuple[Window, ...] = Field(min_length=1)
    t: Array = Field(description="Daily grid of the load series, d")
    q_in_m3_d: Array = Field(description="Feed flow, m3/d")
    cod_in_kg_d: Array = Field(description="COD load in, kg COD/d")
    tkn_in_kg_n_d: Array = Field(description="TKN load in, kg N/d")
    charge_in_keq_d: Array | None = Field(
        default=None, description="Strong-ion difference in, keq/d"
    )
    gas_flow: ObservedSeries | None = Field(
        default=None, description="Biogas, m3/d at 0 degC 1 atm dry"
    )
    ch4_fraction: ObservedSeries | None = Field(
        default=None, description="CH4 mole fraction of dry gas"
    )
    cod_out: ObservedSeries | None = Field(
        default=None, description="Effluent total COD, kg COD/m3"
    )
    tan_out: ObservedSeries | None = Field(default=None, description="Effluent TAN, kg N/m3")
    ph: ObservedSeries | None = Field(default=None, description="Digestate pH")
    alkalinity: ObservedSeries | None = Field(
        default=None, description="Total alkalinity, kg CaCO3/m3"
    )
    vfa: ObservedSeries | None = Field(default=None, description="VFA, kg/m3 as acetic acid")
    V_liq_m3: float = Field(gt=0.0, description="Declared liquid volume, m3")
    T_op_K: float = Field(gt=0.0, description="Operating temperature, K")
    pK_a_ac: float = Field(default=4.76, description="pK_a of acetic acid at T_op, -")
    pK_a_co2: float = Field(default=6.35, description="pK_a of CO2/HCO3- at T_op, -")
    pK_a_IN: float = Field(default=9.25, description="pK_a of NH4+/NH3 at T_op, -")


class WindowBalance(ToolOutput):
    """Closure of one window."""

    window: Window
    n_samples: int
    cod_in_kg: float | None = Field(description="COD fed over the window, kg")
    cod_out_ch4_kg: float | None = Field(description="COD leaving as methane, kg")
    cod_out_effluent_kg: float | None = Field(description="COD leaving in the effluent, kg")
    cod_closure: float | None = Field(description="(in - out) / in, -; None if not evaluable")
    cod_admissible: bool | None
    n_in_kg: float | None
    n_out_tan_kg: float | None
    n_closure: float | None = Field(description="(TKN in - TAN out) / TKN in, -")
    n_admissible: bool | None
    implied_sid_keq_m3: float | None = Field(
        description="Strong-ion difference implied by pH, alkalinity, VFA and TAN, keq/m3"
    )


class MassBalanceOutput(ToolOutput):
    """Closure per window and an overall admissibility verdict."""

    windows: tuple[WindowBalance, ...]
    charge_drift: float | None = Field(
        description="Relative range of the implied SID across windows, -"
    )
    charge_consistent: bool | None
    admissible: bool = Field(description="Every evaluable window closes within its band")
    units: dict[str, str]


# ------------------------------------------------------------------ gsa


class GSAMorrisInput(ToolInput):
    """Morris screening of a model's parameters on scalar summaries of its outputs."""

    model: str = Field(default="adm1_fitted")
    parameters: tuple[str, ...] = Field(min_length=1, description="Parameters to screen")
    outputs: tuple[str, ...] = Field(min_length=1, description="Outputs to summarise")
    summary: Literal["mean", "final", "max", "min"] = Field(default="mean")
    window: Window | None = Field(default=None, description="Summarise over this window only, d")
    n_trajectories: _PosInt | None = Field(default=None, description="At most the config ceiling")
    n_levels: Annotated[int, Field(ge=2)] | None = None
    seed: int = Field(description="Seed of the trajectory draw (rule 4)")


class MorrisIndices(ToolOutput):
    """Elementary-effect statistics of one output."""

    output: str
    mu: Array = Field(
        description="Mean elementary effect per parameter, output unit per unit range"
    )
    mu_star: Array = Field(description="Mean absolute elementary effect")
    sigma: Array = Field(description="Sd of the elementary effects (interaction / nonlinearity)")
    ranking: tuple[str, ...] = Field(description="Parameters by descending mu_star")


class GSAMorrisOutput(ToolOutput):
    """Morris screening results."""

    parameters: tuple[str, ...]
    results: tuple[MorrisIndices, ...]
    n_trajectories: int
    n_evaluations: int
    units: dict[str, str]


class GSASobolInput(ToolInput):
    """Variance-based indices on a (reduced) parameter set, second order included."""

    model: str = Field(default="adm1_fitted")
    parameters: tuple[str, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = Field(min_length=1)
    summary: Literal["mean", "final", "max", "min"] = Field(default="mean")
    window: Window | None = None
    n_samples: _PosInt | None = Field(default=None, description="Base sample N, a power of two")
    second_order: bool | None = None
    seed: int = Field(description="Seed of the scrambled Sobol sequence (rule 4)")

    @model_validator(mode="after")
    def _power_of_two(self) -> GSASobolInput:
        n = self.n_samples
        if n is not None and n & (n - 1):
            raise ValueError("n_samples must be a power of two")
        return self


class SobolIndices(ToolOutput):
    """Sobol indices of one output."""

    output: str
    variance: float = Field(description="Total variance of the summary over the design")
    S1: Array = Field(description="First-order indices, -")
    S1_conf: Array = Field(description="Half-width of the bootstrap confidence interval")
    ST: Array = Field(description="Total-order indices, -")
    ST_conf: Array
    S2: Array | None = Field(description="(k, k) second-order indices, NaN on the diagonal")
    S2_conf: Array | None
    ranking: tuple[str, ...] = Field(description="Parameters by descending ST")


class GSASobolOutput(ToolOutput):
    """Sobol results."""

    parameters: tuple[str, ...]
    results: tuple[SobolIndices, ...]
    n_samples: int
    n_evaluations: int
    units: dict[str, str]


# ------------------------------------------------------------------ identifiability


class ProfileLikelihoodInput(ToolInput):
    """Multi-start profile of one parameter against data."""

    model: str = Field(default="adm1_fitted")
    data: tuple[ObservedSeries, ...] = Field(min_length=1)
    parameters: tuple[str, ...] = Field(min_length=1, description="Free parameters of the fit")
    profile: str = Field(description="The parameter to profile (one of `parameters`)")
    center: dict[str, float] = Field(
        default_factory=dict, description="Best-fit values to start from (missing = default)"
    )
    grid: Array | None = Field(
        default=None, description="Profile values; default: n_grid over the bounds"
    )
    n_grid: Annotated[int, Field(ge=3)] | None = None
    n_starts: _PosInt | None = None
    seed: int = Field(description="Seed of the multistart draw (rule 4)")

    @model_validator(mode="after")
    def _profile_in_set(self) -> ProfileLikelihoodInput:
        if self.profile not in self.parameters:
            raise ValueError(f"profile parameter {self.profile!r} is not among {self.parameters}")
        return self


class ProfileLikelihoodOutput(ToolOutput):
    """The profile, its confidence interval and the identifiability verdict."""

    parameter: str
    grid: Array = Field(description="Profiled values, parameter unit")
    chi2: Array = Field(description="Minimised weighted SSR at each grid value, -")
    chi2_min: float
    threshold: float = Field(description="chi2_min + the chi-square quantile (1 dof)")
    interval: tuple[float | None, float | None] = Field(
        description="Confidence interval on the grid; None where it runs to the bound"
    )
    identifiable: bool = Field(description="Interval closed on both sides inside the bounds")
    flat: bool = Field(description="Profile rise below flat_fraction x threshold: non-identifiable")
    best_fit_per_point: Array = Field(description="(n_grid, k) optimum of the free parameters")
    n_evaluations: int


class FisherInfoInput(ToolInput):
    """FIM at a point from finite-difference sensitivities against the data's weights."""

    model: str = Field(default="adm1_fitted")
    data: tuple[ObservedSeries, ...] = Field(min_length=1)
    parameters: tuple[str, ...] = Field(min_length=1)
    at: dict[str, float] = Field(default_factory=dict, description="Point of linearisation")


class FisherInfoOutput(ToolOutput):
    """FIM conditioning, correlations and the null directions."""

    parameters: tuple[str, ...]
    fim: Array = Field(description="(k, k) Fisher information, 1/unit^2")
    eigenvalues: Array = Field(description="Descending")
    eigenvectors: Array = Field(description="(k, k), columns")
    condition_number: float
    rank: int
    null_directions: Array = Field(description="(n_null, k) unit vectors the data do not inform")
    correlation: Array = Field(description="(k, k) parameter correlation from the pseudo-inverse")
    crlb_sd: Array = Field(description="Cramer-Rao lower bound on each sd; inf on a null direction")
    ill_conditioned: bool
    n_evaluations: int


# ------------------------------------------------------------------ fitters


class _FitInput(ToolInput):
    model: str = Field(default="adm1_fitted")
    data: tuple[ObservedSeries, ...] = Field(min_length=1)
    parameters: tuple[str, ...] = Field(min_length=1, description="Parameters to fit")
    bounds: dict[str, tuple[float, float]] = Field(
        default_factory=dict, description="Tighter bounds than the model's, by name"
    )
    start: dict[str, float] = Field(
        default_factory=dict, description="Starting point (missing = default)"
    )
    seed: int = Field(description="Seed of the starts / population (rule 4)")


class FitLSQInput(_FitInput):
    """Constrained multistart least squares."""

    n_starts: _PosInt | None = None
    max_nfev_per_start: _PosInt | None = None


class FitDEInput(_FitInput):
    """Differential evolution with fixed seed, population and budget."""

    popsize: _PosInt | None = None
    max_generations: _PosInt | None = None


class FitCMAESInput(_FitInput):
    """CMA-ES with fixed seed and budget."""

    max_evaluations: _PosInt | None = None


class FitOutput(ToolOutput):
    """A fit: the optimum, its cost, and the covariance where a Jacobian exists."""

    method: str
    parameters: tuple[str, ...]
    theta: Array = Field(description="Best parameters, parameter units")
    lower: Array
    upper: Array
    chi2: float = Field(description="Weighted SSR at the optimum, -")
    n_data: int
    covariance: Array | None = Field(description="(k, k) sigma^2 (J^T J)^-1, None when unavailable")
    sd: Array | None = Field(description="Sqrt of the covariance diagonal")
    at_bound: tuple[str, ...] = Field(description="Parameters within 1 % of a bound")
    starts_chi2: Array = Field(description="Cost of every start / generation best")
    converged: bool
    message: str
    n_evaluations: int


# ------------------------------------------------------------------ mcmc


class BayesMCMCInput(ToolInput):
    """Reduced-parameter MCMC with a configurable likelihood."""

    model: str = Field(default="adm1_fitted")
    data: tuple[ObservedSeries, ...] = Field(min_length=1)
    parameters: tuple[str, ...] = Field(min_length=1)
    bounds: dict[str, tuple[float, float]] = Field(default_factory=dict)
    start: dict[str, float] = Field(default_factory=dict, description="Centre of the initial ball")
    likelihood: Literal["gaussian", "ar1", "heteroscedastic"] = Field(default="gaussian")
    ar1_rho: float | None = Field(default=None, ge=-1.0, le=1.0)
    heteroscedastic_cv: float | None = Field(default=None, ge=0.0)
    n_walkers: Annotated[int, Field(ge=4)] | None = None
    n_steps: Annotated[int, Field(ge=2)] | None = None
    seed: int = Field(description="Seed of the sampler (rule 4)")

    @model_validator(mode="after")
    def _even_walkers(self) -> BayesMCMCInput:
        if self.n_walkers is not None and self.n_walkers % 2:
            raise ValueError("n_walkers must be even")
        return self


class BayesMCMCOutput(ToolOutput):
    """Posterior summary and convergence diagnostics. Not a posterior unless `converged`."""

    parameters: tuple[str, ...]
    mean: Array
    sd: Array
    quantiles: dict[str, Array] = Field(
        description="'q05','q25','q50','q75','q95' -> per parameter"
    )
    rhat: Array = Field(description="Split Gelman-Rubin R-hat per parameter")
    ess: Array = Field(description="Effective sample size per parameter")
    acceptance_fraction: float
    converged: bool = Field(description="All R-hat below threshold and all ESS above the floor")
    samples: Array = Field(
        description="(n, k) thinned posterior draws (unreliable if not converged)"
    )
    log_prob_max: float
    n_walkers: int
    n_steps: int
    n_evaluations: int
    warning: str = Field(default="")


# ------------------------------------------------------------------ filters


class FilterEnKFInput(ToolInput):
    """Ensemble Kalman filtering on a registered state-space model."""

    model: str = Field(description="Registered state-space model")
    observations: Array = Field(description="(n_steps, n_obs) observations; NaN where missing")
    observation_sd: Array = Field(description="(n_obs,) observation sd")
    process_sd: Array = Field(description="(n_state,) process noise sd added per step")
    initial_mean: Array = Field(description="(n_state,)")
    initial_sd: Array = Field(description="(n_state,)")
    parameters: tuple[str, ...] = Field(default=(), description="Slow parameters to augment")
    parameter_lower: Array | None = None
    parameter_upper: Array | None = None
    n_ensemble: Annotated[int, Field(ge=2)] | None = None
    seed: int = Field(description="Seed of the ensemble (rule 4)")


class FilterEnKFOutput(ToolOutput):
    """Analysis mean and sd per step."""

    t: Array = Field(description="Step index or time, model units")
    mean: Array = Field(description="(n_steps, n_state)")
    sd: Array = Field(description="(n_steps, n_state)")
    parameter_mean: Array | None = Field(description="(n_steps, n_params)")
    parameter_sd: Array | None
    n_evaluations: int


class FilterMHEInput(ToolInput):
    """Moving-horizon estimation on a registered state-space model."""

    model: str
    observations: Array
    observation_sd: Array
    process_sd: Array
    initial_mean: Array
    initial_sd: Array
    parameters: tuple[str, ...] = ()
    parameter_lower: Array | None = None
    parameter_upper: Array | None = None
    horizon_steps: _PosInt | None = None
    state_lower: Array | None = None
    state_upper: Array | None = None


class FilterMHEOutput(ToolOutput):
    """Estimated state per step and the window parameters."""

    t: Array
    mean: Array = Field(description="(n_steps, n_state)")
    parameter_estimate: Array | None = Field(description="(n_steps, n_params) per window")
    chi2: Array = Field(description="Window cost per step")
    n_evaluations: int


# ------------------------------------------------------------------ residual_diag


class Covariate(ToolInput):
    """A covariate to group residuals by."""

    name: str
    t: Array = Field(description="Times of the covariate samples, d")
    value: Array = Field(description="Numeric covariate values")
    categorical: bool = Field(default=False, description="Group by exact value instead of bins")


class ResidualDiagInput(ToolInput):
    """Residuals with the covariates that might explain their structure."""

    t: Array = Field(description="Residual times, d")
    residual: Array = Field(description="Observed minus predicted, output unit")
    covariates: tuple[Covariate, ...] = Field(default=())
    n_bins: Annotated[int, Field(ge=2)] | None = None


class CovariateStructure(ToolOutput):
    """Residual structure along one covariate."""

    name: str
    bin_edges: Array | None
    bin_labels: tuple[str, ...]
    bin_mean: Array
    bin_se: Array
    bin_n: Array
    eta_squared: float = Field(description="Between-bin share of the residual variance, -")
    p_value: float = Field(description="One-way ANOVA p-value")
    structured: bool


class ResidualDiagOutput(ToolOutput):
    """Where the residual is structured."""

    n: int
    mean: float
    sd: float
    lag1_autocorrelation: float
    durbin_watson: float
    runs_p_value: float
    trend_slope_per_d: float
    trend_p_value: float
    serially_structured: bool
    covariates: tuple[CovariateStructure, ...]
    most_explanatory: str | None = Field(
        description="Covariate with the largest eta^2 that is structured"
    )


# ------------------------------------------------------------------ voi


class VOIAssayInput(ToolInput):
    """Expected information gain of each requestable assay on a day, from posterior samples."""

    model: str = Field(default="adm1_fitted")
    samples: Array = Field(description="(n, k) posterior draws")
    parameters: tuple[str, ...] = Field(min_length=1)
    day: float = Field(ge=0.0, description="Sample day of the assay, d")
    assays: tuple[str, ...] = Field(
        default=(), description="Subset of the catalogue (default: all)"
    )
    n_outer: _PosInt | None = None
    n_inner: _PosInt | None = None
    seed: int = Field(description="Seed of the Monte Carlo draws (rule 4)")


class AssayVOI(ToolOutput):
    """EIG of one assay."""

    assay: str
    channel: str
    unit_cost: int
    eig_nats: float = Field(description="Expected information gain on the parameters, nats")
    eig_per_unit: float
    predictive_sd: float = Field(description="Sd of the predicted assay over the posterior")
    noise_sd: float = Field(description="Assay noise sd at the predictive mean")


class VOIAssayOutput(ToolOutput):
    """EIG per assay, ranked."""

    day: float
    results: tuple[AssayVOI, ...]
    ranking: tuple[str, ...] = Field(description="Assays by descending EIG per unit cost")
    n_evaluations: int


# ------------------------------------------------------------------ validate


class ValidateInput(ToolInput):
    """Hold-out forecast metrics of predictions (point or ensemble) against observations."""

    observed: tuple[ObservedSeries, ...] = Field(min_length=1)
    t: Array = Field(description="Prediction times, d")
    predicted: dict[str, Array] = Field(
        description="Output -> (n_t,) point prediction or (n_samples, n_t) predictive ensemble"
    )
    holdout: Window | None = Field(default=None, description="Score only inside this window")


class OutputMetrics(ToolOutput):
    """Metrics of one output."""

    output: str
    n: int
    mae: float
    rmse: float
    nrmse: float = Field(description="RMSE over the observed sd, -")
    bias: float = Field(description="Mean of predicted minus observed")
    coverage: dict[str, float | None] = Field(description="'50','90' -> empirical coverage")
    interval_score: dict[str, float | None]
    crps: float | None
    constraint_violations: int = Field(description="Predicted points outside the admissible range")


class ValidateOutput(ToolOutput):
    """Validation of a forecast."""

    results: tuple[OutputMetrics, ...]
    n_total: int
    ensemble: bool


# ------------------------------------------------------------------ assays / budget


class RequestAssayInput(ToolInput):
    """Request a laboratory assay on a day, at its declared cost and turnaround."""

    assay: str = Field(description="Assay name from configs/tools/assays.yaml")
    day: float = Field(ge=0.0, description="Sample day, d")


class AssayResult(ToolOutput):
    """One reported value."""

    channel: str
    value: float
    unit: str
    sd: float = Field(description="Declared sd of the assay at this value")


class RequestAssayOutput(ToolOutput):
    """The assay result, reported on `report_day`."""

    assay: str
    sample_day: float
    report_day: float
    results: tuple[AssayResult, ...]
    unit_cost: int


class RemainingBudget(ToolOutput):
    """What is left of the cell's envelope (§6.6)."""

    simulator_evals: int = Field(description="Evaluations left, count")
    simulator_evals_total: int
    wall_clock_min: float = Field(description="Minutes left")
    wall_clock_min_total: float
    assay_units: int
    assay_units_total: int
    n_calls: int = Field(description="Calls logged by the registry so far")


TOOL_INPUTS: dict[str, type[ToolInput]] = {
    "describe_model": DescribeModelInput,
    "simulate": SimulateInput,
    "feed_loads": FeedLoadsInput,
    "data_qc": DataQCInput,
    "mass_balance": MassBalanceInput,
    "gsa_morris": GSAMorrisInput,
    "gsa_sobol": GSASobolInput,
    "profile_likelihood": ProfileLikelihoodInput,
    "fisher_info": FisherInfoInput,
    "fit_lsq": FitLSQInput,
    "fit_de": FitDEInput,
    "fit_cmaes": FitCMAESInput,
    "bayes_mcmc": BayesMCMCInput,
    "filter_enkf": FilterEnKFInput,
    "filter_mhe": FilterMHEInput,
    "residual_diag": ResidualDiagInput,
    "voi_assay": VOIAssayInput,
    "validate": ValidateInput,
    "request_assay": RequestAssayInput,
}

TOOL_OUTPUTS: dict[str, type[ToolOutput]] = {
    "describe_model": DescribeModelOutput,
    "simulate": SimulateOutput,
    "feed_loads": FeedLoadsOutput,
    "data_qc": DataQCOutput,
    "mass_balance": MassBalanceOutput,
    "gsa_morris": GSAMorrisOutput,
    "gsa_sobol": GSASobolOutput,
    "profile_likelihood": ProfileLikelihoodOutput,
    "fisher_info": FisherInfoOutput,
    "fit_lsq": FitOutput,
    "fit_de": FitOutput,
    "fit_cmaes": FitOutput,
    "bayes_mcmc": BayesMCMCOutput,
    "filter_enkf": FilterEnKFOutput,
    "filter_mhe": FilterMHEOutput,
    "residual_diag": ResidualDiagOutput,
    "voi_assay": VOIAssayOutput,
    "validate": ValidateOutput,
    "request_assay": RequestAssayOutput,
}
