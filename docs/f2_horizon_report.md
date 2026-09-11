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
complete de-anonymisation. The finding is **review finding F2** of the final whole-branch
review (not the lead's); the lead ruled on it — first 240 d, later revised on the
measurements below (§13–§15) — and every ruling in this report is the lead's response to
that finding.

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

## 12. Addendum — an earlier loss-of-adaptation onset: does the shift complete on `adapted`?

*Requested by the coordinator (07:17 UTC) to decide between (c) make the shift complete and
(d) retire. S7-02 and S5-01 on the `adapted` baseline as staged, with the
`ammonia_inhibition_shift` onset moved from day 120 to day 60 and to day 30, at 200 and
240 d. Same method as §11 (truth through the harness at each row's own seed; for S7-02 the
SAO-less fitted model, shift known and unknown). No scenario file changed.*

**S7-02 — the truth, and the structural residual with the shift known**

| onset | H | sound | SAO share at end (X_ac / X_sao) | acetate onset → peak (day) → end, kg COD/m³ | structural residual, post-onset: gas mean / rms rel | acetate mean / rms abs | acetate at end, truth / fitted | gas at end, truth / fitted |
|---:|---:|---|---|---|---|---|---|---|
| 120 (as staged, §11) | 200 | yes | **0.4 %** (1.154 / 0.004) | 0.04 → 2.72 → 1.27 | −0.000 / 0.000 | +0.006 / 0.008 | 1.27 / 1.29 | 434 / 434 |
| 120 (as staged, §11) | 240 | yes | **3.2 %** (1.171 / 0.039) | 0.03 → 2.98 → 0.84 | −0.001 / 0.005 | +0.056 / 0.099 | 0.84 / 1.03 | 435 / 433 |
| 60 | 200 | yes | **4.5 %** (1.104 / 0.052) | 0.04 → 2.67 (d145) → 1.04 | −0.000 / 0.003 | +0.044 / 0.070 | 1.04 / 1.28 | 437 / 434 |
| 60 | 240 | yes | **20.3 %** (0.926 / 0.236) | 0.05 → 2.58 (d208) → 0.53 | +0.001 / 0.030 | +0.255 / 0.492 | 0.53 / 1.03 | 444 / 433 |
| 30 | 200 | yes | **14.0 %** (0.982 / 0.160) | 0.05 → 2.61 (d47) → 0.71 | −0.000 / 0.011 | +0.114 / 0.181 | 0.71 / 1.28 | 437 / 434 |
| 30 | 240 | yes | **37.5 %** (0.697 / 0.419) | 0.04 → 2.62 (d61) → 0.42 | +0.002 / 0.039 | +0.408 / 0.736 | 0.42 / 1.03 | 446 / 433 |

With the shift *unknown* to the fitted model (structural + parameter) every onset gives the
same loud parameter signal as before: gas rms 10 %, CH₄ +0.6–0.8 %, acetate −1.1 to −1.2
kg COD/m³ mean (the fitted model predicts 0.04 where the truth has 0.4–1.0).

**S5-01 — the truth (key check)**

| onset | H | sound | SAO share at end (X_ac / X_sao) | acetate onset → peak (day) → end, kg COD/m³ | CH₄ at end | pH at end |
|---:|---:|---|---|---|---:|---:|
| 120 (as staged) | 240 | yes | 9.0 % (0.934 / 0.092) | 0.03 → ~1.8 → 1.76 | — | — |
| 60 | 200 | yes | 21.3 % (0.857 / 0.232) | 0.05 → 4.13 (d179) → 0.80 | 0.617 | 7.71 |
| 60 | 240 | yes | 47.3 % (0.512 / 0.459) | 0.04 → 3.94 (d96) → 0.44 | 0.625 | 7.72 |
| 30 | 200 | yes | 42.5 % (0.591 / 0.436) | 0.05 → 4.18 (d75) → 0.50 | 0.613 | 7.71 |
| 30 | 240 | yes | **64.6 %** (0.330 / 0.604) | 0.05 → 3.98 (d96) → 0.37 | 0.626 | 7.73 |

**Reading.**

- **The shift does complete on `adapted` — it needs ~200 days after the onset, not 120.**
  S5-01 with the onset at day 30 reaches X_sao 0.60 against X_ac 0.33 by day 240, which is
  the figure the 2026-09-03 record claimed; so that measurement was almost certainly made
  with the onset early in the run (or a longer post-onset run), and the row was later
  staged with the onset at day 120, leaving 120 days for a transition that takes 200. The
  record correction of `3be4ef9` stands as written (the claim is not reproducible *as the
  rows are staged*); this addendum says why.
- **On S7-02 the shift is slower** (a different seed, hence a different influent draw, and
  the same seed on the same row gives 37.5 % where S5-01 gives 64.6 % at onset 30 / 240 d),
  but at onset 30 it is well past single digits by day 240 and still climbing: X_sao 0.42
  against X_ac 0.70, the acetoclasts down 40 % from their onset value.
- **What the structural residual looks like when it exists.** With the shift known, the
  SAO-less model matches gas to within 4 % rms and CH₄ to 0.3 % even at onset 30 / 240 d —
  both pathways turn acetate into methane, so the *route* changes and the gas barely
  does. The structural signature is **acetate only**: the SAO-less model holds acetate at
  ~1.0 kg COD/m³ while the truth draws it down to 0.42 (onset 30) or 0.53 (onset 60) by day
  240 — a factor of 2–2.5 by the last day, a mean gap of 0.25–0.41 kg COD/m³ over the
  post-onset window, growing month by month. That is kg-scale on acetate, in a Tier C
  record with weekly speciation at 8 % noise, and it is **not** tens of per cent on gas; it
  is a different kind of signal from `unadapted`'s (+6 kg COD/m³ and +5 % gas from day 0),
  because there the fitted model has no route at all for the acetate, while here it has
  one that is merely being inhibited.
- **The parameter fault still acts on a population that exists at the onset**: X_ac 1.10–1.21
  at day 30 or 60 on every run, the acetate spike to 2.6 kg COD/m³ follows within a month,
  and the parameter half stays loud. Nothing becomes a phantom.
- **The cost of an early onset is the short clean baseline**: at onset 30 a workflow has
  one month of adapted operation to learn the plant before the acetate spike; at onset 60
  it has two, and the share at 240 d is 20 % rather than 37 %. Both runs stay sound.
- **S5-01's key holds at every onset** and the row becomes richer, not weaker: acetate
  rises 80–100× to ~4 kg COD/m³ within 45–70 days of the onset and then **recovers** as
  syntrophic oxidation takes over (to 0.4–0.8 by the end). A bounded update of the
  inhibition constant is still the correct action; the recovery is the pathway shift the
  header describes, now actually visible in the record.

**Answer to the question asked.** Yes: at onset 30, S7-02 at 240 d carries a completed-enough
shift (37.5 % SAO share, rising) for the compound row to mean what its header says with a
**one-field change** (`onset_day: 120 → 30`), and S5-01 moved with it reaches the takeover
the record claimed (64.6 %). The structural residual that results is acetate-only and
grows to a factor of ~2.5 by day 240 — unmistakable on the acetate channel, invisible on
gas. If the lead requires a gas-scale structural residual, no onset on `adapted` provides
it and (d) is the answer; if an acetate-scale one is acceptable, (c) with onset 30 (or 60,
trading half the share for a two-month baseline) is viable at 240 d and marginal at 200 d
(14 % / 4.5 %). Onset 120 as staged is not viable at either horizon.

Provenance: `<scratchpad>/probe_onset.py` at `3be4ef9`; results in `probe_onset.json` (not
committed). Nothing in `scenarios/` changed.

## 13. STOP — at a real 200-d horizon `biogas_mean` is out of band, and §3's horizon table was wrong

*Status line for the coordinator: 200 d NOT committed — the 200-d panel fails the anchor
gate; §12 pushed; holding for the lead.*

**What was measured** (24-seed Plant B clean panel generated *at* 200 d, `OUTPUT_DAYS = 200`,
settled from day 30; the report block regenerated at 200 d says the same):

| row | at 180 d | at 200 d (real panel) | at 240 d (real panel) | declared band | status at 200 d |
|---|---:|---:|---:|---|---|
| `biogas_mean` | 3143, ratio 1.489 | **3216, ratio 1.523** | 3207, ratio 1.519 | ratio in [0.6, 1.5] | **OUTSIDE by 0.023** |
| `digester_pH_median` | 7.232 | 7.226 | 7.218 | 7.27 ± 0.4 | inside |
| `alkalinity_median` (calibrated) | 5.116 | 5.046 | 4.939 | ± 35 % | inside |
| `vfa_median` | 0.780 | 0.771 (ratio 0.65) | 0.757 | ratio in [0.25, 4] | inside |
| `fos_tac_median` | 0.151 | 0.151 (ratio 0.65) | 0.151 | ratio in [0.5, 2] | inside |

Souring: **24/24 sound** at 200 d. Triggers at 200 d, Plant B: overload **8.92 %** pooled
(per-run 4.09–16.37 %, 24/24), foaming **8.72 %** (2.34–16.96 %, 24/24), FOS/TAC > 0.40 and
> 0.30 both 0.00 %. Plant A `adapted`: overload 0.29 % (8/24), foaming 0.22 % (6/24). The
Plant C and Plant A `unadapted` rows at 200 d are still computing and will be added.

**Why §3's table was wrong, stated plainly.** The per-horizon ratios in §3 (1.447 at 200 d,
"widest margin") were **not** measured on 200-d runs. They were the settled means over
days 30–H *inside the 240-d runs*. A 200-d run is not the first 200 days of a 240-d run:
the equalisation tank is initialised from the whole-horizon mean of arrivals (recorded in
the decisions log as dormant-but-horizon-sensitive), and the generator's realisation
depends on `n_days`, so the trajectories differ from day 0. The difference is not small
for this row — the windowed estimate at 200 d was 3055, the real 200-d panel is 3216
(5 %). I presented a windowed estimate as if it were a horizon measurement, and the lead's
choice of 200 d was made on it. That was my error; the caveat in §3 about the tank was
there but I did not act on it. Real fixed-horizon panels at 190, 210 and 220 d are running
now and will replace §3's table (§14), so the lead has a true curve.

