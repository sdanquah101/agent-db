# P2 agents: a redesign note (for the lead's ruling)

Status: **PROPOSAL for the coordinator's review and the lead's ruling. No code, no config and
no test changes until it is ruled on.** This is a proposal in the way `docs/p2_agents_design.md`
was.

Written by the P2 component session on 2026-11-22 after the lead's ruling "Redesign note",
relayed by the coordinator (session_01Cu6G2kQjP2QSzvtkyP8cPr). That ruling followed the lead's
question after the smoke run: can the agent arm's architecture reach the right result at all?
The coordinator reviewed `main` at `4033a2d` and found it cannot.

**The remaining seven live runs are stopped.** No live call was made for this note, and the
store `/home/user/p2_agents_pilot2_store` and the stores in `/home/user/p2_agents_pilot_void/`
are untouched. Nothing here reads `truth_store/`. Truth labels come from `scenarios/*.yaml`
only.

Sources:
- The code on `main` at `4033a2d`: `workflows/p2_multi_agent/{agents,evidence,workflow,messages}.py`.
- Three live runs:
  - the smoke run S7-01 B/A r0, `run_45be0bcd18b9` (18 Nov), in `/home/user/p2_agents_pilot2_store`;
  - S7-01 B/A r0 `run_6481d0e4803c` and r1 `run_47eac085da8e` (13 Nov), set aside in
    `/home/user/p2_agents_pilot_void/2026-11-13T0248Z_pilot1_noverdict`.

  These are machine-local stores, not committed. Lines quoted from them are marked "(record)".
- Three committed reports:
  - `reports/p2_power/h4_cells.json` (the H4 cells offline, 16 rows: 8 per arm);
  - `reports/p2_power/cells.json` (eight development cells, procedural offline);
  - `reports/background/dev_cells.json` (the four clean development cells against the band).

---

## 0. The answer in one paragraph

**As built, the agent arm cannot conclude a correct fault label on any H4 run or any faulted
development cell.**
- On the 8 H4 runs, the only labels it can reach are `none` (all 8 runs) and `parameter` (2
  runs). Both are wrong for those runs. The six faulted development cells are no better, and only
  the four clean cells can end right (`none`).
- The cause is that admission reads the base procedural workflow's signatures, never the agents'
  evidence (A1). That base runs at its offline fallbacks, so the signatures are fixed before any
  agent acts.
- On top of that, the null-case rule assumes one fault, so two simultaneous faults are not
  admissible together on any input (A5).

The agents' own problems (B7–B13) matter, but fixing them alone changes no outcome.

**The question for the lead (§3)** is how much authority an agent's cited, code-checked test
gets over admission. **I recommend option (c):**
- each label is admitted by its own code test on cited calls;
- thresholds are calibrated on clean runs to a fixed false-positive rate;
- the null table reports and routes, but does not veto a label.

The comparison stays honest because every arm that uses P2's admission is re-scored under the
same rule. P0 and P1 are untouched.

---

## 1. The coordinator's findings, checked

Each finding is checked against the code and the records. **Agree** means the code and
records show it as stated. Where I add evidence or refine the claim, it says so.

### A. The label can never be right

**A1. Admission ignores the agents. Agree.**
- `AgentRun.__init__` builds `self.base = procedural.Workflow(cfg, procedural.offline_responder)`
  (`agents.py:2488`).
- `code_steps` runs only the procedural steps on that base (`agents.py:2519-2538`).
- `admitted_claims` calls `evidence.admit_agent(self.lab, b.table, b.signatures)` with
  `b = self.base` (`agents.py:2821-2824`).
- `agents.py` reads `signatures` and never writes one. The only references are reads, at
  `agents.py:2059`, `2587`, `2822-2824` and `3151`.
- A claim counts only if its label is already in that admitted list (`agents.py:2831`).

This is the flaw §1 of `docs/p2_agents_design.md` set out to remove. It says a decision point
was "offered labels code already admitted. It can only agree with code". The agent arm rebuilt
that one level up: the agents can now choose their tests, but nothing their tests show reaches
admission.

**Added evidence:** the verifier's alternative is judged on the same base signatures
(`agents.py:2058-2060`, `evidence.py:565-578`).

**A2. `sensor` is never admissible. Agree, and it corrects my smoke-run comment on #53.**
- `step_profile` takes the `dq.coupled` reading from the base's decider, with the fallback
  `{"code": "insufficient"}` (`workflow.py:1701-1702`).
- `s1_holds` needs `coupled_inside` and a reading in `("coupled_inside", "assay_implicates")`
  (`workflow.py:1703-1705`).
