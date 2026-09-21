# P0 — the scripted pipeline (milestone 5, proposal §6.5)

Status: **proposed 2026-09-21** by the P0 session; the coordinator takes the rules below to
the lead for sign-off (CLAUDE.md rule 5 makes P0 the baseline of the whole benchmark, so
the lead decides its rules). Every threshold, size and seed is a key of
`configs/workflows/p0.yaml`, named here in `code`; the pipeline reads that file and nothing
else for its settings, so a ruling changes a value, never the code.

## 1. What P0 is

A predeclared sequence with fixed rules and no conditional branching beyond the thresholds
declared here: what a competent engineer would script today, run inside the jail
(`tools.sandbox.launch`) against the registry of a run (`tools.open_registry`). It sees
the tier's observation record, the operator's feed log and assays, the operator's notes,
the redacted manifest and the tools; nothing else. Its outputs are the shared task state
(§6.6, `state/task_state.py`) and a report, written through the registry into
`runs/<id>/workflows/p0/`.

### 1.1 What P0 is told beyond the record

The runner (`tools/runner.py`, privileged) writes P0's configuration into the sandbox as
`p0_config.json` before launch: the contents of `configs/workflows/p0.yaml`, plus the
**declared instrument noise and drift** of every sensor (`cv`, `sd_abs`, the drift random
walk's scale and bound, from `configs/observation/sensors.yaml`: the visible sensor
contract of §6.1, "every sensor has a declared model") and the **declared geometry** of
every plant (the liquid volume and the set point, from `configs/plants/`, the qualitative
plant contract the card §4.1 lists as visible). Nothing derived from the run's truth, its
scenario or its seeds enters; the same document goes into every cell's sandbox (tested).
**Flagged for the lead** (§6, point 1): the declared noise is what P0 weights residuals
with; the alternative is estimating it from the data.

The label vocabulary is also read from the configuration (`labels`), because the rule-1
checker forbids the bare token of a forbidden module name in workflow code and one class
shares its name with the `state` package.

## 2. The fixed sequence, and what each step feeds the next

Costs are simulator evaluations; wall-clock is what binds in practice: a 200-day
evaluation of `adm1_fitted` on a generated cell costs 11–12 s on Plants B and C at this
head (the operator's daily feed log caps the integrator step at one day; 2.5–4.4 s on a
constant log, 2.1 s at 30 days; one constant-log vector in 27 took 290 s: a stiffness
pocket, §7).

| # | Step | Tool(s) | Feeds forward |
|---|---|---|---|
| 0 | Read the record; one evaluation at the defaults | `describe_model`, `feed_loads`, `simulate` | the model's interface; the declared daily loads; the baseline prediction; the measured evaluation time (recorded, not used for sizing — §4) |
| 1 | Data QC on every sensor | `data_qc` | per-sensor flags → the exclusion rules (§3.1) → the calibration data set |
| 2 | Mass balance over fixed windows | `mass_balance` | COD / N closure and charge consistency per window → attribution evidence |
| 3 | Morris screening of the declared parameter set | `gsa_morris` | ranking by normalised μ* → the Morris subset |
| 4 | Sobol on the Morris subset, second order included | `gsa_sobol` | total-order indices → the Sobol subset; interaction evidence |
| 5 | Identifiability on the Sobol subset | `fisher_info` (profiles when the plan allows, §4) | CRLB per parameter, null directions → the **approved subset** |
| 6 | Screened fit | `fit_lsq` (multistart), then `fit_de` | the optimum (the lower χ²), its Jacobian covariance → the point prediction (one `simulate`) |
| 7 | Posterior on the approved subset | `bayes_mcmc` | intervals when `converged`; otherwise the failure is recorded and the Fisher intervals stand (§3.5) |
| 8 | Residual diagnostics per calibrated output | `residual_diag` | structure by feed batch, load, temperature, time → attribution evidence; the second pass (§3.4) |
| 9 | Requested assays | `request_assay` | the declared spend (§3.6) → independent checks in the report |
| 10 | Validation on the frozen hold-out window | `validate` | forecast metrics; coverage from the predictive ensemble |
| 11 | Attribution and abstention | — | the final label (§3.7), the abstentions (§3.8), the state and the report |

The windows: the record `[0, T]` is split at `windows.holdout_fraction` (0.25) of `T`: the
**calibration window** is `[windows.calibration_start_d, T (1 − holdout_fraction))`, the
**hold-out window** the rest; nothing in the hold-out is used before step 10. Mass-balance
windows are consecutive blocks of `mass_balance.window_d` (30 d) over the record.

## 3. The rules

### 3.1 Data quality and exclusion (`qc.*`)

