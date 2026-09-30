# P2 launch brief — procedural roles with model-backed decision points (proposal §6.5)

Status: **DRAFT 2 for the lead's approval, 2026-09-30.** Written by the coordinator
(`docs/coordinator.md`) after the lead's rulings of 2026-09-30: "Freeze P1", "prepare the
P2 launch brief", "P2 should not be agents with prompts", "run the knowledge audit on the
P1 transcripts". Draft 1 (seven prompted agents) is withdrawn. Nothing here launches
anything: a P2 session starts only on `launch: p2-multi-agent` from the lead
(CLAUDE.md, "Who starts a component session"), after PR #27 has merged on the lead's word.

The audit this draft rests on is `docs/p1_knowledge_audit.md` (rubric:
`docs/p1_knowledge_audit_rubric.md`), a read-only grading of all twenty revision-2 runs
(ten on GPT-5.6-luna, ten on Claude Opus 5.5) against eight process signatures.

## 1. Where the project stands

- **P0** built, frozen, characterised (17/78 exact on the sweep; `none` on 43 of 61
  faulted cells; no unsupported claims; harness ruled out as the cause of its misses;
  the admissible set of every cell known).
- **P1** frozen on 2026-09-30: revision 2 of the prompts (`prompt_sha256 c80a3752…`)
  with `gpt-5.6-luna`, no brief (PR #27 carries the freeze). Six development arms on the
  ten development cells, one run each:

  | arm | concluded | exact | primary = truth | `none` on the 4 clean cells | cost, USD |
  |---|---|---|---|---|---|
  | old prompt / GPT | 10 | 0 | 1 | 0 | 0.35 |
  | revision 1a / GPT | 10 | 0 | 1 | 0 | 0.43 |
  | revision 1b / GPT | 8 | 1 | 2 | 0 | 0.31 |
  | **revision 2 / GPT (frozen)** | 10 | 1 | 4 | 0 | 0.42 |
  | revision 2 + brief / GPT | 10 | 0 | 3 | 0 | 0.47 |
  | revision 2 / Claude Opus 5.5 | 10 | 2 | 2 | 0 | 9.86 |

## 2. What the knowledge audit found, and what it changes

**The answer to "do the agents have and use AD knowledge".** Mixed, split by model. The
Claude arm was process-literate but misapplied: 30 of its 41 evidence items invoke a
real signature in a form a process engineer would accept (the COD balance as arbiter
with both alternatives excluded by mechanism; a three-way differential across coupled
channels; the TAN-to-alkalinity coupling; assays used to acquit a routine channel).
The GPT arm was not process-based in the majority of its items (29 of 57): a QC flag
became a `sensor` label, z-statistics were read as verdicts without the magnitude
beside them, labels were attached to numbers by vocabulary. Where GPT was literate it
was misapplied in the same way as Claude, and in a second way Claude never showed: the
true signature seen and outranked (S2-01: pH at −17.5σ listed as one of four flagged
records, TAN flagged instead; S5-01: the ammonia-inhibition presentation recorded in
adjacent items and never assembled).

**The finding that governs P2's design.** Both arms were wrong for one repeated reason:
the plant's background misfit was taken as the fault. On the clean development cells the
tools report gas +11–25 % at default parameters, COD closure −0.14 to −0.19 and two
inadmissible balance windows; after any fit the channels keep 5–19σ biases. No step in
either arm asked what a clean record on this plant looks like. P0 hit the same wall and
was rescued by ruling B (thresholds: at least three inadmissible windows; QC flags and
charge inconsistency alone never fire). The P1 prompts cannot name thresholds, by the
prompt rule. So signature S7, the null case, was never reachable by P1 on these cells,
and every P1 arm's 0/4 on `none` is explained. The failure is the absence of a null
reference step, not the absence of process knowledge.

**Consequences for P2.**
1. P2's roles are procedures. Eight signatures the models never supplied in 20/20 runs
   become steps (§4); the decisions the transcripts show the models doing well stay
   with a model (§5).
2. P2 needs a **declared background**, the way it already has declared instrument noise:
   a per-plant null band for balance closure and residual profile, published in the
   benchmark card and carried in the tool results (`mass_balance` returns closure with
   its band; `residual_diag` returns the profile with the plant's background envelope).
   This is a benchmark decision, not a P2 one (§6, decision 1). Without it, `none` stays
   unscoreable for any model-backed workflow, and P2 would inherit P1's wall.
3. The first P2 metric is `none` on the clean cells, before exact attribution.

## 3. The roles: which are code, which have a model behind them

Seven roles from §6.5. Each is a procedure written from the review and from P0's rules,
with typed inputs and outputs. A model is called only at the decision points the
procedure exposes, each with a fixed output schema; it cannot skip, add or reorder
steps, and writes no free text into the task state.

| Role | Procedure (code) | Model-backed decisions | Tools it may call |
|---|---|---|---|
| **Coordination** | A state machine over the §6.6 task state: QC gate → balance → screening → fit → residual profile → verification → conclude or abstain. Evidence hygiene: one label per cited call; no relabelling of an item between turns; a refusal budget with the vocabulary shown once. Cannot approve its own output. | None. | None numerical; the stopping actions only. |
| **Data quality** | QC produces quarantines and abstentions, never a label (P0 rulings B(a), B(b)). Mandatory S1 table before any `sensor` label: the candidate channel's residual beside its physically coupled channels' residuals and any assay of them. The first-HRT excursions the QC flags as spikes go to the state test, not to quarantine. | Which windows to trust; which assay to buy against a suspected channel and on which day; the coupled-channel reading, written into a typed field. | `data_qc`, record inspection, `set_sensor_status` (quarantine only), assay request via the design role. |
| **Influent** | S8 with the null band: an `influent` label requires closure outside the plant's band **and** an onset or feed-covariate pattern; charge inconsistency alone never fires. The feed-log inspection is a step, with operator notes read as negative anchors. | Reading the feed log and notes; which balance window; the mechanistic statement once the table exists. | `mass_balance`, feed characterisation, record inspection. |
| **Identifiability** | A physics-forced candidate list per plant (on Plant A, the ammonia inhibition constant and the hydrolysis constants are always screened, so a Morris on pH cannot drop the parameter a scenario is about); Morris → Sobol → profiles / FIM; early-window vs late-window residual on every channel **before** any early quarantine (S4). | The fitted subset within the candidate list; whether an early/late difference warrants the state test. | `gsa_morris`, `gsa_sobol`, `profile_likelihood`, `fisher_info`, `residual_diag`. |
| **Calibration** | Screened fit; a split-window fit at the best common step across two or more channels (P0's R4); the inhibited-steady-state check when TAN and VFA are both high (S3); a `simulate(biomass_scale)` pair whenever the early window differs (S4); `bayes_mcmc` by procedure on the approved subset (Level-8 discipline: `posterior_intervals` abstained only after a failed call). A bound-hit is never a kinetic update. | Accept or reject a fit; interpret a bound-hit; the split-window reading. | `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc`, `simulate`, `residual_diag`. |
| **Experimental design** | Value-of-information on request; the assay budget enforced by the registry. | Which assay, which day, against which prediction: the audit found these choices apt in 9 of 10 Claude runs. | `voi_assay`, assay requests. |
| **Verification** | S7 first: the residual profile at defaults and after the fit against the plant's background envelope, and the balance against its band; a label passes only over an explicit null case that failed. Hold-out validation (the verifier alone sees it). S6 only on P0's R3 criterion (two or more channels structured after the fit, or a parameter at a bound) **and** a failed hold-out. Receives the proposed result, the full action log and the frozen validation data; sees no free text from proposing roles. Returns pass / fail / abstain. | One decision: the mechanistic differential, written from the tables (the audit found this correct in form whenever the reference was right). | `validate`, read-only state and log. |

Four roles have a model behind them (data quality, influent, identifiability,
calibration) plus two narrow model decisions (experimental design; the verifier's
differential). Coordination is code. The three-role minimum of the proposal's descope
clause is data quality, calibration and verification.

## 4. The eight steps P2 encodes (from the audit, §7)

1. **S7, the null reference**, before any label: channel residual profile at defaults and
   after the screened fit against the plant's background envelope, not against
   instrument noise. Removes the whole Claude-arm failure mode and three of GPT's six
   wrong primaries.
2. **S8 with a null band**: `influent` needs closure outside the band and an onset or
   feed-covariate pattern; charge alone never fires.
3. **S1 as a mandatory table** before any `sensor` label; QC flags produce quarantines and
   abstentions, never a label. Six of GPT's eight sensor labels came from this gap.
4. **S4 as a step**: early vs late residual on every channel before quarantining early
   spikes; the `biomass_scale` pair when the early window differs.
5. **S3/S5 change-point and inhibition tests**: split-window fit at the best common step;
   physics-forced candidates per plant; the VFA/TAN/pH inhibited-steady-state check.
6. **S6 in the verifier only**, on R3 plus a failed hold-out.
7. **Level-8 discipline**: the sampler by procedure; the abstention only after a failure.
8. **Evidence hygiene** in the coordinator.

## 5. What is left to the model, on the audit's evidence

Assay choice; the mechanistic differential once the tables exist; reading operator notes
as evidence and negative anchors; the fitted subset within a physics-forced list, and
declining a bound-hit as a kinetic update (0 false kinetic updates in 20 runs);
abstention wording once the scored terms are procedural.

## 6. Decisions the lead is asked for before launch

1. **The declared background.** Publish a per-plant null band (balance closure and
   residual envelope) in the benchmark card and carry it in the tool results, as
   declared noise is carried today. It applies to every workflow. P0 already runs on
   ruling B's thresholds; the frozen P1 cannot use it (its prompts are fixed), so P1's
   0/4 on `none` stands as its record. Alternatives: state the band numerically in the
   P2 prompts (weaker: a prompt, not a tool result); or leave `none` unscoreable for
   model-backed workflows (then RQ3 cannot be answered on the null cells).
2. **S5-01's injected magnitude** multiplies K_I_nh3 by 0.1; the fitted model's declared
   box is [0.2, 5.0]. No bounded update can reach the truth. Record it, and decide
   whether the scenario's magnitude or the box moves (a G1-frozen change either way).
3. **S6-02 at tier B** shows no alkalinity/pH deficit in any tool output (inside the
   clean-cell envelope); P0 also read `none`. Decide whether Level-6 needs tier C or a
   larger magnitude to be visible, or whether S6-02 B/B is admissible-`none` by design.
4. **`data_qc` labels the Level-4 start-up transient as spikes** (S4-01 days 0, 1, 7).
   P2's step 4 works around it; a tool change (a first-HRT flag class) would be cleaner
   and is a `tools/impl/` change, so it is the lead's.
5. **Two runs per cell** for all P2 development runs (one run per cell left every P1
   difference inside the noise).

## 7. What the P2 session delivers, in order

1. `docs/p2_design.md`: the seven procedures as step lists with their decision points and
   output schemas, the message schemas, the tool allow-lists, the routing state machine,
   the null-reference step and where the band comes from, the budget accounting (one run,
   one budget, summed over roles: evaluations, wall clock, tokens, assay units), the
   ablation switches (§6.7 E: verifier off, coordinator off, each specialist off,
   persistent state off, self-correction off; each a flag with a test), the record
   schema. Reviewed by the coordinator before any live call.
2. The three-role minimum (data quality, calibration, verification) offline on the
   scripted and recorded doubles, with tests: a role cannot call a tool outside its
   list (negative control); the verifier never receives free text (a planted claim);
   the budget summed across roles; the message log; the null case in the verifier's
   output; every decision point's schema.
3. The three-role minimum live on three development cells (one clean, two faulted), two
   seeds each. **Go / no-go:** if the null reference does not produce `none` on the clean
   cell, stop and report; that is a benchmark finding about the band, not a P2 task.
4. The seven roles offline, then live on the ten development cells, two seeds each; the
   P2 development report against the frozen P1 rows.
5. The ablations, verifier-off first.
6. On the lead's word only: the P2 freeze; the held-out variants of §7 for P1 and P2.

## 8. Success criteria, cost, risks

- `none` on at least two of the four clean development cells with no loss of primary
  hits on the faulted cells against the frozen P1 (4/10); no unsupported claim, no
  false kinetic update; budget parity from the logs; every ablation switch tested;
  abstention precision scored (`abstain` on a representable cell is a miss).
- Cost: the frozen P1 arm was about USD 0.42 and 14 runner-hours per ten cells on GPT.
  P2 under the same per-run token cap, two seeds per cell: tens of USD and a few
  runner-days for the development phase including ablations. Wall clock is bounded by
  the same per-cell allowance as P1.
- Risks and mitigations: the verifier abstains on everything (abstention precision is
  scored); the coordinator smuggles a conclusion (it holds no numerical tool and the
  verifier sees no free text; tested); message overhead eats the token budget (per-run
  cap, per-role attribution in the log); seven procedures is a lot of writing (the
  three-role minimum first, and P0 already contains those three in scripted form);
  P2 built twice (the launch protocol); machine-instance effects (comparisons on counts
  and labels, never wall clock across instances).

## 9. What the coordinator needs from the lead

1. Decisions 1–5 of §6, or edits to §3–§5.
2. The merge word for PR #27 once its review passes.
3. `launch: p2-multi-agent`. The coordinator then starts one P2 session with this brief,
   the audit, the proposal, `docs/p1_design.md`, `docs/coordinator.md` and the standing
   constraints, and reviews its design document before any live call.