- In the agent arm that decider is always `offline_responder`, so `s1_holds` is always false.
  The smoke run's record says so: `"point": "dq.coupled", "role": "data_quality", "status":
  "fallback", "output": {"code": "insufficient", "sensor": "ph"}` (record).

Rerun offline here, `admit_agent` with NS failed on `ph` and the coupled channels inside:
- with the reading `insufficient`, it returns
  `{'admitted': [], 'rejected': [{'label': 'sensor', 'code': 'signature_absent'}]}`;
- with the reading `coupled_inside`, it returns `{'admitted': ['sensor'], 'rejected': []}`.

**At tier A `coupled_inside` is vacuously true.** `s1_table` computes
`all(... for c in present)` over an empty `present` (`evidence.py:404-409`). The smoke run's
record reads `"coupled_present": [], "coupled_inside": true` (record).

**My comment on #53 put the smoke run's refusal down to the tier; that was wrong.** The tier
did not cause it. The offline fallback did, and would have at any tier.

**Added finding (D1).** The same vacuous truth means the *procedural* arm with a live decider
admits `sensor` at tier A with no corroborating channel. The design note recorded this:
attempt 3's `dq.coupled` readings each "restated `"coupled_inside": true`". This note does not propose changing the
procedural arm (§9), but any new rule should treat "no coupled channel observed" as unknown,
not as inside.

**A3. `structural` is never admissible. Agree.**
- `signatures["holdout_failed"]` is written only by the procedural `step_verify`
  (`workflow.py:1979`), which the agent arm never calls (`agents.py:2519-2532`).
- The agent arm's `t_validate` records `holdout_failed` to the workspace recorder only:
  `self.rec.produce(index, "holdout_failed", ...)` (`agents.py:1876`).
- `structural_case` returns `(False, "holdout_unavailable")` whenever `holdout_failed` is
  `None`, on both branches (`evidence.py:513-517`). Rerun offline with `r3` and
  `structural_proposed` both true:
  - `NM=True` gives `(False, 'holdout_unavailable')`;
  - `NM=False` gives `(False, 'holdout_unavailable')`.

**Added evidence:** `structural` is also a round-2-only claim (`messages.py:45`, `362-365`). Round 2
starts only on a `fail` whose alternative is admitted (`agents.py:2058-2064`, `2684`). So
`structural` is blocked twice.

On 13 Nov (r0) the verifier's one `validate` call was refused as well: `"refused: no objective
sensor has a hold-out sample"` (record). That is a consequence of B9.

**A4. `influent` needs NB failed. Agree.**
- `admit` judges `influent` on `bool(t.get("NB"))` (`evidence.py:454`).
- In `h4_cells.json` NB is `false` in 8 of 8 runs; both arms share one null table per run.
- `NULL_CASE_ROUTES` (`agents.py:137-140`) with `specialists_for` (`agents.py:2429-2440`) routes
  the influent role only when NB failed or the null stands. In the 3 runs where NS or NM failed,
  `routing` lacks `influent`, for example `"routing": ["data_quality", "identifiability",
  "calibration", "verification"]` for S7-01 B/A r0.

**Added evidence:** the influent role's own onset proposal never reaches admission.
- The base's `influent.onset` point gets the fallback `onset_day: None`
  (`workflow.py:1720-1727`).
- `onset_test` returns `no_onset` for `None` (`evidence.py:231-233`).
- So the `influent` signature can come only from the code's feed covariate
  (`workflow.py:1739`).
- At B/A even the onset test was unavailable: the smoke record reads `"onset": {"passes":
  false, "code": "influent_off"}` (record).

**A5. The null cases assume one fault. Agree.**
- NS is "exactly one channel failed, every other channel's after-fit mean inside"
  (`evidence.py:152-157`). NM is "two or more" (`evidence.py:147-149`).
- `sensor` needs NS on its channel (`evidence.py:446`). `parameter` needs NM and not NB
  (`evidence.py:462`).
- A second fault that shows on a second channel turns NS into NM, which makes `sensor`
  inadmissible and `parameter` admissible. S7-01 B/B r0 and B/C r0 have `"NM": true`,
  failed channels `["ch4_fraction", "ph"]` and `["ch4_fraction", "ph", "vfa_total"]`, and
  `"admitted": ["parameter"]`. Their truth is `[sensor, influent]` (`scenarios/S7-01.yaml`), so
  that label is wrong.
- Naming `sensor` and `influent` together needs NS and NB together. A mislabelled feed would
  have to fail the balance while every channel but one stays inside. In S7-01 it shows on
  channels instead (NB false in 8 of 8).

**A6. The null stands in 5 of 8 H4 runs despite two faults. Agree.**
- It stands in every r1 of S7-01 (B/A, B/B, B/C) and in both S7-02 runs: `"null_rejected":
  false`, `"failed": []`.
- Then `none` (wrong) and abstain are the only reachable outcomes (§2).
- `truth_admitted` is `[]` in all 16 rows of `h4_cells.json`.

### B. The agents are hampered even where a label is admissible

**B7. Citation keys. Agree.**
- `check_finding` looks a cited value up in `ws.rec.produced`, under the exact key
  (`agents.py:1988-1993`).
- The refusal names the missing key and no valid one: "no cited call produced `{key}`; cite the
  call it rests on".
- The names can differ from the payload:
  - `t_qc` returns the dumped tool output, whose field is `drift_signal_to_noise`, but makes it
    citable as `signal_to_noise` (`agents.py:1234`);
  - `t_residual` makes six statistics citable (`agents.py:1693-1695`), while `residual_diag`'s
    output also carries `trend_p_value` (`tools/impl/residual_diag.py:146`), `time_eta_squared`
    and more, none of them citable.

