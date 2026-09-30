# Knowledge audit of the P1 revision-2 transcripts (rev2 = gpt-5.6-luna, rev2_claude = claude-opus-5-5)

Auditor: fresh-context read-only session, 2026-09-30, launched by the coordinator
(session_01Cu6G2kQjP2QSzvtkyP8cPr). Rubric: `scratchpad/knowledge_audit_rubric.md`.
Branch audited: `origin/claude/p1-anthropic-arm` at `dbf2e45`, scratch worktree
`scratchpad/audit_wt` (removed at the end). Nothing under `truth_store/` was opened; the
truth label and fault description come from `scenarios/<id>.yaml` and
`reports/p1_pilot/records/index.csv`. No test, no live call, no edit, no push.

Inputs read in full: the twenty `state.json`, `calls.jsonl`, `llm_calls.jsonl`,
`report.json`, `manifest.json`; `configs/workflows/p1_prompts/{system,task,expert_brief}.md`
(the brief was **not** sent to either arm: `brief_sha256` is empty in every run);
`docs/proposal.md` §6.3–6.7; `docs/benchmark_card.md` §4.3, §6; `docs/p0_design.md` §3.7
(rules R1–R6); `docs/milestones.md` (the P0 pilot rounds on the same ten cells and the
five-arm P1 development table).

---

## 0. What was visible, and what a grader must know before grading

**Visible reasoning per arm.** Zero characters of reasoning text in either arm. Every
GPT turn carries `thinking` blocks with `encrypted_content` only (a signature, no summary);
every Claude turn carries `thinking` blocks with empty content (display omitted). Free
text between tool calls: luna 3 short lines in 2 of 10 runs (harness-facing, e.g.
"Now Fisher on the top candidates"); Claude 3 short lines in 3 of 10 runs. So the audit
grades what the rubric anticipates: the arguments to `set_sensor_status` (the `reason`
field), `record_evidence` (statement + values + cited calls), `conclude` (the summary),
the order and choice of tool calls, and the evidence items that survived into
`state.json`. Both models wrote their reasoning into those fields at some length
(Claude's evidence statements run to 60–90 words; luna's 20–40), so the grading is on
real content, not on inference from silence.

