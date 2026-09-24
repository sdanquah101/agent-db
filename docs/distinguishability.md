# Distinguishability: which labels the record admits (evaluation side)

*Ruling of 2026-09-24 (PR C of the coordinator's relay). Method version 3, after the
review and the re-review of PR #25 and before any result was computed. §2.0 and §3 are
superseded by version 3 as described there. Method choices are recorded in
`docs/decisions.md`. This analysis never replaces the truth-label score, and nothing under
`workflows/` can import it.*

## 1. The question

The attribution score (§6.7 B, `eval/attribution.py`) asks whether a workflow's final
label set equals the truth label set. When the visible record at a tier supports several
explanations equally well, a workflow cannot be expected to pick the true one, and a miss
there is not the same failure as a miss where the record is decisive.

For every cell, this analysis computes an **admissible label set** *A*: the labels whose
best explanation of the tier's visible record is statistically as good as the best of
all. It then reports a second score, **`attribution_admissible`**, *next to*
`attribution_exact`, never instead of it. The score is true when the final primary label
is in *A* or in the truth. It **only ever adds credit**: a workflow that answers the truth
is never marked wrong by it.

## 2.0 Method version 3: the calibrated null (re-review of PR #25)

The re-review found that a null at the default parameters is misspecified. The
default-parameter model misfits even a clean record (the benchmark card, §4.2): on
S0-01 C/B, χ²(none) is 9,357 over 506 samples, and gas flow alone has χ²/n = 63. So any
class that rescales gas flow beat `none` by about 300, and would have earned
admissible credit for "sensor" on a clean cell. Version 3 changes four things.

- **The null is the calibrated no-fault baseline.** Under `none`, the background
  multipliers `Y_ac`, `k_m_ac`, `k_m_h2` and `Y_h2` are fitted to the calibration window
  (`distinguishability.baseline_parameters` in `configs/eval.yaml`; these are P0's four
  most-approved parameters, and not the Level-5 targets). Every other class is fitted on
  top of that same calibrated background, with the baseline held at its fit (a
  conditional fit). The baseline's k is shared by every class, so it cancels.
- **Overdispersion.** Each sensor's χ² is divided by its dispersion under the calibrated
  baseline on the Level-0 cell of the same plant and tier (χ²/n, floor 1; the
  quasi-likelihood treatment of known misfit).
  - The Level-0 cells run first and use their own baseline.
  - Plant A has no Level-0 cell, so its cells use their own calibrated baseline and are
    flagged in `overdispersion_source`. This is conservative: it can only favour `none`.
- **The penalty is a joint test.** A class's score is χ² plus the likelihood-ratio
  critical value of its k knobs at α / m (α = 0.05, m = 5 alternatives, Bonferroni),
  plus 2 ln N for a best-of-N search. With every class competing at once on noise,
  `none` is then admissible at least 1 − α of the time.
  - `tests/test_distinguish.py` checks this jointly on 400 noise records, with the
    sensor class's real closed form and a linear-Gaussian surrogate for the fitted
    classes.
  - On the same records, the version-2 rule (2k + 2 ln N) falls short, as the reviewer
    found (0.873).
- **The parameter class** is, on top of the baseline, a constant change of the two
  Level-5 target parameters (k = 2). On a Level-5 cell it is also the truth's own change
  point at the known onset, with the baseline before the onset.

**The chance rate** of the second score is |A ∪ truth| / 6: what a uniform guess over the
six labels scores. The CLI stratifies by it.

## 2. Hypothesis classes

The analysis uses the fitted model (`tools.fitted.FittedADM1`), built on the privileged
side as the registry builds it: the plant's declared configuration, the run's visible
feed log and the run's fitted extensions. It does not use the registry, which would
append to the run's call logs. Each label is represented by the knobs of its class,
fitted from the defaults (all multipliers 1):

| label | forms (free parameters *k*) | fit |
|---|---|---|
| `none` | the defaults (*k* = 0) | — |
| `parameter` | a constant multiplier on 6 parameters (§2.1) (*k* = 6); and, on a cell whose injected fault is a parameter shift, **the truth's own form**: the shifted parameters change at the known onset, defaults before it (*k* = number shifted) | bounded least squares on log multipliers from the defaults, to convergence |
| `sensor` | on one calibrated sensor, applied to the default prediction: a scale step after an onset (every 10 d), or a linear drift (*k* = 2) | closed-form weighted least squares |
| `influent` | a constant scale on each feed's logged mass in [0.5, 2] (*k* = number of feeds); and, on a cell with an injected unrecorded delivery, **the truth's own form**: one delivery of free mass on its known day and feed (*k* = 1) | least squares; a bounded scalar fit |
| `state` | `biomass_scale` in [0.25, 4] (*k* = 1) | bounded scalar fit |
| `structural` | one fitted extension left out (*k* = 0 each), or the declared active volume scaled in [0.6, 1.4] (*k* = 1) | enumeration, and a scalar fit |

Where a class has several forms, the best form is taken and the choice pays the search
penalty (§3).

### 2.1 The parameter subset

The six parameters of the constant form are fixed before any fit:
- `k_hyd_ch` and `K_I_nh3`, the parameters the Level-5 faults shift;
- `Y_ac`, `k_m_ac`, `k_m_h2` and `Y_h2`, the four P0 approved most often across the
  78-cell sweep (on 55, 38, 27 and 26 cells).

### 2.2 The truth's own form, and what no class can represent

With truth access, the truth's class gets its representable form: a Level-5 shift as a
change point at its known onset (`distinguish/segments.py`, integrated in two segments
with the harness's own helpers), and S3-02's injected delivery on its known day. Without
that, a constant multiplier cannot represent a mid-record shift, a sensor step could
absorb the cell, and the second score would credit the wrong answer.

These truths are **not representable** by any class here:
- a time-windowed fractionation change (S3-01);
- a per-day solids change (S3-03);
- a stagnant zone.

For those cells the admissible score is **null, not credited**
(`truth_representable: false`, with the limit named in `truth_class_limited`).

## 3. The likelihood and the admissibility rule

**The likelihood.**
- **The data** are the cell's visible record, `runs/<id>/observations/sensors.json`,
  **cut at the end of P0's calibration window**. That is `duration × (1 −
  holdout_fraction)` with `holdout_fraction` from `configs/workflows/p0.yaml`, as the
  ruling asked; the hold-out is never read.
- **Which samples.** Only the sensors P0 calibrates are used, so temperature is left
  out. Missing, saturated and flatlined samples are dropped for every class alike.
- **The residual** is `(observed − predicted)/sd`. The sd is the declared
  `sqrt((cv·v)² + sd_abs²)`, floored as P0 floors it. χ² is the sum of squared residuals.
- **The truth store is read for the answer key's labels, the injected faults** (for the
  truth's own form and the representability flag), and the fitted extensions. It is
  never read for the data.

**The rule.** For every class *L*, AIC_L = χ²_L + 2 k_L + 2 ln N_L. N_L is the number of
candidates the class chose its best from:
- for `sensor`, every (sensor, onset or drift) candidate;
- for `structural`, every alternative;
- for a class with several forms, the number of forms.

The last term is the **look-elsewhere correction**. Without it, the sensor class wins on
pure noise. A label is **admissible** if AIC_L − min_M AIC_M ≤ `margin`.
- **The margin** is set in `configs/eval.yaml` (`distinguishability.margin`: 2, the
  "substantial support" margin of Burnham and Anderson). The set at
  `sensitivity_margin` (10) is reported beside it.
- **A multi-label truth** passes `truth_admissible` when any one of its labels is
  admissible. No joint class is fitted.

**Calibration.** On pure white noise around the defaults (300 records of nine sensors),
`none` must stay admissible against the sensor class at least `none_admissible_rate_min`
(0.95) of the time. `tests/test_distinguish.py` checks it. Without the correction the
rate is below one half, which reproduces the reviewer's finding. The rate on the
Level-0 cells is reported with the results (`none_admissible` per cell).

**Convergence.** The least-squares fits run to convergence, up to `lsq_max_nfev` function
evaluations, and the scalar fits up to `scalar_max_iter` iterations. Each class reports
`converged` and its status. A fit that stops short is reported, not hidden.

**Known caveat.** Drifting sensors (pH, CH4, H2) have a random-walk component that is not
white noise, so a white-noise χ² over-penalises slow offsets on those channels. χ² per
sensor is reported, so this can be checked.

## 4. Outputs

- `truth_store/<id>/admissible.json`, per run (method version 2). It holds:
  - per class: χ², *k*, the candidate count and search penalty, AIC, the convergence
    status and the fitted knobs;
  - the admissible sets at both margins;
  - `n_admissible`, `chance_rate` (1/|A|) and `none_admissible`;
  - `truth_admissible`, `truth_representable` and `truth_class_limited`.

  It sits beside the answer key. A workflow can never read it.
- `eval/` reads the file when it exists and adds the columns `admissible_set`,
  `n_admissible`, `admissible_chance_rate`, `truth_admissible`, `truth_representable`,
  `attribution_admissible` (primary label in *A* ∪ truth) and
  `attribution_admissible_set` (every final label in *A* ∪ truth). Without the file these
  columns are `None`, and every existing column is unchanged. `python -m eval` prints
  the second score beside the exact one, stratified by |*A*| with the chance rate, so
  that a broad answer cannot look good.
- `reports/p0_distinguishability.{csv,json}`: the per-cell table, and the P0 sweep
  scored with both columns side by side.

## 5. Where the code lives

`distinguish/` is a top-level package (listed in `pyproject.toml`), run outside every
sandbox. The rule-1 checker forbids it to workflows, by import and by the
`"distinguish..."` string form, and `eval/` reads its precomputed file without importing
it.

## 6. Compute

The simulations of the classes that need no fit are shared across the tiers of a
(scenario, plant) pair; the fits are per tier. Fitting to convergence costs more than the
first draft estimated:

| class | simulations per cell |
|---|---|
| `parameter` | up to about 40 × 7 |
| `influent` | up to about 40 × 5, plus 25 |
| `state` and the volume fit | about 25 each |

That is a few hundred simulations per cell, at 14–25 s each. The analysis runs with
checkpoints after the positive-control ladder, and its compute is reported. If it goes
past about one sweep (~100 runner-hours), the pairs not run are listed rather than
squeezed. Every simulation has a 120 s timeout, because of the recorded stiff pocket; a
timed-out trial's residuals are set to 10³ and counted.