In the smoke run, 12 of the 14 `emit_finding` refusals are of this kind (record), for example:
- data_quality: `drift_flag`, `n`, `trend_slope_per_d`, `gas_background_rms_z_max`;
- identifiability: `sobol_ST_k_m_ac_pH`, `K_I_nh3`;
- calibration: `pH_after_fit_mean_z_mean`, `ph_after_fit_mean_z_mean`, and a call index (27)
  that never returned;
- verification: `time_eta_squared`, `trend_p_value`.

The other two are a missing unit and the verifier naming an alternative on a pass.

**B8. Code-step outputs are neither fetchable nor citable. Agree.**
- `code_steps` copies the procedural recorder's `actions` and `failures` only, not its
  `outputs` or `produced` (`agents.py:2534-2535`).
- `stored` answers from `self.rec.outputs` (`agents.py:1901-1903`). At data_quality's first turn
  that is empty. The smoke record shows five refusals, "no stored output with call_index N; have
  []", for N = 3, 4, 9, 12 and 13 (record).
- Every role is shown the code steps' results through `brief()` (`agents.py:2585-2587`).

**Added finding (D2).** Because the actions are copied, a code-step index passes the
"call returned" check (`agents.py:1968`). The refusal then says "no cited call produced `x`",
which misleads the model about why.

**B9. Quarantine mutates the shared series, with no floor and no undo. Agree.**
- `t_status` runs `s.value = np.where(inside, np.nan, s.value)` on the workspace's own series
  (`agents.py:1761-1807`, the loop under `for start, end in windows`).
- It checks only that a window does not run backwards and does not reach into the hold-out.
- In the smoke run, data_quality quarantined `ph` over `[0.0, 150.0]` and `temperature` over
  `[0.0, 150.0]`, the whole calibration window (record). Later calls were then refused:
  - calibration and verification `residual_diag`: "ph has fewer than 4 samples in the
    calibration window";
  - identifiability `fisher_info`: "no sensor with observed samples in the calibration window"
    (record).
- **Added evidence (13 Nov, r0):** all sensors set out of the objective, then `validate` was
  refused: "no objective sensor has a hold-out sample" (record).

**B10. An inadmissible claim is accepted and then judged. Agree.**
- `check_finding` never consults admission (`agents.py:1945-2084`).
- `conclude()` turns a `pass` with no admitted claim into `abstain:no_proposal` over a failed
  null (`agents.py:2914-2919`). This is the smoke run's exact outcome:
  `"verdict": {"verdict": "abstain", "reason": "no_proposal", "admitted": [], "rounds": 1}`
  after the verifier's `"verdict": "pass"` on data_quality's `sensor` claim (record).
- Over a standing null the same pass becomes `none` (`agents.py:2911-2913`): a passed fault
  claim is written as "no fault".

**B11. The turn and time budgets were never tried live. Agree, with one refinement:** the drop
is recorded but not acted on.

identifiability used 8 of 8 turns and gave no finding in all three live runs. Its tool time was
4,173 s (smoke run) and 1,716 s and 2,269 s (13 Nov).

The record says so: `"identifiability (round 1): no finding: 8 turns used without a finding"`
(`agents.py:2657`, record). But the brief of the next role lists only the findings that exist
(`agents.py:2545`). The coordinator and the verifier are not told that a routed role came back
empty. Turns are set per role at 12/12/8/14/6/14 (`configs/workflows/p2_agents.yaml:16-33`).
§6 has the measured use.

**B12. Round 2 needs a `fail` whose alternative is admitted. Agree.**
- `second_round` runs only on `verdict == "fail"` with `rounds >= 2` (`agents.py:2684`).
- A `fail` is refused unless `admissible_alternative` admits it (`agents.py:2058-2064`).
- The smoke verifier's third refusal: "verdict: the alternative 'structural' is not admitted by
  the evidence" (record).

**B13. There is no readable reasoning. Agree.**
- The smoke run's 33 responses hold 52 `thinking` blocks and 47 `tool_use` blocks.
- Every `thinking` block has empty text and only an opaque `signature` of 2,519 to 8,791
  characters, and there are 0 `text` blocks (record).
- `assessment` is filled only from `text` blocks (`agents.py:2284-2286`), so `report.json`
  has no assessments.

### C. Why it was not caught

**C14. No test concludes a label end to end. Agree in substance.** Two tests do conclude `sensor`
(`tests/test_p2_agents_harness.py:751` and `:1000`). Both first call `_admit_everything`. It
replaces `admit_agent` with a function that admits all five labels
(`tests/test_p2_agents_harness.py:679-686`), and it is used 8 times in that file.

The test at line 739 says so itself: "with the real admission (no S1 signature on this fake
cell) the sensor claim is not admitted". Through the real admission, the tests reach only
`none` and abstentions.

**C15. The arm was frozen before any live call. Agree.**
- The agent arm's frozen record dates from 2026-10-30 (`docs/decisions.md`, "The agent arm's own
  frozen record").
- The first live call was on 2026-11-11, and the first finished live runs were on 2026-11-13.

**Added (C16).** The offline model `OfflineModel` builds correct findings from code, not from
the schema it is sent. So the dry run could not show the schema bug of 17 Nov, nor any of A1–A6:
an offline run abstains by construction (`abstain:verifier_abstain` in all 8 agent rows of
`h4_cells.json`).

---

## 2. Reachability as things stand