**The background these records carry, which neither model was told.** Reading the tool
outputs across the twenty runs shows a plant-level background that every label has to
exceed, and that the prompts describe only qualitatively ("the fitted model will not
reproduce the record to instrument precision, because the feed log is an imperfect
description"):

| cell (default parameters, `simulate` at 1.0) | gas_flow mean_z / rms_z | COD closure mean, inadmissible windows of 5 | `admissible` flag | charge_consistent |
|---|---|---|---|---|
| S0-01 B/A (truth none) | +3.97 / 7.48 | n/a at tier A | true | null |
| S0-01 B/B (none) | +3.98 / 7.35 | −0.136, 2 (−0.275, −0.267) | **false** | true |
| S0-01 B/C (none) | +3.93 / 7.31 | −0.142, 2 | **false** | true |
| S1-01 B/B (none) | +8.04 / 10.54 | −0.193, 2 (−0.481: CH4 COD alone exceeds declared COD in days 30–60) | **false** | false |
| S2-01 B/B (sensor pH) | +7.57 / 9.64 | −0.123, 1 | false | false |
| S4-01 B/B (state) | +0.36 / 7.99 | −0.078, 0 | false | false |
| S6-02 B/B (structural) | +2.60 / 7.50 | −0.059, 0 | false | false |
| S8-01 B/B (sensor gas ×1.08 from d60) | +8.29 / 11.11 | −0.163, 1 (−0.411) | false | true |

Three consequences. (i) On these plants the null case is **not** "residuals within the
declared instrument noise": at defaults the gas residual is 7× the meter's noise in the
clean cell, and the P0 pilot record says the same of the fitted model ("after the fit
every channel keeps its 5–19σ background bias", milestones, P0 round 2). (ii) The
`mass_balance` tool declares the clean cells inadmissible (2 of 5 windows, closure −0.14
to −0.19). P0's own R2 rule fired on that background and was raised by ruling B(c) to
"at least 3 inadmissible windows"; P0's R1 (sensor) and R5 (state) also fired on the
background on 8/10 and 9/10 pilot cells before rulings B(a)/(b). The P1 prompts, by
design, name no P0 rule and no threshold. (iii) Therefore signature S7 as the rubric
defines it (residual within declared noise, calibration intervals cover, hold-out
validates) was never reachable for P1 on these cells: no run in either arm got a fit
that removed the gas offset (fits went to bounds or left rms_z ≈ 7), and neither agent
sees the hold-out. Every "none" in the five-arm development table is 0/4 for every
arm, including the brief arm; this audit finds the same and explains why.

This does not excuse the wrong labels. It changes what "misapplied" means: in the null
cells the models applied S2/S8 to a balance and a residual profile that a process
engineer with the same tool outputs *and no plant reference* would also have read as an
open balance. The failure is the absence of the S7 reference step, not the absence of
process knowledge. Elsewhere (S2-01, S4-01, S5-01) the signatures were present in the
outputs and were misread or the deciding tool was never run; those are graded as such.

Grade key: **LC** = LITERATE-CORRECT, **LM** = LITERATE-MISAPPLIED, **NPB** =
NOT-PROCESS-BASED, **UNS** = UNSUPPORTED. Call indices are the registry `call_index`
values the models cited; turn numbers are the assistant turns of `llm_calls.jsonl`
(0-based).

---

## 1. Per-run audit — rev2 (gpt-5.6-luna)

### R1. run_bb097887455f — S0-01 B/A, truth **none**, label **sensor** (flag gas_flow), conf 0.88

Tool path: t0 QC + balance + record inspection; t1 `set_sensor_status(gas_flow, flagged)`
on the QC `informative_missingness` flag (event_missing_ratio 2.625) before any
simulation; Morris on pH only; Fisher; default `simulate` (call 7); residual_diag on
pH/gas/temperature (8–10); fit k_m_ac,Y_ac on pH alone → both at bounds (call 11);
residual_diag pH (13); VFA and alkalinity assays at day 140 (14, 15); t11 flags pH.

Evidence (5 recorded; 4 refused):
- E0/E4 [sensor] gas_flow QC informative missingness → excluded. **NPB**. A missingness
  pattern is not an instrument misreporting; no channel comparison; the vocabulary offers
  `missing_transient` for exactly this.
- E1 [sensor] "After the constrained fit, pH residuals remain time-structured and
  serially correlated ... large step at day 139" with bias_z −5.10, step_z 9.47 **and
  rmse_z 0.347** (call 13: mean residual −0.021 pH units against sd_abs 0.02). **NPB**.
  The z-statistics were read without the magnitude beside them: a pH channel whose rms
  residual is a third of its declared noise is the S7 case for that channel, not a
  fault. The "step" is the tool's best-split statistic, reported for every channel.
- E2 [sensor] VFA assay day 140, disagreement_z −0.50 → "no comparable chemistry
  discrepancy". **UNS**. A null result labelled as sensor evidence.
- E3 [sensor] alkalinity assay z 1.40 "weaker than the structured pH residual". **UNS**.
  Same; and the coupled channels agreeing with the model is the S1 evidence that pH is
  *fine*, inverted.
- `set_sensor_status(ph)` reason, t11 (the most telling passage of the arm): "pH
  residuals retain strong time/serial structure and a day-139 step (bias_z -5.1002,
  step_z 9.4698); the two independent day-140 chemistry assays are not comparably
  discrepant, so pH is not used for the final calibration."

S7 tested: **No**. The pH rmse_z 0.35 was in hand and not read as clean; the gas rms_z 7.5
was never named as the background. S1 before the sensor call: **performed and
inverted** (assays bought, agreement read as confirming a pH fault). Wrong label →
missing S7; tool output **available and misread** (calls 13, 14, 15). Seven abstentions
including `posterior_intervals` with no sampler call.

### R2. run_310eec3d8b5d — S0-01 B/B, truth **none**, label **sensor** (flag tan) + **influent**, conf 0.7

t1 excluded ch4_fraction, gas_flow, pH, temperature on QC flags (informative
missingness ×3, one spike at day 44) before any simulation; fit Y_ac alone on
alk/COD/TAN/VFA → 1.5 at bound; residual_diag ×4; COD assay day 100 (z 0.92); later
excluded TAN on its post-fit residual; refit Y_ac → 1.5 again; four `conclude`
refusals over the interval method.

Evidence (3):
- E0 [sensor] TAN bias_z −4.26, "time-associated step/serial pattern, no feed covariate
  explanatory; supports a TAN measurement problem". **LM**. Single-channel-offset form
  (S1) is admissible only when the coupled channels are clean; here after the fit alk
  −1.9, VFA −2.1, COD +6.7, gas +4.6 (calls 9–12, 8) — every channel off in a different
  direction, which is the background. No TAN assay was bought (the one assay unit went
  to COD).
- E1 [influent] VFA residual most explained by feed_high_strength_waste (η² 0.45 on
  n = 22), plus 2 inadmissible windows, closure −0.136. **LM**. S8/S2 form; the closure
  is the null background and below P0's post-ruling threshold.
- E2 [sensor] ch4_fraction QC missingness. **NPB**.

S7: **No**. S1/S8: partial (S8 read; no coupled comparison before the TAN call). Wrong →
S7; **available and misread** (its own post-fit residual table).

### R3. run_411a6974f233 — S0-01 B/C, truth **none**, label **influent**, conf 0.68

Ran QC/balance, quarantined 4 items on QC spikes/missingness (pH quarantined 0–150 for
informative missingness), Morris over 11 outputs, Fisher, then a 4-parameter fit that
consumed 220 evaluations and the whole wall clock (92.6/90 min); no `residual_diag` at
all; the harness forced `conclude`.

Evidence (1): E0 [influent] "balance check is inadmissible in two 30-day windows despite
charge consistency, negative mean COD closure (−0.142)". **LM**. S8 stated correctly, on
the null background, with nothing else examined. S7: **No**. S1/S8: S8 only. Wrong →
S7; **never run** (no residual analysis; the fitted values K_I_nh3 3.44, K_S_ac 1.04,
Y_ac 1.15, k_m_ac 0.85 were reported with full-bound intervals "as calibration
quantities").

### R4. run_4f51186790c1 — S1-01 B/B (noise ×2, gaps ×2), truth **none**, label **sensor** (flag gas_flow), conf 0.86

t1 flagged gas_flow (QC spikes at days 52, 110) and TAN (spikes 70, 105 + missingness)
before simulation; Morris, Sobol (80 evals), Fisher; three refused fits then a 2-parameter
fit → k_m_ac at 3.0 (bound), Y_ac 1.28; forced to conclude at 5.9 min left; no
`residual_diag`.

Evidence (3): E0 [sensor] gas QC spikes + missingness → excluded. **NPB**. E1 [sensor]
TAN spikes + missingness. **NPB**. E2 [influent] closure −0.193, 2 inadmissible, charge
drift 0.40. **LM** (S8 on the null; the conclude summary then says "the balance
inconsistency is therefore not sufficient evidence to revise the influent mapping" and
keeps the sensor label anyway). S7: **No**. S1: **No**. Wrong → S7; **never run**.

### R5. run_21ed776886d4 — S2-01 B/B, truth **sensor (pH drift −0.01/d from d45, recalibration steps)**, label **sensor**, flag **tan** (truth pH), conf 0.9

t1 flagged ch4_fraction, gas_flow, pH, temperature on QC flags; Morris/Sobol/Fisher;
fit Y_ac,k_m_ac on alk/COD/TAN/VFA → both at bounds; residual_diag on all eight
channels (10–17); TAN and alkalinity assays at day 84 (18, 19); default simulate (20);
TAN excluded on its residual; conclude.

Evidence (5):
- E0 [sensor] gas bias_z 16.3, "far above instrument noise, strong time explanation,
  large step". **LM**. Size and time structure only; gas at +8σ mean is this plant's
  background (S0-01 B: +4.6 after the same fit; S1-01: +8.0 at defaults).
- E1 [sensor] ch4_fraction bias_z −7.55 "beyond its declared noise" — rmse_z 1.14, mean
  −0.008 against sd_abs 0.01. **NPB**.
- E2 [sensor] alkalinity bias −6.2 while the day-84 assay is z −1.07. **LM**. The
  lab-channel form of S1 (independent assay vs routine) is right; one point at 1σ decides
  nothing.
- E3 [sensor] TAN bias −7.78 while the day-84 TAN assay agrees with the model (z −0.13).
  **LM**. Correct S1 form for a lab channel; one point against a 21-sample window; and
  the same test on the channel that mattered was not made.
- E4 [sensor] pH: bias_z −17.5, early −9.4/late −15.8, step_z 11.95, time η² 0.54 —
  the largest residual of any channel and the true fault. Statement: "QC-flagged and
  shows a very large structured residual and step, not a plausible kinetic-only
  discrepancy." **LM**. It saw the channel but ranked it with three others and flagged
  TAN. The S1 test that decides pH — pH against alkalinity/VFA (both within ~1σ of the
  model after fit: alk −6.2 bias but rms 1.7, VFA −0.6) and the charge balance the
  scenario names (`charge_consistent: false`, call 4) — was in hand and not made.

S7: **No**. S1 before the sensor call: **partial** (assays for TAN/alk, not pH vs its
coupled channels). Flagged sensor wrong → S1 on pH; **available and misread** (calls 4,
15). Note pH had been excluded from the objective at t1 on a QC missingness flag, so it
was never a calibration channel; the drift was carried as one more "flagged record".

### R6. run_c18d9139cb2a — S3-01 C/B, truth **influent (feed mislabelled d60–120)**, label **influent** + **sensor** (flag tan), structural review **true**, conf 0.78

t1 quarantined single spikes in alk/gas/pH, *excluded TAN on the QC drift flag*
(signal_to_noise 4.59, slope −0.0021/d) and temperature; Morris/Sobol/Fisher; a
4-parameter fit → all four at bounds (call 9); residual_diag ×6 (11–16); COD/alk/VFA
assays day 140; feed-log inspection; 8 evidence items in one turn; default simulate;
conclude with 12 abstentions.

Evidence (8):
- E0/E4 [sensor] TAN excluded for QC drift. **NPB**. On a Plant-C cell where one feed's
  true N content departs from the catalogue for 60 days, a drifting reactor TAN is the
  process consequence, not the analyser; the TAN-vs-feed-N test (S1's fourth bullet;
  the feed TKN assays were in `inspect_record`) was never made.
- E1 [structural] COD residual late bias 13.4, time-structured "not a clean kinetic
  calibration". **NPB**. Structural from a z-score; and the same call 13 is recorded
  again as E3 under influent ("reading the same residual a second way is not a second
  cause", the system prompt).
- E2 [influent] gas residual load-structured (η² 0.25), early +0.2 → late −7.0, step
  day 31 → "input/feed discrepancy rather than a uniform sensor offset". **LC**. The S2
  onset-plus-load form; the record supports it (the onset the tool finds, day 31, is the
  best split, not the true day 60, but the inference is sound).
- E3 [influent] COD residual "matching the timing of the feed-log instrumentation note"
  (day-29 note: transmitter re-ranged, "no change to the recorded volumes"). **LM**.
  Anchoring on a note is literate; this note denies the change.
- E5 [influent] charge inconsistent, closure −0.033 admissible. **LM** (charge alone;
  P0 ruling B(b) recorded that it fires on the background 8/10).
- E6 [influent] alkalinity assay day 140 z −3.45 against the bounded fit "corroborating
  the observed late channel level rather than a routine alkalinity sensor offset". **LC**
  (S1 negative test done right).
- E7 [structural] pH bias −13.2, serial, step day 122 — with rmse_z 0.64. **NPB** (pH
  within its noise; structural from z).

S7: **No**. S1/S8: partial. Primary correct; the secondary sensor and the structural
review are wrong: S1 for TAN **available (feed assays) and never compared**; S6's own
criterion (fit improves only by leaving the boxes; hold-out fails) was not applied.

### R7. run_eaf88ae16f7f — S4-01 B/B, truth **state (biomass ×0.25 at t=0)**, label **state** + **influent**, conf 0.76

t1 quarantined QC "spikes": ch4_fraction days 0–1, cod_total days 0 and 7, gas 44/114/128,
pH day 0, VFA day 7. Those days are the record's own start-up transient: ch4_fraction
0.538 on day 1 (median 0.665), VFA 2.15 kg/m³ on day 7 (median 0.90), COD 34.4 on day 7
(median 24.6). Then Morris, Fisher, Y_ac fit (0.518, near bound), residual_diag ×7,
three assays (COD 2.17, TAN 2.67, VFA 0.51), 15-day balance, t11 *excluded* the five
QC-flagged sensors wholesale, refit Y_ac on alk+TAN → 0.5 at bound.

Evidence (2):
- E0 [influent] COD residual +13.3 most explained by HSW, COD assay 2.17, charge drift.
  **LM** (S2 covariate form on n = 20; COD is +6.7 to +10 in the null cells).
- E1 [state] "TAN is persistently above the model from the calibration start through the
  late window (early 5.95, late 12.4) ... more consistent with a latent inventory/state
  offset". **NPB**. S4 is an early transient that *decays*; this is a bias that grows.
  The right label was reached by elimination and vocabulary.

S7: **No**. S1/S8: partial. The S4 signature was **available and misread** (the day
0–7 excursions in VFA/COD/CH4 fraction that heal, delivered by `data_qc` as "spikes"
and quarantined) and the S4 test **never run** (`simulate(biomass_scale=...)` exists and
was used by this same model on S5-01 and S8-01 as a two-point test; not here).

### R8. run_9a9a662d1b88 — S5-01 A/A (tier A: gas, pH, temperature), truth **parameter (K_I_nh3 ×0.1 from d120)**, label **influent** + **sensor** (flag gas_flow), conf 0.82

t1 quarantined pH (one spike at day 270) *and removed it from the objective*; Morris on
gas → K_I_nh3 ranked first, Sobol confirms (ST 0.91); Fisher; fit K_I_nh3 alone → 0.2,
the lower bound (call 9; the scenario's injected multiplier is 0.1, *below* the declared
lower bound 0.2 — see §6); residual_diag gas (11: step day 229 step_z 6.7, time η² 0.20);
four assays at day 220: TAN +3.89σ, alkalinity +2.01σ, VFA +7.02σ, digestate VS +5.73σ
(12–15); biomass_scale 0.5/2.0 simulations; quarantined gas from day 229; relabelled
the assay items from state to influent.

Evidence (7):
- E0 [sensor] gas residual "strongly structured in time with a large step at day 229 ...
  no significant load/feed structure; channel-specific sensor-like pattern". **LM**. S1
  form needs the other channel; pH had been quarantined at t1 and its residual (+18.5σ,
  high from the start: the Claude run's call 6 on the same record) never looked at.
- E1–E4 [state] the four assays, each "above the model prediction at the gas-fit point".
  **NPB ×4**: 'state' with no mechanism.
- E5 [influent] "Independent TAN is 3.8876 sd above the model value at day 220,
  consistent with the declared feed mapping understating nitrogen". **LM**.
- E6 [influent] VS +5.73σ "with the high TAN this points to an influent/state-loading
  mismatch". **LM**.

What the assays show, read as a process engineer would: VFA more than doubled (5.0 vs
2.3 kg/m³), TAN high, alkalinity high, pH held high (7.78 vs 7.68), gas roughly flat
(mean_z −1.7) — the inhibited steady state of ammonia inhibition (S3), the parameter
Morris had ranked first, the parameter the fit had driven to more inhibition. Two
consecutive evidence items (E5 "feed N understated", E3 "VFA far above the model") sat
next to each other and were not joined. S7: **No**. S1/S8: partial (assays bought and
misread). Missing S3 → parameter; **available and misread** (calls 6–9, 12–15).

### R9. run_98a743d03687 — S6-02 B/B, truth **structural (omitted precipitation)**, label **sensor** (flag vfa_total) + **influent**, conf 0.84

t1 flagged ch4/gas/pH on QC flags; Morris/Sobol/Fisher; default simulate (8);
residual_diag ×4; assays VFA d147 (z 0.33), TAN d147 (−0.73), alk d28 (+1.97); Y_ac fit →
1.052 interior, interval [0.92, 1.18]; residual_diag ×4; two more assays (VFA d140
−0.18, TAN d140 +0.03); quarantined VFA after day 133 (note: "sampling technician on
leave"); refit; VFA d28 assay (+0.15); *excluded the whole VFA record*; refit Y_ac →
1.091; 14-day balance; conclude with 18 abstentions. 12 refusals, 27 turns.

Evidence (17): E0, E15, E16 [sensor] QC flags → **NPB ×3**. E1 [influent] charge drift
0.43, closure −0.059, 0 inadmissible → **LM**. E2/E14 [influent] alkalinity residual
structured by HSW (η² 0.48, n = 21, bias +0.37) → **LM ×2**. E3/E11 [state] TAN
early −1.9 → late +1.4 → **NPB ×2**. E4 [influent] VFA bias +2.5 → **NPB**. E5, E8, E9,
E12 [sensor] VFA assays at days 147/140/28 "close to the model, not the high routine
observation" → **LM ×4**: the assay-vs-routine form is S1 for a lab channel, but the
differences are 0.05–0.08 kg/m³ against the assay sd 0.06 (routine 0.79/0.80 vs assays
0.727/0.748), one sigma, and the whole channel was excluded on it. E6 [sensor] TAN assay
z −0.73 → "late routine-sampling problem" → **NPB** (that is agreement). E7 [state] alk
assay +1.97 "does not establish a fault" → **UNS** (labelled while saying it shows
nothing). E10/E13 [sensor] VFA bias 2.37 after quarantine "beyond declared noise" with
rmse_z 1.12 → **NPB ×2**.

S7: the only run in either arm that *wrote down* the null test — two `[none]` items
("Y_ac ... 90 % Fisher interval includes the default, so the fit itself does not
support a kinetic change"; "the final constrained calibration still converges
interiorly on Y_ac near default"), both refused for value keys — and then labelled
sensor + influent anyway. Counted as **attempted, not applied**. S1/S8: partial. The S6
signature the scenario describes (alkalinity and pH below the model, gas right) is
**not present in the tool outputs at tier B** (alk bias_z +0.37, pH mean_z −0.30, gas
+2.6 — all inside the S0-01 B envelope); P0 also read `none` here. The honest verdict
from these outputs was `none` with the two inorganic-carbon abstentions, which this run
did include (`alkalinity_total_budget`, `inorganic_carbon_balance`) among 18 abstentions
taken by vocabulary.

### R10. run_b90d0e4907a5 — S8-01 B/B, truth **sensor (gas ×1.08 from d60; bayes_mcmc fails)**, label **sensor** (flag gas_flow, scale 1.278) + **structural**, conf 0.86

t1 flagged ch4/gas/pH/temperature on QC flags; Morris/Sobol/Fisher; default simulate;
residual_diag ×4 (alk +2.5, COD −3.0, TAN +7.0, VFA +0.7); Y_ac fit → 0.631 interior
[0.545, 0.717]; residual_diag ×4 after fit (alk 0.3, COD −1.7, TAN 1.4, VFA −2.2);
assays COD d42 (0.85), VFA speciation d49 (acetate z −16.2: 0.034 vs 0.077 kg/m³),
TAN d91 (1.6), alk d98 (−0.6); residual_diag on the excluded gas/CH4/pH; biomass_scale
0.5/1.5/0.8/1.2 simulations; conclude with 21 abstentions. `bayes_mcmc` never called.

Evidence (6): E0 [influent] closure −0.163, 1 inadmissible → **LM** (S8 on the
background; not carried into the label). E1 [sensor] pH QC missingness → **NPB**. E2
[sensor] gas bias 13.2, rms 11.1, time-structured "supports a gas-flow instrument fault
rather than a kinetic change" → **LC**: the record supports it (after the fit every
other channel is within ~2σ and the four assays agree with the model), though the
statement gives only size and time, not the coupling that makes it true. E3
[structural] COD/TAN after fit "remain time-structured with large early bias" (COD
rmse 1.9) → **NPB**. E4 [structural] acetate speciation assay z −16 → **NPB** (S6 needs
fits that improve only by leaving the boxes and a failed hold-out; the fitted Y_ac was
interior and the acetate parameters were never fitted). E5 [structural] VFA step_z 3.5
→ **NPB**.

S7: **No**. S1/S8: **yes, implicitly** (assays on the coupled channels, all agreeing).
Primary correct; scale 1.278 folds the plant's +11 % background in with the meter's
+8 %; secondary structural wrong, S6 criterion **available and contradicted** (interior
fit). The Level-8 half of the scenario was never exercised: no sampler call, yet
`posterior_intervals` abstained (uncredited by the published rule).

---

## 2. Per-run audit — rev2_claude (claude-opus-5-5)

A pattern first, since it holds in 10 of 10 runs: turn 0 is `data_qc` + `mass_balance`
(+ `simulate` at defaults in 8/10); turn 1–2 is `residual_diag` on the largest channels;
the label hypothesis is formed by turn 3–4 from the balance and the from-day-0 residual
profile; the rest of the run tests alternatives by mechanism (a fit, and in 2 runs
`biomass_scale`, as the parameter and state tests; assays as the sensor test) and
writes the differential into the evidence statements. No sensor was ever excluded on a
QC flag alone (single-day quarantines only; `ch4_fraction` set back to `ok` in S6-02 with
the reason "offset −0.01 within sd_abs 0.01 and drift bound 0.03").

### C1. run_6cc3b7ed917b — S0-01 B/A, truth **none**, label **influent**, conf 0.65

Evidence (5): E0 [influent] gas under-predicted from day 0 (bias 7.17, early 7.3/late
4.9), "no significant structure by load or temperature; the gas sensor itself has no
drift or spike flags" → **LM** (S2 from a from-day-0 offset that is the plant
background). E1 [influent] "Independent digestate VS assay on day 130 ... 15.583 vs
13.455: the digester holds more volatile solids than the feed log and catalogue imply,
while gas is also higher than predicted. More feed organic matter than declared explains
both; **a gas-meter fault would not raise digestate VS, and slower kinetics would raise VS
but lower gas.**" → **LM**: a correct three-way differential across coupled channels
(S1 vs S2 vs S5), misapplied because the null cell's own tier-C record shows the same pair
(S0-01 B/C at defaults: VS +4.3, gas +3.9). E2 [influent] Fisher intervals span the
bounds and the Y_ac/k_dis fit runs to 0.5/4.0 "to compensate the gas deficit: the misfit
is not a kinetic change" → **LC** as a statement (bound-hit ≠ parameter change), used for
influent by elimination. E3 [influent] after the fit the gas residual is still biased →
**LM**. E4 [influent] informative missingness → no claim → **UNS** (an abstention note
under an influent label).

S7: **No** — but note what it did test: `simulate(biomass_scale=2.0)` (call 8) as a
state test and a fit as a parameter test; S7 was the one alternative with no step.
S1/S8: **yes** (VS vs gas). Wrong → S7; **available and misread** (the rms_z 7.48 at
defaults is the background; "background" never named).

### C2. run_c91f0ef369cb — S0-01 B/B, truth **none**, label **influent**, conf 0.65

Evidence (4): E0 balance −0.136, 2 inadmissible, "more COD reached the digester than
declared" → **LM** (S8 on the null). E1 after the fit gas +7.6 and COD high from day 0
→ **LM**. E2 digestate COD +10, "unstructured by load/feed, independent lab channel from
gas flow" → **LM** (coherent multi-channel offset, the right form). E3 TAN low from the
start, day-120 TAN assay z −1.83 agrees with the routine channel "so the TAN sensor is
not the cause ... less N reaching the digester" → **LM** (S1 negative test done, then S2
by default). Also ran `biomass_scale=1.5` (call 20) as the state test. S7: **No**.
S1/S8: **yes**. Wrong → S7; available and misread.

### C3. run_1f496ca167b5 — S0-01 B/C, truth **none**, label **influent**, conf 0.7

Evidence (5): E0 balance → **LM**. E1 after a 4-parameter fit (interior: Y_ac 1.27,
k_m_ac 0.89, k_m_h2 1.15, k_m_pro 1.11, finite Fisher intervals) "gas flow and digestate
VS stay biased high from the first day to the end with no step; kinetics cannot raise
both gas and residual VS at once, which an under-declared feed COD/solids load does" →
**LM** (literate differential; background). E2 VS residual flat in time, structured by
fog fraction → **LM**. E3 VS assay agrees with routine VS → "not a sensor fault" → **LC**
(S1 negative test). E4 TAN over-predicted → "declared feed N too high relative to its
COD" → **LM**. S7: **No** — this run came closest to the S7 route (a converged interior
fit with finite intervals) and declined it because gas stayed at rms 7.5. S1/S8: yes.
Wrong → S7; available and misread.

### C4. run_5aa4b15dc26c — S1-01 B/B, truth **none**, label **influent**, conf 0.7

51 evaluations, 12 turns. Evidence (3): E0 [influent] "COD balance built on the declared
feed is inadmissible: methane COD plus effluent COD exceed declared COD in (30–60 d
window CH4 alone exceeds COD in), and closure varies by window in a way anti-correlated
with declared load (−0.48 in 30–60 d vs −0.03 in 60–90 d ...). **A kinetic change cannot
create COD; a constant meter scale cannot produce window-dependent closure.**" → **LM**.
The most process-literate S8 statement in the corpus: the arbiter applied, both
alternatives excluded by mechanism, the numbers read per window; wrong because this cell
is `none` and the tool reports the same open balance on it. E1 gas +13.6 structured by
feed batch and thickened-WAS fraction, "residual ≈ 0 in the WAS-dominated 58–90 d
window; Morris shows the largest kinetic effect on gas flow (Y_ac μ* 91 m³/d) is far
below the ~650 m³/d mean residual, so no kinetic parameter in bounds can explain it" →
**LM** (a sensitivity-magnitude test of S5 that P0 does not have; background). E2 two TAN
assays (+3.6σ, +1.6σ) confirm the routine channel → "rules out a gas-meter-only fault"
→ **LM**. S7: **No**. S1/S8: yes. Wrong → S7; available and misread. Note the record
itself: S1-01 at defaults shows gas +25 % (mean_z 8.0) and CH4 COD exceeding declared
COD in one window on a cell whose only injections are noise ×2 and gaps ×2 (§6).

### C5. run_1fe3b00f112d — S2-01 B/B, truth **sensor (pH)**, label **influent**, conf 0.75

Ran residual_diag on gas, TAN, alkalinity (5, 6, 12–14) — **never on pH**. The default
`simulate` (call 4) already showed pH mean_z −1.49, rms_z 1.77, the second-largest
rms after gas, observed mean 7.057 against predicted 7.268 (−0.21 pH units = 10× sd_abs;
record min 6.69 where S0-01 B's is 7.02). Bought TAN d100 (z −16.1) and alkalinity d30
(z −5.2), both agreeing with the routine channels.

Evidence (6): E0 balance −0.12 every window → **LM**. E1 gas under-predicted and TAN
over-predicted from the start, "opposite-signed offsets in carbon and nitrogen channels
from day 0 ... not a single sensor, not a decaying initial state" → **LM** (explicit
differential against S1 and S4 — literate — on channels that are the background, while
the faulty channel was not in the comparison). E2 TAN steady, no step → **LM**. E3 fit
(k_hyd_li to bound) leaves residuals → "not a parameter change" → **LC**. E4/E5 assays
confirm routine TAN and alkalinity → "so the offsets are not a routine-sensor fault; less
N reached the digester" → **LM ×2** (the S1 negative test is right for those channels;
the inference to influent is not).

S7: **No**. S1 before the label: **yes, for the wrong channels**. Missing S1 on pH
(pH departing while alkalinity and VFA agree with each other; the tool's
`charge_consistent: false` in call 3, cited as influent evidence): **available in call 4
and misread; `residual_diag(ph)` never run.**

### C6. run_d07d559fc20b — S3-01 C/B, truth **influent**, label **influent**, conf 0.65

Evidence (4): E0 gas, TAN, alkalinity all over-predicted "with small early bias and large
late bias (onset ~day 31 for gas), and gas residual is structured by load and feed batch:
the pattern of less degradable COD and less N reaching the digester than the
log/catalogue imply" → **LC** (S2's onset-and-load form; early −0.7 → late −8.2, load
η² 0.26 structured, feed_batch structured; the tool's best split is day 31, the truth
day 60). E1 day-138 assays confirm low TAN (−5.4σ) and alkalinity (−3.2σ) → not sensor
→ **LC**. E2 charge inconsistent, closure −0.033 admissible → **LM** (charge alone). E3
four-parameter fit at bounds leaves residuals → not parameter → **LC**. S7: No. S1/S8:
yes. Correct; the batch-window end (residual returning to zero at day 120) was not
examined, so the mapping revision is not localised to the batch.

### C7. run_8fe9dd4f9892 — S4-01 B/B, truth **state**, label **influent**, conf 0.65

Evidence (3): E0 refit (Y_ac, k_hyd_li to lower bounds) leaves TAN/COD bias "from the
start: the misfit is not kinetic"; closure −0.078 → **LM**. E1 "TAN is under-predicted by
a constant ~0.18 kg N/m³ from day 0 with no time, load, feed or temperature structure;
an independent lab TAN assay on day 98 confirms the plant value (0.7415 vs 0.543), so
the TAN sensor is correct and more nitrogen reaches the digester" → **LM** (S1 negative
then S2; S4 never tested). E2 "Alkalinity is under-predicted from the start (**no step at
the day-6 reagent change**), **as extra ammonium bicarbonate from an N-richer feed would
produce**; the day-98 alkalinity assay agrees with the sensor" → **LM** — the most
chemically literate statement in the arm (TAN→NH₄HCO₃ alkalinity coupling; an operator
note used as a negative anchor), on the wrong hypothesis.