**What the real numbers say so far.** On real panels the row sits at the band edge at every
horizon measured — 1.489 (180 d), 1.523 (200 d), 1.519 (240 d) — so **the horizon does not
decide this row**; 180 d was inside by 0.7 % of its margin and both equalised horizons are
outside by ~0.02. Everything else in the 200-d ruling stands: the partition is removed at
any single value, every other anchored row is inside, souring is 24/24, every answer key
that holds at 240 d holds at 200 d (S5-01 included), and S7-02 is the separate question.

**Recommendation, revised.** Keep 200 d (or whichever single value the lead prefers once
§14 is in), and rule on `biogas_mean`'s **comparison basis or band** as a recorded decision:
the simulated figure is a 170-day settled mean of a February–July window with a
tank-initialisation transient at its head, compared against a three-year annual mean; the
row has been within ±0.03 of the band edge on every panel since the calcium ruling and was
already named "the row to watch". I am not widening the band and not touching the tank,
calibration or seeds. The 200-d edits (all twenty scenarios, the README, the schema pin,
`OUTPUT_DAYS`, the decisions entry, the regenerated report block) are held locally,
uncommitted, until the lead rules.

## 14. The true horizon curve — measured on real panels, one per horizon

*Status line: 200 d NOT committed; real-panel curve below; the row's horizon dependence is
the tank initialisation, not the season; holding for the lead.*

