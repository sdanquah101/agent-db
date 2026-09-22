# The evaluation suite (milestone 6, proposal §6.7, Appendix A, §7)

Status: **built 2026-09-22** by the evaluation session on `claude/eval-suite` (draft PR);
the interpretations of §2–§5 are recorded in `docs/decisions.md` and are the lead's to
overrule. Every threshold, window, mapping and seed is a key of `configs/eval.yaml`
(schema `eval/config.py::EvalConfig`); nothing numerical is in the code.

## 1. What the suite is

`python -m eval` scores a run directory, or a batch selected from the truth-side index,
and writes a per-run table (CSV + JSON) and an aggregate per (scenario, plant, tier,
workflow) with seeded bootstrap intervals where a cell has more than one run. It reads
**records only** (`eval/records.py`):

| record | what it supplies |
|---|---|
| `truth_store/<id>/manifest.json` | plant, tier, horizon |
| `truth_store/<id>/faults.json` | the answer key: `truth_label`, level, `correct_conclusion` |
| `truth_store/<id>/parameters.json` | the true parameters per integration segment |
| `truth_store/<id>/calls.jsonl` | the truth-side log: timestamps, runtimes, **the meter** (evaluations and assay units per call, added by this session), `injected_failure` |
| `runs/<id>/calls.jsonl` | the visible log the task state's actions name (`seq`, `args_hash`) |
| `runs/<id>/workflows/<wf>/state.json` | the §6.6 task state |
| `runs/<id>/workflows/<wf>/summary.json` | the runner's verdict: completion, wall clock, the meter's cost fields |
| `truth_store/index.jsonl` | run id → cell, for batch selection |

Nothing under `eval/` imports `workflows/`, a scenario file, the harness or a plant; the
rule-1 checker now also flags a workflow module that imports or opens `eval/`
(`tests/test_eval_isolation.py`, both directions with a negative control). The scorer
writes nothing under `runs/` or `truth_store/` (tested).

A run the runner launched and that failed — killed on the wall clock, no state, an
invalid state — is scored with `completed = False` and every metric that needs the state
`None`; it stays in every denominator (§6.7 D). A run never launched is scored the same
way when named explicitly.

## 2. Family B — attribution and epistemic discipline (`eval/attribution.py`)

- **Attribution accuracy**: the final label *set* (`final.label` ∪ `final.secondary_labels`)
  equals `truth_label` as a set (`attribution_exact`); the Jaccard overlap is the partial
  credit (`attribution_partial`); `primary_in_truth` says whether the primary alone is
  right. A compound truth named in either order is exact.
- **False kinetic drift** (`false_kinetic_drift`, on runs whose truth is not
  `parameter`): any parameter of group `kinetics` in `configs/tools/model.yaml` whose
  point estimate lies outside the central 90 % of the **declared uniform box prior** on
  its bounds — the prior `bayes_mcmc` declares (`configs/tools/mcmc.yaml`) — is a drift.
  The bounds and the group are read from `model.yaml` and nowhere else. `Y_ac` and the
  other stoichiometric parameters do not count. `false_kinetic_update` separately reports
  a `kinetic_update` offered where the answer key forbids it.