S7: No. S1/S8: yes (and the TAN–alkalinity coupling used). Missing S4: the start-up
transient is **in the record** (VFA 2.15 on day 7, COD 34.4 on day 7, CH4 fraction 0.54
on day 1; `data_qc` reports them as spikes at days 0, 1, 7) and was not examined; the
early/late split was read for TAN (early 8.5 → late 18.2, which argues against a decaying
state for that channel); `simulate(biomass_scale)` **never run** in this cell (run twice
by this model in the null cells).

### C8. run_fd74a0e24f3b — S5-01 A/A, truth **parameter (K_I_nh3)**, label **influent**, conf 0.7

Evidence (4): E0 gas residual time-structured, "overpredicting mid-record and
underpredicting late, tracking the feed TS assays rather than load; **not a random
background misfit**" → **LM** (the time bins [−20, −33, −31, −8, +16] are a late change,
read as a feed-TS trend without a check). E1 VS assays +2.9σ at day 130 and +6.2σ at day
255 → "more volatile solids reached the digester" → **LM** (VS growing after the day-120
onset is the process consequence). E2 TAN +2.0/+2.3σ → "more feed nitrogen ... and with
the positive pH residual present from the start" → **LM** (the TAN↔pH coupling is read
correctly; pH held high with TAN high is the S3 presentation). E3 fit of k_dis, k_m_ac to
lower bounds leaves structure → "not kinetics" → **LM**: the screened set (10 parameters,
Morris on gas and pH) **did not contain K_I_nh3**, so the parameter test excluded the
parameter.