**`biogas_mean` on the 24-seed Plant B clean panel, each panel generated at its own
horizon** (`OUTPUT_DAYS` = H, settled from day 30, panel median of the settled mean, anchor
2111 m³/d):

| horizon (d) | 180 | 190 | 200 | 210 | 220 | 240 |
|---|---:|---:|---:|---:|---:|---:|
| `biogas_mean`, m³/d | 3143 | 3058 | 3216 | 3071 | 3274 | 3207 |
| ratio to the anchor | 1.489 | **1.449** | **1.523** | **1.455** | **1.551** | 1.519 |
| against [0.6, 1.5] | in | in | **out** | in | **out** | out |
| sound | 24/24 | 24/24 | 24/24 | 24/24 | 24/24 | 24/24 |
| overload trigger, pooled | 7.67 % | 7.87 % | 8.92 % | 8.13 % | 8.42 % | 8.18 % |
| foaming trigger, pooled | 7.20 % | 6.70 % | 8.72 % | 8.29 % | 8.18 % | 8.47 % |

Every other anchored row is inside its band at every horizon (§13's table for 200 d; the
190/210/220 panels likewise: 22 of 23 rows in, only `biogas_mean` moves against its edge).

**What the curve says.** It is not a curve: the row jumps by ±5 % between horizons ten
days apart (3058 → 3216 → 3071 → 3274), with no trend. That is not the seasonal window §3
described — a window effect is smooth and monotone over ten-day steps — it is the
**horizon-dependent initial state**: the equalisation tank on Plant B is initialised from
the whole-horizon mean of arrivals, so every horizon starts the digester from a different
day-0 tank content, and the realisation the generator draws differs with `n_days` as well.
Those two effects re-roll the early months of every run, and the settled mean over
days 30–H carries the re-roll. The decisions log of 2026-09-10 recorded exactly this
initialisation as "dormant-but-fault-sensitive", left for the lead because the fix
(initialise from the first hold-up window) moves every Plant B cell. It is **not dormant**:
it makes an anchored row horizon-sensitive by 5 %, which is more than the row's whole
margin to its band edge. The seasonal effect of §3 is real but second order beside it.

**So the row is a coin flip against its edge**, whatever the horizon: 1.449–1.551 across
six horizons on the same feed, the same seeds and the same calibration, band edge 1.5. The
180-d figure that was "inside by 0.7 % of its margin" was one draw of that coin.

**Recommendation, third and last revision, with the reasons.**

1. **The horizon does not fix this row and should not be chosen to.** Any single value
   removes the partition; the lead's other reasons for 200 d hold at 190 or 210 as well
   (every other row in, souring 24/24, every key that holds at 240 d holds). If the lead
   wants a horizon that is in band *on today's panel*, **210 d** is (1.455) and keeps 90
   post-onset days for the loss-of-adaptation rows; but the number above says that
   choosing 210 d because it is in band is choosing the lucky draw.
2. **The honest fix is the tank initialisation**, which is the lead's call and a change to
   the truth model at the freeze: initialise the buffer from the first hold-up window (the
   recorded fix), so the day-0 state stops depending on the horizon. It moves every Plant B
   and C cell; the panel would be re-measured and every anchored row re-checked. I have not
   touched it and will not without the ruling.
3. **Otherwise rule on the row's basis or band**: a 24-seed 150–210-day settled mean with a
   re-rolled head, compared to a three-year annual mean, has never been better than 0.7 %
   inside its edge since the calcium ruling; it is a measured fact about the comparison,
   recorded rather than tuned.

**The other rows at 200 d, for completeness** (24 seeds each; 180-d values in brackets):

