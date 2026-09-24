# Distinguishability: which labels the record admits (evaluation side)

*Ruling of 2026-09-24 (PR C of the coordinator's relay). Method choices are recorded
in `docs/decisions.md`. This analysis never replaces the truth-label score, and nothing
under `workflows/` can import it.*

## 1. The question

The attribution score (§6.7 B, `eval/attribution.py`) asks whether a workflow's final
label set equals the truth label set. If the visible record at a tier supports several
explanations equally well, a workflow cannot be expected to pick the true one, and a
miss there is not the same failure as a miss where the record is decisive. For every
cell, this analysis computes an **admissible label set** *A*: the labels whose best
explanation of the tier's visible record is statistically as good as the best of all.
It then reports a second score, **`attribution_admissible`** (the final primary label is
in *A*), *next to* `attribution_exact`, never instead of it.

## 2. Hypothesis classes

The analysis uses the fitted model (`tools.fitted.FittedADM1`), built on the privileged
side as the registry builds it:
- the plant's declared configuration;
- the run's visible feed log;
- the run's fitted extensions.

It does not use the registry. The registry would append to the run's call logs, and
the evaluator scores those logs.

Each label is represented by the knobs of its class, starting from the defaults
(all multipliers 1):

| label | knobs (free parameters *k*) | fit |
|---|---|---|
| `none` | none (*k* = 0) | — |
| `parameter` | a constant multiplier on 6 parameters (§2.1), each within its declared bounds | bounded least squares on log multipliers, from the defaults; at most 6 function evaluations plus their 2-point Jacobians |
| `sensor` | on **one** calibrated sensor, applied to the default prediction: a scale step after an onset (onsets every 10 d), or a linear drift (offset plus slope) (*k* = 2) | closed-form weighted least squares; no simulation beyond the defaults |
| `influent` | one constant scale per feed's logged mass, in [0.5, 2] (*k* = number of feeds, 4 here) | as `parameter` |
| `state` | `biomass_scale` in [0.25, 4] (*k* = 1) | bounded scalar minimisation, at most 10 iterations |
| `structural` | the best of: one fitted extension left out (*k* = 0 each), or the declared active volume scaled in [0.6, 1.4] (*k* = 1) | enumeration plus a scalar fit |

### 2.1 The parameter subset

The six parameters are fixed before any fit:
- `k_hyd_ch` and `K_I_nh3`, the parameters the Level-5 faults shift;
- `Y_ac`, `k_m_ac`, `k_m_h2` and `Y_h2`, the four P0 approved most often across the
  78-cell sweep (on 55, 38, 27 and 26 cells).

One subset for every cell keeps the cost fixed and the classes comparable.

### 2.2 What the classes cannot represent

These limits are declared, not hidden:
- the fitted model has no mid-record parameter change (Level 5 shifts at day 120);
- it has no time-windowed fractionation change (S3-01) and no per-day solids change
  (S3-03);
- it has no stagnant zone.

In each case the class's best constant representative stands in. So a label may be
*inadmissible because the model cannot say it*, not because the record excludes it. The
table names, for every cell whose injected fault falls in such a class, which limit
applies (`truth_class_limited`, empty when none does).

## 3. The likelihood and the admissibility rule

**The likelihood.**
- The data are the cell's visible record, `runs/<id>/observations/sensors.json`. Only
  the tier's instruments are used, and only the sensors P0 calibrates (temperature is
  left out). Missing, saturated and flatlined samples are dropped for every class alike,
  because the record flags them. The whole record is used, not P0's calibration window.
- The residual of each sample is `(observed − predicted)/sd`, with the declared sd
  `sqrt((cv·v)² + sd_abs²)` from `configs/observation/sensors.yaml`, floored as P0
  floors it (`calibration.min_relative_sd`, `sd_floor_abs`).
- χ² is the sum of squared residuals.
- This is the likelihood a workflow could compute. The truth store is read for three
  things, never for the data:
  - the answer key's labels;
  - the injected fault types, for the class-limited flag;
  - the fitted model's declared extensions, read as the registry reads them.

**The rule.** For every class *L* with best χ²_L and *k_L* free parameters,
AIC_L = χ²_L + 2 k_L. A label is admissible if AIC_L − min_M AIC_M ≤ 2.
- 2 is the conventional "substantial support" margin of Burnham and Anderson.
- The margin is on AIC, not raw χ², so a class cannot win by having more knobs.
- The truth's own class does not have to be admissible. When it is not, the table flags
  `truth_admissible: false`: the record at that tier prefers a different explanation.

**Sensitivity.** The analysis also computes *A* at a margin of 10 ("essentially no
support" beyond it) and reports it. The primary column uses 2.

**Known caveat.** Drifting sensors (pH, CH4, H2, temperature) have a random-walk
component that is not white noise. A white-noise χ² over-penalises slow offsets on those
channels, which favours classes that can absorb an offset (sensor, influent). The table
reports χ² per sensor so this can be checked.

## 4. Outputs

- `truth_store/<id>/admissible.json`, per run: the class χ², *k* and AIC; the admissible
  sets at both margins; `truth_admissible`; `truth_class_limited`; the fitted knob
  values; and the method version.
  - It sits beside the answer key because it is derived from it. A workflow can never
    read it.
- `eval/` reads that file when it exists, through `eval/records.py`, and adds the
  columns:
  - `admissible_set`;
  - `attribution_admissible`: the final primary label is in *A*;
  - `attribution_admissible_set`: every final label is in *A*;
  - `truth_admissible`.
  - Without the file these columns are `None`, and every existing column is unchanged.
- `reports/p0_distinguishability.csv` and `.json`: the per-cell table, and the P0 sweep
  scored with both columns side by side.

## 5. Where the code lives

- The analysis is `distinguish/`, a new top-level package.
  - It imports `tools.fitted`, `sim.plants` and `configs`, and runs outside every
    sandbox.
  - The rule-1 checker adds `distinguish` to the names no workflow may import, and a
    test checks that no module under `workflows/` does.
- `eval/` does not import `distinguish/`. It reads the precomputed file, so the
  evaluator's own import allow-list is unchanged.

## 6. Compute

The simulations are shared across the tiers of a (scenario, plant) pair, because the
tiers share the truth and the feed log. The fits are per tier.

| work | simulations |
|---|---|
| `none` + the extension drops | about 5 per pair, shared across its tiers |
| `state` fit | about 12 per cell |
| `structural` volume fit | about 12 per cell |
| `influent` fit | about 30 per cell |
| `parameter` fit | about 45 per cell |
| **total** | about 100 per cell, 7,800 for the 78 cells ≈ 35–45 runner-hours at 14–25 s |

That is about one sweep's compute, three processes in parallel, with checkpoints. Every
simulation has a 120 s timeout, because of the recorded stiff pocket inside the bounds.
A timed-out or failed simulation is a very bad fit, not a crash: every residual of that
trial is set to 10³. The number of timeouts is logged in each `admissible.json`.