S7: No. S1/S8: yes. Missing S3 → parameter: VFA assay **never bought** (luna bought it:
+7σ); K_I_nh3 **never screened or fitted**; a split-window fit **never run**; pH +18.5σ
high from the start **available (call 6) and read as feed N**.

### C9. run_70f3cc12fb4b — S6-02 B/B, truth **structural**, label **influent**, conf 0.6

Evidence (4): E0 gas +8 % "structured by feed composition, most by thickened-WAS
fraction and feed batch, not by load or time; refitting hydrolysis/disintegration/
acetoclastic kinetics leaves it unchanged (rmse_z 7.4967 → 7.467)" → **LM** (S2
covariate form; +8 % is below the null cells' +11 %). E1 closure −0.059, charge
inconsistent → **LM**. E2 "**Against a sensor fault: the independent gas-composition,
alkalinity and pH channels agree with the model within declared noise, and the gas-flow
residual is not load-structured as a meter scale error would be**" → **LC** (a proper S1
exclusion, and the only explicit declared-noise comparison in the arm). E3 TAN assay
+2.7σ during the high-WAS batch, while the day-29 TAN assay (+0.3σ) and the day-117 VS
assay (−0.1σ) agree with the model → "the N-rich feed delivered more degradable material
than declared" → **LM** (two of three assays say no fault; the one that disagreed
decided).