| Plant | baseline | sound | overload pooled | per-run | runs | foaming pooled | per-run | runs |
|---|---|---|---:|---|---:|---:|---|---:|
| B | — | 24/24 | 8.92 % (7.67) | 4.09–16.37 % | 24/24 | 8.72 % (7.20) | 2.34–16.96 % | 24/24 |
| C | — | 24/24 | 9.14 % (9.22) | 2.34–14.04 % | 24/24 | 7.43 % (7.67) | 2.92–12.28 % | 24/24 |
| A | `unadapted` | 24/24 | 1.36 % (1.49) | 0.00–4.09 % | 21/24 | 0.12 % (0.14) | 0.00–2.92 % | 1/24 |
| A | `adapted` | 24/24 | 0.29 % (0.28) | 0.00–2.34 % | 8/24 | 0.22 % (0.25) | 0.00–1.75 % | 6/24 |

Operator FOS/TAC > 0.40 and > 0.30: 0.00 % on every row (one run on B at 220 d, 0.04 %).

Nothing is committed beyond this report. The 200-d edits are held locally; no tolerance,
tank, calibration or seed has been touched; nothing has been regenerated.

## 15. The tank-initialisation fix, measured — and the real cause of the jitter

*Status line: §15 pushed: tank-init fix measured; **it is not the cause** (the jitter is
unchanged with it); the cause is the influent generator's non-prefix-stable stream layout,
verified directly; with a prefix-stable layout the jitter collapses and `biogas_mean` lands
**stably at 1.50–1.54, above the band at every horizon** — the row's level is set by the feed
and calibration and the lead must rule on its basis or band; holding. Nothing committed but
this section.*

### 15.1 The tank fix alone

Implemented locally in `sim/plants/equalisation.py` (one call site in the harness passes
the window): the hold-up is set from the first 30 days of arrivals instead of the
whole-horizon mean, and the tank's day-0 level and load from the first hold-up window. The
14 equalisation tests pass unchanged (they call `buffer_series` with the old default).
Plant C has no buffer (checked: only `plant_B.yaml` declares `equalisation`); Plant A
neither.

| Plant B, 24 seeds, panel generated at H | 190 d | 200 d | 210 d |
|---|---:|---:|---:|
| `biogas_mean` ratio, §14 (no fix) | 1.449 | 1.523 | 1.455 |
| `biogas_mean` ratio, **tank fix** | 1.443 | 1.524 | 1.442 |
| m³/d, tank fix | 3046 | 3218 | 3043 |
| souring | 24/24 | 24/24 | 24/24 |
| overload / foaming, tank fix | 8.15 % / 7.01 % | 8.60 % / 8.89 % | 7.30 % / 7.55 % |

**The jitter did not collapse**: the fix moves the row by less than 1 % at every horizon and
the ±5 % pattern between horizons ten days apart is intact. §14's attribution of the
jitter to the tank initialisation was **wrong**; the tank contributes under a percent.
Plant C (9.14 % / 7.43 %) and both Plant A rows are bit-identical with the fix, as they
should be; S5-01 and S7-02 at onset 30 / 200 d reproduce §12 exactly (42.5 % / 14.0 %).

### 15.2 The real cause, verified directly

