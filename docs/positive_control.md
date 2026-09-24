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