S7: **partial** (E2). S1/S8: yes. The S6 signature is not in the outputs at tier B (see
R9); the honest verdict was `none`/abstain. Confidence 0.6, the lowest in the arm.

### C10. run_858d60d966db — S8-01 B/B, truth **sensor (gas)**, label **sensor** (flag gas_flow, scale 1.297), conf 0.7

A diagnostic sequence worth recording: default simulate; residual_diag gas (bias 13.2,
step day 10, step_z 6.4), TAN, COD, CH4, pH, alk; a `simulate(k_dis=3.0)` probe; feed-log
and assay inspection; biomass_scale 1.5/0.6 probes (a state test); then **two
`set_sensor_status` quarantines used as windows** (days 0–10 kept, then 10–60 kept) with
a `simulate` each, to read the observed/predicted gas ratio before and after the step
(0.84 → 1.30); TAN and COD assays at day 105 (z 1.29, −0.61); then the flag.

Evidence (3): E0 gas residual large, serially structured, steps at day 10, "**other
channels show no matching step**" → **LC** (S1 explicit). E1 "COD balance built on the
measured gas is inadmissible: measured outputs exceed the declared COD input, impossible
unless the gas meter over-reads or extra COD entered" → **LC** (S8 as arbiter, both
branches named). E2 "Independent digestate assays on day 105 agree with the default
model, so the digestate does not show the extra COD/N an influent error of ~30 % would
imply; the gas excess is a metering error" → **LC** (S8 resolved by a third, independent
measurement — the brief's own rule, which this arm never received).

