# Distinguishability: which labels the record admits (evaluation side)

*Method version 4, the coordinator's decision on the second re-review of PR #25
(2026-09-25), taken before any result was computed. Method choices are recorded in
`docs/decisions.md`. This analysis never replaces the truth-label score, and nothing under
`workflows/` can import it.*

**This is an upper bound on distinguishability, optimistic by construction.** Every class
is built on the truth simulation: the true parameters, the true influent and the true
initial state, which no workflow knows. Where this analysis finds two labels
indistinguishable, a workflow cannot be expected to tell them apart. Where it finds them
distinguishable, a workflow may still fail to, because it must also estimate everything
the analysis is given.

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

## 2. The classes: the truth, less its fault, plus one candidate

**The reference.** For each (scenario, plant), the truth is rebuilt with
`sim.run.harness.simulate_truth`. It uses:
- the scenario, re-timed to the plant's horizon as the matrix re-timed it;
- the run's own seeds, taken from the truth manifest and checked against
  `RunSeeds.derive`;
- the run's target feed.

The rebuilt channels must equal the stored `channels.npz` exactly, or the analysis
stops. On every pair run so far the maximum difference is 0.

The reference for every class is that truth with the injected fault **removed**. The
Level-1 nuisances (`sensor_noise`, `random_gaps`) carry no label and are part of the
record's noise, so they stay in every class. `sensor_noise` scales the declared noise.

**Each class adds only its own candidate perturbation.** The candidates are the fault
library's own faults (`sim/faults`), applied by the simulator or by the observation
operator exactly as a scenario applies them:

| label | candidates | fitted knob (*k*) | discrete search (*N*) |
|---|---|---|---|
| `none` | the reference itself | — | 1 |
| `sensor` | on one calibrated sensor, from an onset every 10 d: a scale step, an offset step, or a calibration ramp reset at recalibration (as `ph_electrode_drift` is) | the size, by closed-form generalised least squares (*k* = 1) | every (sensor, form, onset) |
| `sensor` | on one online sensor that can flatline: an injected flatline window, onset every 10 d, 2–16 d long | none (*k* = 0) | every (sensor, window) |
| `influent` | an unrecorded delivery (every 20 d; 1, 3 or 10 median deliveries); a fractionation redraw (`feed_mislabelled`; onset every 40 d, 30 or 60 d, concentration 5 or 50); a solids ramp (`moisture_drift`; onset every 40 d, 60 or 150 d, ±30 %) | the magnitude, on its grid (*k* = 1) | every (form, onset[, duration]) |
| `state` | every biomass state at t = 0 × 0.1, 0.25, 0.5, 2 or 4 (`biomass_misinitialised`) | the multiplier, on its grid (*k* = 1) | 1 |
| `parameter` | a change point on `K_I_nh3`, or on the three `k_hyd`, from an onset every 40 d (0 = from the start), × 0.2, 0.5, 2 or 5 | the multiplier, on its grid (*k* = 1) | every (group, onset) |
| `structural` | one truth extension switched off: `sao`, `ionic_strength` or `carbonate` (§2.1) | none (*k* = 0) | 3 |

The grids are in `configs/eval.yaml` (`distinguishability`).

**The truth's own fault is always a candidate of its class,** with its true onset,
duration and magnitude, and for a fractionation redraw its own seed. That makes the
bound optimistic: the truth class always contains the exact truth.

A candidate whose onset falls after the calibration window changes nothing the analysis
reads, and is not generated. A magnitude fitted on a grid is at best as good as the
continuous optimum, so paying *k* = 1 for it is conservative.

### 2.1 The one structural candidate the harness cannot run

The plants' truth models carry four extensions. Three can be switched off through
`simulate_truth`'s own settings: the analysis passes a harness configuration that seeds
only the enabled extensions' states. The fourth, **`precipitation`, cannot**:
`simulate_truth` always feeds dissolved calcium (`S_ca`) to the reactor
(`sim/run/harness.py`), and a model without the extension refuses it.
- Offering that candidate needs a change under `sim/`, which this PR does not make.
- So the structural class offers three candidates. Every document names the fourth in
  `structural_not_offered`.