"**Yes**" means the agent arm can conclude the label on that run for some sequence of model
actions; "no" names the condition that blocks it. Outcomes are computed from the committed null
tables, the committed `admitted` lists and the code above. Correct labels (from the scenario
files) are in **bold**.

Blocking conditions:
- **S-sig:** `s1_holds` is false, because the base's `dq.coupled` is the offline fallback
  `insufficient` (`workflow.py:1701-1705`).
- **S-null:** NS did not fail (`evidence.py:446`).
- **I-null:** NB did not fail (`evidence.py:454`).
- **I-route:** the influent role was not routed (`agents.py:137-140`).
- **T-null:** neither NS nor NM failed (`evidence.py:457`).
- **T-sig:** no early/late firing on a failed channel with the biomass pair improving (not in the
  committed `admitted` list).
- **P-null:** NM did not fail, or NB did (`evidence.py:462`).
- **X:** `holdout_failed` is never written (`agents.py:1876`), so the case returns
  `holdout_unavailable` (`evidence.py:516-517`). The claim is also round-2 only, and round 2
  needs an admitted alternative (`messages.py:362-365`, `agents.py:2058-2064`).

### The 8 H4 runs (truth S7-01 = `sensor`+`influent`; S7-02 = `structural`+`parameter`)

| run | null | sensor | influent | state | parameter | structural | none |
|---|---|---|---|---|---|---|---|
| S7-01 B/A r0 | NS (`ph`) | **no: S-sig** | **no: I-null, I-route** | no: T-sig | no: P-null | no: X | yes (wrong) |
| S7-01 B/A r1 | stands | **no: S-null** | **no: I-null** | no: T-null | no: P-null | no: X | yes (wrong) |
| S7-01 B/B r0 | NM | **no: S-null, S-sig** | **no: I-null, I-route** | no: T-sig | yes (wrong) | no: X | yes (wrong) |
| S7-01 B/B r1 | stands | **no: S-null** | **no: I-null** | no: T-null | no: P-null | no: X | yes (wrong) |
| S7-01 B/C r0 | NM | **no: S-null, S-sig** | **no: I-null, I-route** | no: T-sig | yes (wrong) | no: X | yes (wrong) |
| S7-01 B/C r1 | stands | **no: S-null** | **no: I-null** | no: T-null | no: P-null | no: X | yes (wrong) |
| S7-02 A/C r0 | stands | no: S-null | no: I-null | no: T-null | **no: P-null** | **no: X** | yes (wrong) |
| S7-02 A/C r1 | stands | no: S-null | no: I-null | no: T-null | **no: P-null** | **no: X** | yes (wrong) |

**Correct primary label reachable: 0 of 8. Both faults: 0 of 8.**

How each `none` is reached:
- over a standing null, by a pass with no claim (`agents.py:2911-2913`);
- over a failed one, by a `fail` with the alternative `none` (`agents.py:2921-2923`), or by a
  passed, cited `none` finding.

### The ten development cells (agent arm)

The nulls come from `reports/p2_power/cells.json`: the same code steps the agent arm's base runs,
at their fallbacks. For S0-01 B/A and B/B they are derived from `reports/background/dev_cells.json`:
- B/A has 0 of 12 statistics outside;
- B/B has 3 outside, but no channel meets `channel_fails` and the COD closure is inside, so NS,
  NM and NB are all false.

