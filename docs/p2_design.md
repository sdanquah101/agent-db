# P2: task-specialised procedures with model-backed decision points (proposal §6.5)

Status: **DRAFT for the coordinator's review**. This is deliverable 1 of
`docs/p2_launch_brief.md` §7. No live model call happens before this document is reviewed.
Written by the P2 component session on `claude/p2-multi-agent`, cut from `main` at
`817b1f9` (PR #30, the declared background, merged).

The brief is the charter. This document turns its §3 table and its §4 steps into
procedures, schemas and switches that can be built and tested. Where the brief leaves a
choice, the choice is made here, with its reason, and listed in §12 for the coordinator.

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
the mechanistic differential once the tables exist.

## 2. Roles, procedures and decision points

Seven roles (§6.5). Each role is a Python procedure with typed inputs and outputs. A
model is called only at the decision points listed for the role. Each decision point has:

- a fixed JSON output schema;
- a declared **fallback**, used when the model's output fails validation twice. The
  fallback is P0's rule for the same choice.

A model cannot add, skip or reorder a step, call a tool, or write into the task state.
Tool calls are made by the procedure, through the role's restricted registry view (§6).

### 2.1 Coordination (code only)

The state machine of §5 over the §6.6 task state. It routes the work and does nothing
else:

- It assembles the proposal from the specialists' findings by the admission table of §4.3.
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
3. First-HRT excursions that QC flags as spikes are not quarantined. They are handed to
   the state test (§2.4, step 4; brief decision 4).
4. **The S1 table**, mandatory before any `sensor` finding. It shows the candidate
   channel's after-fit `mean_z` and `rms_z` beside the same statistics of its physically
   coupled channels, read from `configs/workflows/p2.yaml` `coupled_channels`:
   - `gas_flow` with `ch4_fraction` and the COD balance;
   - `ph` with `alkalinity`, `vfa_total` and `tan`;
   - `tan` with `ph`;
   - `vfa_total` with `ph` and `alkalinity`;
   - `digestate_ts` with `digestate_vs`.

   Any assay of these channels is shown with them.
5. A `sensor` finding is emitted only when the S1 table holds: the candidate is outside
   the band (null case NS of §4), and every coupled channel's after-fit mean is inside.

**Decision points.**

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `dq.trust` | Which windows to trust, per sensor | `{sensor, quarantine: [[t0, t1]], reason: enum{flatline, spike_run, outage, none}}`, inside the calibration window | P0 §3.1 |
| `dq.assay` | Which assay to request against a suspected channel, and on which day | `{assay: enum(price list), day, target_sensor}`, passed to the design role | no assay |
| `dq.coupled` | The coupled-channel reading of the S1 table | `{sensor, coupled_consistent: bool, code: enum{coupled_agree, coupled_disagree, assay_acquits, assay_implicates, insufficient}}` | `insufficient`, so no sensor finding |

**Tools:** `data_qc`, `inspect_record`, `set_sensor_status` (quarantine only).

### 2.3 Influent

**Steps.**
1. `mass_balance` over the calibration window, in 30-day windows as the band uses.
2. The feed-log and notes inspection, as a step. Operator notes are data. A note that
   names a cause is a **negative anchor**: it is recorded and never used as evidence for
   that cause.
3. An `influent` finding requires two things:
   - **NB failed** (§4): the mean closure and the worst window are outside the band on
     the same side, or there are more inadmissible windows than any clean run;
   - an onset or feed-covariate pattern: P0's R2 feed η² ≥ 0.15 on the primary residual,
     or a closure onset dated by `influent.onset`.

   Charge inconsistency alone never produces one.

**Decision points.**

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `influent.onset` | The feed log and notes reading | `{onset_day: number or null, feed_id: enum(catalogue) or null, anchors: [note_day]}` | `null`, `null`, `[]` |
| `influent.window` | Which balance window to report as the worst | `{window_index}` among the evaluable windows | the band's worst-window rule |
| `influent.mechanism` | The mechanistic statement, once the table exists | `{code: enum{fractionation, moisture, unrecorded_delivery, mislabel, none}}` | `none` |

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
4. **S4, the early-versus-late residual step.** On every calibrated channel, the bias in
   the first 30 days is compared with the bias after them. This happens **before** any
   early quarantine.

**Decision points.**

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `ident.subset` | The fitted subset beyond the reference fit | `{parameters: [name]}` ⊂ forced list ∪ Morris kept, 2 to 4 of them | the reference fit's subset |
| `ident.state_test` | Whether the early/late difference warrants the state test | `{run_state_test: bool, channels: [sensor]}` | P0's R5 thresholds |

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
4. **The inhibited-steady-state check** when TAN and VFA are both high against the band:
   both channels' after-fit `mean_z` are above the band maximum.
5. **The `simulate(biomass_scale)` pair** whenever `ident.state_test` is true.
6. `bayes_mcmc` by procedure on the approved subset. `posterior_intervals` is abstained
   only after a failed call (Level-8 discipline).
7. **A bound hit is never a kinetic update.** It is a finding of type `bound_hit`, which
   the verifier reads under S6.

**Decision points.**

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `cal.accept` | Accept or reject a fit | `{accept: bool, code: enum{converged, not_converged, worse_than_reference, bound_hit}}` | accept iff χ² ≤ the reference χ² |
| `cal.bound` | How to read a bound hit | `{code: enum{identifiability_limit, data_limit, structure_hint}}`; the enum has no kinetic-update value | `identifiability_limit` |
| `cal.split` | How to read the split window | `{common_step_day: number or null, channels: [sensor]}` | P0's R4 arithmetic |

**Tools:** `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc`, `simulate`, `residual_diag`,
`declared_background`.

### 2.6 Experimental design

**Steps.**
1. `voi_assay` when a role requests an assay and the plan allows the cost.
2. The registry enforces the assay budget. The role cannot exceed it, and asks before
   every request.

**Decision points.**

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `design.assay` | Which assay, on which day, against which prediction | `{assay: enum(price list), day, prediction: enum(channel)}` | P0 §3.6 |

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
   goes into the state.
2. **Admission.** Each proposed label must rest on a null component that failed (§4.3).
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

| id | Decision | Output schema | Fallback |
|---|---|---|---|
| `verify.differential` | The mechanistic differential among the admitted labels | `{label: enum(admitted ∪ {none}), rejected: [{label, code: enum{null_not_failed, signature_absent, coupled_disagree, holdout_passed, superseded}}]}` | the first admitted label in P0's order (sensor, influent, state, parameter, structural); `none` if no label is admitted |

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
- `mean_z` and `rms_z` are computed with P0's declared-noise weights over the calibration
  window. This is the driver's arithmetic (`scripts/declared_background.py::_Series`),
  which a test already pins to P1's `sim_summary`. P2 imports the same function into the
  workflow side, with a test that the two agree.

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
clean runs of its plant and tier. That is how a new clean run meets the published band.

- **Each single statistic** falls outside on 15 % of clean runs. Exchangeability
  predicts 2/N for a leave-one-out envelope of N − 1 others, and 2/(N + 1) against the
  published envelope of N.
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
  than declared is the ladder's Level 1, whose truth is `none`. This principle comes from
  the scenario ladder's definition, not from any cell's placement.
- **NB, the balance's null case.** It fails when either of these holds:
  - the mean COD closure and the worst window are both outside, on the same side;
  - the inadmissible-window count is **above** the band maximum.

  Fewer inadmissible windows than any clean run is not a fault.
- **NM, the multi-channel case.** It fails when two or more channels' null cases fail.
- **NS, the single-channel case.** It fails when exactly one channel's null case fails
  and every other calibrated channel's after-fit mean is inside the band.

**The null is rejected when NB, NM or NS fails.** Leave-one-out false-alarm rates on the
committed clean record, as rejections out of clean runs:

| Component | All | A/A | A/B | A/C | B/A | B/B | B/C | C/A | C/B | C/C |
|---|---|---|---|---|---|---|---|---|---|---|
| NB | 8/120 (0.07) | 0/20 | 2/20 | 1/20 | 0/10 | 2/10 | 2/10 | 0/10 | 1/10 | 0/10 |
| NM | 10/120 (0.08) | 0/20 | 2/20 | 2/20 | 0/10 | 1/10 | 1/10 | 0/10 | 2/10 | 2/10 |
| NS | 5/120 (0.04) | 1/20 | 1/20 | 1/20 | 1/10 | 0/10 | 0/10 | 1/10 | 0/10 | 0/10 |
| **Null rejected** | **19/120 (0.16)** | 1/20 | 4/20 | 4/20 | 1/10 | 2/10 | 2/10 | 1/10 | 2/10 | 2/10 |

So on a clean run the rule is expected to leave `none` standing about 84 % of the time.
The leave-one-out figure is conservative, because the published envelope is over N runs,
not N − 1. The brief's success criterion is `none` on at least two of the four clean
development cells.

**How the rule was chosen, so that it is not fitted to the answer.**
- The components were chosen only on these clean-record rates.
- The target, declared before any development cell is judged by it, is an overall
  leave-one-out false-alarm rate below 0.20.
- No development cell's placement was used to choose or tune the rule.
- The development cells' placement (`reports/background/dev_cells.json`) was published
  as a finding before this rule existed. It is not an input here.
- **A disclosure:** the author had read that finding before writing this rule. The
  components are justified by the clean-record rates above and by the ladder's
  definitions, not by the cells. Whether that separation suffices is for the
  coordinator to judge (§12, question 2).
- The rule is now fixed. If a live clean cell's `none` fails at deliverable 3, that is
  reported as the go/no-go finding, not corrected.

### 4.3 Admission: which label rests on which null case

A label is admitted by the verifier only over an explicit null case that failed, **and**
with the signature its role found. A signature without a failed null case is rejected,
with code `null_not_failed`. That is the rule that would have stopped both P1 arms.

| Label | Null case that must fail | Signature that must also hold (role) |
|---|---|---|
| `sensor` | NS on that channel | the S1 table: the coupled channels inside, `dq.coupled` = `coupled_agree` or `assay_implicates` (data quality); a QC flag alone never qualifies |
| `influent` | NB | an onset or feed-covariate pattern (influent); charge alone never qualifies |
| `state` | NS or NM | an early-window bias with the late window inside, and the `biomass_scale` pair improving the early window (identifiability, calibration) |
| `parameter` | NM, with NB not failed | a common change point on two or more channels within 30 days, and no feed covariate (calibration) |
| `structural` | NM | P0's R3 criterion and a failed hold-out (verifier, S6) |
| `none` | none failed, **or** a failure that no label's signature explains | — |

When the null is rejected but no signature explains it, the label is `none`, with:
- confidence `attribution.confidence.none`, lowered to `multiple`;
- the reason code `null_failed_unexplained` in the state.

It is not an abstention. The brief scores abstention on a representable cell as a miss.

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
| REFERENCE | identifiability, then calibration | the reference fit of §3 |
| SCREEN | identifiability | steps 1–4, then `ident.subset` |
| FIT | calibration | steps 2–6, each skipped when its trigger does not fire or P0's ladder says the plan cannot afford it |
| PROFILE | data quality | the S1 table |
| PROPOSE | coordination | the findings assembled by §4.3 |

**Assays.** A role's request is routed to the design role at two points: after REFERENCE
(data quality's `dq.assay`) and after FIT (calibration). The design role decides, and
the registry charges.

**Budget guard.** Before each expensive state the coordinator reads `tools.remaining()`.
It applies P0's deterministic plan at `plan.eval_seconds_assumed` = 12 s, with P0's
ladder. When the wall clock left falls below the reserve (P1's 6 minutes), it goes
straight to PROPOSE and VERIFY with what exists.

**REVISE.** This is one round, taken only on `fail`. The failing reason codes go back to
the roles that produced the rejected findings. Those roles re-run their decision points
with the codes as input; codes, never text. No new reference fit is made.

**CONCLUDE.**
- After `pass`, the state is written and the run validated once (§7).
- After `fail` with no round left, the label is `none` with `null_failed_unexplained`
  when the null was rejected, and plain `none` otherwise.
- After `abstain`, the abstentions the verifier named are written, with the label it
  gave.

## 6. Tool allow-lists and messages

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
`workflows/p2/messages.jsonl` and never edited.

| Message | Fields |
|---|---|
| `Task` | `seq`, `from_role` = coordination, `to_role`, `state`, `inputs`: references to prior messages and call indices |
| `Finding` | `role`, `label` (Label), `null_case` (enum NB / NM / NS / none), `rests_on` (ruled statistic keys), `signature` (enum code), `calls` (call indices), `values` (published evidence keys only, as P1's produced-value check) |
| `Table` | `role`, `kind` (enum `s1`, `null`, `balance`, `early_late`, `split`), `rows` (numbers and enums only) |
| `DecisionRecord` | `role`, `point` (id from §2), `schema_sha256`, `inputs_digest`, `output` (validated against the schema), `attempts`, `fallback_used`, `llm_call_ids` |
| `Proposal` | `labels` (ranked), `findings` (refs), `prediction` (call index of the `simulate` or ensemble), `estimates`, `abstentions` |
| `Verdict` | `verdict` (enum pass / fail / abstain), `null_table` (ref), `admitted` (labels), `rejected` (label, code), `holdout_failed` (bool), `abstentions` |

**No message field carries free text.**
- The only free text in a run is the `annotations` of the task state and the report's
  prose. Both are written by the coordinator at CONCLUDE from the enums, and are never
  read by a role.
- A model's output is accepted only through its decision point's schema, whose strings
  are all enums.

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
| `roles.influent` | No balance step. NB is still placed by the verifier, but no `influent` finding is possible. |
| `roles.identifiability` | The fitted subset is the reference subset. There is no S4 step and no forced list. |
| `roles.calibration` | Only the reference fit. No split window, no MCMC (`posterior_intervals` abstained), no biomass pair. |
| `roles.design` | No assays. |
| `persistent_state` | Each decision point sees only its own step's tables, never the accumulated state or the earlier decisions. |
| `self_correction` | No REVISE. A `fail` concludes at once (§5). |

Deliverable 5 runs them **verifier off first**, as the brief says.

## 9. Budget accounting and the record

**One run, one budget**, summed over roles:
- simulator evaluations, wall clock and assay units, enforced by the registry exactly as
  for P0 and P1;
- model tokens and requests, through P1's `ModelGateway` with the same per-run caps
  (6 M tokens; turns counted as decision-point requests, 60).

Every registry call carries its role in the action's `step` (`<role>.<state>`). Every
gateway attempt carries `role` and `point`. The runner's `summary.json` gains:
- `by_role.{evaluations, wall_clock_s, assay_units, tokens, requests}`;
- the same totals as P0 and P1, so the comparison reads one row per run.

**The record**, `runs/<id>/workflows/p2/`:

| File | Writer | Content |
|---|---|---|
| `state.json` | the workflow | `TaskState` with `workflow` = `p2`. `classification.rule` names the null component and the signature code, for example `NS+s1`. `plan` carries the routing trace and the ablation switches. |
| `report.json` | the workflow | the conclusions and the tables, for a human |
| `messages.jsonl` | the workflow | every typed message, in order |
| `decisions.jsonl` | the workflow | every `DecisionRecord` |
| `llm_calls.jsonl` | the gateway (privileged) | every model attempt, verbatim, with role and point; reserved name, as P1's |
| `summary.json` | the runner (privileged) | totals and `by_role` |

The evaluator reads `state.json` and the logs, as for P1. No evaluator change is
proposed, because `eval/` is frozen. The evaluator scores P2's label, evidence and
abstentions through the shared schema.

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
   - a signature without a failed null case is rejected with `null_not_failed`.
6. **Every decision point's schema:** a valid output is accepted. An invalid one is
   retried once, then the declared fallback is used and recorded.
7. **Every ablation switch:** a run with the switch off records it, omits its element,
   and still writes a valid state.
8. **Like-for-like:** the reference fit's statistics computed in the workflow equal the
   driver's `_Series` arithmetic on the same record, and the reference fit's settings are
   the served `procedure` block.
9. **Rule 1:** nothing under `workflows/p2_multi_agent/` reads the truth store. This is
   the existing checker plus a test of the new package.

## 11. Development plan and go/no-go

**Deliverable 2.** The three-role minimum offline (data quality, calibration and
verification, with coordination as code), with the tests of §10. It also measures the
reference fit's wall clock alone on the machine on one generated cell.

**Deliverable 3.** The three-role minimum live, on three development cells with two
seeds each:

| Cell | Truth | Why |
|---|---|---|
| S0-01 B/B | `none` | the go/no-go cell |
| S2-01 B/B | `sensor` (pH drift) | data quality's S1 path |
| S8-01 B/B | `sensor` (gas scale) with an injected sampler failure | calibration's Level-8 path |

All three labels are in the three roles' reach. `influent`, `state`, `parameter` and
`structural` need the other roles.

**Go/no-go.** If the null rule does not leave `none` on S0-01 B/B, stop and report. That
is a finding about the band and the rule, not a P2 task.

**Model.** The proposal is the frozen P1's model and settings: `gpt-5.6-luna`, reasoning
`high`, no temperature. Then a P2-versus-P1 difference is the procedure's and not the
model's (§12, question 1). Each decision point is one request with one forced tool whose
input schema is the decision's schema.

**Cost.** About 15–25 decision requests per run, against P1's up to 60 turns. The cost
per run is expected below P1's USD 0.04, and deliverable 2 will measure it. The
runner-hours are dominated by the reference fit (§3).

## 12. Questions for the coordinator

1. **The model.** Is it the frozen P1's `gpt-5.6-luna` (proposed), or another?
2. **The null rule (§4).** Three components, a leave-one-out false-alarm rate of 0.16 on
   the clean record, and the target of < 0.20 declared before any development cell is
   judged by it. Accept, or name another target?
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