- No Level 0–5 truth is structural, so no cell's truth is affected. Only the structural
  class's reach as an alternative is.

**What no class represents.** The likelihood does not model which samples are missing.
So `informative_missingness` (S4-02) is **not representable**. Its admissible score is
**null, not credited** (`truth_representable: false`, with the limit named in
`truth_class_limited`). Every other Level 1–5 fault is a candidate of its class.

## 3. The likelihood and the admissibility rule

**The data** are the cell's visible record, `runs/<id>/observations/sensors.json`, **cut
at the end of P0's calibration window**. That is `duration × (1 − holdout_fraction)`, and
the hold-out is never read. The sensors are those P0 calibrates, so temperature is left
out.

**The Gaussian term.** For each sensor, the residual `y − μ` is compared with the
observation model's own noise at the declared σ, with **no dispersion rescaling**.
- `μ` is the candidate's noiseless observation: the channel interpolated at the sample
  times, with the candidate's sensor fault if it has one.
- **The covariance** is white noise `(cv μ)² + sd_abs²` plus the sensor's random-walk
  drift. The drift adds `sd √dt · z` at every sample of the sensor's grid and restarts
  at each recalibration of the tier. Two samples of one recalibration interval share
  `min(i, j) − start + 1` steps, and samples of different intervals share none. That is
  the drift the model draws, which `tests/test_distinguish.py` checks against 3,000 of
  its draws.
- **Each candidate is scored with its own covariance:** the declared noise at the
  candidate's own predicted level, as the observation model would draw it under that
  hypothesis, with the log-determinant included. A sensor candidate's size is solved in
  closed form with the reference covariance (the truth less its fault), then scored with
  its own.
- **Which samples.** Missing, saturated, fouled and flatlined samples give no value.

**The flag term.** Flatlined samples stay visible to the sensor class through their flags.
A stuck sensor repeats its last reading, so a flatlined value carries no new information,
but the flag does.
- **The model.** The flags enter through the observation model's own flatline episode
  model (hazard × dt per sample, episodes of the declared length), as −2 log P(flags).
- **Missing samples.** A missing sample's flag is unobservable.
- **The flatline candidate.** It says every sample in its window is flagged, as
  `observe` flags an injected flatline. So its window must be flagged throughout, and
  its flags then cost nothing.
- **Why 2 d at least.** A one-sample hold is the sensor's own declared episode, not a
  candidate fault. So candidate windows are at least 2 d.

**The score.** For every class *L*, the score is the deviance (the Gaussian term plus the
flag term, which is −2 log-likelihood up to a constant shared by every class) plus a
penalty:

  score_L = deviance_L + c(k_L) + 2 ln N_L

- **The fitted knobs.** *c*(k) is the critical value of the alternative at α / m
  (α = 0.05, m = 5 alternatives competing with `none`, Bonferroni).
  - For *k* ≥ 1 it is the likelihood-ratio value χ²_k at 1 − α/m. That is 6.63 for
    *k* = 1.
  - A fixed alternative (*k* = 0: an extension left out, a flatline window) is a simple
    hypothesis. Its gain over the null is `2 δ·w − |δ|²` for a fixed whitened shift δ.
    That exceeds *c* with probability at most P(Z > √c), whatever |δ| is. So its critical
    value is Φ⁻¹(1 − α/m)², which is 5.41.
  - `none` pays nothing.
- **The search.** 2 ln N is the look-elsewhere correction for a class's discrete search.

A label is **admissible** if score_L − min_M score_M ≤ `margin`.
- **The margin.** `distinguishability.margin` is 2, the "substantial support" margin of
  Burnham and Anderson. The set at `sensitivity_margin` (10) is reported beside it.