| cell | truth | null | correct label reachable? |
|---|---|---|---|
| S0-01 B/A | none | stands | **yes** |
| S0-01 B/B | none | stands | **yes** |
| S0-01 B/C | none | NM | **yes**, through a `fail` with the alternative `none` or a passed, cited `none` finding |
| S1-01 B/B | none | NB | **yes**, as for B/C |
| S2-01 B/B | sensor | NM | no: S-null, S-sig |
| S3-01 C/B | influent | NM | no: I-null, I-route (`parameter` reachable, wrong) |
| S4-01 B/B | state | stands (`null_partial`) | no: T-null |
| S5-01 A/A | parameter | stands | no: P-null |
| S6-02 B/B | structural | stands | no: X (the procedural record's hold-out also **passed**) |
| S8-01 B/B | sensor | NS + NB | no: S-sig |

**4 of 10, all four clean cells. 0 of 6 faulted.**

---

## 3. The central question: how much authority do the agents' cited tests get?

The lead's question is whether this architecture can reach the right result at all. That turns
on one choice: what may admit a label.

In every option:
- **code** computes the test, from calls that returned;
- the model chooses the calls and makes the claim;
- **code** writes the label.

The options differ in which calls count, and whether the null table can veto.

### (a) Minimal: the agents' checked results feed the existing signatures; the null rule is unchanged

The agents' outputs replace three base fallbacks:
1. **data_quality's S1 reading.** A typed `s1_reading` in its finding, checked against the S1
   table code computed, replaces `dq.coupled`.
2. **The verifier's `validate` result** becomes `signatures["holdout_failed"]`, and `structural`
   is recomputed.
3. **The influent role's cited `onset_day`** is passed to `onset_test`.

Admission (`admit_agent`) and the null cases stay as frozen.

- **Fixes:** A1 for three signatures, A2 and A3. It also makes the comparison with the
  procedural arm exact: same admission, and only who supplies three readings differs.
- **Leaves broken:**
  - A4: NB is still needed for `influent` (false in 8 of 8);
  - A5: one fault per null case;
  - A6: a standing null still allows only `none`;
  - the vacuous tier-A reading (D1).
- **Comparison:** P0 and P1 are untouched. The procedural P2 is the exact control.

| H4 run | sensor | influent | state | parameter | structural | none |
|---|---|---|---|---|---|---|
| S7-01 B/A r0 | **if** DQ reads `coupled_inside` (vacuous at tier A, D1) | **no: I-null** | no: T-sig | no: P-null | if the hold-out fails and R3 holds over all channels | yes |
| S7-01 r1 (all three tiers) | **no: S-null** | **no: I-null** | no: T-null | no: P-null | if the hold-out fails and R3 holds over all channels | yes |
| S7-01 B/B r0, B/C r0 | **no: S-null** | **no: I-null** | no: T-sig | yes (wrong) | if the hold-out fails and R3 holds on ≥2 failed channels | yes |
| S7-02 A/C r0, r1 | no | no | no | **no: P-null** | **if** the hold-out fails and R3 holds over all channels | yes |

At most **3 of 8** reach a correct primary label, each conditional. **Both faults: 0 of 8**, so H4
cannot be tested.

Development cells: S8-01 `sensor` "if" (it has NS). S6-02 stays "no", because its hold-out passed
in the procedural record. At most **1 of 6** faulted, and 4 of 4 clean.

### (b) Agent-run evidence can admit a label; the null rule is amended

For each label, a **signature computed by code from the agent's own cited calls**:
- `sensor`: a cited `residual_diag` on the channel past a step or bias threshold, with the
  coupled channels inside *where observed*;
- `influent`: a cited onset test on the role's proposed day, or a cited `mass_balance` outside
  the band;
- `state`: early/late bias on the agent's residuals with the biomass pair improving;
- `parameter`: a common change point on failed channels;
- `structural`: a failed `validate` and R3.

The null rule is amended: **any** failed null case admits any label whose agent signature holds.
The case-matching of `admit` (NS for `sensor`, NB for `influent`, and so on) is dropped.

- **Fixes:** A1 to A5 when the null is rejected. Two labels can be admitted together.
- **Leaves broken:** A6. A standing null still allows only `none`, which is 5 of 8 H4 runs and 3
  of 6 faulted cells. On clean cells whose null fails (S0-01 B/C, S1-01 B/B), a false label
  becomes reachable, at an uncontrolled rate.
- **Comparison:** the agent arm now has a different admission from the procedural arm. A gain
  could be the rule's, not the agents'. Remedy: re-score the procedural floor under (b), with its
  code-step calls as its "citations". P0 and P1 are untouched; that their rules differ is stated
  beside every comparison.

| H4 run | sensor | influent | state | parameter | structural | none |
|---|---|---|---|---|---|---|
| S7-01 B/A r0 | **if** cited test | **if** cited test (no COD-window onset at B/A: only the balance or feed) | if | if | if | yes |
| S7-01 B/B r0, B/C r0 | **if** | **if** | if | if | if | yes |
| S7-01 r1 ×3, S7-02 ×2 | **no: null stands** | **no** | no | **no** | **no** | yes |

At most **3 of 8** reach the primary label, and both faults at most 3 of 8, each conditional.
**S7-02: 0 of 2.** Development cells: S2-01, S3-01 and S8-01 become "if", so at most 3 of 6
faulted. Clean cells stay reachable, with a new false-positive route.

### (c) Recommended: per-label tests at a calibrated false-positive rate; the null reports and routes but does not veto

1. **Per-label admission, as in (b).** A label is admitted by its own code test on **cited**
   calls, the agent's or a code step's (B8 makes both citable), each marked with its origin.
2. **The null table no longer vetoes or gates a label.** It is computed and reported as frozen,
   it routes (§5), and it stays the procedural arm's rule.
3. **Every label test has a threshold calibrated on clean runs** to a fixed false-positive rate,
   chosen by the lead (say 5% per label). Calibration uses the band's ten clean seeds
   (900001–900010) and new clean seeds; simulation costs evaluations only. Ten seeds resolve a
   rate to only 10%, so I propose 40 or more per tier.
4. **Compound faults are admitted together** by the explain-away step of §4.
5. **The run is scored twice:** under the frozen admission (comparable with every earlier
   number) and under (c). The procedural arm is re-scored under (c) as its code-only floor.

- **Fixes:** A1 to A6, D1 (an unobserved coupled channel is "unknown", never "inside") and
  B10's "passed fault claim written as no fault".
- **Leaves open:** the power of each test is what it is; a fault inside the clean band's
  variation is missed, and that miss is measured, not hidden. Calibration needs new clean runs.
- **Comparison:** the same as (b), with the false-positive rate made explicit and equal for every
  arm scored under the P2 admission. P0 and P1 are untouched and scored as frozen.

| H4 run | sensor | influent | state | parameter | structural | none |
|---|---|---|---|---|---|---|
| S7-01 (all six) | **if** its test clears the calibrated threshold | **if** | if | if | if | yes |
| S7-02 (both) | if | if | if | **if** | **if** | yes |

Up to **8 of 8** primary labels and **8 of 8** both faults, each conditional on its test.
Development cells: up to 6 of 6 faulted. On clean cells, `none` is reachable and a false label
is limited to the calibrated rate.

**Why (c).** H4 asks whether agents gain with two simultaneous faults. Under (a) no run can name
both, so H4 is untestable. Under (b) the 5 of 8 runs where the null stands cannot be argued at
all. Only (c) lets an agent's own test decide while keeping false positives bounded and stated.

The cost is a new rule, which must be calibrated and frozen before any live call (§8). The
re-scoring keeps the agents' gain separable from the rule's.

**What I would not do: (d), accept the claim when the verifier passes.** It puts admission in
model hands, against rule 5's spirit and the design's "code writes the label". It would make the
result unauditable.

---

## 4. Compound faults

**Why the frozen cases cannot admit two at once.** Each label is tied to one null case:
- `sensor` needs NS: exactly one failed channel and every other channel inside
  (`evidence.py:152-157`, `446`);
- `influent` needs NB (`evidence.py:454`);
- `parameter` needs NM and not NB (`evidence.py:462`).

| pair | what admission needs | why it fails |
|---|---|---|
| `sensor` + `influent` | NS and NB together | the feed fault must show in the balance and on no channel. S7-01's mislabelled feed shows on channels (`ch4_fraction`, `vfa_total` at B/B and B/C r0), giving NM; NB is false in 8 of 8 |
| `sensor` + `parameter` | NS and NM at once | contradictory |
| `structural` + `parameter` (S7-02) | both through NM | needs a failed hold-out that the agent arm never records (A3). In both S7-02 runs the null stands |

**Proposed (under (c)): explain away, then re-judge.**
1. Admit every label whose own test passes on cited calls (§3 (c)).
2. **Explain-away check, in code.** Account for the admitted causes:
   - drop an admitted sensor's channel from the objective;
   - re-fit with the influent correction the influent role cited;
   - free the parameter the calibration role cited.

   Then recompute the placement against the band on the remaining channels.
3. If the remaining channels are inside, the label set is the admitted set. If not, the run
   either abstains with `unexplained_residual` or, with a second round left, routes the
   remaining failure to the specialists.
4. The label set's order follows the existing `LABEL_TIE_BREAK` and confidence rule (the lead's
   "match").