The influent generator draws, per feed in order, seven blocks of length `n_days` from
**one** stream (`sim/influent/generator.py`, the "Randomness" paragraph, which states it:
"the blocks are `n_days` long, so the horizon is not prefix-stable: a 100-day run is not the
first 100 days of a 200-day run"). A block of a different length shifts every later block,
so changing the horizon re-rolls every feed from day 0 — the first feed included, because
its second block starts where its first ends. Tested: the same seed at 190 and 200 d on
Plant B gives deliveries that differ on every feed from day 0 (relative differences of
order 1–10¹⁴ against zero-delivery days). **Every horizon is a different 24-seed panel**, and
the row's ±5 % "curve" is the sampling spread of a 24-seed median, not a horizon effect.

### 15.3 A prefix-stable layout, measured (local, committed nowhere)

Each block drawn from its own child stream keyed by `(seed, feed, block)` and each assay's
noise by `(seed, feed, assay)`; the fractionation draw stays at the head of the main
stream; the fault layer keeps its own seed. Verified: a 200-d run's first 190 days equal the
190-d run on every feed's deliveries and moisture, the influent series and the
fractionation. Measured **with the tank fix as well**:

| Plant B, 24 seeds, panel generated at H | 190 d | 200 d | 210 d |
|---|---:|---:|---:|
| `biogas_mean`, m³/d | 3174 | 3244 | 3239 |
| ratio to the anchor | **1.504** | **1.536** | **1.534** |
| against [0.6, 1.5] | out by 0.004 | out | out |
| `digester_pH_median` (band 7.27 ± 0.4) | 7.228 | 7.227 | 7.224 |
| `alkalinity_median` (calibrated) | 4.911 | 4.912 | 4.923 |
| `vfa_median` (ratio band 0.25–4) | 0.743 (0.63) | 0.744 (0.63) | 0.744 (0.63) |
| `fos_tac_median` (ratio band 0.5–2) | 0.151 (0.65) | 0.151 (0.65) | 0.151 (0.65) |
| souring | 24/24 | 24/24 | 24/24 |
| overload trigger | 7.04 % (24/24) | 7.12 % (24/24) | 6.86 % (24/24) |
| foaming trigger | 6.52 % (24/24) | 6.63 % (24/24) | 6.42 % (24/24) |
| FOS/TAC > 0.40 / > 0.30 | 0 / 0 | 0 / 0 | 0 / 0 |

**The jitter collapses.** The three horizons sit within 2 % of each other on every quantity
— a smooth, small window effect, which is what a horizon change should do — and the
trigger rates, which jumped by a point between horizons before, now move by 0.3 points.
The layout, not the tank, was the cause.

**Where the row lands.** Stably at **1.50–1.54, above the band edge at every horizon**. The
old layout's 1.489 at 180 d and 1.449/1.455 at 190/210 d were lucky draws of a re-rolled
panel; the level of the row is set by the feed and the calibration, and no horizon brings it
inside. **The lead still needs to rule on the row's comparison basis or band**; the horizon
question and this row are now decoupled.

The other rows at 200 d with the prefix-stable layout (their realisations change once,
like every cell's): Plant C 24/24 sound, overload 9.82 % (6.43–14.04 %, 24/24), foaming
8.50 % (3.51–15.20 %, 24/24); Plant A `adapted` 24/24, 0.24 % (8/24) / 0.24 % (7/24);
Plant A `unadapted` 24/24, 1.19 % (16/24) / 0.07 % (3/24). S5-01 at onset 30 / 200 d:
SAO share **42.2 %**, acetate 0.04 → 3.82 → 0.62; S7-02: **20.8 %** (was 14.0 % under the
old realisation), acetate 0.05 → 3.33 → 0.78; both sound. §12's conclusion stands and
strengthens slightly under the new draw.

### 15.4 What adopting the prefix-stable layout would mean

It is a change to the influent generator at the freeze — the lead's call, like the tank:
every cell's realisation changes once (all plants); the anchored rows are re-measured
(above: all in band except `biogas_mean`, exactly as before); the trigger tables move (B
~7.1 % / 6.6 % rather than ~8.9 % / 8.7 %); `tests/test_generator.py`'s determinism and
stream-independence tests hold in form (still seeded, still ordered) but any pin on a
realised value moves and the "Randomness" paragraph is rewritten to say the horizon *is*
prefix-stable. It is the right property — a longer run should extend a realisation, not
re-roll it, and it makes any future horizon change safe — and it is what would have made
§3's windowed table a measurement rather than an estimate. The tank fix is principled and
harmless (< 1 %) and would go with it.

**Recommendation.** (1) Adopt the prefix-stable layout and the tank fix together, on the
lead's ruling, then equalise the horizon at 200 d (or any single value; they now differ by
under 2 %). (2) Rule on `biogas_mean`'s basis or band as a separate decision: at 1.50–1.54
on a stable panel it is outside by 0.004–0.036, on a comparison of a 24-seed
February–July settled mean against a three-year annual mean. (3) Rule on S7-02 (§12
stands: onset 30 gives 21 % at 200 d under the new draw). Nothing is committed: the 200-d
edits, the tank fix and the generator variant are all local.

## 16. Ruling 2 — `biogas_mean`: what the anchor column measures, and where the hidden degradability sits

*Status line: ruling 1 landed at `1353341` (prefix-stable generator + first-window tank;
one plausibility test red at the band edge, recorded, not weakened). This section is the
ruling-2 report: (a) the anchor column is total metered biogas, so the basis is right in
kind; (b) the HSW and FOG hidden degradability centres sit above the cited literature
(0.95 vs ~0.84, 0.98 vs ~0.92) — a feed-centre question for the lead, not changed here.
Consequence: the g1 gate and one default-suite test are red with the band unchanged; I am
continuing with rulings 3 and 4 and will hold regeneration only on HOLD.*

*The lead's ruling 2 of 2026-09-11: band and comparison basis unchanged until the cause is
known; two read-only checks. This is a finding, not a fix — no band, basis or feed centre
was changed.*

### 16.1 (a) What Muscatine's biogas column measures

**Total metered biogas production: the sum of the flow to the waste-gas burner (flare) and
the flow to the boiler.** Three sources agree. The dataset's own SCADA data dictionary
(`anchor/raw/iowa-muscatine-wrrf/SCADA-data-dictionary.csv`) defines `Biogas` as "Total
biogas flow (sum of Biogas_burner and Biogas_boiler)", with `Biogas_burner` "Digester Gas
Flow Rate to Waste Gas Burner" (0–1000 cfm) and `Biogas_boiler` "Digester Gas Flow Rate to
Boiler" (0–120 cfm), plus the daily totals `V-burner_FT3` and `V-Boiler_FT3`. The LABS data
dictionary defines the daily `Biogas` column, the one the anchor uses, as "Average daily
biogas flow, cfm — calculated biogas flow as total biogas volume in cubic feet divided by
1440 minutes per day". And the dataset's paper (Schroer & Just 2023, *ACS ES&T Engineering*,
open-access copy at https://pmc.ncbi.nlm.nih.gov/articles/PMC10928704/) says the biogas
variable is built "by first summing the flow to the waste gas burner and flow to the
boiler", that "daily total biogas volume was recorded in cubic feet", and gives a daily
average of 103.5 cfm ≈ 149,000 ft³/d for the plant's two 485,000-gal digesters — which is
the anchor's 2111 m³/d per digester to the unit conversion. There is no CHP engine in the
metered paths and no statement of unmetered losses; the plant flares most of its gas (the
burner meter's range is eight times the boiler's).

So the basis is right in kind: the anchor is total production, not gas delivered to a
consumer net of flare. Two caveats already in the declared tolerance stand: the meter
states neither temperature nor pressure for its cubic feet (the anchor is at "the meter's
conditions", the simulator's `q_gas_stp_dry` at 0 °C and 1 atm dry, and the band was widened
to 0.6–1.5 for that), and the division by two assumes the two digesters produce equally.

### 16.2 (b) The hidden degradability centres against the literature

The truth-side fractionation (`configs/influent/feed_fractionation.yaml`) gives each
stream a non-inert COD share, `1 − f_xi − f_si`: **high-strength waste 0.95** (lipid COD
share 0.75, inert 0.05, both marked ASSUMED; the lipid share was raised on the lead's
decision of 2026-09-02 so the derived COD/VS met the measured 2.23) and **FOG 0.98** (lipid
0.95, inert 0.02, ASSUMED). The primary sludge and WAS shares (0.67, 0.55) are standard
ADM1 sludge values and were not asked about.

Literature, as cited in the open-access review of FOG co-digestion
(https://pmc.ncbi.nlm.nih.gov/articles/PMC8072289/, citing Jeganathan et al. 2006,
Davidsson et al. 2008 and Ziels et al. 2016): lipids convert **94.8 %** to biogas, proteins
**71 %**, carbohydrates **50.4 %**; the theoretical yield of lipid is 1.0 m³ CH₄/kg against
0.63 for protein and 0.42 for carbohydrate. Brown grease measured in BMP gives 354 mL CH₄ per
g COD at 35 °C and 1 atm (https://www.frontiersin.org/journals/environmental-engineering/articles/10.3389/fenve.2024.1354582/full),
which is ~90 % of the 395 mL/g COD theoretical at those conditions, and the same paper
cites 0.40–0.77 m³ CH₄ per kg VS removed for pilot-scale brown grease (Zhang et al. 2014).
The cited FOG biodegradability range is therefore **~85–95 %** of COD.

Weighting each stream's own fractionation by those conversion fractions gives the
biodegradable share the literature implies: **HSW 0.84** (0.75 × 0.948 + 0.10 × 0.504 +
0.06 × 0.71 + 0.04 × 1.0) against the truth's **0.95**; **FOG 0.92** against the truth's
**0.98**. **Both streams sit above their literature range — HSW by ~11 points, FOG by ~6 —
and HSW is the one clearly outside**: no cited value for a food-processing waste with
25 % non-lipid COD reaches 95 % biodegradable, while FOG at 98 % is at the top edge of the
grease-trap range (94.8 % for pure lipid) rather than beyond it.

**How much of the 1.5× that could explain, estimated, not measured.** HSW and FOG carry
70 % of the plant's COD load (3232 and 1689 of 7052 kg COD/d at the anchored volumes).
Moving their degradable shares to the literature-implied values would remove 343 + 103 =
446 kg COD/d of the 6064 kg/d the truth degrades, i.e. **~7 % less gas**, which would take
the row from 1.536 to ~1.43 — inside the band with a margin, on a back-of-envelope that
ignores ADM1's own hydrolysis and LCFA-inhibition kinetics (which already leave some
non-inert COD unconverted at a 20-d HRT, so the true sensitivity is smaller). Two other
contributors stand beside it: the meter-conditions unknown (a meter at 35 °C and slight
overpressure reads 10–13 % more volume than 0 °C dry for the same gas), and the seasonal
window of §3. None of the three alone is the whole 1.5×; the degradability centres are the
one that is a *modelling* choice rather than a measurement basis.

**What this implies, for the lead.** The ruling's condition — "only if the basis is right"
— is met, and the answer to (b) is that the high-strength waste's degradability centre is
outside its literature range. That is a change to a frozen feed centre, which is the lead's
call and is not made here: `f_xi`/`f_si` of the HSW (and FOG) would move, the derived
COD/VS check (±10 % against the measured 2.23) would have to be re-satisfied by
redistributing the lipid share, every Plant B and C cell would change, and the anchored
rows and pins would be re-measured. Until then `biogas_mean` stays the row to watch at
1.50–1.54 on a stable panel, outside its band by 0.004–0.036, recorded as such.

### 16.3 Consequence for CI, stated now

`tests/test_g1_anchor.py::test_the_biogas_the_simulator_makes_is_the_biogas_the_plant_measures`
asserts `biogas.passed`, and `test_a_row_calibrated_to_the_anchor_is_never_counted_as_a_match`
asserts every independent row matched. With the band unchanged (ruling 2) and the layout
adopted (ruling 1), both fail at the 200-d panel (1.536) — the g1 job of CI, which runs on
any change under `sim/`, will be red on the side branch and on PR #15 once fast-forwarded.
I am not weakening those tests: they are doing their job. The coordinator decides whether
CI-green in step (iii) means the ruff and pytest jobs or the g1 gate as well (which cannot
be, without the lead moving the band or the feed centre).

The default pytest job is also touched, by one test. The full suite at the ruling-1 commit
is 366 passed, 2 skipped, **1 failed**:
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings`, a single-seed
(seed 11) 180-d unbuffered Plant B run that asserts the same [0.6, 1.5] biogas ratio. Under
the new layout that seed gives 3168 m³/d against the anchor's 2111, ratio **1.5004** — the
same excess on one seed, at the band edge by 0.0004. It passed at the PR head because that
seed's old realisation happened to sit below the edge. Left red, recorded in the ruling-1
decisions entry; it moves with whatever the lead decides for the row.


## 17. Ruling 4 — S7-02 at onset 120 on the 365-d horizon: the takeover completes

*Status line: rulings 1–3 landed at `1353341`, `7d1554d`, `3ec7bb8` (one commit each,
ruff green, the default suite green but for the one band-edge plausibility test recorded at
`1353341`; the g1 gate red for the same row). This section is the ruling-4 verification;
its commit carries the scenario record, the truth-side record and the decisions entry.
Next: fast-forward PR #15 to the side-branch head, CI, then regeneration as the last
action. Nothing regenerated yet; no HOLD received.*

**The question.** Ruling 4 keeps S7-02 as staged — onset day 120, `adapted` baseline — on
Plant A's new 365-d horizon (ruling 3), and asks whether the takeover completes there:
report the X_sao / X_ac trajectories, whether the recorded 0.60 / 0.46 is reached and by
what day, and correct the record to what is reached. Measured through the harness at each
row's own seed (S7-02 1072, S5-01 1051), current feed, the prefix-stable generator of
ruling 1, 365 d, monthly samples of the truth state.

**S7-02** (omitted SAO + loss of adaptation at day 120):

| day | X_ac | X_sao | SAO share of X_ac + X_sao | acetate, kg COD/m³ |
|---:|---:|---:|---:|---:|
| 119 | 1.177 | 0.0001 | 0.0 % | 0.04 |
| 150 | 1.226 | 0.0005 | 0.0 % | 2.34 |
| 180 | 1.240 | 0.003 | 0.2 % | 1.39 |
| 210 | 1.208 | 0.012 | 1.0 % | 1.58 |
| 240 | 1.150 | 0.045 | 3.8 % | 1.51 |
| 270 | 1.070 | 0.145 | 11.9 % | 1.61 |
| 300 | 0.837 | 0.311 | 27.1 % | 0.99 |
| 330 | 0.580 | 0.481 | 45.4 % | 0.38 |
| 365 | 0.371 | 0.691 | 65.1 % | 0.31 |

X_sao reaches **0.60 on day 348**; X_ac falls to **0.46 on day 350**; SAO carries half the
acetate-consuming biomass from day 338. Acetate peaks at 3.91 on day 158 and is back to
0.31 at the end as the oxidisers take the flux. Sound throughout (pH 7.70, CH₄ 0.62 at the
end).

**S5-01** (the same loss of adaptation, no omission — the control):

| day | X_ac | X_sao | SAO share | acetate, kg COD/m³ |
|---:|---:|---:|---:|---:|
| 119 | 1.079 | 0.0001 | 0.0 % | 0.02 |
| 180 | 1.022 | 0.003 | 0.3 % | 3.62 |
| 240 | 0.958 | 0.103 | 9.7 % | 3.13 |
| 270 | 0.734 | 0.361 | 33.0 % | 1.08 |
| 300 | 0.472 | 0.622 | 56.9 % | 0.26 |
| 330 | 0.267 | 0.693 | 72.2 % | 0.30 |
| 365 | 0.139 | 0.778 | 84.8 % | 0.19 |

0.60 on **day 298**, 0.46 on **day 302**, half the biomass from day 291; acetate peaks at
3.73 on day 201. Sound throughout (pH 7.76, CH₄ 0.65).

**Answer.** Yes: on 365 d the record's 0.60 / 0.46 **is reached**, by day ~350 for S7-02
and ~300 for S5-01, and the record now says exactly that (the scenario headers, with the
monthly table in the S7-02 file; the truth-side record; the S6-01 cross-reference; the
harness note). The figure first recorded on 2026-09-03 as "in 240 d" was not reproducible
at any commit (§11, corrected at `3be4ef9`); the year is what it takes on the current
feed. The two rows differ in the fitted model, not in the truth's timing beyond the fifty
days the omission costs S7-02's oxidisers (they start from the same 7e-5 seed but the
S7-02 truth's acetate pool relaxes later).

**What that makes of the row.** The structural half of S7-02 rests on a pathway that
carries a few per cent of the flux until day ~250, a quarter by day 300 and the majority
from day ~340: a structural residual that is a **ramp through the last four months**, on
acetate first and on the gas as the route changes — the "ramp that follows the growing
oxidiser population" the answer key describes, which at 200 d it was not (§11: 0.4 % of
the flux, every channel reproduced by an SAO-less fit). The parameter half is unchanged: a
step at day 120 on the adapted baseline, acetate up 100× within forty days. The onset-30
staging (§12 c) and the `unadapted` staging (§11) are not needed and are closed by the
ruling; retirement (§12 d) is off the table.

**Not changed.** No onset, magnitude, baseline, seed, budget, answer key or tolerance.

## 18. Regeneration at `a91e71a` — the last action; stopping

*Status line: done. PR #15 (`claude/g1-scenario-generation`) is fast-forwarded to
`a91e71a`, the ruling-4 commit; the 117-cell matrix was regenerated at that head as the
last action and verified; this section and the milestones line are a docs-only commit on
the side branch so that the PR head stays the SHA every manifest carries. I have stopped:
no further push, no merge, no tag. HOLD was not received; CI is red only where §16.3 said
it would be.*

**The four commits, one per ruling** (each with `ruff check .` and `ruff format --check .`
green and the default suite green but for the one band-edge test recorded at the first):

| ruling | commit | what |
|---|---|---|
| attribution | `e688535` | the common-horizon question is review finding F2, not the lead's |
| 1 | `1353341` | prefix-stable influent generator; blend tank from its first window; tests |
| 2 | `7d1554d` | `biogas_mean` investigated, band and basis unchanged (§16) |
| 3 | `3ec7bb8` | the horizon is the plant's: A 365 d, B and C 200 d; trigger tables re-measured |
| 4 | `a91e71a` | S7-02 stays at onset 120 on 365 d; the takeover completes (§17) |

**CI at `a91e71a`** (run 34586669039, the pull-request event; the push event is the same):
ruff **green**; pytest py3.11 and py3.12 **red on exactly one test**,
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings`, ratio 1.5004
against the 1.5 edge (369 passed, 2 skipped, 1 failed on both); gate G1 anchor panel
**red on exactly the two `biogas_mean` tests** (`biogas_mean` 3244 against 2111, ratio
1.536; 21 of 22 independent rows matched; 11 passed, 2 failed). All three failures are the
one row the lead's ruling 2 left as the row to watch, with the band the lead's; nothing
was weakened.

**The regeneration**, `python -m sim.run.matrix --runs-root runs` after clearing `runs/`
and `truth_store/`, working tree clean at `a91e71a`:

| | |
|---|---|
| head | `a91e71a90288bba292faaf0ce643ce305c0c3488`, 0 dirty files, every manifest carries it |
| cells | **117 / 117 generated, 117 / 117 sound digesters**; 0 soured, 0 failed |
| wall-clock | **748 s (12 min 28 s)**, 10:03:54–10:16:22 UTC |
| per plant (sum of per-cell wall) | A 21 cells 296 s; B 48 cells 231 s; C 48 cells 218 s |
| index | `truth_store/index.jsonl` **117 lines, 117 unique ids**; 117 run dirs, 117 truth dirs |
| horizons in the manifests | every Plant A cell 365 d / 365 n_days (21); every B and C cell 200 d (48 + 48) |
| store | 27 MB under `runs/`, 20 MB under `truth_store/` |
| verification | `verify_regen.py`: index, run dirs and truth dirs agree; redacted manifests carry no scenario id, seeds or baseline; every run has `calls.jsonl`; the 32-byte salt appears in no visible file |

The expected wall-clock impact of the 365-d Plant A cells (decisions, ruling 3: under two
minutes on ~13 min) is confirmed the easy way: the whole regeneration took 12.5 min, no
longer than the last full one at the old horizons (~13 min); Plant A's thirteen truth
integrations account for 296 s of per-cell wall against B's 231 s for sixteen.

**Trigger-rate tables for all three plants** (24 clean Level-0 seeds each, at the matrix
horizons under the prefix-stable generator; the four-row form, Plant A as its two
baselines; also in `docs/g1_anchor_report.md` §5.4, the benchmark card and the decisions
entry of ruling 3):

| Plant | baseline | horizon | sound | overload, pooled | per-run range | runs firing | foaming, pooled | per-run range | runs firing | operator > 0.40 / > 0.30 |
|---|---|---:|---|---:|---|---:|---:|---|---:|---:|
| **B** | — | 200 d | 24/24 | **7.12 %** | 2.34 – 16.37 % | 24/24 | **6.63 %** | 1.75 – 14.04 % | 24/24 | 0.00 % / 0.00 % |
| **C** | — | 200 d | 24/24 | **9.82 %** | 6.43 – 14.04 % | 24/24 | **8.50 %** | 3.51 – 15.20 % | 24/24 | 0.00 % / 0.00 % |
| **A** | `unadapted` | 365 d | 24/24 | **1.02 %** | 0.00 – 3.27 % | 21/24 | **0.09 %** | 0.00 – 0.60 % | 5/24 | 0.00 % / 0.00 % |
| **A** | `adapted` | 365 d | 24/24 | **0.22 %** | 0.00 – 1.19 % | 11/24 | **0.20 %** | 0.00 – 1.19 % | 10/24 | 0.00 % / 0.00 % |

(180-d panels of 2026-09-10 for comparison: overload 7.67 / 9.22 / 1.49 / 0.28 %; foaming
7.20 / 7.67 / 0.14 / 0.25 %.) B and C still bracket the anchor's 7.78–9.18 % exceedance;
the Plant A pathway finding stands at 4.6× (was 5.3×).

**Open for the lead, unchanged by anything here:** `biogas_mean` at 1.536 against
[0.6, 1.5] — the basis is right in kind, the hidden HSW / FOG degradability centres sit
above the cited literature (§16.2), and the band, basis and centres are the lead's to move.
Until then the g1 gate and one plausibility test are red on that row alone.
