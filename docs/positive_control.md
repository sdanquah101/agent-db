# The positive-control ladder for P0 (pre-registered)

*Status: pre-registration. This document, including its pass criteria and cell list, is
committed before any ladder run starts. Results are appended in §8 below the line and
are never edited into §1–§7. Ruling of 2026-09-24 (PR B of the coordinator's relay).*

## 1. What the ladder asks

The single-seed Level 0–5 sweep (`reports/p0_sweep_scored.csv`) found that P0
- never attributes an influent cell (0/21) or a state cell (0/14),
- attributes 2 of 10 parameter cells exactly, and
- names the faulty sensor on 5 of 21 sensor cells.

A miss has four possible explanations. P0 ran out of budget; P0 lacked information the
record could have carried; P0 never considered the right explanation; or the data do not
distinguish the truth (PR C's question). Each rung of the ladder removes exactly one
handicap, on cells that P0 missed, and asks whether the miss goes away:

| rung | handicap removed | question |
|---|---|---|
| R1 | budget | Is the miss budget-limited? |
| R2 | feed information | Is the miss caused by the feed record differing from the true feed? |
| R3 | candidate set | Is the miss caused by the shifted parameter never being fitted? |

## 2. What the ladder is not

- **Diagnostics, never baseline rows.** Every ladder run is a diagnostic. None is a P0
  entry, none is a row of `reports/p0_sweep_scored.csv` or of any baseline table, and
  none is ever compared with P1 or P2 as if it were P0. Results go only to
  `reports/p0_positive_control*.{csv,json}`, and every row carries `rung`, `variant` and
  `diagnostic: true`.
- **P0 is not changed to look better.** R1 and R2 change nothing in P0. R3 adds one
  configuration hook that is **off by default**. With the hook off, P0 is byte-for-byte
  the P0 of the baseline (§5.3).
- **Truth enters only as a declared, logged experimenter variant.** R2's exact feed and
  R3's shifted parameter are truth information. The *experimenter* (the ladder driver
  `scripts/positive_control.py`) reads them from the truth store and supplies them as a
  declared configuration variant. The driver writes each variant's content and sha256
  into the report row. P0 itself never reads the truth store: nothing under
  `workflows/` changes its imports, and the rule-1 checker still passes. The R3 variant
  enters P0's sandbox only as its configuration file, the same channel every run uses.
  An R2 variant is a separate run store whose feed record the driver rewrote.

## 3. Cells and rungs

Ids are store-specific; cells are named by scenario, plant and tier. "Baseline" means
the cell's row in `reports/p0_sweep_scored.csv`, as updated by PR A.

**R1, budget.** The scenario's `simulator_evals` and `wall_clock_min` are multiplied by
3, and assay units stay as they are. The budget reaches the registry through the
`scenario=` argument of `tools.runner.run_workflow`, the route the tests use for short
cells. P0's configuration is untouched.
- All 10 parameter cells: S5-01 A/{A,B,C}; S5-02 B/{A,B,C}, C/{A,B,C}, A/A.
- Four sensor and state cells: S2-01 B/B, S2-03 C/B, S4-01 B/B, S4-02 C/B.
- **10×** on two cells, fixed now: S5-02 B/B and S5-01 A/B (one per scenario and one per
  plant, both missed at baseline).

**R2, true feed.**
- *The variant.* The cell is generated into a separate diagnostic store, with the same
  scenario, seed and plant. The driver checks that the truth arrays (`parameters.json`,
  `influent.npz`, `states.npz`) equal the original cell's. It then rewrites
  `observations/feed_log.csv` with the true delivered wet mass per day from
  `truth_store/<id>/influent.npz`. Background mislogs, background unrecorded deliveries
  and the injected delivery are all removed from the record.
- *Why this route.* `sim/` has no argument for an exact feed log. Adding one is a change
  under `sim/`, which the rules forbid, so the rewrite is done after generation, by the
  driver.
- *Cells.* S3-02 at Tier C and Tier B on Plants B and C (4 cells). S3-02 is the one
  influent fault in the logged mass, so it is what R2 can repair.
- *Negative control.* S3-01 and S3-03 at Tier C on Plants B and C (4 cells). Their faults
  are in the feed's *composition* (fractionation, total solids). The fitted model maps any
  feed log through the declared catalogue (`tools/fitted.py`), so an exact log cannot
  repair them, and the rung should not move them.
- *Not attempted.* A composition-exact variant would need a privileged hook in
  `tools/fitted.py`. That widens this PR, so it is proposed in the PR body and not built.

**R3, candidate set.** A new configuration key, `screening.force_include` (default `[]`),
names parameters that P0 adds to its approved subset after the Fisher step, so they are
always fitted.
- *Config files.* The driver writes one variant per scenario from the truth of the fault
  declaration: S5-01 `[K_I_nh3]`; S5-02 `[k_hyd_ch, k_hyd_pr, k_hyd_li]`. They live in
  the scratch driver output and are recorded (content and sha256) in each row.
  `configs/workflows/p0.yaml` is not edited.
- *Cells and budget.* All 10 parameter cells, at the baseline budget.

## 4. What is measured

These are the evaluator's columns (`docs/eval_design.md`), read from the logs as always:
- `attribution_exact` and `primary_in_truth`;
- `false_kinetic_drift` and `false_kinetic_update`;
- `abstention_correct` where applicable;
- the recovery columns;
- the meter's evaluations and wall clock.

For R3 two more quantities, derived from the same logs:
- whether every forced parameter is in the fitted set;
- each forced parameter's estimate against the last-segment truth, and whether its
  reported interval covers that truth.

**Known truth caveat for S5-01** (measured in the store, not assumed):
- The fitted model's default is BSM2.
- Plant A's truth before day 120 is 11.11× BSM2 for `K_I_nh3` (its adapted baseline),
  which is outside the fitted bounds [0.2, 5].
- After the shift it is 1.111×.
- The recovery target is the last segment, 1.111, so recovering the "shift" on S5-01
  means estimating a value close to the fitted default. The table reports this next to
  every S5-01 row.

## 5. Pass criteria (pre-registered)

A cell *moves* under a rung if its `attribution_exact` goes from false at baseline to
true under the rung. For R3 only, recovery (below) is also a move.

### 5.1 Per rung

- **R1 (budget-limited).** R1 *passes* if at least 3 of the 10 parameter cells move, or
  at least 2 of the 4 sensor and state cells move. It *fails* if at most one cell moves in
  each group. Anything in between is *inconclusive*.
  - Prediction, written before the run: R1 fails. P0's plan starts from fixed step sizes
    and only halves them when the budget is short (`Plan.ladder`), so a larger allowance
    removes fallbacks but buys no bigger design. The sweep's Level-5 cells used 227–362
    of their evaluations, with 0–2 fallbacks.
  - The 10× cells test whether that prediction holds when nothing can bind. If they move
    and 3× does not, the verdict is "budget-limited above 3×".
- **R2 (feed-limited).**
  - R2 *passes* if at least 2 of the 4 S3-02 cells move, and at most 1 of the 4 control
    cells moves.
  - If at least 2 control cells move as well, the verdict is *confounded*: the feed
    record's background noise, not the injected fault, mattered.
  - It *fails* if no S3-02 cell moves.
- **R3 (candidate-limited).**
  - *Mechanical check:* every forced parameter appears in the fitted set on 10 of 10
    cells. Anything less is a bug in the hook, and the rung is reported as not run.
  - R3 *passes* if at least 3 of the 10 cells move, where a cell moves if either:
    - its attribution becomes exact; or
    - every forced parameter is estimated within 25 % of its last-segment truth, or
      inside a reported interval that covers it.
  - It *fails* if at most one cell moves.
  - The two movement kinds are reported separately. A recovered parameter with a wrong
    label means P0's attribution rule, not its fit, is the limit.

### 5.2 Rules that apply to every rung

- The comparison is always this rung against the baseline row of the same cell, with
  one seed. No rung is tuned after it has run. A criterion that turns out to be
  unmeasurable is reported as such, not replaced.
- Time-dependent paths (wall-clock fallbacks, the plan's timing gates) can differ
  between two runs of the same code. A cell whose rung row differs only on such a path is
  reported with both rows and marked `time_dependent_path`, and its move is counted only
  if it does not depend on that path.

### 5.3 Hook off is P0 unchanged

The ruling asks for a test that, with the hook off, the eight Level 0–5 pilot cells are
byte-identical. Those cells are S0-01 B/{A,B,C}, S1-01 B/B, S2-01 B/B, S3-01 C/B,
S4-01 B/B and S5-01 A/A.
- **(a) A unit test.** On the short test cell, the default configuration and one with
  `force_include: []` produce the same normalised `state.json`. This is the normalisation
  of the existing same-cell-twice test. It is part of `pytest -q`.
- **(b) A full re-run.** The eight pilot cells are re-run at PR B's head with the hook
  off. Their `state.json`, `summary.json` and `report.md` are compared with the PR A
  outputs of the same cells: bytes first, then the normalised state. The only
  differences allowed are the wall clock, the sequence numbers and the time-dependent
  paths named under §5.2. Any other difference fails the check, and R3 is then not run.

## 6. Compute cap and order

Expected runner-hours:

| item | runs | hours per run | runner-hours |
|---|---|---|---|
| R1 3× | 14 | ~1.7 | ~24 |
| R1 10× | 2 | ~2.5 | ~5 |
| R2 | 8 | ~1.4 | ~11 |
| hook-off check | 8 | ~1.3 | ~10 |
| R3 | 10 | ~1.5 | ~15 |
| **total** | | | **~65** |

The cap is about 100 runner-hours, three processes in parallel. Nothing runs in parallel
with PR A's re-runs, so timings are comparable.

Order:
1. The §5.3 (b) hook-off check.
2. R3, the cheapest decisive rung.
3. R1 at 3×.
4. R2.
5. R1 at 10×.

A checkpoint commit (partial tables, a "runs done / 56" line) goes to the branch about
every 3 hours. If the cap is reached, the unrun items are listed, not squeezed.

## 7. Reporting

- `reports/p0_positive_control.csv` and `.json` have one row per (cell, rung, variant),
  scored by the unchanged evaluator. They add the columns `rung`, `variant`,
  `variant_sha256`, `diagnostic`, `baseline_run_id` and `baseline_attribution_exact`.
- `reports/p0_positive_control_summary.json` holds the per-rung verdicts of §5.
- §8 below holds the results in plain language, one paragraph per rung, including
  failures and anything unmeasurable.

---

## 8. Results

### 8.1 The hook-off check (§5.3 b): passed, 2026-09-24 14:10 UTC

The eight pilot cells were regenerated into their own store, and every one was
byte-identical to the baseline in observations and truth arrays. They were then run at
PR B's head with the hook off, and compared with the baseline outputs
(`reports/p0_positive_control_hookoff.json`).

- **Bytes.** `state.json`, `summary.json` and `report.md` differ on all 8, as expected:
  the run id is store-specific and the wall clock differs.
- **Normalised state, run id masked: identical on 6 of 8.** S0-01 B/A, S0-01 B/C, S1-01
  B/B, S3-01 C/B, S4-01 B/B and S5-01 A/A.
- **S0-01 B/B and S2-01 B/B differ on one time-dependent path (§5.2).**
  - In the baseline sweep, which ran three cells at a time under load, the plan's MCMC
    guard refused the sampler ("mcmc: bound 88 at the measured rate").
  - Here, at a lighter load, the sampler fitted the plan and was called. It did not
    converge, so P0 recorded the failure and kept the Fisher intervals.
  - Final result, classification, screening, residuals and abstentions are identical.
    The validation block differs only by its call index, shifted by the one extra
    action.

No difference traces to the hook, so the check passes and R3 runs.

---

## 9. Amendment, 2026-09-24 ~17:30 UTC (review of PR #23)

This amendment follows an adversarial review the coordinator relayed on 2026-09-24.
It is committed **before R3 is scored and before any R2 run**. §1–§7 are not edited;
where they are superseded, this section says so.

### 9.1 R2 is redefined: remove only the background noise

§3 defined R2's variant as the true delivered mass. For S3-02 that makes R2 meaningless.
S3-02's fault *is* an unrecorded delivery, so writing the true mass puts the injected
delivery into the record and the fault vanishes from what P0 sees. "R2 fails" would then
be certain in advance, and would be misread as "not feed-limited".

R2's variant is now **the true delivered mass minus the scenario's injected unrecorded
deliveries**:
- The background mis-logs and background unrecorded deliveries of
  `configs/influent/generator.yaml` are removed from the record.
- The injected fault stays in the record exactly as the baseline has it.
- The driver recomputes the injected amount as the generator adds it: the feed's
  configured nonzero median delivery, in kg, times the fault's multiple. It checks that
  the amount never exceeds the true mass that day. On S3-02 B/C, day 90, the true
  delivery is 94,905 kg, all of it the injected delivery, and the rewritten log keeps 0
  there, as the baseline log does.

The question R2 asks becomes: does the background noise of the feed log hide the injected
delivery from P0?

The other R2 cells were checked for the same problem:
- S3-01 (mislabel) and S3-03 (moisture) carry no injected mass. Their faults are in the
  feed's composition, and their rewritten log is the true delivered mass.
- They stay R2's negative control, as §3 says.

The generated log is now kept beside the diagnostic store (`<store>/r2/feed_logs/`),
not under `runs/<id>/`, which holds only the observations, the redacted manifest and
`calls.jsonl`.

### 9.2 The verdicts are computed in code

`python -m scripts.positive_control verdict` computes every §5 verdict from the ladder
table and writes `reports/p0_positive_control_summary.json`. It is committed here,
before any R3 result is read. The per-row measures it reads are computed by `score`:
- `moved_exact`: `attribution_exact` False at baseline, True here.
- `time_dependent_path`: the plan's timing-gated fields (`guards_tripped`, `fallbacks`,
  `steps_skipped`) differ from the baseline run's. This is how §5.2 is operationalised.
- For R3, from the evaluator's `recovery_detail` against the last-segment truth:
  - `forced_in_approved` and `forced_fitted` (the mechanical check);
  - `forced_within_25pct` and `forced_interval_covers`, where every forced parameter
    must pass;
  - `moved_recovery`, which counts a move when every forced parameter is within 25 % or
    covered.
- **§5.2 made strict.** A move on a row marked `time_dependent_path` is reported, but it
  is not counted toward a pass. The driver cannot show that a move does *not* depend on
  a timing-gated path, so the conservative reading is taken.

### 9.3 The forcing is auditable

`score` copies each variant's `variants.jsonl` (per run: cell, budget, configuration
content and sha256) and the R3 configuration files into `reports/positive_control/`, so
the forced list can be checked from the repository.