This costs one refit per admitted label, about 100 evaluations each, judged from the
calibration role's 100–108 per run in the three live runs. It fits the 750-evaluation envelope
when the routing grants are fixed (§5).

**When the null stands but faults are present** (5 of 8 H4 runs, 3 of 6 faulted development
cells):
- **frozen rule:** only `none` or abstain; a fault is missed by construction;
- **(c):** a label test may still pass at its calibrated rate. If none passes, `none` is the
  label, and the miss is scored and reported as the test's power, not hidden.

I recommend reporting the clean-cell false-positive rate with its confidence interval beside
every hit rate.

---

## 5. Routing

**Today:**
- data_quality always goes first;
- over a failed null, `NULL_CASE_ROUTES` routes NB to influent, and NM or NS to identifiability
  and calibration;
- over a standing null, all three go (`agents.py:137-140`, `2429-2440`);
- design is routed on conflict, and the verifier last.

As a result the influent role was skipped in all 3 H4 runs whose null failed. Each of those has
an influent fault in truth.

**Proposed: route every specialist in round 1**, with design still routed on conflict only.
Measured cost of a role when it is routed:

| role | requests | tokens | evaluations | tool time |
|---|---|---|---|---|
| influent (13 Nov r1, the one live routing) | 12 | 636,766 | 0 | 0.007 s |
| identifiability (3 runs) | 8 | 186–197k | 172–276 | 1,716–4,173 s |

At that run's rate (USD 0.1018 for 1.86 M tokens), the influent role cost about **USD 0.035**.

The live runs so far peaked at 57 requests, 1.86 M tokens and USD 0.122, against caps of 240
requests, 14 M tokens and USD 1.00. Routing every specialist adds at most one role, about 12
requests and 0.64 M tokens, and stays well under the caps.

**The evaluation grants must change with it.** `grants_for` splits the evaluations left equally
among the routed proposers (`agents.py:2457`). In the smoke run data_quality was granted 555, and
then identifiability and calibration 277 each (record, `route.1` decisions).

Adding influent, which used 0 evaluations, would cut each share to about 185, below
identifiability's measured 172–276. **Proposed:** each role draws from the shared envelope up to
a per-role ceiling, so evaluations one role leaves unused stay available to the others. The
registry still enforces the envelope (rule 2).

---

## 6. Fixes for B7–B13

**B7, citable keys.**
- Make the citable keys **the shown keys**. `produce()` is called with the payload's own field
  names, for example `drift_signal_to_noise`.
- Every scalar a role is shown is either citable or listed as not citable under
  `"not_citable"`.
- The refusal lists the valid keys of the cited calls, up to 20: "no cited call produced
  `drift_flag`; call 12 produced: bias_z, rmse_z, …".
- Design choice: the shown key, not a renamed one. A model cites what it reads.

**B8, code-step evidence.**
- At the end of `code_steps`, copy the base recorder's `outputs` and `produced` into the
  workspace recorder under their own call indices, each marked `origin: "code"`.