S7: No (sensor excluded by mechanism instead). S1/S8: yes. Correct; the scale factor
1.297 and the day-10 onset fold in the plant's +11 % background (truth 1.08 from day 60).
`bayes_mcmc` never called; no `posterior_intervals` abstention (consistent with the rule,
inconsistent with the answer key).

---

## 3. Per-run table

| arm | cell | truth | label (+secondary) | flag / scale | n evid. | LC / LM / NPB / UNS | S7 tested | S1/S8 checked before the call | missing signature | deciding output |
|---|---|---|---|---|---|---|---|---|---|---|
| luna | S0-01 B/A | none | sensor | gas_flow | 5 | 0/0/3/2 | N | S1 done, inverted | S7 | available, misread (calls 13–15) |
| luna | S0-01 B/B | none | sensor + influent | tan | 3 | 0/2/1/0 | N | S8 only | S7 | available, misread |
| luna | S0-01 B/C | none | influent | gas_flow* | 1 | 0/1/0/0 | N | S8 only | S7 | never run (no residual_diag) |
| luna | S1-01 B/B | none | sensor | gas_flow | 3 | 0/1/2/0 | N | N | S7 | never run |
| luna | S2-01 B/B | sensor (pH) | sensor | **tan** | 5 | 0/4/1/0 | N | partial (assays, not pH) | S1 on pH | available, misread (calls 4, 15) |
| luna | S3-01 C/B | influent | influent + sensor, struct. review | tan | 8 | 2/2/4/0 | N | partial | S1 on TAN vs feed N (secondary); S6 (review) | available, not compared |
| luna | S4-01 B/B | state | state + influent | – | 2 | 0/1/1/0 | N | partial | S4 (right label, wrong reason) | available (QC "spikes"), misread; biomass_scale never run |
| luna | S5-01 A/A | parameter | influent + sensor | gas_flow | 7 | 0/3/4/0 | N | partial | S3 → parameter | available, misread (calls 6–9, 12–15) |
| luna | S6-02 B/B | structural | sensor + influent | vfa_total | 17 | 0/7/9/1 | attempted, not applied | partial | S6 not observable at tier B; S7 | signature absent from outputs |
| luna | S8-01 B/B | sensor (gas) | sensor + structural | gas_flow 1.278 | 6 | 1/1/4/0 | N | Y (implicit) | S6 criterion (secondary) | available, contradicted (interior fit) |
| claude | S0-01 B/A | none | influent | – | 5 | 1/3/0/1 | N | Y | S7 | available, misread |
| claude | S0-01 B/B | none | influent | – | 4 | 0/4/0/0 | N | Y | S7 | available, misread |
| claude | S0-01 B/C | none | influent | – | 5 | 1/4/0/0 | N | Y | S7 | available, misread (interior fit declined) |
| claude | S1-01 B/B | none | influent | – | 3 | 0/3/0/0 | N | Y | S7 | available, misread |
| claude | S2-01 B/B | sensor (pH) | influent | – | 6 | 1/5/0/0 | N | Y (wrong channels) | S1 on pH | call 4 misread; residual_diag(ph) never run |
| claude | S3-01 C/B | influent | influent | – | 4 | 3/1/0/0 | N | Y | – | – |
| claude | S4-01 B/B | state | influent | – | 3 | 0/3/0/0 | N | Y | S4 | QC "spikes" not examined; biomass_scale never run |
| claude | S5-01 A/A | parameter | influent | – | 4 | 0/4/0/0 | N | Y | S3 → parameter | K_I_nh3 never screened/fitted; VFA assay never bought; pH +18σ misread |
| claude | S6-02 B/B | structural | influent | – | 4 | 1/3/0/0 | partial | Y | S6 not observable; S7 | signature absent from outputs |
| claude | S8-01 B/B | sensor (gas) | sensor | gas_flow 1.297 | 3 | 3/0/0/0 | N | Y | – | – |