- **Correct abstention** (`abstention_correct`): every quantity of `abstain_on` appears in
  the state's structured abstentions (`final.abstentions` ∪ `abstentions`), binary, with
  the fraction beside it. `abstention_applicable` marks a structural or compound truth;
  a run with `abstain_on` outside that set (S8-01's `posterior_intervals`) is scored and
  flagged. Names must match exactly: the answer key's vocabulary and the workflow's are a
  shared contract (`scenarios/*.yaml` `abstain_on` vs `docs/p0_design.md` §3.8).
- **Unsupported claims** (`unsupported_claim_rate`): the claims are the evidence items of
  the structured classification (`classification.evidence`). An item is unsupported when
  it names no call, when a named `call_index` does not map through `actions` to a visible
  log line with the same name and argument hash and outcome `ok`, or when none of the
  resolved calls is a tool that returns the claimed quantity (`claim_sources` in
  `eval.yaml`: by the item's value keys, by its rule where no key is mapped). An item
  whose value keys **and** rule are all unregistered in `claim_sources` cannot be checked
  against "returned the claimed quantity" and scores as `unmapped_claim` declares —
  unsupported by default (the conservative reading of Appendix A; PR #19 review, B2).
  **P1's contract:** every evidence rule and value key a workflow emits must be registered
  in `claim_sources`, or its claims score as unsupported. Free text (`annotations`,
  `report.json`) is never read.
- A launched run that left no valid state is an attribution **miss** (`attribution_exact`
  False, `attribution_partial` 0.0), not an absent datum: Appendix A scores a "fraction
  of runs" and §6.7 D keeps failed runs in the denominator (the coordinator's reading,
  2026-09-22). The aggregate's `attribution_exact_n` beside the rate keeps the
  completed-only rate derivable. The drift and abstention fields stay `None` (no estimate
  to judge); a run never launched is `None` throughout.

## 3. Family A — calibration and prediction (`eval/prediction.py`)

- **Forecast-window errors** (MAE, RMSE, nRMSE, bias), **coverage at 50/90 %**, the
  **interval score at α = 0.1** and the **CRPS** per channel (`q_gas_stp_dry`,
  `ch4_fraction`, `pH`, `vfa_titrimetric`, `tan`) come from the state's `validation`
  block, accepted only when every call it names resolves to a logged `validate` line with
  outcome `ok` **and** its hold-out window is the frozen `[T (1 − f), T]` with `f` from
  `eval.yaml` (0.25, P0's declared value, checked equal by a test). Otherwise every
  forecast field is `None` and `forecast_reason` says why. The interval metrics carry
  their source (`interval_source` = `final.interval_method`); `crps_posterior` is filled
  only from a posterior predictive, `crps` from any ensemble, and a point prediction
  abstains on both. "CH₄ flow" is carried by the record's biogas flow and CH₄ fraction —
  no sensor reports a methane flow.
  *Limit, recorded:* the metric values are the `validate` tool's as the state carries
  them; the prediction series is not in the record, so the evaluator verifies the trail
  and the window rather than recomputing — and the window it verifies is the state's own
  `validation.holdout`, since `validate`'s real window sits inside the opaque argument
  hash. Persisting `validate`'s input window and its output on the privileged side
  (truth store) would close both (follow-up (a)).
- **Mass/charge balance** (`cod_balance_error` = |mean COD closure|, `n_cod_inadmissible`,
  `charge_drift`, `charge_consistent`) from the state's `mass_balance` block when a logged
  `mass_balance` call with outcome `ok` exists among the actions.
- **Parameter recovery** (`recovery_*`), Levels 0–5 only: for every parameter in
  `final.parameters` that the truth carries, |estimate − truth multiplier|, the relative
  error, whether `[lower, upper]` covers the truth, and whether the estimate sits at a
  bound; the truth multiplier is the **last segment**'s value over the BSM2 default (a
  constant-parameter fit is scored against the regime the record ends in; the runner's
  pilot table did the same). A Level-6, -7 or -8 cell has `recovery_scored = False` and
  every recovery field `None` whatever the state reports (tested with the same estimates
  on a Level-0 and a Level-6 cell).

## 4. Family C — information efficiency (`eval/efficiency.py`)

`simulator_evals`, `assay_units` and `n_calls` are sums over the truth-side log's
workflow records (everything after the last `registry.open`) of the meter counts the
registry writes per call; `wall_clock_s` is the runner's measurement, `log_span_s` the
log's own span, `tool_runtime_s` the summed runtimes, `tokens` the runner's field (empty
for P0). The state's self-report is compared with the meter (`self_report_mismatch`) and
the summary's meter fields — evaluations, assay units and the call count — with the log
(`meter_agrees_with_summary`).
**Uncertainty reduction per assay unit** (RQ4): the mean over reported parameters of
1 − (interval width / prior 90 % interval width), clipped at zero, divided by the assay
units spent; abstained when none were.

## 5. Family D — reliability (`eval/reliability.py`)

`completed` is the runner's verdict — `state.final.completed` **and** the process exited 0
— so it is half self-report: a P1 that writes `completed: true` and exits 0 counts as
completed whatever it did in between; the rest of the row says what it did. `invalid_actions` counts logged errors whose detail
starts with a validation-failure prefix plus every `budget_exceeded` refusal;
`tool_errors` the other errors; `injected_failures` the Level-8 outcomes only the
truth-side log shows; `verifier_rejections` the records named `verifier.reject` (reserved
for P2; zero by construction now); `retries` the calls repeated with the same name and
argument hash — on P0 these are its identical re-simulations of one parameter vector
(the point prediction for the residuals and again for validation), not retries after a
failure; the count is what §6.7 D and the provenance log's docstring define. Variance
across seeds is the aggregate's `_sd` per metric.

## 6. The aggregate (`eval/aggregate.py`, §7)

Rows are grouped by `(scenario_id, plant, tier, workflow)` — the §7 cell on its plant,
since a Plant B row also runs on Plant C. For every numeric or boolean metric: `_n`,
`_mean` (a rate for booleans), and with more than one row `_sd` and a central 90 %
percentile-bootstrap interval of the mean (`_lo`, `_hi`; 2,000 resamples, seed 20260922,
all from `eval.yaml`). Numpy only; the mixed-effects analysis of §7 is a later, separate
step on these tables.

## 7. The meter (follow-up (d) of milestone 5)

`CallRecord` gained two truth-side fields, `n_evaluations` and `assay_units`, written by
the registry with every call — as the meter's count before and after the call on every
path, so a tool that charges the meter directly (the filters, per ensemble transition)
is counted like one that goes through a `MeteredModel` (PR #19 review, B1) — and dropped
from the visible projection like the timestamp and the runtime; `tools/runner.py` fills `summary.json`'s cost fields from the registry's
meter after the launch and keeps the state's own numbers beside them as
`self_reported_*`. A task state that misreports its budget does not change the scored
cost (`tests/test_runner_meter.py`, `tests/test_eval_metrics.py`).