- `stored` then fetches them, and they can be cited.
- Design choice: under (c), code-origin evidence may admit a label. That keeps the agent arm at
  least as strong as the procedural floor. The report counts which admissions rested only on
  code evidence, so the agents' contribution stays visible.

**B9, quarantine floor and scope.**
- A quarantine is recorded as a **mask**, not a write to the series. `s.value` keeps the
  observed data, and the objective, `residual_diag` and `fisher_info` read through the mask.
- **Floor:** refuse a quarantine that leaves a sensor fewer than 4 samples in the calibration
  window. That is `t_residual`'s own minimum (`agents.py:1681-1682`). Excluding a whole sensor is
  done through `status: excluded`, never by quarantining the whole window.
- **Scope:** the mask applies to fits and the objective. A diagnostic call may ask for the
  unmasked series by setting `raw: true`, recorded as such.
- **Objective floor:** at least one sensor with hold-out samples stays in the objective, so
  `validate` can run (13 Nov r0).
- An undo, `set_sensor_status` with `quarantine: []` and `reset: true`, is logged as a reversal.

**B10, inadmissible claims and what a pass means.**
- At emit time, `check_finding` runs the admission test for the claimed label on the cited calls.
- If it fails, the finding is **refused** with the test's code and what would satisfy it, for
  example "sensor: no cited residual_diag on ph clears |step_z| ≥ T".
- Design choice: refuse, not flag. The role can then still run the test within its turns.
- **A pass means:** "the leading admitted claim survives the verifier's challenge". The verifier
  is routed only when an admitted claim or a cited `none` finding exists. Otherwise the run
  concludes by rule, without a verdict.
- A passed fault claim is never written as `none`. `conclude()` writes `none` only when no
  specialist made a fault claim, or when every fault claim was refuted.

**B11, turn and time budgets, and the "no finding" signal.**

Measured use in the three live runs (requests per role; the 13 Nov runs were inflated by the
schema bug):

| run | data_quality | influent | identifiability | calibration | verification | wall time |
|---|---|---|---|---|---|---|
| 13 Nov r0 (cap 12/12/8/14/14) | 12 | not routed | 8 | 14 | 15 | 3,058 s |
| 13 Nov r1 | 12 | 12 | 8 | 11 | 14 | 3,508 s |
| smoke run | 10 | not routed | 8 | 7 | 8 | 6,021 s |

Proposed:
- **identifiability's turns: 8 → 14.** It hit its cap without a finding in 3 of 3 runs.
- **The last turn must emit.** The harness tells a role "one turn left: emit now" before its last
  turn.
- **A routed role that returns nothing** is recorded as a typed `no_finding` message. The
  coordinator and the verifier see it in their brief.
- **Time:** P2 keeps its ruling of no wall-clock limit (2026-10-13). identifiability's 1,716 to
  4,173 s is Sobol and FIM work. It is bounded by an evaluation ceiling per call (the
  `gsa_sobol` sample count) and by B9's floor, which stops refused FIM retries. A clock is not
  needed.

**B12, round 2.**
- A `fail` may name any label as its alternative, provided it cites a test that bears on it.
- Round 2 asks the alternative's claimant role to run its admission test; if the test fails, the
  `fail` stands as "alternative not shown".
- A `fail` with an admitted alternative is concluded as today.

**B13, readable assessment.**
- Every `emit_finding` carries a typed `assessment`: at most 1,200 characters, each sentence
  required to name a cited call index, and checked by code to cite only calls in the finding.
- It goes to `messages.jsonl`, as role prose does now (§3.3 of the design note).
- Separately, ask the provider for reasoning summaries, if `tools/llm.py`'s client can request
  them. **This needs checking.** The current blocks are encrypted, and summaries would be logged
  only where the agreement allows.

---

## 7. The tests the rebuild must carry

All of these run offline, and none of them stubs `admit_agent`.

1. **A model double that reads only what a live model is sent.** It builds every call and
   finding from the request's messages and tool schemas alone, never from `Workspace`, `base` or
   `rec`. It is scripted per scenario: "call `residual_diag` on the failing channel, cite the
   keys shown". A guard test fails if the double imports or touches harness state.
2. **One end-to-end reachability test per label**, through the real admission:
   - `sensor`, `influent`, `state` and `parameter`, each on a single-fault development cell;
   - `structural` on S6-02 or S6-01;
   - `none` on S0-01 B/B.

   Each has its **control**: the same run with the decisive cited call removed, or its value
   inside the band, does not conclude the label.
3. **Compound:** S7-01 at B/B concludes both `sensor` and `influent` when both tests pass. Its
   control: with one test failing, only the other label is concluded.
4. **A passed fault claim is never `none`.** Control: with no fault claim, a standing null gives
   `none`.
5. **Every shown scalar is citable or listed as not citable.** Control: a renamed key is refused,
   and the refusal names the valid keys.
6. **The quarantine floor.** A whole-window quarantine is refused. Control: a 2-day window is
   accepted, and a later `residual_diag` on that sensor runs.
7. **Emit-time admission.** An inadmissible claim is refused with its code. Control: the
   admissible claim is accepted.
8. **The last-turn signal, and `no_finding` reaching the verifier's brief.** Control: a role that
   emits early sees no signal.