\* luna S0-01 B/C set `flag_sensor: gas_flow` (one quarantined spike) under an influent label.

## 4. Per-arm totals

| | rev2 (luna) | rev2_claude |
|---|---|---|
| recorded evidence items | 57 | 41 |
| LITERATE-CORRECT | 3 (5 %) | 10 (24 %) |
| LITERATE-MISAPPLIED | 22 (39 %) | 30 (73 %) |
| NOT-PROCESS-BASED | 29 (51 %) | 0 (0 %) |
| UNSUPPORTED | 3 (5 %) | 1 (2 %) |
| runs where S7 was tested before labelling | 0 (1 attempted after the fact: S6-02) | 0 (1 partial: S6-02, "within declared noise") |
| sensor labels preceded by an S1 coupled-channel check | 1 of 8 (S8-01; 3 partial) | 1 of 1 (S8-01) |
| influent labels preceded by an S8 balance reading | 5 of 5 (as the sole evidence in 3) | 9 of 9 (with residual profile and assays in 9) |
| sensors excluded from the objective on QC flags alone, before any simulation | 6 of 10 runs (2–5 sensors each) | 0 of 10 |
| runs with a wrong primary label | 6 | 8 |
| ... where the deciding signature's tool output was available and not used as such | 4 (S0-01 A, S0-01 B, S5-01, + flag in S2-01) | 6 (S0-01 ×3, S1-01, S2-01, S5-01) |
| ... where the deciding tool was never run | 2 (S0-01 C, S1-01: no residual analysis) | 2 (S4-01: biomass_scale; S5-01: K_I_nh3 / VFA assay) — both also had misread outputs |
| ... where the signature is not observable in any output obtained | 1 (S6-02) | 1 (S6-02) |
| harness refusals (record_evidence / conclude / fit) | 56 | 25 |
| primary label = truth / exact set | 4 / 1 | 2 / 2 |

## 5. The answer to the audit question

**Mixed, and split cleanly by arm.** The Claude arm is process-literate-but-misapplied:
30 of 41 items invoke a real signature in a form a process engineer would accept —
the COD balance as arbiter with both alternatives excluded by mechanism, a
coupled-channel differential ("a gas-meter fault would not raise digestate VS; slower
kinetics would raise VS but lower gas"), the TAN-to-alkalinity coupling, independent
assays used to acquit a routine channel, sensitivity magnitude against residual
magnitude — and they are wrong for one reason repeated nine times: the plant's
background (gas +11–25 % at defaults, COD closure −0.06 to −0.19, two inadmissible
windows on the clean cells) was taken as the fault, because no step ever asked what a
clean record on this plant looks like. The luna arm is not process-based in the majority
of its items (29 of 57): a label is produced as a by-product of data-quality policing (a
QC missingness or spike flag becomes "sensor"; 6 of 10 runs excluded 2–5 sensors before
the first simulation), z-statistics are read as verdicts without the magnitude beside
them (pH flagged at rmse_z 0.35; CH4 fraction flagged at a mean offset below its
sd_abs), and labels are attached to numbers by vocabulary (four `[state]` items on four
assay disagreements with no mechanism; `[structural]` on step_z 3.5). Where luna was
literate (22 items) it was misapplied the same way as Claude, plus a second way Claude
never showed: the true signature seen and outranked (S2-01: pH at −17.5σ listed as one of
four "flagged records", TAN flagged instead; S5-01: VFA +7σ, TAN +3.9σ, pH high and the
K_I_nh3 fit at its bound recorded in adjacent items and attributed to feed nitrogen). The
three most telling quotations:

1. luna, S0-01 B/A, `set_sensor_status(ph)` at turn 11, with rmse_z 0.347 and a mean
   residual of −0.021 pH units in the cited call: "After the default and constrained fit,
   pH residuals retain strong time/serial structure and a day-139 step (bias_z −5.1002,
   step_z 9.4698); the two independent day-140 chemistry assays are not comparably
   discrepant, so pH is not used for the final calibration." — numbers without a
   mechanism, and the coupled channels' agreement read as confirmation.
2. Claude, S1-01 B/B, evidence E0 on a `none` cell: "methane COD plus effluent COD exceed
   declared COD in (30–60 d window CH4 alone exceeds COD in) ... A kinetic change cannot
   create COD; a constant meter scale cannot produce window-dependent closure." — S8
   applied exactly as the literature would, on a balance the tool reports open for the
   clean plant.
3. luna, S5-01 A/A, evidence E5 beside E3 (VFA +7.02σ) and after the K_I_nh3 fit ran to
   its bound: "Independent TAN is 3.8876 sd above the model value at day 220, consistent
   with the declared feed mapping understating nitrogen reaching the digester rather than
   a gas-sensor explanation." — the ammonia-inhibition presentation (VFA up, TAN up, pH
   held high, gas flat) split across items and never assembled.

The counter-example that shows the knowledge is there when the reference is: Claude on
S8-01, where the meter's excess (+28 %) exceeds the background, the other channels and
two assays agree with the model, and the run says so in three literate-correct items and
a windowed before/after ratio test.

## 6. Differences in kind of reasoning between the two models (not in score)

- **Where the label comes from.** Claude forms one hypothesis from the balance and the
  from-day-0 residual profile by turn 3–4, then spends the run trying to break it
  (fit-to-bounds as the parameter test in 10/10 runs; `biomass_scale` as the state test
  in 2; assays as the sensor test in 9/10; an explicit "against a sensor fault" item in
  S6-02). Luna's label emerges from housekeeping: QC flags → `set_sensor_status` →
  `record_evidence[sensor]` in the same turn (6 of 10 runs), and the residual/assay work
  later adds labels rather than testing one (S3-01: 8 items, 3 labels, plus a structural
  review; S6-02: 17 items, 3 labels, 18 abstentions).
- **What a number means.** Claude reads magnitudes with the z's (offset −0.01 within
  sd_abs 0.01; 0.84 → 1.30 observed/predicted; Y_ac μ* 91 m³/d against a 650 m³/d gap;
  "constant ~0.18 kg N/m³ from day 0"). Luna reads z's as verdicts and records
  `step_day`/`step_z` for every channel as if a step had been found.