`data_qc` runs on every sensor of the tier with the declared ceilings (`flatline_min_samples`,
`spike_mad_multiplier` of `configs/tools/data_qc.yaml`, not loosened) and event windows
= the days whose declared COD load exceeds its `qc.event_load_quantile` (0.90) quantile.
Then, per sensor, in this order:

1. `flatline` → every flatlined segment is **quarantined** (its samples become missing);
   a segment of at least `qc.flatline_flag_d` (3 d) **flags** the sensor (`sensor`
   evidence) and adds the abstention `<sensor>_claims` over that window.
2. `spikes` → the spike samples are dropped, the sensor is not flagged.
3. `drift` → if the excursion `|slope| × span` exceeds `qc.drift_bound_factor` (1.0) × the
   instrument's **declared** drift bound, the sensor is **flagged and excluded** from the
   calibration objective (it stays in the record for the cross-channel checks); a drift
   inside the declared bound is the instrument being itself and is recorded, not
   excluded. A sensor that declares no drift is flagged on any drift finding. (A clean
   30-day cell flagged its pH probe's own declared random walk before this rule.)
4. `informative_missingness` → recorded; the abstention `missing_transient` is added and
   the `state` evidence counter incremented (§3.7).
5. A sensor with fewer than `qc.min_samples` (8) observed samples inside the calibration
   window is excluded from the objective (not flagged).

The calibration objective uses the sensors of `calibration.channels` that the tier carries
and the rules above did not exclude; `temperature` is never in it (no calibratable
parameter moves it). The weight of a sample is `sd = sqrt((cv · |v|)² + sd_abs²)` from the
declared noise, floored at `calibration.min_relative_sd` (0.02) × the series' median
absolute value.

### 3.2 Screening (`screening.*`)

Morris on all parameters of the model's interface, `gsa.morris_trajectories` (8),
outputs = the mean over the calibration window of every calibrated channel, seed
`seeds.morris`. A parameter is kept if its μ* normalised by the largest μ* of that output
exceeds `screening.morris_min_relative` (0.10) on any output; the kept set is capped at
`screening.morris_keep` (4) by the maximum normalised μ*. Sobol on the kept set with
`gsa.sobol_samples` (32; a power of two), second order on, seed `seeds.sobol`: a
parameter stays if its total-order index exceeds `screening.sobol_min_total` (0.05) on any
output; at least `screening.min_subset` (2) stay, by descending ST. The second-order table
is reported as interaction evidence and does not change the subset.

### 3.3 Identifiability (`identifiability.*`)

`fisher_info` on the Sobol subset at the defaults against the calibration data. A
parameter whose CRLB standard deviation exceeds `identifiability.max_relative_crlb` (0.5)
× its bound width, or that lies on a null direction, is dropped as practically
non-identifiable from these data; at least `screening.min_subset` stay. The survivors are
the **approved subset**. After the fit, the Fisher intervals of §3.5 come from the fit's
own Jacobian covariance at the optimum (`sigma² (JᵀJ)⁻¹` with `sigma² = chi² / (n − k)`:
the Fisher information at the optimum scaled by the residual variance, which the fitter
already computes, so no evaluation is spent twice), clipped to the parameter's bounds;
`profile_likelihood` (grid `identifiability.profile_grid` (5), one start) is run on the
approved parameters in order of worst conditioning while the plan allows it (§4), and a
closed profile interval replaces the Fisher one.

### 3.4 The fit (`fit.*`) and the second pass

`fit_lsq` from the defaults with `fit.lsq_starts` (3) starts and
`fit.lsq_max_nfev_per_start` (40), seed `seeds.lsq`; then `fit_de` with `fit.de_popsize`
(4) and `fit.de_generations` (8), seed `seeds.de`. The optimum is the lower χ². One
`simulate` at the optimum gives the point prediction over the whole record.

**Second pass.** If the sensor rule (§3.7, R1b) fires on the post-fit residuals, the
offending channel is excluded from the objective and the fit is repeated from the first
optimum with the same sizes, once (`fit.second_pass: true`). Its result replaces the first
where the plan allows the cost; otherwise the first stands and the state says the
parameters are provisional.

### 3.5 Uncertainty and the Level-8 fallback (`mcmc.*`)

`bayes_mcmc` on the approved subset, Gaussian likelihood, `mcmc.walkers` (8, or 2k if
larger) walkers and `mcmc.steps` (30) steps, seed `seeds.mcmc`, from the optimum. If
`converged` is true the reported intervals are the posterior 5–95 % quantiles. If it is
false — a genuine non-convergence or the Level-8 injected failure, which P0 cannot and
must not tell apart — **the posterior is not reported**: the event is recorded under
`tool_failures`, the abstention `posterior_intervals` is added, and the intervals are the
Fisher intervals at the optimum (`estimate ± z · CRLB sd`, `uncertainty.z` 1.645), the
profile interval where one was computed. P0 never retries the sampler.

### 3.6 Assays (`assays.*`)

Spent once, after the fit, at the day of the largest absolute standardised residual of
the primary channel (`calibration.primary_channel`, gas flow) inside the calibration
window: `vfa_speciation` (2 units) if at least 2 units remain, else `alkalinity` (1), then
`tan` while units remain and `assays.max_requests` (2) is not reached. Each result is
compared with the point prediction at its sample day; a disagreement beyond
`assays.disagreement_z` (3) standard deviations counts as `structural` evidence when the
calibrated channels of the same quantity agree with the model, and as nothing otherwise.
The values are reported; they do not enter the objective.

### 3.7 Attribution (`attribution.*`)

Evidence is collected as named items and the rules are tried in a fixed order; the first
that fires sets the label, the others that fire are listed as `secondary_labels` (a
compound row therefore reports one primary label and the evaluator scores both). The rule
is a pure function of the collected evidence (`workflows/p0_scripted/pipeline.py::classify`),
tested on constructed evidence. In order:

- **R1 sensor.** (a) A sensor flagged by §3.1 (drift beyond its declared bound, a long
  flatline). (b) Exactly one calibrated channel whose post-fit residual is biased beyond
  `attribution.sensor_bias_z` (3.0) in standardised units, or shows a step in time (the
  means before and after the best split differ by more than `attribution.sensor_step_z`
  (3.0) standard errors), while every other calibrated channel is within
  `attribution.clean_bias_z` (1.5) and not serially structured, and the COD balance is
  admissible. (c) `charge_consistent` is false and the pH residual is serially structured.
  For `gas_flow` the scale factor is estimated as the median of observed / predicted after
  the step (`estimate_scale_factor`). The second pass of §3.4 follows R1b.
- **R2 influent.** The COD closure is inadmissible in at least
  `attribution.balance_windows_min` (2) windows, or the primary channel's residual is
  explained most by a feed covariate (the dominant feed of the day, or a feed's mass
  fraction) with η² of at least `attribution.feed_eta2_min` (0.15). The action is
  `revise_influent_mapping`; kinetics are not moved.
- **R5 state.** The primary residual is biased beyond `attribution.state_bias_z` (3.0)
  in the first `attribution.transient_d` (30 d) of the record and within `clean_bias_z`
  after it, or informative missingness was found (§3.1). Parameters are reported
  unchanged.
- **R4 parameter.** A common change point: at least `attribution.parameter_channels_min`
  (2) calibrated channels show a step beyond `attribution.parameter_step_z` (3.0) whose
  split days lie within `attribution.step_day_tolerance_d` (20 d) of each other, the COD
  balance is admissible and no feed covariate explains the primary residual. The bounded
  update of the approved subset is offered (`kinetic_update`).
- **R3 structural.** No common change point, and at least
  `attribution.structural_channels_min` (2) calibrated channels stay structured after the
  fit: RMS standardised residual at least `attribution.structural_rmse_z_min` (2.0),
  serially structured, and explained most by load or time (or a fitted parameter sits at
  a bound). `recommend_structural_review` is set and the parameter values are abstained
  on (§3.8).
- **R6 none.** Otherwise: the calibration stands, with its intervals.

R4 is tried before R3 so that a regime change (Level 5: a step in time that a constant
parameter cannot fit) is not read as persistent structure; R5 before both so that the
initial transient of a mis-initialised state (Level 4) is not read as a change point.
Moving parameters is not by itself evidence of a fault: a Level-0 calibration moves them
too. Confidence is `attribution.confidence.single` (0.8) when the rules that fired agree on
one label, `attribution.confidence.multiple` (0.5) when they do not,
`attribution.confidence.none` (0.6) for R6.

**What P0 never does:** move a kinetic parameter because a note says so (notes are data:
their days and authors are recorded, their text is not interpreted); report a posterior
that did not converge; fit through a flagged sensor; read the hold-out before step 10.

### 3.8 Abstentions

`posterior_intervals` (§3.5); `<sensor>_claims` for a quarantined channel (§3.1);
`missing_transient` (§3.1); `parameter_values` and `<channel>_budget` for the structured
channels under R3 (`alkalinity_budget` when alkalinity is one of them,
`inorganic_carbon_balance` with it); `kinetic_attribution` under R1–R3 (the parameters are
reported as screened, not as an update). The list is in the state and the report.

## 4. The plan and the budget fallbacks (`plan.*`)

P0 reads `tools.remaining()` before every expensive step. The plan is **deterministic**:
sizes are the declared ones scaled to the cell's declared envelope with a declared cost
per evaluation, `plan.eval_seconds_assumed` (12 s, set from the measurement above before
the pilot), never the one measured during the run — so the same
cell gives the same plan on every machine at least that fast. For each expensive step the
projected cost is its declared bound (the registry's own cost rule) × `eval_seconds_assumed`;
if it exceeds `plan.step_share` (0.35) of the wall-clock left, or its bound exceeds the
evaluations left, the step takes the declared fallback in order, and the state records
which:

| Step | Fallback ladder |
|---|---|
| Morris | halve `morris_trajectories` down to `plan.morris_min_trajectories` (4); below that, screen by the Fisher information at the defaults instead |
| Sobol | halve `sobol_samples` down to `plan.sobol_min_samples` (8); below that, skip Sobol and take the Morris subset |
| Profiles | run while the projected cost fits `plan.profile_share` (0.15); else Fisher only |
| LSQ / DE | halve starts / generations down to 1 / `plan.de_min_generations` (2); below that, the single LSQ start |
| MCMC | halve steps down to `plan.mcmc_min_steps` (10); below that, skip MCMC (`posterior_intervals` abstained, Fisher intervals stand) |
| Second pass | skipped when its projected cost does not fit |
| Ensemble | `validate.ensemble_size` (8) draws; halved to 2; below that, the point prediction alone |

A runtime guard is the one non-deterministic element: if the wall-clock left is below the
projection at the *measured* rate, the same fallback is taken and recorded under
`plan.guards_tripped`. It fires only on a machine slower than the assumed rate.

## 5. The output contract

`runs/<id>/workflows/p0/state.json` — the shared task state (`state.task_state.TaskState`,
§6.6): data-quality status per sensor; tier; candidate model; the classification (label,
secondary labels, confidence, evidence with the tool calls it rests on); the approved
subset and the screening trail; the residual-diagnostics summary per output; actions
taken (name, version, the visible log line's sequence number and argument hash, handed
back by the registry with every call; tested to match `calls.jsonl` line for line); tool
failures; the remaining
budget; validation status; abstentions; the final label and the final parameter estimates
with intervals and the method that produced them; the plan and its fallbacks; the notes
seen (day, author, length). `report.json` — the same conclusions in prose lines with the
tables, for a human. Both are written through `tools.run.write_output` (§6, point 3) and
contain nothing that is not derivable from the visible record and the tool outputs: no
scenario id, no seed, no truth label, no baseline, no timestamp (a test asserts it). The
runner adds `summary.json` beside them (wall-clock, evaluations and assay units used,
completion, the final label) from its privileged side, and one row per cell to
`reports/p0_pilot.csv`.

## 6. Open points for the lead

1. The declared instrument noise as P0's weights (§1.1).
2. The rules and thresholds of §3, as declared; the sizes of §4 against the frozen
   budgets — the pilot (`docs/milestones.md`) measures whether P0 completes comfortably.
3. Two registry additions, both plumbing for the task state and nothing the registry PR
   tested changes: (a) `runs/<id>/` gains `workflows/<name>/` for a workflow's own
   outputs, written through the registry (`run.write_output`, restricted to that
   directory, traversal refused); the layout ruling of 2026-09-04 said the run directory
   holds the observations, the redacted manifest and the call log — this is the fourth
   thing, and it is workflow-written. (b) Every call envelope carries the visible log
   line's `seq`, `args_hash` and version (`tools.last_call()`), so a workflow names its
   actions the way the log does without re-implementing the hash; the truth-side outcome
   is not in it (an injected failure still reads `ok`).
4. A 200-day evaluation on a generated cell costs 11–12 s; a cell of 4,000 evaluations
   would take over thirteen hours, and a 90-minute allowance buys about 450, so the
   wall-clock allowance is what binds and P0's sizes are set by it (§4): at 12 s the
   declared plan runs Morris with 4 trajectories, Sobol with N = 8, one LSQ start, two DE
   generations and no MCMC inside 90 minutes. Whether the budgets should be re-declared is
   the pilot's question.

## 7. Recorded limits

- At 30 days the Fisher information at the defaults drops every Sobol parameter as
  practically non-identifiable (relative CRLB 4–9) and the declared minimum of two stands;
  whether 200 days identify more is the pilot's to say.
- MCMC with the sizes the wall clock allows (8 walkers × 30 steps) will rarely converge on
  ADM1; P0 then reports Fisher intervals by the same rule the Level-8 row exercises. This
  is stated, not hidden; a larger allowance is the lead's call.
- One parameter vector (k_dis × 2 with k_m_aa × 0.5 on Plant B, constant log) integrated
  in 274–290 s against 3 s for the rest: a stiffness pocket inside the declared bounds. P0 cannot
  avoid it; the wall-clock guard absorbs it. Recorded for the registry (solver settings are
  frozen under G1).