9. **Calibration:** on the clean calibration seeds, each label's measured false-positive rate is
   at or below the frozen rate. Control: a threshold set to 0 fails the test.
10. **The two scores:** each run is scored under the frozen admission and under the new one.
    Control: for the procedural arm on a cell where the two rules agree, the scores are equal.

---

## 8. What is frozen and must move; the cost; the order of work

**Frozen today, and what moves:**

| item | where | moves? |
|---|---|---|
| The agent arm's frozen record (`frozen_record_sha256` `d167f1e4…`, `config_digest` `efebeff5…`) | `configs/workflows/p2_agents.yaml` | yes |
| The agent code digest `agents_frozen_sha256` `06291b87…` and its six `tools_sha256` | `configs/workflows/p2_agents.yaml`, pinned in `tests/test_p2_agents_freeze.py`, `tests/test_p2_h4_cells.py` | yes |
| The rule tables `rules_sha256` `0aadaf43…` (`CLAIMS_FOR_LABEL`, `NULL_CASE_ROUTES`, `ROUND_TWO_ONLY_CLAIMS`) | `configs/workflows/p2_agents.yaml` | yes |
| `admit_agent` and `structural_case` (the agent arm's admission) | `workflows/p2_multi_agent/evidence.py` | yes, under (b) or (c): a **new** function beside them |
| The procedural `admit` and the null rule (frozen 2026-10-07) | `evidence.py:416-475` | **no** (§9) |
| The prompts | `p2_prompts/agents/*.md` | yes |
| The live approval (`approval_digest` `96db9a43…`) | `configs/workflows/p2_live_approval.yaml` | renewed once, at the end |
| The offline floor | `reports/p2_power/h4_cells.json`, `cells.json` | regenerated under both rules |

**The cost.** On this project, each freeze move has taken:
- one PR re-pinning three digests;
- the coordinator's review;
- the lead's word.

Each approval has taken:
- one PR;
- the lead's word;
- a dry run, about 2.5 h on four parts;
- a one-run smoke run, about 1.7 h and USD 0.07.

**Proposed: one ruling lifts the freeze for the rebuild.** Each PR moves its pins mechanically, as
the 17 Nov fix did. The arm is re-frozen **once**, then gets one approval, one dry run and one
smoke run. That is 1 freeze cycle and 1 approval cycle, not one of each per PR.

**Order of work: small PRs, each green, each with its tests and controls.**
1. **The model double** (§7.1), with the reachability test for `none` and its control. These pass
   today.
2. **Citations** (B7, B8): shown keys, the refusal lists keys, code-step outputs fetchable and
   citable.
3. **Quarantine as a mask, with its floor, scope and objective floor** (B9).
4. **The conclusion's meaning** (B10, B12): emit-time admission against the frozen rule, a pass
   means a survived challenge, and no fault claim becomes `none`.
5. **The lead's admission option** (a, b or c), with the per-label reachability tests, the
   compound test and their controls (§7.2–7.4). Under (c), this includes the calibration
   (§7.9) and the new clean seeds.
6. **Routing and grants** (§5), **turns and the `no_finding` signal** (B11).
7. **The readable assessment** (B13).
8. **The offline floor regenerated** under both rules, for both arms (§7.10).
9. **Re-freeze and renew the approval.** Then a dry run and a smoke run, each on the lead's word
   relayed by the coordinator.

Each PR updates `docs/decisions.md` and `docs/milestones.md`. A ruling the lead must take
before PR 5 is the false-positive rate per label and the number of clean seeds.

---

## 9. What I would not change, and why

- **P0 and P1, and their freezes.** They are the baselines. Rule 5 and the comparison need
  them as they are.
- **The procedural P2's `admit` and the null rule as frozen on 2026-10-07.** They remain the
  "decision points only" arm and the second score of every agent run. Changing them would move
  every earlier number. D1, the vacuous tier-A reading, is recorded, not fixed there.
- **The registry, its tools, versions and budgets** (rules 2 and 3). The rebuild changes what
  is citable, not what is computed.
- **Code writes the label; a model never does.** All three options keep this. It is what makes
  a result auditable.
- **Cited values are checked against what the calls produced, units included** (J5, rule 6).
  B7 fixes the keys, not the check.
- **The verifier's independence:** the hidden hold-out (J7), and a silent verifier abstains
  (J1).
- **Truth isolation** (rule 1), the live driver's gates, the approval machinery, the caps, the
  `emit_finding` schema fix of 17 Nov, and the model.
- **No wall-clock limit for P2** (2026-10-13). Time is bounded by evaluations, not a clock.
- **`CLAIMS_FOR_LABEL`:** one claimant role per label. It keeps responsibility for a claim clear.
  Only `structural`'s round-2 restriction is revisited (B12).

---

## 10. Questions for the lead

1. **The admission option:** (a), (b) or (c). I recommend (c).
2. **Under (c):** the false-positive rate per label (I suggest 5%), and the number of clean
   calibration seeds per tier (I suggest at least 40).
3. **Lifting the freeze for the rebuild:** one ruling, re-frozen once at the end (§8).
4. **Routing every specialist in round 1** (§5): yes or no.
5. **Whether to request provider reasoning summaries** (B13), subject to a check of the client.
