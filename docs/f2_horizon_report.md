# F2 — equalising every scenario's horizon: the measurements and a recommendation

*G1 remediation session, 2026-09-10, for the coordinator and the lead. Measured at
`6e258f6` (the F1/F3/F4/F5/F6 head of PR #15, CI green) with `duration_days: 240` on all
twenty scenarios held **locally and uncommitted**. Nothing was tuned, no tolerance was
widened, no seed, feed, tank, calibration or kinetic constant was touched, and nothing has
been regenerated.*

**Verdict in one line:** 240 d is safe for every row except that `biogas_mean` moves
0.019 outside its declared band for a reason that is the comparison's basis, not the
simulator; a shorter common horizon (200 d) keeps every anchored row in band but does not
keep every answer key right, because the S7-02 structural signal is a pathway shift that
does not complete even at 240 d — and that last fact predates F2 and needs the lead's call
regardless of the horizon.

## 1. The ruling, and what changed

`duration_days` and the derived `n_days` are public (they are in the redacted manifest).
Until the ruling they took two values — 180 d for Levels 0–4 and 8, 240 d for Levels 5–7 —
which partitioned the ladder: a Plant B/C run at 240 d was exactly one of {S5-02, S6-02,
S6-03, S7-01}; a Plant A run at Tier A and 180 d was the Level 2–4 subset. With F1 that was
complete de-anonymisation. The lead ruled every horizon be equalised to 240 d.

In the working tree: `duration_days: 240` on all twenty scenarios (twelve were 180 d);
nothing else in any scenario. `scenarios/README.md` says so, `tests/test_scenario_schema.py`'s
pin moved with it, the anchor panel (`anchor.compare_generated.OUTPUT_DAYS`) runs at the
matrix horizon, and S3-03's header notes that its ramp holds after d180.

## 2. Anchored rows at 240 d — which moved, which are outside their band

24-seed Plant B clean panel (seeds 1000–1023), settled from day 30, `OUTPUT_DAYS`
180 → 240. The 18 influent rows come from a separate 730-d draw and do not move.

| row | at 180 d (committed report) | at 240 d | declared band | status |
|---|---:|---:|---|---|
| `biogas_mean` (m³/d per digester) | 3143, ratio **1.489** | 3207, ratio **1.519** | ratio in [0.6, 1.5] | **OUTSIDE by 0.019 in ratio (≈ 40 m³/d)** |
| `digester_pH_median` | 7.232 | 7.218 | 7.27 ± 0.4 | inside |
| `alkalinity_median` (calibrated row, not counted) | 5.116 | 4.939 | ± 35 % | inside |
| `vfa_median` | 0.780 (ratio 0.66) | 0.757 (ratio 0.64) | ratio in [0.25, 4] | inside |
| `fos_tac_median` | 0.151 (ratio 0.65) | 0.151 (ratio 0.65) | ratio in [0.5, 2] | inside |

Exactly one row is outside: `biogas_mean`, the one the coordinator expected. No other row
is within 5 % of an edge. 22 of 23 rows in band; 21 of 22 independent rows.

## 3. Why `biogas_mean` moves — seasonal phase, not a change of state

Every cell starts at day-of-year 1. The settled window at 180 d is 31 Jan – 29 Jun; at
240 d it runs on to 28 Aug, into the late-summer peak of the trucked feeds (high-strength
waste and FOG seasonal peaks at day 250 with log-amplitudes 0.25 and 0.20; primary sludge
peak at day 200, amplitude 0.10). Panel-mean inflow by 30-day month over days 0–240: 105,
105, 101, 103, 110, 117, 113, 119 m³/d; panel-mean gas: 3021, 3020, 2747, 2784, 3036,
3575, 3521, 3671 m³/d. Months 6–8 carry 10–15 % more feed and 15–25 % more gas than
months 2–5, and 21 of 24 seeds have a higher gas mean over days 180–240 than over days
30–180. The anchor's `biogas_mean` is the mean of the whole three-year Muscatine daily
record, all seasons. The row therefore compares a partial-year window against an annual
mean, and extending the window into the high season raises the ratio. The steady state is
unchanged: alkalinity median 4.93 → 4.89 across the two windows, pH flat.

One second-order effect, already recorded as dormant-but-horizon-sensitive in the
decisions log: the equalisation tank is initialised from the whole-horizon mean of
arrivals, so the first 180 days of a 240-d run are not bit-identical to a 180-d run (the
30–180 window inside the 240-d runs gives a panel median of 3079 rather than 3143). Same
conclusion either way.

**The ratio at every common horizon**, same 24 runs, panel median of the settled mean:

| common horizon (d) | 180 | 190 | **200** | 210 | 220 | 230 | 240 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `biogas_mean` ratio | 1.459 | 1.452 | **1.447** | 1.471 | 1.486 | 1.517 | 1.519 |

Any single value up to 220 d removes the partition and keeps the row in band; 200 d has
the widest margin (the window closes before the summer load rises).

## 4. Plant B souring at 240 d

**24/24 sound**, unchanged from 180 d; no seed sours at any day. The matrix's own 117 cells
at 240 d (scratch generation, §8): 117/117 sound. The souring pin was not touched.

## 5. Both triggers on all four rows at 240 d

24 seeds each, clean Level-0, settled from day 30; the 180-d value in brackets.

| Plant | baseline | overload pooled | per-run range | runs firing | foaming pooled | per-run range | runs firing | FOS/TAC > 0.40 | > 0.30 |
|---|---|---:|---|---:|---:|---|---:|---:|---:|
| **B** | — | **8.18 %** (7.67) | 3.32 – 13.27 % | 24/24 | **8.47 %** (7.20) | 2.84 – 13.27 % | 24/24 | 0.00 % (was 0.17) | 0.00 % (was 0.25) |
| **C** | — | **9.28 %** (9.22) | 3.79 – 12.32 % | 24/24 | **8.18 %** (7.67) | 3.32 – 12.32 % | 24/24 | 0.00 % | 0.00 % |
| **A** | `unadapted` | **1.72 %** (1.49) | 0.00 – 4.27 % | 23/24 | **0.24 %** (0.14) | 0.00 – 0.95 % | 11/24 | 0.00 % | 0.00 % |
| **A** | `adapted` | **0.39 %** (0.28) | 0.00 – 1.42 % | 13/24 | **0.38 %** (0.25) | 0.00 – 1.42 % | 14/24 | 0.00 % | 0.00 % |

B and C still bracket the anchor's 7.78–9.18 % exceedance on overload and sit at it on
foaming, in every run. The Plant A pathway ordering holds on overload (`unadapted` 4.4×
`adapted`; 5.3× at 180 d); the foaming reversal noted at 180 d has shrunk to parity within
noise (0.24 % against 0.38 %, 11 against 14 firing runs). The one run that exceeded the
operator's 0.40 at 180 d (seed 1021) does not at 240 d; neither operator threshold fires on
any run of the four panels.

## 6. Answer keys — which depend on the horizon

**The twelve rows that grew from 180 to 240 d.** Each fault starts at its declared onset
and runs further; none of these answer keys depends on the horizon:

| row | fault timing | at 240 d | key unchanged because |
|---|---|---|---|
| S0-01 | none | 60 more clean days | nothing to detect; a false positive is still the failure |
| S1-01 | noise ×2, gaps ×2 from d0 | same rates, 60 more days | MCAR by construction |
| S2-01 | pH drift −0.01/d from d45, reset on the tier's recalibration cadence | more drift-and-step repeats | the pattern is what is diagnosed |
| S2-02 | CH₄ analyser flatline d90–96 | unchanged window | a 6-day episode inside the run |
| S2-03 | gas-meter scale ×1.08 from d60 | 180 faulted days instead of 120 | constant scale from the onset |
| S3-01 | mislabelled feed d60–120 | unchanged window | the batch is the batch |
| S3-02 | unrecorded delivery at d90 | unchanged | one day's balance failure |
| S3-03 | moisture ramp −30 % over d30–180 | ramp unchanged, then **held** at −30 % to d240 (`_ramp_factor` holds after its window) | a trend to a new level; the plateau makes it more identifiable |
| S4-01 | biomass mis-initialised at d0 | 60 more settled days | the transient's timing and shape are the evidence |
| S4-02 | informative missingness from d0 | both hidden-state triggers fire throughout | scaling of the multipliers |
| S8-01 | gas-meter fault from d60; `bayes_mcmc` fails | as S2-03 | same fallback task |
| S8-02 | gas-meter fault from d60; false note at d75 | as S2-03 | the note is false about the same cause |

**The eight rows already at 240 d** are untouched by F2. But checking whether a *shorter*
common horizon would keep their keys right turned up a finding that predates F2:

### The S5-01 / S7-02 pathway shift does not complete at any horizon, on any tree since 2026-09-03

Measured through the full harness at each scenario's own seed, Plant A adapted baseline,
end-of-run state (X in kg COD/m³, acetate in kg/m³):

| tree | S5-01 X_ac / X_sao at 240 d | S5-01 acetate d119 → 240 | S7-02 X_ac / X_sao at 240 d | S7-02 acetate d119 → 240 |
|---|---:|---:|---:|---:|
| `42bbe8e` (2026-09-03, the ruling-2 commit) and every commit through `fd76983` (09-09) | 0.839 / **0.154** | 0.033 → 2.83 | 1.129 / **0.090** | 0.031 → 1.14 |
| `39d0e14` (after the liquor ruling) | 0.967 / 0.071 | 0.027 → 1.46 | 1.186 / 0.028 | 0.027 → 0.66 |
| current (`6e258f6`, identical from `c8c048f` onward) | 0.934 / **0.092** | 0.028 → 1.76 | 1.171 / **0.039** | 0.028 → 0.78 |

SAO biomass share (X_sao / (X_ac + X_sao)) at the end of the run on the current tree, by
horizon: S5-01 **1.2 % / 3.6 % / 9.0 %** and S7-02 **0.4 % / 1.0 % / 3.2 %** at
200 / 220 / 240 d. All runs sound.

The record says otherwise: `scenarios/S7-02.yaml` and the decisions entry of 2026-09-03
("the feed re-seeds syntrophic oxidisers") state as *measured* that the transition takes
X_sao from 7e-5 to **0.60** while the acetoclasts fall from 1.2 to **0.46** in 240 d, and
the truth-side plant record repeats "SAO grows in and takes over inside the horizon". That
number is not reproduced at `42bbe8e` — the commit that recorded it, with the reseeding
term in place — nor at six later commits (`9db569b`, `4a022e8`, `56aeceb`, `fd76983`,
`39d0e14`, current), each run from its own worktree with its own package on the path. It
cannot be traced to a committed state; a different seed, burn-in or constant at the time is
the likely explanation. The later feed changes moved the numbers further, but the takeover
was already absent on the 09-03 tree.

What it means:

- **S5-01** (parameter; `kinetic_update_allowed`): the diagnosable signal is the acetate
  accumulation after d120 — 60–100× within four months, sustained — present and large at
  every horizon from 180 d up. **The key holds.** The header's account of the mechanism
  (a completed takeover) is wrong and needs correcting.
- **S7-02** (structural + parameter; `abstain_on` the pathway split,
  `recommend_structural_review`): the structural half assumes syntrophic oxidation grows in
  and carries the flux so that the SAO-less fitted model's residual grows. At 240 d SAO is
  3 % of the acetate-consuming biomass; at 200 d 0.4 %. The structural residual is small at
  240 d and essentially absent at 200 d. **Whether the key is still right is the lead's
  call** — it is the design change the stop condition names. S6-01 (SAO carries 99.8 % of
  the flux from day 0 on the `unadapted` baseline) and S6-04 are unaffected.

## 7. Budgets

Every declared budget is per workflow and untouched: `simulator_evals` counts
integrations, `assay_units` counts assays, `wall_clock_min` is a wall-clock. A simulator
evaluation of a 240-d cell costs ~1.33× a 180-d one, so the wall-clock budget binds ~25 %
sooner on the twelve rows that grew (at Levels 0–2, 90 min against ~4,000 evaluations —
the count, not the clock, was already the binding constraint). Reported, not changed.

## 8. Generation cost

All 117 cells generated at 240 d into a scratch root outside the repository: 117/117
generated, 117/117 sound, **21.4 min** wall-clock on this container (~10 min at 180 d —
more than the 1.33× the horizon implies, because every cell pays the longer horizon and the
two-segment rows integrate further), **30 MB** under `runs/` and **21 MB** under
`truth_store/` (25 + 17 MB at 180 d), 117 index lines, one per id.

## 9. Recommendation

The `biogas_mean` excursion is **(b)**: an artefact of comparing a February–August window
against an annual-mean anchor, not a degradation the horizon causes and not evidence for a
different horizon. The simulator, tank, calibration and seeds are unchanged.

On the horizon, the three constraints the coordinator set pull against each other, and the
numbers are:

| common horizon | removes the partition | every anchored row in band | every answer key right |
|---|---|---|---|
| **200 d** | yes | **yes** (`biogas_mean` 1.447, the widest margin) | **no** — S7-02's structural signal is 0.4 % SAO share, dead; S5-01's parameter signal is intact |
| 220 d | yes | yes, marginally (1.486) | S7-02 at 1.0 % share, still essentially absent |
| **240 d** | yes | **no** — `biogas_mean` 1.519 against 1.5 | S7-02 at 3.2 % share: thin, and the lead's call either way |

So no single horizon in 180–240 d satisfies all three as the rows stand today, and the
reason is not F2: S7-02's structural half rests on a transition the truth does not perform
inside 240 d on any committed tree. My recommendation:

1. **Equalise at 240 d**, the lead's figure. It keeps the loss-of-adaptation rows exactly as
   designed (120 d after the onset) and gives S7-02 the most structural signal any horizon
   in range offers.
2. **Have the lead re-declare `biogas_mean`'s comparison basis** as a recorded decision —
   either a seasonally matched window on the anchor side (the same days of the year the
   simulated window covers) or a band stated for the window actually compared. That is a
   basis correction, not a widening to pass, and I am not making it on my own because it
   changes a declared tolerance.
3. **Rule on S7-02 separately from F2.** Options the lead may weigh: keep the key and
   accept a thin structural signal (recorded in the card as a known weakness); re-stage the
   row so the structural half is real (for example on the `unadapted` baseline, where SAO
   carries the flux from day 0, which makes it S6-01 plus a parameter fault); or measure
   how long the shift takes to complete on the current feed (a longer probe, off the
   matrix) and decide with that number. In every case the S5-01/S7-02 headers, the
   2026-09-03 decisions entry and the truth-record note must be corrected to the measured
   shift before the freeze.

If the lead prefers 200 d instead: it removes the partition and keeps every anchored row in
band, and S5-01, S6-01, S6-04 and all twelve grown rows keep their keys; only S7-02's
structural half is lost, and it is already close to lost at 240 d.

## 10. Provenance

| | |
|---|---|
| Code | `6e258f6` on `claude/g1-scenario-generation`; the F2 duration edits local and uncommitted |
| Panels | `anchor.compare_generated.output_panel`, seeds 1000–1023, 240 d, settled from d30; Plant A rows via S0-01 restaged on plant A with the baseline named |
| Windowed gas means | one 240-d run per seed, means over [30, H] for H = 180…240 and per 30-day month |
| Pathway shift | `simulate_truth` on S5-01 and S7-02 at their own seeds, at 200/220/240 d on the current tree and at 240 d in worktrees of `42bbe8e`, `9db569b`, `4a022e8`, `56aeceb`, `fd76983`, `39d0e14` (each with its own package on `PYTHONPATH`) |
| Scratch generation | `python -m sim.run.matrix --runs-root <scratchpad>/scratch240/runs`, 1282 s |

## 11. Addendum — S7-02 re-staged on the `unadapted` baseline, measured, not committed

*Requested by the coordinator (07:06 UTC) so the lead can choose with numbers. Nothing in
`scenarios/S7-02.yaml` has changed; the record correction of `3be4ef9` is the only commit.*

**Method.** S7-02 (SAO omitted from the fitted model from day 0; `K_I_nh3` ×0.1 at day 120)
integrated through the full harness at its own seed on each baseline and horizon. Then an
**SAO-less fitted model** — the truth's extensions less `sao`, the true geometry, the same
influent, started from the truth's own burn-in state — integrated over the same grid in two
variants: *shift known* (the fitted model is handed the true parameter trajectory, so any
residual is purely structural) and *shift unknown* (the fitted model keeps the pre-onset
constant, so the residual is structural plus parameter). Residuals are fitted minus truth,
over the pre-onset window (days 30–120) and the post-onset window (120–H). Gas and CH₄ are
relative; acetate is absolute in kg COD/m³ (S_ac).

**The truth on each baseline**

| baseline | H | sound | SAO share of acetate-consuming biomass, d119 → end | X_ac / X_sao at end | acetate d119 → end (peak after onset), kg COD/m³ | gas mean pre → post onset, m³/d |
|---|---:|---|---|---:|---|---|
| `adapted` (as it stands) | 200 | yes | 0.000 → **0.004** | 1.154 / 0.004 | 0.036 → 1.27 (2.72) | 437 → 449 |
| `adapted` (as it stands) | 240 | yes | 0.000 → **0.032** | 1.171 / 0.039 | 0.029 → 0.84 (2.98) | 445 → 470 |
| `unadapted` (re-staged) | 200 | yes | **0.998 → 1.000** | 0.000 / 0.963 | 0.227 → 0.23 (0.58) | 421 → 442 |
| `unadapted` (re-staged) | 240 | yes | **0.998 → 1.000** | 0.000 / 0.983 | 0.179 → 0.25 (0.63) | 429 → 463 |

On the `unadapted` baseline SAO carries the whole acetate flux from day 0 and **the
parameter fault does nothing to the truth**: the constant it moves belongs to a population
that is not there (X_ac ≈ 0), so acetate and gas do not react to the onset at all.

**The structural residual an SAO-less fitted model sees**

| baseline | H | variant | gas, post-onset: mean rel / rms rel | CH₄ fraction, post: mean rel | acetate, post-onset: mean abs / rms (kg COD/m³) | acetate at end: truth / fitted | gas at end: truth / fitted |
|---|---:|---|---|---:|---|---|---|
| `adapted` | 200 | shift known (structural only) | −0.000 / 0.000 | −0.0001 | **+0.006 / 0.008** | 1.27 / 1.29 | 434 / 434 |
| `adapted` | 200 | shift unknown (structural + parameter) | +0.007 / 0.109 | +0.010 | −1.25 / 1.37 | 1.27 / 0.04 | 434 / 429 |
| `adapted` | 240 | shift known (structural only) | −0.001 / 0.005 | −0.0008 | **+0.056 / 0.099** | 0.84 / 1.03 | 435 / 433 |
| `adapted` | 240 | shift unknown (structural + parameter) | +0.008 / 0.102 | +0.010 | −1.65 / 1.83 | 0.84 / 0.04 | 435 / 445 |
| `unadapted` | 200 | shift known | −0.587 / 0.614 | −0.35 | +22.6 / 24.4 | 0.23 / 32.5 | 414 / 99 |
| `unadapted` | 200 | shift unknown | +0.035 / 0.132 | −0.014 | +1.90 / 2.00 | 0.23 / 2.02 | 414 / 427 |
| `unadapted` | 240 | shift known | −0.612 / 0.635 | −0.50 | +25.2 / 27.0 | 0.25 / 29.7 | 436 / 137 |
| `unadapted` | 240 | shift unknown | +0.027 / 0.116 | −0.016 | +2.43 / 2.62 | 0.25 / 2.12 | 436 / 432 |

Pre-onset (days 30–120), the same fitted model: on `adapted` the residual is zero on every
channel (the omitted pathway carries nothing); on `unadapted` it is already large — gas
+5–6 % (rms 0.14), acetate **+6.1 kg COD/m³** — because the fitted model has no route for
the acetate the truth's SAO consumes. That is S6-01's residual, from day 0.

**Reading.**

- **As it stands (`adapted`), the structural half is faint.** With the parameter shift
  known, the SAO-less model reproduces gas and CH₄ to better than 0.1 % (200 d) and 0.5 %
  (240 d); the only structural trace is acetate, +0.006 kg COD/m³ mean over the post-onset
  window at 200 d and +0.056 at 240 d (0.2 kg COD/m³ by the last day, where the truth's SAO
  has started to draw acetate down). A workflow would have to detect a late, acetate-only
  divergence of 5–20 % against a 1–3 kg COD/m³ accumulation the parameter fault itself
  causes. The parameter half is loud (gas rms 10 %, acetate off by 1.3–1.7 kg COD/m³ if the
  shift is not modelled). **At 200 d the row is a parameter row with a structural label on
  it; at 240 d the structural half exists but is small.**
- **Re-staged on `unadapted`, the halves swap.** The structural residual is large and
  present from day 0 (gas +5 %, acetate +6 kg COD/m³ before the onset; after the onset a
  fitted model that keeps the adapted constant is off by 2–2.4 kg COD/m³ and 12–13 % rms on
  gas, and one that takes the shift sours outright, gas −60 %) — the S6-01 signal, properly
  diagnosable. But the parameter fault is a phantom: it moves a constant of a population the
  truth does not have, and no observable reacts to it. **The `parameter` label and
  `kinetic_update_allowed: true` would then rest on nothing a workflow can see**, which
  turns the "partial attribution, abstain on the confounded part" design into a row whose
  correct answer is the S6-01 answer plus a fault that cannot be attributed because it has
  no effect.
- Either way the compound row degenerates towards a single-fault row on the current feed;
  which half survives is the choice. Neither horizon repairs it: 200 → 240 d moves the
  `adapted` structural residual from ~0 to small, and does nothing on `unadapted`.

**Options for the lead, with the numbers above** (none taken): (a) keep S7-02 as staged
and record in the card that its structural half is small at 240 d and that abstention on
the pathway split is the safe answer — honest, but the row then scores mostly on S5-01's
signal; (b) re-stage on `unadapted` and change the key to S6-01's (drop `parameter`, drop
`kinetic_update_allowed`), which makes it a duplicate of S6-01 at Tier C with an inert
fault attached — probably not worth a row; (c) give the transition longer or a stronger
push (an earlier onset, or a horizon well beyond 240 d — outside F2's equalised value) so
the shift completes on the `adapted` baseline and the compound row means what its header
says; the time to completion on the current feed is not yet measured and would need a probe
run off the matrix; (d) retire S7-02 from the frozen library and carry the compound
structural-plus-parameter idea as a Level-7 row to be designed against a measured
transition after the freeze.

Provenance: `<scratchpad>/restage_s702.py`, run at `3be4ef9`; results in
`restage_s702.json` (not committed).