- **Coupled channels.** Claude couples channels in its statements (gas↔VS, TAN↔alkalinity,
  CH4 COD↔feed COD, gas ratio↔digestate COD) in every run; luna's items are almost all
  single-channel, and the only multi-channel move it makes — buy assays — it reads point
  by point (S2-01, S5-01, S6-02).
- **Notes.** Both used operator notes as anchors and both did it competently in form
  (Claude: "no step at the day-6 reagent change"; luna: the day-133 technician note for a
  VFA window); neither followed a note as an instruction.
- **The fixed prior.** Claude reached `influent` 9 times in 10, including the one sensor
  cell it missed (S2-01) and the parameter and state cells: its first read is always the
  balance, and the balance is always open. Luna reached `sensor` 8 times in 10 (flagging
  gas_flow 4×, tan 3×, vfa 1×), because its first act is always QC.
- **Budget and friction.** Claude used 51–259 evaluations and 12–23 turns with 25
  refusals; luna 130–348 evaluations, 10–27 turns, 56 refusals (value keys, interval
  methods, `end_d`), lost two runs to the wall clock (S0-01 C at 92.6/90 min, S1-01 at
  84.6) and never examined residuals in either.
- **Same blind spots.** Neither arm named the background, ran a split-window fit, called
  `bayes_mcmc`, or examined the first two weeks of a record as a transient; both treated
  the day-0/day-7 excursions of S4-01 as outliers.

## 7. Implications for P2 procedural roles

Signatures that must be encoded as steps (the model did not supply them in 20/20 runs):

1. **S7, the null reference (data-quality / coordinator role).** Before any label, the
   channel residual profile at defaults and after the screened fit, compared with the
   plant's background envelope (from the clean generator or the P0 round-2 record: gas
   rms_z ≈ 7, biases 5–19σ after fit; closure −0.14 with two inadmissible windows), not
   with instrument noise. A label requires a channel or a balance that leaves the
   envelope. This single step removes the Claude arm's whole failure mode and 3 of luna's
   6 wrong primaries.
2. **S8 with a null band (influent role).** `influent` needs closure outside the null band
   (P0: ≥ 3 inadmissible windows) *and* an onset or a feed-covariate pattern; charge
   inconsistency alone never fires (ruling B(b)). The `mass_balance` result should carry
   the band so the model cannot read `admissible: false` as a verdict.
3. **S1 as a mandatory table (data-quality role).** Any `sensor` label must be preceded by
   the candidate channel's residual beside its physically coupled channels' residuals and
   any assay of them, and by a rule that QC flags (spikes, informative missingness, a
   single drift flag on a lab channel) produce quarantines and abstentions, never a label
   (P0 rulings B(a), (b)). This is where 6 of luna's 8 sensor labels came from.
4. **S4 as a step (identifiability / calibration role).** Early-window vs late-window
   residual on every channel *before* quarantining early "spikes", and a
   `simulate(biomass_scale)` pair whenever the early window differs; the QC spike list for
   the first HRT is handed to the state test, not to the quarantine.
5. **S3/S5 change-point and inhibition tests (calibration role).** A split-window fit at
   the best common step across ≥ 2 channels (P0's R4), and a candidate list that is
   physics-forced per plant (K_I_nh3 and the hydrolysis constants always screened on
   Plant A), so that Morris on pH cannot drop the parameter that the scenario is about;
   the VFA/TAN/pH inhibited-steady-state test as an explicit check when TAN and VFA are
   both high.
6. **S6 (verifier role).** Structural review only on P0's R3 criterion (≥ 2 channels
   structured after the fit, or a parameter at a bound) *and* a failed hold-out; the
   verifier is the only role that can see the hold-out, so this is the one signature P1
   could never test.
7. **Level-8 discipline (verifier).** The sampler is called by procedure (P0 does), and
   `posterior_intervals` is abstained only after a failed call; neither arm called it.
8. **Evidence hygiene (coordinator).** One label per cited call; no relabelling of an item
   between turns (luna S5-01 moved four assay items from state to influent); a refusal
   budget with the vocabulary shown once.

Decisions that can be left to the model (the transcripts show it does them well):

- Which assay to buy, on which day, against which prediction: Claude's choices (VS at
  tier A, TAN before and after a suspected batch, COD and TAN on the day the balance is
  worst) were apt in 9/10 runs, and its windowed observed/predicted ratio in S8-01 is a
  diagnostic P0 does not have.
- Writing the mechanistic differential once the tables exist (the gas/VS/kinetics
  three-way, the TAN/alkalinity coupling, the meter-vs-influent resolution by a third
  measurement): these were correct in form whenever the reference was right.
- Reading operator notes as evidence and as negative anchors.
- Choosing the fitted subset within a physics-forced candidate list, and declining to
  offer bound-hitting or non-identified values as a kinetic update (0 false kinetic
  updates in 20 runs; every run set `kinetic_update: false`).
- Abstention wording, once the answer-key-scored terms are procedural (luna's 18–21
  abstentions by vocabulary would otherwise cost precision).

## 8. Observations for the coordinator (outside the rubric, found on the way)

- **S5-01's injected magnitude is outside the fitted model's box.** The fault multiplies
  K_I_nh3 by 0.1 from day 120; `describe_model` declares K_I_nh3 bounds [0.2, 5.0]. Luna's
  K_I_nh3-only fit ran to 0.2 and was discounted, as the prompt instructs ("a fitted value
  at or near its bound is a warning sign"). The scored "bounded update" cannot reach the
  truth in this cell; worth a `docs/decisions.md` entry.
- **The null cells are not reachable by P1 as the tools stand.** S0-01 B/B, B/C and
  S1-01 present `admissible: false`, two inadmissible windows, closure −0.14/−0.14/−0.19,
  and gas +11–25 % at defaults; P0 needed ruling B to stop reading them as faults, and the
  prompts cannot name the thresholds. Every P1 arm in the five-arm table scores 0/4 on
  "none reached on none cells". Either the null band goes into the tool result, or the
  prompt states it numerically, or `none` stays unscoreable for P1.
- **S6-02 at tier B shows no alkalinity/pH deficit in the outputs** (alkalinity mean_z
  +0.10 and pH −0.30 at defaults, inside the S0-01 B envelope of −1.46 and −0.25); P0
  also read `none`. The Level-6 signature may need tier C (digestate TS) or a larger
  magnitude to be visible through `residual_diag`.
- **`data_qc` labels the Level-4 transient as spikes.** In S4-01 the days 0, 1 and 7
  excursions of CH4 fraction, COD and VFA are the healing start-up; both arms quarantined
  or ignored them on the QC flag.
- **The Level-8 sampler failure was never exercised by P1**: neither model called
  `bayes_mcmc` in S8-01 (P0 does by plan), so half of that scenario cannot score P1.
- **Wall-clock loss in the luna arm** (S0-01 C at 92.6/90 min after a 220-evaluation fit;
  S1-01 concluded with 5.4 min left and no residual analysis) is a procedural cause of two
  of its six wrong primaries, separate from knowledge.
