# P2: task-specialised procedures with model-backed decision points (proposal §6.5)

Status: **DRAFT, revision 2, for the coordinator's review.** This is deliverable 1 of
`docs/p2_launch_brief.md` §7. Revision 2 answers the review of 2026-10-05 at `c502899`.
Four decisions are **PENDING THE LEAD'S RULING** (§13) and are written as defaults, not
as decided. No live model call happens before the coordinator's review and the lead's
approval. Written by the P2 component session on `claude/p2-multi-agent`, cut from
`main` at `817b1f9`.

The brief is the charter. This document turns its §3 table and its §4 steps into
procedures, schemas and switches that can be built and tested. Where the brief leaves a
choice, the choice is made here, with its reason.

**Paths, used throughout.**

| What | Path |
|---|---|
| The workflow package | `workflows/p2_multi_agent/` |
| Its configuration | `configs/workflows/p2.yaml` |
| Its decision templates | `configs/workflows/p2_prompts/` |
| A run's record | `runs/<id>/workflows/p2/` |

## 1. What P2 is, against P0 and P1

| | P0 | P1 | P2 |
|---|---|---|---|
| Registry, tools, budgets | the run's | the same | the same, one budget per run summed over roles |
| Where it runs | the jail | the jail | the jail, the same stub and checks |
| Who decides the next call | a fixed script | the model | a fixed state machine (code) |
| Where a model is called | never | every turn | at **declared decision points** only, each with a fixed output schema |
| Null reference | P0's thresholds (ruling B) | none (the prompt rule forbids thresholds) | the declared background, by the null rule of §4 |
| Output | `state.json`, `report.json` | the same, plus the model log | the same, plus the message and decision logs (§9) |

**The governing finding** (brief §2): both P1 arms took the plant's background misfit for
the fault, and no step asked what a clean record on this plant looks like. P2's answer is
procedural. Every label must rest on a null case that failed against the published band,
and the steps the models never supplied are code. A model chooses only where the audit
shows models choosing well: assays, windows, the fitted subset within a forced list, and
the mechanistic differential once the tables exist. **Every test that sets a label's
evidence is code**; no decision point can supply one.

## 2. Roles, procedures and decision points

Seven roles (§6.5). Each role is a Python procedure with typed inputs and outputs. A
model is called only at the eleven decision points listed below. Each decision point has:

- a fixed JSON output schema;
- **declared inputs**: the only things its request may contain;
- a versioned **template**, `configs/workflows/p2_prompts/<point>.md`, whose sha256 is
  recorded in every decision record (§6.2);
- a declared **fallback**, used when the output fails validation twice. The fallback is
  P0's rule for the same choice.

A model cannot add, skip or reorder a step, call a tool, or write into the task state.
Tool calls are made by the procedure, through the role's restricted registry view (§6).

### 2.1 Coordination (code only)

The state machine of §5 over the §6.6 task state. It routes the work and does nothing
else:

- It assembles the proposal from the specialists' findings by the admission table of §4.4.
- It enforces evidence hygiene:
  - one label per cited call;
  - no relabelling of an evidence item between rounds;
  - a refusal budget per role.
- It cannot approve its own output: the verifier does that.
- It holds no numerical tool. Its only actions are the stopping actions `conclude` and
  `abstain`, and both are gated on a verifier verdict (§5).

No decision point.

### 2.2 Data quality

**Steps.**
1. `data_qc` on every sensor, with P0's declared ceilings and event windows.
2. P0's §3.1 rules give quarantines and exclusions. **QC never produces a label** (P0
   rulings B(a), B(b)).
3. **Brief decision 4, in code.** First-HRT excursions that QC flags as spikes are not
   quarantined. They go to the early/late test (§2.4, step 4). The first HRT is the
   declared liquid volume over the mean declared daily feed volume of the calibration
   window, computed by code.
4. **The S1 table**, mandatory before any `sensor` finding. It shows the candidate
   channel's after-fit `mean_z` and `rms_z` beside the same statistics of its physically
   coupled channels, read from `p2.yaml` `coupled_channels`:
   - `gas_flow` with `ch4_fraction` and the COD balance;
   - `ph` with `alkalinity`, `vfa_total` and `tan`;
   - `tan` with `ph`;
   - `vfa_total` with `ph` and `alkalinity`;
   - `digestate_ts` with `digestate_vs`.

   Any assay of these channels is shown with them.
5. A `sensor` finding is emitted only when the S1 table holds, **by code**: the candidate
   fails alone (NS of §4), and every coupled channel's after-fit mean is inside the band.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `dq.trust` | QC's findings per sensor (codes, flagged windows), the first-HRT window, the record's sample counts | `{sensor, quarantine: [[t0, t1]], reason: enum{flatline, spike_run, outage}}` | P0 §3.1 |
| `dq.assay` | the S1 table, the assay price list, the units left | `{assay: enum(price list), day, target_sensor}`, passed to the design role | no assay |
| `dq.coupled` | the S1 table, any assay of the candidate and its coupled channels | `{sensor, code: enum{coupled_inside, coupled_outside, assay_acquits, assay_implicates, insufficient}}` | `insufficient`, so no sensor finding |