- **A multi-label truth** passes `truth_admissible` when any one of its labels is
  admissible.

**The joint noise calibration, declared.** The records are drawn by the observation model
itself: white noise, the recalibrated drift walk, pH fouling, flatline episodes and
missingness, around a known truth. On each record every class competes with `none` at
once.
- **How each class is scored.** The sensor class runs its real closed form and flatline
  search. Each simulated class is the linear-Gaussian surrogate of its search: the best
  of *N* independent χ²₁ gains, the exact gain of a one-knob fit under the right
  covariance and the worst case of independent directions. The four extensions are
  given the same gain at *k* = 0, the worst case of a fixed alternative that points
  along the noise. That is four, not the three offered, which is conservative.
- **The rates.** On the model's own noise, `none` is admissible on **0.9825 of 400
  records** (declared minimum `none_admissible_rate_min` = 0.95; the test checks it on
  300).
- **The limit is correlation the observation model does not have.** With the white noise
  replaced by an AR(1) process of the same marginal sd, the rate is **0.96 at
  ρ = 0.3** and **0.79 at ρ = 0.6** (400 records each). The method's guarantee is for
  the noise the benchmark draws, which has no such correlation. A real plant's record
  might, and this analysis would then admit alternatives more often than α says. The
  test checks that the rate falls with ρ.

## 4. The Level-0 requirement

Before any sweep, `none` must be admissible on every Level-0 cell: S0-01 on Plants B and
C, at Tiers A, B and C. The truth's class must also be admissible on S2-03 C/B, S2-02 C/B
and one S5 cell. The results and the time per cell are in the PR (§6 below).

## 5. Outputs

- `truth_store/<id>/admissible.json`, per run (method version 4). It holds:
  - for each class: the deviance, *k*, the candidate count, the penalty, the score and
    its distance from the best, the best candidate's knobs, and the deviance per sensor;
  - the admissible sets at both margins, `n_admissible`, `chance_rate` and
    `none_admissible`;
  - `truth_admissible`, `truth_representable` and `truth_class_limited`;
  - the reproduction check (`truth_reproduced_max_abs`), the truth candidate's own
    deviance, and the simulation counts and time.

  It sits beside the answer key. A workflow can never read it.
- **The chance rate** of the second score is |A ∪ truth| / 6: what a uniform guess over
  the six labels scores. The CLI stratifies by it.
- `eval/` reads the file when its method version is the configured one. It adds the
  columns `admissible_set`, `n_admissible`, `admissible_chance_rate`,
  `truth_admissible`, `truth_representable`, `attribution_admissible` (primary label in
  *A* ∪ truth) and `attribution_admissible_set` (every final label in *A* ∪ truth).
  Without the file these columns are `None`, and every existing column is unchanged.
- `reports/p0_distinguishability.{csv,json}`: the per-cell table, and the P0 sweep
  scored with both columns side by side.

## 6. Compute

The simulations are shared by the tiers of a (scenario, plant) pair. The fits are
closed-form or grid look-ups, so they cost seconds per tier.
- **Per pair.** On a 200-d cell a pair takes about 100 simulations. A 365-d Plant A
  cell takes about 165, because the grids cover a longer calibration window. The 32
  pairs of Levels 0–5 come to about 3,400 simulations.
- **Timing.** Measured at 13–14 s each (200 d), that is about PLAN runner-hours, well
  within one sweep (~100 runner-hours).
- **Caching and failures.** `--cache-dir` keeps every simulation, so a re-analysis
  integrates nothing. Every simulation has a 180 s timeout. A candidate that times out
  or that the simulator refuses is reported (`simulation_failures`) and is not scored.

## 7. Where the code lives

`distinguish/` is a top-level package (listed in `pyproject.toml`), run outside every
sandbox. The rule-1 checker forbids it to workflows, by import and by the
`"distinguish..."` string form. `eval/` reads its precomputed file without importing
it.
