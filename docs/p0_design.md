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
**declared instrument noise** of every sensor (`cv`, `sd_abs` from
`configs/observation/sensors.yaml`, the visible sensor contract of §6.1: "every sensor has
a declared model"). Nothing derived from the run's truth, its scenario or its seeds enters;
the same file goes into every cell's sandbox. **Flagged for the lead** (§6, point 1): the
declared noise is what P0 weights residuals with; the alternative is estimating it from the
data.

## 2. The fixed sequence, and what each step feeds the next

Costs are simulator evaluations; wall-clock is what binds in practice (a 200-day
evaluation of `adm1_fitted` costs 2.5–4.4 s on Plants B and C at this head, one vector in
27 took 290 s: a stiffness pocket, §7).

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
3. `drift` → the sensor is **flagged and excluded** from the calibration objective; it
   stays in the record for the cross-channel checks.
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
the **approved subset**. After the fit, `fisher_info` at the optimum gives the intervals
of §3.5; `profile_likelihood` (grid `identifiability.profile_grid` (5), one start) is run
on the approved parameters in order of worst conditioning while the plan allows it (§4).

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

Evidence is collected as named counters and the label is the first rule that fires, in
this order (a compound row therefore reports one primary label; the other rules that
fired are listed as `secondary_labels`, and the evaluator scores both):

- **R1 sensor.** (a) A sensor flagged by §3.1 (drift, a long flatline). (b) Exactly one
  calibrated channel whose post-fit residual is biased beyond `attribution.sensor_bias_z`
  (3.0) in standardised units, or structured in time with a step (the mean before and
  after the best split differ by more than `attribution.sensor_step_z` (3.0)), while every
  other calibrated channel is within `attribution.clean_bias_z` (1.5) and unstructured,
  and the COD balance is admissible. (c) `charge_consistent` is false and `ph` is the
  channel whose residual is structured. For `gas_flow` the scale factor is estimated as
  the median of observed / predicted after the step (`estimate_scale_factor`).
- **R2 influent.** The COD closure is inadmissible in at least
  `attribution.balance_windows_min` (2) windows, or the residual of the primary channel
  is structured by the feed-batch covariate (η² above `attribution.feed_eta2_min` (0.15))
  more than by any other covariate. The action is `revise_influent_mapping`; kinetics are
  not moved.
- **R3 structural.** At least `attribution.structural_channels_min` (2) calibrated
  channels stay structured after the fit (serially structured and structured by load or
  time), or a fitted parameter sits at a bound while its channel's residual stays
  structured; `recommend_structural_review` is set and the parameter values are abstained
  on (§3.8).
- **R4 parameter.** A fitted parameter of the approved subset moved from 1 by more than
  `attribution.parameter_move_z` (3.0) interval half-widths, the residuals of its channels
  are unstructured after the fit, and the balances close. The bounded update is reported.
- **R5 state.** The residual of the primary channel is structured in time only in the
  first `attribution.transient_d` (30 d) of the record (bias beyond
  `attribution.state_bias_z` (3.0) there, within `clean_bias_z` after), or informative
  missingness was found (§3.1) — parameters are reported unchanged.
- **R6 none.** Otherwise.

Confidence is `attribution.confidence.single` (0.8) when one rule fired,
`attribution.confidence.multiple` (0.5) when more than one, `attribution.confidence.none`
(0.6) for R6.

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
per evaluation, `plan.eval_seconds_assumed` (4.0 s), never the measured one — so the same
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
taken (name, version, args hash, the registry's call index); tool failures; the remaining
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
3. `runs/<id>/` gains `workflows/<name>/` for a workflow's own outputs, written through the
   registry (`run.write_output`, restricted to that directory, traversal refused); the
   layout ruling of 2026-09-04 said the run directory holds the observations, the redacted
   manifest and the call log — this is the fourth thing, and it is workflow-written.
4. A 200-day evaluation costs 2.5–4.4 s; a cell of 4,000 evaluations would take over four
   hours, so the wall-clock allowance (90–150 min) is what binds, and P0's sizes are set by
   it (§4). Whether the budgets should be re-declared is the pilot's question.

## 7. Recorded limits

- MCMC with the sizes the wall clock allows (8 walkers × 30 steps) will rarely converge on
  ADM1; P0 then reports Fisher intervals by the same rule the Level-8 row exercises. This
  is stated, not hidden; a larger allowance is the lead's call.
- One parameter vector (k_dis × 2 with k_m_aa × 0.5 on Plant B) integrated in 290 s
  against 3 s for the rest: a stiffness pocket inside the declared bounds. P0 cannot
  avoid it; the wall-clock guard absorbs it. Recorded for the registry (solver settings are
  frozen under G1).