**`dq.trust` is constrained by code** (brief decision 4; the review's item 6). A
quarantine is refused when it:
- overlaps the first HRT, so a model cannot erase the S4 signal;
- covers any sample that QC did not flag (a flatline segment, a spike sample or an
  outage);
- reaches into the hold-out.

A refusal is logged as `p2.dq.refused` and counted. The model can narrow QC's
quarantines; it can never widen them.

`dq.coupled` names what the coupled channels show, not what it implies.
`coupled_inside` (the deviation is isolated) supports a `sensor` finding.
`coupled_outside` (the coupled channels moved too) speaks against one.

**Tools:** `data_qc`, `inspect_record`, `set_sensor_status` (quarantine only).

### 2.3 Influent

**Steps.**
1. `mass_balance` over the calibration window, in 30-day windows as the band uses.
2. The feed-log and notes inspection, as a step. Operator notes are data. A note that
   names a cause is a **negative anchor**: it is recorded and never used as evidence for
   that cause.
3. **The onset test, in code.** It passes only when either of these holds:
   - **a dated onset:** every closure window before the onset day is inside the band's
     per-window envelope (`cod_closure_windows`), and at least two windows after it are
     outside, on the side NB failed;
   - **a feed covariate:** P0's R2 feed η² ≥ 0.15 on the primary residual, computed by
     `residual_diag` on the reference fit.

   A closure that is offset in every window has no onset, so it does not pass. The model
   proposes a day; the code accepts or rejects it.
4. An `influent` finding requires **NB failed** (§4) **and** the onset test passed.
   Charge inconsistency alone never produces one.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `influent.onset` | the feed log, the notes (as quoted data), the per-window closures with the band's per-window envelope | `{onset_day: number or null, feed_id: enum(catalogue) or null, anchors: [note_day]}` | `null`, `null`, `[]` |
| `influent.window` | the per-window closures | `{window_index}` among the evaluable windows | the band's worst-window rule |
| `influent.mechanism` | the balance table, the feed log, the onset test's result | `{code: enum{fractionation, moisture, unrecorded_delivery, mislabel, none}}`, reported only, never a label | `none` |

**Tools:** `mass_balance`, `feed_loads`, `inspect_record`, `declared_background`.

### 2.4 Identifiability

**Steps.**
1. The **physics-forced candidate list** for the plant, from `p2.yaml`
   `forced_candidates`. On Plant A it always includes `K_I_nh3` and the three hydrolysis
   constants, so a Morris screen on pH cannot drop the parameter a scenario is about.
2. Morris and Fisher, by P0's rules and seeds. This is the band's declared screening
   (§3), so the reference fit is like-for-like with the band.
3. Sobol and profiles only where P0's ladder (§4 of `docs/p0_design.md`) says the plan
   allows.
4. **The early/late test, in code** (S4; the review's item 7). On every calibrated
   channel, against the reference fit, it uses P0's R5 thresholds from `p0.yaml`. A
   channel **fires** when both of these hold:
   - its bias in the first `attribution.transient_d` (30 d) is beyond
     `attribution.state_bias_z` (3.0);
   - its bias after that window is within `attribution.clean_bias_z` (1.5).

   The test runs **before** any quarantine of the first HRT. Its result is code's alone;
   there is no decision point for it.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `ident.subset` | the forced list, the Morris ranking and kept set, the Fisher relative CRLBs | `{parameters: [name]}` ⊂ forced list ∪ Morris kept, 2 to 4 of them | the reference fit's subset |

**Tools:** `describe_model`, `gsa_morris`, `gsa_sobol`, `profile_likelihood`,
`fisher_info`, `residual_diag`.

### 2.5 Calibration

**Steps.**
1. **The reference fit (§3).** This is the band's declared procedure, run once:
   - `fit_lsq` with 1 start, 40 evaluations and P0's seed, on the reference subset;
   - one `simulate` at the optimum.

   It is P2's first calibration as well as the verifier's null reference, so it is never
   spent twice.
2. The fit on `ident.subset`, when that differs from the reference subset. It is warm
   started from the reference optimum and costed by P0's ladder.
3. **S3/S5, the split-window fit.** It is run when two or more channels show a step
   (P0's R4 inputs): two fits either side of the best common step day, within P0's 30-day
   tolerance.
4. **The inhibited-steady-state check (S3), in code.** It runs only on a tier that
   carries both `tan` and `vfa_total`. Its output is a `Table` of kind `inhibition`:
   - `tan_mean_z`, `vfa_mean_z` and `ph_mean_z` after the reference fit;
   - `inhibited: bool`, true when both TAN's and VFA's after-fit means are above the band
     maximum and pH's is not above it.

   `inhibited` counts as a `parameter` signature (§4.4).
5. **The `simulate(biomass_scale)` pair** whenever the early/late test fires on any
   channel: the reference optimum at biomass scales 0.5 and 2.0. The pair **improves the
   early window** when either scale lowers the early window's RMS standardised residual,
   on the channels that fired, below the reference's.
6. `bayes_mcmc` by procedure on the approved subset. `posterior_intervals` is abstained
   only after a failed call (Level-8 discipline).
7. **A bound hit is never a kinetic update.** It is a finding of type `bound_hit`, which
   the verifier reads under S6.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `cal.accept` | the fit's χ², its convergence, the reference χ², bound hits | `{accept: bool, code: enum{converged, not_converged, worse_than_reference, bound_hit}}` | accept iff χ² ≤ the reference χ² |
| `cal.bound` | the parameter, its bounds, its estimate and Fisher sd | `{code: enum{identifiability_limit, data_limit, structure_hint}}`; the enum has no kinetic-update value | `identifiability_limit` |
| `cal.split` | the per-channel step statistics and split days, from code | `{common_step_day: number or null, channels: [sensor]}`, accepted only where P0's R4 arithmetic agrees within 30 d | P0's R4 arithmetic |

**Tools:** `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc`, `simulate`, `residual_diag`,
`declared_background`.

### 2.6 Experimental design

**Steps.**
1. `voi_assay` when a role requests an assay and the plan allows the cost.
2. The registry enforces the assay budget. The role cannot exceed it, and asks before
   every request.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `design.assay` | the request and its reason code, `voi_assay`'s table, the price list, the units left | `{assay: enum(price list), day, prediction: enum(channel)}` | P0 §3.6 |

The audit found these choices apt in 9 of 10 runs **on Claude**, not on GPT. With GPT
(§13, decision d) this decision point may be weaker than the audit suggests.

**Tools:** `voi_assay`, `request_assay`.

### 2.7 Verification

The verifier receives three things:
- the proposal, as typed fields only;
- the full visible action log (`calls.jsonl`, projected);
- the frozen hold-out data, through its own `validate` calls.

It **receives no free text from any role**: no statement, no annotation and no model
output except the enum fields of the decision records. This is tested with a planted
claim (§10).

**Steps, in order.**
1. **S7, the null table.** `declared_background(plant, tier)` is read, and every ruled
   statistic of the reference fit (§3) is placed against the band: 12, 35 or 63
   statistics by tier. The null components NB, NM and NS of §4 are evaluated. The table
   goes into the state. **A run without a completed null table** (the reference fit
   unfinished) **abstains** (§13, decision c).
2. **Admission.** Each proposed label must rest on a null component that failed (§4.4).
   A label without one is rejected, whatever its signature.
3. **The hold-out.** One `validate` call on the proposal's prediction. The verifier is
   the only role that holds `validate`.
4. **S6.** `structural` is admitted only on two conditions:
   - P0's R3 criterion: two or more channels stay structured after the fit, or a
     parameter sits at a bound;
   - a failed hold-out, by the criterion of §12, question 3.
5. **The differential:** one decision, made from the tables.
6. **The verdict:** `pass`, `fail` (with reason codes) or `abstain`.

**Decision points.**

| id | Inputs | Output schema | Fallback |
|---|---|---|---|
| `verify.differential` | the null table, the admitted labels with their signature tables, the hold-out flag | `{label: enum(admitted ∪ {none}), rejected: [{label, code: enum{null_not_failed, signature_absent, coupled_outside, holdout_passed, superseded}}]}` | the first admitted label in P0's order (sensor, influent, state, parameter, structural); `none` if no label is admitted |

The differential can only choose **among labels code already admitted**, or `none`. It
cannot admit one.

**Tools:** `declared_background`, `validate`, the read-only state and log.

### 2.8 Which roles have a model

- Four roles have model decisions inside their procedure: data quality, influent,
  identifiability and calibration.
- Two roles have one narrow decision each: experimental design and the verifier's
  differential.
- Coordination is code.

The three-role minimum of the descope clause is data quality, calibration and
verification, with coordination always present as code.

## 3. The reference fit: like-for-like with the band

The band's statistics come from a **declared procedure**, served in the tool's
`procedure` block:
- a default `simulate`;
- `mass_balance` in 30-day windows over `[0, 0.75 T]`;
- Morris with 4 trajectories and seed 101, then P0's Morris rule (relative μ* ≥ 0.10,
  keep ≤ 4, at least 2);
- Fisher with relative CRLB ≤ 0.5;
- `fit_lsq` with 1 start, 40 evaluations per start and seed 104;
- one `simulate` at the optimum.

A run is comparable with the band only if its statistics come from the same procedure.
So:

- P2's **first** calibration is the reference fit, run with the `procedure` block's
  settings as served, never retyped.
- The verifier places the **reference fit's** statistics against the band, never those
  of a later, better fit. A later fit changes P2's estimates, not the null table.
- **The arithmetic is reimplemented in the workflow** (the review's item 5).
  `mean_z` and `rms_z` with P0's declared-noise weights over the calibration window, and
  the placement, are written in `workflows/p2_multi_agent/`. Nothing is imported from
  `scripts/`: `scripts/declared_background.py` reads truth manifests
  (`manifest_baseline`), and an import would break the truth-isolation test's allow-list.
  A test pins the workflow's arithmetic to the driver's `_Series` on the same record,
  run from the test side, which may import both.

**Cost.** On the clean record the reference procedure averaged:

| Plant | Evaluations, mean | Evaluations, max | Wall clock, mean | Wall clock, max |
|---|---|---|---|---|
| A | 130 | 175 | 57 min | 76 min |
| B | 144 | 187 | 46 min | 82 min |
| C | 141 | 204 | 37 min | 65 min |

The wall-clock figures were measured with four computations sharing the machine, so they
overstate a lone run. Against budgets of 450–750 evaluations (Plant A 225–375) and
90–150 minutes, that is a large share. It is why the reference fit must be P2's own
first fit and never an extra one. Deliverable 2 measures it alone on the machine (§11).

## 4. The null rule

### 4.1 Why not "any statistic outside"

The coordinator's leave-one-out check, reproduced and extended in
`scripts/null_rule_loo.py` (report: `reports/background/null_rule_loo.json`, pinned by
`tests/test_null_rule_loo.py`), judges each clean run against the envelope of the other
clean runs of its plant and tier.

- **Each single statistic** falls outside on 15 % of clean runs. Exchangeability
  predicts 2/N for one statistic against a leave-one-out envelope of N − 1 others, and
  2/(N + 1) against the published envelope of N.
- **"Any statistic outside"** fires on 90 of 120 clean runs (75 %).
- **"Any channel's after-fit mean outside"** fires on 66 of 120 (55 %).

A null rule built on either would put `none` out of reach on most clean runs, which is
P1's wall again. The band is unchanged. What changes is how P2 reads it.

### 4.2 The rule

Three **null components**. Each is a conjunction of placements against the published
envelope, `min ≤ value ≤ max` exactly, with **no margin** (the lead's ruling). Temperature
is placed and shown but is never part of a component, because no calibratable parameter
moves it (P0's rule).

- **A channel's null case fails** when three things hold together:
  - its `mean_z` is outside at the defaults;
  - its `mean_z` is outside after the reference fit, on the **same side**;
  - its after-fit `rms_z` is **above** the band maximum.

  A rise in scatter alone, with the means inside, never fails it. More noise or more gaps
  than declared is the ladder's Level 1, whose truth is `none`.
- **NB, the balance's null case.** It fails when either of these holds:
  - the mean COD closure and the worst window are both outside, on the same side;
  - the inadmissible-window count is **above** the band maximum.

  Fewer inadmissible windows than any clean run is not a fault.
- **NM, the multi-channel case.** It fails when two or more channels' null cases fail.
- **NS, the single-channel case.** It fails when exactly one channel's null case fails
  and every other calibrated channel's after-fit mean is inside the band.

**The null is rejected when NB, NM or NS fails.**

**A gap, by design** (the review's item 3). One channel can fail while another channel's
after-fit mean is outside without a full failure. Neither NS nor NM fires there, and that
run reads `none` for its channels. This happens on 7 of 120 clean runs. It can also be an
S1/S3-coherent change.

Adding it as a fourth component would raise the rule's clean false-alarm rate to 26 of
120 (0.22; 95 % interval 0.15–0.30), above the target of §4.3. So it reads `none` by
design. The state records the code `null_partial` so that it can be counted. Its cost in
power is measured in deliverable 2 (§11).

### 4.3 Its clean false-alarm rate, and what that rate is

Leave-one-out false alarms on the committed clean record, as rejections out of clean runs:

| Component | All | A/A | A/B | A/C | B/A | B/B | B/C | C/A | C/B | C/C |
|---|---|---|---|---|---|---|---|---|---|---|
| NB | 8/120 (0.07) | 0/20 | 2/20 | 1/20 | 0/10 | 2/10 | 2/10 | 0/10 | 1/10 | 0/10 |
| NM | 10/120 (0.08) | 0/20 | 2/20 | 2/20 | 0/10 | 1/10 | 1/10 | 0/10 | 2/10 | 2/10 |
| NS | 5/120 (0.04) | 1/20 | 1/20 | 1/20 | 1/10 | 0/10 | 0/10 | 1/10 | 0/10 | 0/10 |
| **Null rejected** | **19/120 (0.16)** | 1/20 | 4/20 | 4/20 | 1/10 | 2/10 | 2/10 | 1/10 | 2/10 | 2/10 |

**How a clean run reads `none`.** All three components must stand. The estimate on the
clean record is that the null is rejected on 16 % of clean runs, with a 95 % interval
(Wilson) of 0.10–0.23 on 19 of 120. So `none` stands on about 84 % of them. The target
is below 0.20.

**What the rate is not** (the review's item 2).
- **It is not a bound on the rule.** The 2/N argument holds for one statistic, not for a
  conjunction with an "every other channel inside" clause. NS can fire more often against
  the wider published envelope; the reviewer's leave-two-out check found 2 such cases.
  The rate is an estimate with the interval above.
- **It is a floor for any cell that is not exchangeable with the clean background.** A
  development cell has its own library seed and influent draw. Where those differ from
  the background's, as the S0-01 B/C digestate solids appear to, the cell's own false-alarm
  rate can be higher than 0.16.

### 4.4 Admission: which label rests on which null case

A label is admitted by the verifier only over an explicit null case that failed, **and**
with the signature its role found. Every signature test is code. A signature without a
failed null case is rejected, with code `null_not_failed`. That is the rule that would
have stopped both P1 arms.

| Label | Null case that must fail | Signature that must also hold (code) |
|---|---|---|
| `sensor` | NS on that channel | the S1 table: every coupled channel's after-fit mean inside; `dq.coupled` ∈ {`coupled_inside`, `assay_implicates`}; a QC flag alone never qualifies |
| `influent` | NB | the onset test of §2.3: a dated onset or a feed covariate; a uniform offset and charge alone never qualify |
| `state` | NS or NM | the early/late test fires on a failed channel, and the `biomass_scale` pair improves the early window |
| `parameter` | NM, with NB not failed | a common change point on two or more channels within 30 d **or** `inhibited` (§2.5), and no feed covariate |
| `structural` | NM | P0's R3 criterion and a failed hold-out (verifier, S6) |
| `none` | none failed, **or** a failure that no label's signature explains | — |

When the null is rejected but no signature explains it, the label is `none`, with:
- confidence `attribution.confidence.none`, lowered to `multiple`;
- the reason code `null_failed_unexplained` in the state.

It is not an abstention. The brief scores abstention on a representable cell as a miss.

**A stated limit** (the review's item 11). A parameter fault that develops smoothly, with
no step, is admitted only through `inhibited`. On a tier without TAN and VFA, Tier A for
example, it can be missed. S5-01 is at Tier A. This is reported, not patched.

### 4.5 Pre-registered predictions on the four clean development cells

This table applies the rule as written to the published placement
(`reports/background/dev_cells.json`) **before any P2 run**. It is a prediction, not an
input: the rule does not change if a live run disagrees.

| Cell | Null components | Expected label | What blocks a wrong admission |
|---|---|---|---|
| S0-01 B/A | none failed | `none` | — |
| S0-01 B/B | none failed. pH's after-fit mean is outside alone, which is not a failure. | `none` | — |
| S0-01 B/C | **NM failed**: `digestate_ts` and `digestate_vs`; VFA's after-fit mean outside, not failed | `none` with `null_failed_unexplained`, **unless** a signature holds | `state` needs the early/late test on a failed channel and the biomass pair. `parameter` needs a common step on two channels or `inhibited`; VFA is low here, not high. `structural` needs R3 **and** a failed hold-out. **The risk, stated:** TS and VS are one physical quantity counted as two channels, so if the hold-out fails, R3 may be met and `structural` wrongly admitted (§12, question 6). |
| S1-01 B/B | **NB failed**: closure −0.191 and the worst window −0.481, both below. `gas_flow` failed alone, but VFA's after-fit mean is outside, so not NS (the gap of §4.2). | `none` with `null_failed_unexplained` | `influent` needs the onset test. A closure offset in every window has no dated onset, and the feed-covariate test is code. A model-proposed onset day is accepted only if every window before it is inside the per-window envelope. `sensor` on gas needs NS, which does not fail. |

So the rule predicts `none` on all four clean cells: two with the null standing and two
with it rejected and unexplained. The prediction holds only if the signature tests reject
as the table says. The brief's success criterion is at least two of four.

### 4.6 How the rule was chosen, and a disclosure

- The components were chosen only on the clean-record rates of §4.3, against a target of
  a rate below 0.20.
- **The timing, plainly** (the review's item 4):
  - the development cells' placement was published on 2026-10-03 and revised on
    2026-10-05 at 18:15 UTC, when the charge drift became unjudged;
  - this rule was written on 2026-10-05 at about 20:45 UTC, after the author had read
    that placement.
- **The clauses that separate this rule from "any after-fit mean outside"** are:
  - the same-side condition at the defaults;
  - the after-fit `rms_z` condition;
  - NS's "every other channel inside".

  These are exactly the clauses that leave S0-01 B/B's pH excursion standing.
- The rule must therefore be argued on its clean-record merits alone: a 0.16 false-alarm
  rate against 0.55 for the simpler rule, and the Level-1 principle for scatter. Whether
  that suffices is the lead's to rule (§13, decision a).

## 5. The routing state machine (coordination)

```
START → QC → BALANCE → REFERENCE → SCREEN → FIT → PROFILE → PROPOSE → VERIFY
                                                                   │
              ┌─────────────────────────── fail (round 1, self-correction on) ┤
              ▼                                                    │
           REVISE → PROPOSE → VERIFY ── pass → CONCLUDE            ├── pass → CONCLUDE
                               └─ fail/abstain → CONCLUDE(none or abstain)
                                                                   └── abstain → CONCLUDE(abstain)
```

**The states and what each runs.**

| State | Role | What happens |
|---|---|---|
| QC | data quality | steps 1–3 |
| BALANCE | influent | steps 1–2 |
| REFERENCE | identifiability, then calibration | the reference fit of §3; the early/late test |
| SCREEN | identifiability | steps 1–3, then `ident.subset` |
| FIT | calibration | steps 2–6, each skipped when its trigger does not fire or P0's ladder says the plan cannot afford it |
| PROFILE | data quality, influent | the S1 table; the onset test |
| PROPOSE | coordination | the findings assembled by §4.4 |

**Assays.** A role's request is routed to the design role at two points: after REFERENCE
(data quality's `dq.assay`) and after FIT (calibration). The design role decides, and
the registry charges.

**Budget guard.** Before each expensive state the coordinator reads `tools.remaining()`.
It applies P0's deterministic plan at `plan.eval_seconds_assumed` = 12 s, with P0's
ladder. When the wall clock left falls below the reserve (P1's 6 minutes), it goes
straight to PROPOSE and VERIFY with what exists. If REFERENCE never completed, the
verifier abstains (§13, decision c).

**REVISE.** This is one round, taken only on `fail`. The failing reason codes go back to
the roles that produced the rejected findings. Those roles re-run their decision points
with the codes as input; codes, never text. No new reference fit is made.

**CONCLUDE.**
- After `pass`, the state is written and the run validated once (§7).
- After `fail` with no round left, the label is `none` with `null_failed_unexplained`
  when the null was rejected, and plain `none` otherwise.
- After `abstain`, the abstentions the verifier named are written, with the label it
  gave.

## 6. Tool allow-lists, messages and templates

### 6.1 The allow-lists

Every role holds a **view** of the run's one registry. A call outside the role's list is
refused in the view, before the registry, and logged as `p2.<role>.refused`. The registry
still enforces budgets (rule 2). The lists are the "Tools" lines of §2, stored in
`p2.yaml` `roles.<role>.tools`.

| Tool | DQ | Influent | Ident | Calib | Design | Verifier | Coord |
|---|---|---|---|---|---|---|---|
| `data_qc`, `set_sensor_status` | ✓ | | | | | | |
| `inspect_record` | ✓ | ✓ | | | | | |
| `mass_balance`, `feed_loads` | | ✓ | | | | | |
| `describe_model`, `gsa_*`, `fisher_info`, `profile_likelihood` | | | ✓ | | | | |
| `residual_diag` | | | ✓ | ✓ | | | |
| `fit_*`, `bayes_mcmc`, `simulate` | | | | ✓ | | | |
| `voi_assay`, `request_assay` | | | | | ✓ | | |
| `declared_background` | | ✓ | | ✓ | | ✓ | |
| `validate` | | | | | | ✓ | |
| `conclude` / `abstain` | | | | | | | ✓ (gated) |

`filter_enkf` and `filter_mhe` are on no list, as in P1: a run registers no state-space
model.

### 6.2 The messages

Every exchange between roles is a typed message (Pydantic), appended to
`runs/<id>/workflows/p2/messages.jsonl` and never edited.

| Message | Fields |
|---|---|
| `Task` | `seq`, `from_role` = coordination, `to_role`, `state`, `inputs`: references to prior messages and call indices |
| `Finding` | `role`, `label` (Label), `null_case` (enum NB / NM / NS / none), `rests_on` (ruled statistic keys), `signature` (enum code), `calls` (call indices), `values` (published evidence keys only, as P1's produced-value check) |
| `Table` | `role`, `kind` (enum `s1`, `null`, `balance`, `onset`, `early_late`, `split`, `inhibition`), `rows` (numbers and enums only) |
| `DecisionRecord` | `role`, `point` (id from §2), `template_sha256`, `schema_sha256`, `inputs_digest`, `output` (validated against the schema), `attempts`, `fallback_used`, `llm_call_ids` |
| `Proposal` | `labels` (ranked), `findings` (refs), `prediction` (call index of the `simulate` or ensemble), `estimates`, `abstentions` |
| `Verdict` | `verdict` (enum pass / fail / abstain), `null_table` (ref), `admitted` (labels), `rejected` (label, code), `holdout_failed` (bool), `abstentions` |

**No message field carries free text.**
- The only free text in a run is the `annotations` of the task state and the report's
  prose. Both are written by the coordinator at CONCLUDE from the enums, and are never
  read by a role.
- A model's output is accepted only through its decision point's schema, whose strings
  are all enums.

### 6.3 The decision templates

Each decision point's request is assembled from:
- its template, `configs/workflows/p2_prompts/<point>.md`;
- its declared inputs, as data.

`p2.yaml` lists every template with its version. The template's sha256 goes into every
`DecisionRecord`, and the runner refuses a run whose templates differ from the committed
ones (P1's frozen-record mechanism).

**The prompt rule, extended** (the review's item 8). No template may contain a labelling
rule the code owns. A test scans every template and fails on any of these:
- a label name, except in `verify.differential`, which receives the admitted labels as
  data;
- a null-component name (NB, NM, NS);
- a threshold number from `p0.yaml` or `p2.yaml`;
- `S\d-\d\d` or `R[1-6]`.

## 7. The hold-out

As in P1, the hold-out `[0.75 T, T]` is not a role's to read. Only the verifier holds
`validate`.

- It is called once per VERIFY round. With self-correction on, that is at most twice.
- Only the boolean `holdout_failed` leaves the verifier. It is used only for S6.
- After CONCLUDE, the concluded prediction is validated once more by the harness, as
  P1's is, and that is the score in the state.

**A known asymmetry, stated rather than hidden.** One bit of hold-out information per
round reaches the proposal through `holdout_failed`, and only to admit or reject
`structural`. P0 and P1 receive none. The brief places S6 in the verifier for this
reason. The verifier-off ablation (§8) removes it.

## 8. The ablation switches (§6.7 E)

Each switch is a key in `p2.yaml` `ablation`. Each has a test that a run with it off:
- leaves the named element out of the record;
- still writes a valid state.

| Switch | Off means |
|---|---|
| `verifier` | PROPOSE goes straight to CONCLUDE with the first proposal. There is no null table, no admission check and no hold-out bit. |
| `coordinator` | The roles run once in the fixed order of §5 with no REVISE. The proposal is the union of the findings, ranked by P0's order. There is no evidence hygiene. |
| `roles.data_quality` | No QC and no quarantines. Every sensor is in the objective. No `sensor` finding is possible. |
| `roles.influent` | No balance step and no onset test. NB is still placed by the verifier, but no `influent` finding is possible. |
| `roles.identifiability` | The fitted subset is the reference subset. There is no forced list. The early/late test still runs, because it is the verifier's input. |
| `roles.calibration` | Only the reference fit. No split window, no MCMC (`posterior_intervals` abstained), no biomass pair. |
| `roles.design` | No assays. |
| `persistent_state` | Each decision point sees only its own step's tables, never the accumulated state or the earlier decisions. |
| `self_correction` | No REVISE. A `fail` concludes at once (§5). |

Which ablations run on which cells, and how many, is in §11. Deliverable 5 runs them
**verifier off first**, as the brief says.

## 9. Budget accounting and the record

**One run, one budget**, summed over roles:
- simulator evaluations, wall clock and assay units, enforced by the registry exactly as
  for P0 and P1;
- model tokens and requests, through P1's `ModelGateway` with the same per-run caps
  (6 M tokens; requests counted against P1's 60 turns).

Every registry call carries its role in the action's `step` (`<role>.<state>`). Every
gateway attempt carries `role` and `point`. The runner's `summary.json` gains:
- `by_role.{evaluations, wall_clock_s, assay_units, tokens, requests}`;
- the same totals as P0 and P1, so the comparison reads one row per run.

**The record**, `runs/<id>/workflows/p2/`:

| File | Writer | Content |
|---|---|---|
| `state.json` | the workflow | `TaskState` with `workflow` = `p2`. `classification.rule` names the null component and the signature code, for example `NS+s1`. `plan` carries the routing trace, the ablation switches, and `null_partial` or `null_failed_unexplained` where they apply. |
| `report.json` | the workflow | the conclusions and the tables, for a human |
| `messages.jsonl` | the workflow | every typed message, in order |
| `decisions.jsonl` | the workflow | every `DecisionRecord` |
| `llm_calls.jsonl` | the gateway (privileged) | every model attempt, verbatim, with role and point; reserved name, as P1's |
| `summary.json` | the runner (privileged) | totals and `by_role` |

The evaluator reads `state.json` and the logs, as for P1. No evaluator change is
proposed, because `eval/` is frozen.

## 10. Tests, before any live call (deliverable 2)

All tests run on P1's two doubles. `ScriptedClient` answers each decision point from a
policy; `RecordedClient` replays.

1. **Allow-lists:** a role calling a tool outside its list is refused, logged and
   counted. The negative control is the same call from a role that holds the tool, which
   succeeds.
2. **No free text reaches the verifier:** a planted claim in a role's model output (an
   extra string field, and a string inside an enum slot) is refused by the schema, and
   the verifier's inputs are scanned for it. The negative control is the same claim
   accepted by a schema that allows text, which the scan then finds.
3. **Budget summed across roles:** the registry's meter equals the sum of `by_role`. A
   role that would exceed the run's budget is refused by the registry, not by the role.
4. **The message log:** every message validates, `seq` is continuous, and every call
   index cited in a message exists in `calls.jsonl`.
5. **The null case in the verifier's output:**
   - on a constructed clean placement, `none` stands;
   - on each of NB, NM and NS constructed to fail, the matching label is admitted only
     with its signature;
   - a signature without a failed null case is rejected with `null_not_failed`;
   - a run with no null table abstains.
6. **Every decision point's schema:** a valid output is accepted. An invalid one is
   retried once, then the declared fallback is used and recorded.
7. **Every ablation switch:** a run with the switch off records it, omits its element,
   and still writes a valid state.
8. **Like-for-like:** the workflow's arithmetic equals the driver's `_Series` on the same
   record. That test lives on the test side, because the workflow imports nothing from
   `scripts/`. The reference fit's settings are the served `procedure` block.
9. **Rule 1:** nothing under `workflows/p2_multi_agent/` reads the truth store, and its
   imports pass the truth-isolation allow-list.
10. **`dq.trust`'s constraints:** a quarantine over the first HRT, over an unflagged
    sample, or into the hold-out is refused. The negative control is a quarantine inside
    a QC-flagged window, which is accepted.
11. **The onset test:** a uniform offset fails it, and a dated step passes it. A
    model-proposed onset day with an outside window before it is rejected.
12. **The templates:** the scan of §6.3, with a planted template line containing a label
    name as its negative control.

## 11. Development plan, power, go/no-go and cost

**Deliverable 2.** The three-role minimum offline (data quality, calibration and
verification, with coordination as code), with the tests of §10. It also does two things
that need no model:
- **It measures the reference fit's wall clock alone** on the machine, on one generated
  cell.
- **Power** (the review's item 10): the reference procedure is run offline on the
  faulted development cells, and the null table and every code signature are reported
  per cell. This gives the hit counts the code alone achieves, before any model is
  involved:

  | Cell | Truth |
  |---|---|
  | S2-01 B/B | sensor |
  | S3-01 C/B | influent |
  | S4-01 B/B | state |
  | S5-01 A/A | parameter |
  | S6-02 B/B | structural |
  | S8-01 B/B | sensor |

  The `null_partial` count is reported with them.

**Deliverable 3.** The three-role minimum live, on three development cells with two
seeds each:

| Cell | Truth | Why |
|---|---|---|
| S0-01 B/B | `none` | the go/no-go cell |
| S2-01 B/B | `sensor` (pH drift) | data quality's S1 path |
| S8-01 B/B | `sensor` (gas scale) with an injected sampler failure | calibration's Level-8 path |

**Go/no-go** (§13, decisions b and c). It is judged on each seed's final label. Stop and
report only if **both** seeds of S0-01 B/B label something other than `none`. A seed
that abstains for want of a null table is excluded, reported, and never counted as
`none`. That is a finding about the band and the rule, not a P2 task.

**Model** (§13, decision d): the frozen P1's `gpt-5.6-luna`, reasoning `high`, no
temperature. Each decision point is one request with one forced tool whose input schema
is the decision's schema.

**Cost and runner time** (the review's item 9; GPT at P1's measured rate, about USD 0.04
per run, and about 50–60 min per run):

| Phase | Runs | Model cost | Runner time |
|---|---|---|---|
| Deliverable 2 (offline, no model) | about 7 reference runs | USD 0 | about 6 h |
| Deliverable 3 | 6 | about USD 0.3 | about 6 h |
| Deliverable 4 (ten cells, two seeds) | 20 | about USD 0.9 | 17–20 h |
| Ablations, every switch on every cell | 9 × 20 = 180 | about USD 8 | 150 h, 6–7 runner-days |
| **Ablations, proposed** | 84 | about USD 4 | about 70 h, 3 runner-days |

The full ablation grid exceeds the brief's "a few runner-days". **Proposed** (pending
the lead, §12, question 7):
- `verifier` off runs on all ten cells × 2 seeds (20 runs);
- each other switch runs on the clean go/no-go cell and the three faulted cells its role
  bears on, × 2 seeds (8 switches × 8 = 64 runs):

  | Switch | Faulted cells |
  |---|---|
  | `data_quality` | S2-01, S8-01, S4-01 |
  | `influent` | S3-01, S2-01, S6-02 |
  | `identifiability` | S5-01, S4-01, S6-02 |
  | `calibration` | S5-01, S8-01, S6-02 |
  | `design` | S2-01, S3-01, S8-01 |
  | `coordinator`, `persistent_state`, `self_correction` | S2-01, S3-01, S6-02 |

## 12. Questions for the coordinator

1. **The model.** Now decision d of §13, for the lead.
2. **The null rule.** Now decision a of §13, for the lead.
3. **`holdout_failed` (§2.7, S6).** The band covers the calibration window only, so there
   is no clean reference for the hold-out. Proposed: the hold-out fails when two or more
   calibrated channels' hold-out `rms_z` exceed their band's after-fit `rms_z` maximum.
   This is conservative, since the hold-out is scored against the same declared noise.
   The alternative, a hold-out band, means extending the background procedure. That is a
   benchmark decision, outside P2.
4. **The one-bit hold-out asymmetry (§7).** Accept as stated, or should S6 wait until
   after CONCLUDE, admitting `structural` only on the final validation and without a
   second round?
5. **The development cells for deliverable 3 (§11).** S0-01 B/B, S2-01 B/B and S8-01 B/B.
6. **Coupled channels in R3's count (§4.5, S0-01 B/C).** `digestate_ts` and
   `digestate_vs` are one physical quantity. Should R3's channel count (a signature, not
   the null rule) count coupled groups, not channels? This question is **motivated by a
   development cell**, so it is stated as such. The null rule would not change, nor would
   its rates.
7. **The ablation grid (§11).** The full 180 runs, or the proposed 84?

## 13. Decisions PENDING THE LEAD'S RULING

Written as defaults. **None is decided.** Each becomes a `docs/decisions.md` entry on
the lead's word.

- **(a) The null rule — PENDING THE LEAD'S RULING.** Default: accept §4 as written, then
  freeze it by recording in `docs/decisions.md` the sha256 of `scripts/null_rule_loo.py`
  and of `reports/background/null_rule_loo.json` at the commit the lead approves.
- **(b) The two-seed go/no-go — PENDING THE LEAD'S RULING.** Default: judged on each
  seed's final label. Stop only if both seeds of S0-01 B/B label something other than
  `none`.
- **(c) A run without a completed null table — PENDING THE LEAD'S RULING.** Default: it
  abstains. It is excluded and reported, and never counts as `none`, toward the go/no-go,
  or toward success.
- **(d) The model — PENDING THE LEAD'S RULING.** Default: GPT, `gpt-5.6-luna` as the
  frozen P1, with about USD 10 in total for deliverables 3–5. Against it: the audit's
  9-of-10 assay choices were Claude's (§2.6).