### 9.4 Corrections to §2 and §8.1

- **§2 said the driver reads R2's exact feed and R3's shifted parameter from the truth
  store.** For R3 that is wrong. The forced names are **hard-coded in the driver from
  the fault types** (`FORCED`: S5-01's `ammonia_inhibition_shift` → `K_I_nh3`; S5-02's
  `hydrolysis_regime_change` → `k_hyd_ch`, `k_hyd_pr`, `k_hyd_li`), not read at run
  time. R2's feed does come from the truth store (`influent.npz`, `faults.json`).
- **§8.1, stated plainly.** The hook-off check passes on 6 of 8 cells by identity. On the
  other 2 (S0-01 B/B, S2-01 B/B) it passes only through §5.2's time-dependent-path
  allowance. In the baseline the MCMC step was refused for time; in the re-run it was
  called, and did not converge.

---

## 10. Amendment, 2026-09-24 ~20:40 UTC (re-review of PR #23)

This follows the coordinator's re-review of a42cce7. It is committed **before any R1, R2
or R3 row is scored**. §1–§9 are not edited.

### 10.1 The time-dependent flag is wall-clock only

§9.2 set `time_dependent_path` whenever the plan's guards, fallbacks or skipped steps
differed from the baseline run's. But the plan's fit check covers the evaluation budget
too, so budget refusals ("N evaluations do not fit") land in `fallbacks`. R1 changes the
budget by design (§5.1's own prediction says a larger allowance removes fallbacks), and
R3 enlarges the Fisher and MCMC designs. With §9.2's strict counting, R1 and R3 could
then almost never pass, for a reason the pre-registration never intended. §5.2 exempts
**wall-clock** paths only.

The flag is now:
- **True** when the set of steps a *wall-clock* guard refused (`"<step>: bound N at the
  measured rate"`, or "refused for time") differs from the baseline run's, on a row run at
  the baseline budget.
- **False** on a rung that changes the budget (R1). There the wall-clock allowance is the
  rung's own lever, so its guard differences are the rung's effect, not timing noise.
- **True** (flagged) when either state is missing. This is the conservative reading §9.2
  promises; such a move is shown and not counted.

A budget-driven fallback alone never sets the flag. `tests/test_positive_control.py`
checks every case above.

### 10.2 The verdict code

- **R2** is judged "fail" when no S3-02 cell moves, before "confounded" is considered.
  §5.1's "confounded" is control moves *as well as* S3-02 moves.
- A rung with cells still to run reads **"incomplete"**, with the verdict so far, rather
  than "not run".
- **R3's recovery move** (`moved_recovery`) requires every forced parameter to be within
  25 % of its last-segment truth **or** inside a reported interval that covers it. This
  is the operational form of §5.1's wording ("estimated within 25 % of its last-segment
  truth, or inside a reported interval that covers it"), declared here as that form.
