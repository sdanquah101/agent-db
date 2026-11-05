# AD-AgentBench — status report and technical deep dive

**As of 2026-11-05.** `main` at `f72fb9e` (merge of PR #46). One open draft PR (#48).
**Scope.** All work done so far: the research design, every component, the methodologies, the
results, the decisions and rulings, the process, the cost, and what is open. It was assembled from
the whole repository: the code, configs, tests and committed reports, the proposal, all design
notes, `docs/decisions.md` (206 entries), `docs/milestones.md` (4,504 lines) and the pull-request
history (#1–#48).
**Status of this document.** A read-only survey. Writing it changed nothing in the codebase, and it
is not a decisions entry. Where two documents disagree, or a document disagrees with the code, the
disagreement is reported in §19 rather than resolved.

> Conventions. **Implemented** = in code on `main` and tested. **Designed** = specified in a
> design note or config but not built or not run. **Open** = an unresolved question or a known
> gap. "The lead" is the project's human design authority. "The coordinator" is the single
> reviewing session named in `docs/coordinator.md`. Digests are shortened to their first and
> last characters.

---

## Contents

1. Executive summary
2. The research design (what the benchmark is for)
3. Timeline: plan against delivery
4. Governance and engineering process
5. The simulator: the hidden truth
6. The real-data anchor and gate G1
7. The scenario library
8. The tool registry, the jail and the budgets
9. P0 — the scripted baseline
10. The evaluation suite
11. Validity studies around P0 (positive control, distinguishability, the F2 horizon study)
12. The declared background and the null rule
13. P1 — the single constrained agent
14. P2 — the procedural "decision points" arm
15. P2 — rebuilt as agents
16. The open PR (#48): the H4 development cells
17. Results across workflows, side by side
18. Cost and compute
19. Inconsistencies and stale documentation found
20. Open items, risks and gaps against the proposal
21. Lessons the project has recorded about itself
Appendix A. Every pull request
Appendix B. Superseded and reversed decisions
Appendix C. Repository facts and today's health check

---

## 1. Executive summary

**What it is.** AD-AgentBench is an open, reproducible benchmark that asks a narrow question:
*does agent discretion — one LLM agent, or several specialised ones — help attribute a mismatch
between an anaerobic-digestion (ADM1) model and plant data to its real cause, compared with a
competent scripted pipeline using identical tools, data and budgets?* Real plants cannot answer
this, because their true parameters and true fault causes are unknown. So the benchmark simulates
plants with a hidden, deliberately richer "truth" model, injects labelled faults, and scores
workflows on attribution, abstention, discipline and cost, not just on fit.

**Where it stands.** In nine weeks of calendar time (2026-09-02 → 11-05) the project completed
what the proposal planned as roughly 26 weeks of work. 44 PRs are merged, 3 closed, 1 open, over
362 commits.

| Component | State |
|---|---|
| ADM1 truth core + extensions (SAO, Davies ionic strength, carbonate, calcite) | Implemented. Ring-tested against bsm2-python to ≤ 5e-4 relative. |
| Three plants (A agricultural; B Muscatine co-digestion; C sludge-only B), influent generator, observation model, 17 fault types, run harness with a separate truth store | Implemented. **Gate G1 frozen** (2026-09-21). |
| Real-data anchor (Muscatine WRRF, ODC-By) | Statistics ingested. 22/22 independent G1 rows in tolerance. The §8 real-data forecasting check is **not built**. |
| Scenario library | 20 scenarios, Levels 0–8; 117 matrix cells. |
| Tool registry v1.0 (16 numerical tools + 8 priced assays) in a user/mount/pid namespace jail | Implemented and frozen. |
| P0 scripted pipeline | Implemented and **frozen**. Level 0–5 sweep: **17/78 exact** attribution (22 %), 25/71 on the admissible-set score. |
| Evaluation suite (families A–D, from logs only) | Implemented. Family E (ablations), the mixed-effects analysis and pre-registration: **not built / not filed**. |
| Validity studies | The positive-control ladder ran, and neither lever moved a label. Distinguishability: the truth is admissible on 60/78 cells. The F2 horizon study fixed a de-anonymisation leak. |
| P1 single agent | Implemented and **frozen** (rev 2 prompt on OpenAI `gpt-5.6-luna`). Development pilot only: best arm 4/10 primary labels, **0/4 `none` on clean cells in every arm**. Not scored on the sweep (not authorised). |
| Declared background + P2 null rule | Implemented and frozen. Clean false-alarm rate 0.16 (95 % CI 0.10–0.23). |
| P2 procedural ("decision points only") arm | Implemented and frozen. Three live pilots (6 runs each, **3/6 correct**, ≈ USD 0.02 in total). It showed no model judgement beyond code. |
| P2 rebuilt as seven role agents with an adversarial verifier | Harness implemented, all rule tables frozen, **no live model turn yet**. The offline floor on the H4 cells is 0/8 (PR #48, open). |

**The central empirical finding so far** is a measurement-design finding, not an agent ranking.
The fitted model, fed the visible feed log, misfits even clean plants by 5–19 σ after fitting
(the "background"). P0 therefore reads most faults as `none`. Every P1 arm reads the background
itself as a fault and never concludes `none`. The project's answer was a declared, served null
reference (the `declared_background` tool and the frozen null rule), on which P2 is now built.

**What is not yet done** (detail in §20):
- the held-out scenario variants;
- pre-registration;
- the 5-seed final matrix (~1,440–1,700 runs);
- P1/P2 scoring on the sweep;
- the agent-arm live pilot (needs a new approval record from the lead);
- the mixed-effects analysis and ablation scoring;
- the §8 real-data forecasting check;
- Docker and pinned dependencies;
- the `g1-frozen` tag;
- the fitted-model ports (Weinrich R3/R4) promised at ADM1 acceptance.

**Spend recorded: ≈ USD 12.2 of LLM calls in total**, 81 % of it on one Claude development arm.

**Found for this report.** None of these is in the project's own records; details in §8.9, §10.3
and §19.
- **The Level-8 injected-MCMC payload is identifiable from its output.** It returns fixed sizes, 0
  evaluations and a NaN log-probability. The visible log line, by contrast, is carefully
  indistinguishable from a genuine failure.
- **The registry's declared cost bounds undercount least-squares tools.** Finite-difference
  Jacobians are not counted: 72 declared, 112 charged.
- **`profile_likelihood` crashes at P0's configured `profile_starts: 1`.** Latent: P0 never reaches
  profiles.
- **The jail has no network namespace.**
- **`verifier_rejections`, needed for H6, is written by nothing.**
- **The visible call log carries no workflow field.** Two workflows on one run could cross-charge
  cost and the D2 credit.
- Several stale documents (README status, benchmark card §8 and §10, docstrings).

---

## 2. The research design

Source: `docs/proposal.md` v0.3 (Ruthie Armah, KNUST–TUM SEED Centre, September 2026).

### 2.1 The gap and the argument
- **Calibration of ADM1 to industrial data is a joint inverse problem.** Influent composition,
  latent states, sensor bias, kinetic parameters and structural error compensate for one another.
  A better fit can mean worse parameters.
- **A residual has several possible causes:** sensor, feed, state, parameter, or an omitted
  mechanism. Existing workflows send every mismatch to the optimiser. The question *"where did
  this error enter?"* is rarely asked and never scored.
- **No published work applies AI agents to AD calibration.** None anywhere holds the numerical
  tools constant while varying only orchestration.
- **Only a synthetic plant with hidden truth can score** parameter recovery, attribution and
  correct abstention.

### 2.2 Objectives O1–O7
| | Objective |
|---|---|
| O1 | A simulated plant with a hidden truth model, realistic influent, an explicit observation model and fault injection. |
| O2 | A frozen, versioned registry of conventional tools, identical for every workflow. |
| O3 | A scenario library with a labelled cause and a correct conclusion per scenario. |
| O4 | Three workflows (P0 scripted, P1 single agent, P2 multi-agent) under equal tools, data, compute and assay budgets. |
| O5 | An evaluation protocol: calibration quality, attribution, information efficiency, reliability, safety, cost. |
| O6 | An anchor to at least one open full-scale dataset. |
| O7 | Open release of everything, with a preprint. |

### 2.3 Research questions and hypotheses
**Research questions:**
- **RQ1.** Practical identifiability by tier and scenario class (the ceiling).
- **RQ2.** Does agent discretion improve attribution?
- **RQ3.** Does multi-agent decomposition add anything beyond a single agent at equal tools and budget?
- **RQ4.** Can a value-of-information agent choose the assay that best reduces uncertainty per cost?
- **RQ5.** What does orchestration cost?

**Hypotheses:**
- **H1.** Screened calibration beats all-parameter calibration out of sample, most at Tier A.
- **H2.** Triage-first workflows show less false kinetic drift than fit-first ones.
- **H3.** P1 beats P0 where the right tool sequence is conditional.
- **H4.** P2 beats P1 only with two or more simultaneous faults.
- **H5.** VoI assay selection beats fixed schedules.
- **H6.** Agents make invalid actions and unsupported claims, and a verifier reduces their propagation.

### 2.4 Design elements
- **Truth vs fitted model.** The truth is an extended ADM1; the fitted model is standard ADM1.
  The fitted model is *structurally wrong by design*.
- **Plants:**
  - A: agricultural cattle slurry + grass silage, statistics-anchored.
  - B: municipal sludge + trucked high-strength waste (HSW) + FOG, dataset-anchored to Muscatine.
  - C: the same digester as B, fed sludge only (a controlled pair).
- **Tiers** are observation masks on identical truth (A ⊂ B ⊂ C):
  - **Tier A:** feed, T, daily pH and biogas, weekly TS/VS.
  - **Tier B:** + continuous CH₄, weekly alkalinity, VFA, TAN, COD.
  - **Tier C:** + VFA speciation, off-gas H₂ and others.
- **Scenario ladder.** Levels 0–8, from clean to compound, tool failure and adversarial notes.
  The truth labels are {sensor, influent, state, parameter, structural, none}.
- **Workflows:**
  - **P0:** QC → balance → Morris → Sobol → profiles → LSQ/DE → MCMC → validate.
  - **P1:** one LLM agent choosing the calls.
  - **P2:** seven roles (data quality, influent, identifiability, calibration, design,
    verification, coordination) with typed messages; the verifier independent.
- **Evaluation:**
  - A: calibration/prediction.
  - B: attribution and epistemic discipline — the new family.
  - C: efficiency.
  - D: reliability.
  - E: ablations.
- **Experimental design:**
  - Factorial core of 16 scenarios × 3 tiers × 2 plants × 3 workflows × 5 seeds ≈ 1,440 runs, plus a separately reported Plant A subset.
  - Held-out variants generated after the freezes and used once.
  - Pre-registration; mixed-effects analysis with bootstrap effect sizes.
- **Gates:**
  - G1 (wk 9): the simulator is realistic.
  - G2 (wk 16): P0 is interpretable.
  - G3 (wk 20): metrics come from logs, and pre-registration is filed.
  - G4 (wk 30): P1/P2 run inside budget with frozen prompts.
  - G5 (wk 34): analysis complete.
- **Non-claims.** The benchmark does not claim simulation success transfers to plants. Out of
  scope: RL/HMARL (P3, deferred), real-plant calibration, operator studies, actuation.

---

## 3. Timeline: plan against delivery

The project started 2026-09-02, so 2026-11-05 is calendar **week 10** of the 36-week plan.
Milestones 1–7 are complete and milestone 8 (P2, planned for weeks 26–30) is far advanced. The
"weeks" in `docs/milestones.md` are plan labels, not elapsed time.

| Milestone (plan weeks) | Delivered | PRs | Dates |
|---|---|---|---|
| 1. Base ADM1 selected; datasets identified (1–2) | Candidate probes; own Petersen ADM1 accepted with conditions; Muscatine and ILRI fetched; anchoring ruling | #1, #3 | 09-02 |
| 2. Truth model + extensions, three plants, influent generator (3–6) | ADM1 core (#2), extensions (#4, #5), plants (#6, salvage #8), catalogue (#9), generator (#10), observation + faults (#11, salvage #13), historian dropout and coordinator file (#14) | #2, #4–#14 | 09-02 → 09-03 |
| 3. Observation model, faults, **G1** (7–9) | Run harness, 19 → 20 scenarios, G1 anchor report, many review rounds; G1 frozen | #15 (18 days) | 09-03 → 09-21 |
| 4. Tool registry v1.0, frozen (10–13) | Registry, 16 tools, 8 assays, fitted model, namespace jail | #17 | 09-21 |
| 5. P0 (14–16) | P0 design, task state, pipeline, runner, two pilot rounds; P0 frozen | #18 | 09-21 → 09-22 |
| 6. Evaluation suite (17–20) | `eval/` families A–D, meter as cost source; the Level 0–5 sweep; rulings A1–A4 and D1–D3; positive control; distinguishability | #19–#25 | 09-22 → 09-28 |
| 7. P1 (21–25) | Agent, gateway, six development arms, Anthropic arm, P1 frozen, knowledge audit, P2 launch brief | #26–#29 | 09-25 → 09-30 |
| 8. P2 (26–30) | Declared background (#30), design + null rule (#31), offline workflow and power run (#32), live wiring and pilots 1–2 (#33), D-1/N-2b/L-1 (#34), tidy-up (#35), pilot 3 (#36); P2-as-agents design (#37) and build steps 1–3b (#38–#46); CI fix (#47); H4 cells (#48, open) | #30–#48 | 09-30 → 11-03 |

**Gates.**
- **G1** was formally gated and frozen at `9f635df`:
  - "G1 not passed" on 09-03;
  - passed conditionally 09-09;
  - "FREEZE" verdict 09-20;
  - merged 09-21.
- **G2, G3 and G4 are never formally declared passed or failed** in `docs/milestones.md`:
  - G2's substance (P0 interpretable) was met with the sweep.
  - G3's pre-registration is not filed.
  - G4 is in progress.

---

## 4. Governance and engineering process

### 4.1 Roles
- **The lead (human)** decides every design question, freeze, live spend and merge, usually in a
  short quoted word: "merge 41", "Freeze P1", "Let's go", "Yes to all three", "a".
- **The coordinator session** (`session_01Cu6G2kQjP2QSzvtkyP8cPr`, appointed 2026-09-03):
  - reviews every open PR independently;
  - relays questions up and rulings down;
  - merges only on the lead's word;
  - **never launches a component.**
  - Its daily routine (`trig_012S8ncXhsvDXbojKiBc4ZFC`, 08:00 UTC) is review-only.
- **Component sessions** start only when the lead sends `launch: <component>`. Each one:
  - lists all open PRs before writing code;
  - opens drafts;
  - never merges or spawns;
  - routes everything through the coordinator.

### 4.2 Why: three duplicate builds
Three of the first six components were built twice by sessions unaware of each other:

| Component | Duplicate PRs | Outcome |
|---|---|---|
| ADM1 core | #2 vs #4 | #4 reduced to the extensions; about 1 h lost |
| Plant layer | #6 vs #7 | #7 closed; its engineering salvaged in #8 |
| Observation model + faults | #11 vs #12 | #12 closed; three items salvaged in #13 |

- **The shape each time:** a routine launched a component per its plan while a decision had
  already reached another session directly.
- **What failed:** adding "check open PRs" to `CLAUDE.md` did not stop the third collision, because
  the second session checked only its named predecessor.
- **The fix:** remove the routine's launch authority, and name the coordinator in the repository
  (`docs/coordinator.md`, PR #14). *Authority, not a checklist.*
- Two launches were later read from paraphrases ("Lets move to the next task" → `launch:
  tool-registry`; "Launch now" → `launch: p0-scripted`). Both are recorded in `docs/decisions.md`.

### 4.3 Review and freeze discipline
- **Reviews.** Every PR gets independent, fresh-context reviews with explicit verdicts (MERGE
  AFTER FIXES / DO NOT MERGE / FIXES NEEDED / PASS / PASS WITH NITS / FREEZE).
  - Findings carry lettered IDs by severity and round: H1–H3 and M1–M7 (G1); B1–B5 and F1–F6
    (later G1 rounds); J0–J3 blocking on PR #41; M1–M6 on #43; and so on.
  - Fixes are routinely **mutation-checked**: build the mutant, show the test fails.
  - Tests must carry **negative controls**, so a guard cannot pass by refusing everything.
- **Regeneration rule.** The scenario matrix is regenerated only at a reviewed head with CI
  green, as the last action, so every manifest's `git_sha` is the merged code. One regeneration
  (`a91e71a`) was declared **VOID** because CI was red.
- **Freezes and their guards:**
  - plant configs;
  - feed catalogue;
  - observation defaults;
  - titrimetric κ;
  - G1 configs;
  - registry v1.0;
  - P0 rules (two-head comparison test, `p0_freeze`);
  - P1 (`check_frozen` before every run);
  - the P2 null rule (by sha256);
  - the P2 decision layer (`check_p2_frozen`);
  - the P2 agent record, rule tables and routing (`check_p2_agents_frozen`).
- **Live LLM spend.** It needs the lead's word. For P2 it also needs a **committed, pushed approval
  record** that binds:
  - the configuration digest;
  - the exact runs;
  - the caps;
  - the freeze digest;
  - a fresh run store.

  The commit must be confirmed on the remote with `git ls-remote`. Each record runs once.
- **Operating rules learned from incidents:**
  - no test suite beside live cells;
  - one process per cell, at most three lanes;
  - a session-tracked watch beside any detached compute (containers were reclaimed mid-run on
    09-30 and 10-02);
  - unfinished P2 runs are rerun once offline and never scored; live runs are never rerun
    automatically.

### 4.4 Conventions
- Python ≥ 3.11 (CI tests 3.11 and 3.12), Pydantic for every schema, ruff (E, W, F, I, UP, B,
  SIM, D, ANN, RUF; line length 100), pytest strict.
- Numerical tolerances and solver settings live in `configs/` and are never hard-coded.
- Every stochastic step takes an explicit seed.
- Every quantity carries an explicit unit, standard-condition basis or wet/dry basis.
- Code: Apache-2.0. Scenarios, results and figures: CC-BY-4.0.

---

## 5. The simulator: the hidden truth

Sources:
- `sim/` (39 modules, 11.4 k lines);
- `configs/{adm1,plants,influent,observation,faults,runs}/`;
- `docs/adm1_comparison.md`, `docs/vfa_gap.md`, `scripts/adm1_candidates/`;
- tests `test_adm1_*`, `test_plants`, `test_mixing`, `test_equalisation`, `test_influent`,
  `test_generator`, `test_observation`, `test_faults`, `test_run_harness`, `test_truth_isolation`,
  `test_plausibility`, `test_reference_window` and `test_visible_prefix`. In this review's reading
  pass these gave 339 passed and 2 skipped (the skips need the git-ignored 88.8 MB SCADA file).

### 5.1 Choosing the base ADM1 (Milestone 1)
**The harness** (`scripts/adm1_candidates/common.py`). Every candidate got the same BSM2 digester:
- V_liq 3,400 m³, V_gas 300 m³, 35 °C, Q 170 m³/d;
- the ADM1-STR sludge feed;
- a start from the Rosen & Jeppsson (2006) steady state.

Two probes:
- **Probe 1:** 100 d at the defaults.
- **Probe 2:** 20 d, with the feed tripled from day 10, as a stiffness test.

The plausibility gate is deliberately wide, so that one implementation's conventions are not
encoded as truth.

| Candidate | Time per simulated day | Probe 1 (pH / CH₄ / q_gas / VFA) | Verdict |
|---|---|---|---|
| PyADM1 (MIT) | 0.20 s | 7.464 / 0.642 / 2956 / 237 | Module globals, no tests → second reference |
| **bsm2-python 0.0.16** (BSD-3) | 0.002 s (one BDF call) | 7.464 / 0.642 / 2956 / 237 | **Primary oracle**; hand-expanded, so extensions are hard |
| QSDsan/EXPOsan 1.4.3 | 0.023 s | 7.466 / 0.644 / 2951 / 238 | Right design; ≈ 1 GB of dependencies and global state → **equation reference only** |
| ADM1F standard | 0.005 s | 7.472 / 0.641 / 2949 / 237 | Under-resolved; PETSc toolchain; would not build as documented (a deployability finding) |
| ADM1F makefile default | 0.006 s | 7.092 / 0.596 / 2611 / **5296** | Fails the gate. It is not ADM1: Haldane uptake on undissociated acetate, plus an index transposition |
| Weinrich ADM1-R1…R4 | — | MATLAB/Simulink only | Earmarked as the *fitted* models |

In Probe 2 the four standard implementations agree within 3 %, with no step-size collapse.

**Decision (the lead, with conditions).** Build an own **Petersen-matrix ADM1** in `sim/`,
ring-tested against bsm2-python. In a matrix model the extensions are added rows; in a
hand-expanded port each one is a hand edit. The conditions:
1. Agree to 3 s.f. on both probes and the BSM2 280-day dynamic influent, or fall back to a
   bsm2-python fork. **Met in week 3.**
2. QSDsan is never a dependency.
3. **Port Weinrich R3/R4 as the fitted models.** **Never done.** The fitted model became BSM2 +
   fitted extensions (2026-09-21), and no entry retires the condition.

### 5.2 The ADM1 core (`sim/adm1/`)
- **State.** The 26 R&J liquid states plus 3 headspace gases (29). The six ion species are
  algebraic; Q is an input. Extension states are appended after 29.
- **19 biochemical processes:**
  - disintegration, 3 hydrolysis, 8 uptake, 7 decay;
  - BSM2 Hill-type pH inhibition;
  - non-competitive H₂ inhibition on fa/c4/pro;
  - free-NH₃ inhibition on acetate uptake;
  - inorganic-N limitation.
- **The Petersen matrix is data** (`configs/adm1/petersen_matrix.yaml`).
  - 26 components carry COD, C, N and charge content.
  - Expressions are evaluated by a restricted AST walker, with no `eval`.
  - The S_IC and S_IN entries are written out explicitly, so the conservation test is real: all four
    balances close to < 1e-12.
- **Parameters** live in `configs/adm1/params_bsm2.yaml`. The fractions BSM2 hard-codes are named
  and validated to sum to 1.
- **Acid–base.** pH is found **algebraically**: a bracketed Brent root-find on the charge balance
  over [0, 14] with xtol 1e-12 on every RHS call. This avoids BSM2's six stiff ion ODEs and its
  t = 0 pH artefact (8.49).
- **Other physics:**
  - S_h2 is an ODE state.
  - Van 't Hoff temperature correction applies to K_w, K_a, K_H and vapour pressure.
  - Gas transfer follows BSM2.
  - Two gas conventions are reported: BSM2, and dry 0 °C / 1 atm (rule 6).
- **Solver** (`configs/adm1/solver.yaml`):
  - SciPy BDF, rtol 1e-6, atol 1e-8, with Radau as a cross-check.
  - Negative states are clipped in the rates only.
  - Influent is sample-and-hold (the default; the integrator restarts at each breakpoint) or
    linear.
- **Validation** (`tests/test_adm1_ring.py`):
  - "3 s.f." is implemented as relative difference ≤ **5e-4**.
  - Probes 1 and 2 are checked state by state, with the Radau cross-check and step-collapse guards.
  - The 280-day BSM2 dynamic influent (26,880 segments) is checked in both influent modes.
  - **Measured worst agreement: 1.5e-4.**

### 5.3 Truth-model extensions (`configs/adm1/extensions.yaml`, `sim/adm1/extensions.py`)
Additive and individually switchable. All three plants enable all four.

1. **Syntrophic acetate oxidation (SAO).**
   - New biomass `X_sao`. Uptake follows k_m_sao · Monod · X_sao, under the hydrogenotrophic pH
     window, IN limitation, its **own weaker NH₃ inhibition** (K_I_nh3_sao **0.05** kmol N/m³,
     ≈ 28× the acetoclastic constant; cited range 0.02–0.1) and H₂ inhibition.
   - k_m_sao is **4.0** (μ_max 0.16 d⁻¹), raised from 2.0 so that SAO can establish at Plant A's
     HRT.
   - Tests: takeover at 60-d HRT; washout at 20-d HRT.
2. **Davies ionic strength.**
   - A(T) scaled from 25 °C; I by fixed point, capped at 0.5 M.
   - pH is reported as −log a_H⁺, and the inhibition terms see activities.
   - Ions are lumped as monovalent, so I may be understated by up to about 2×.
3. **Carbonate second dissociation.** pK_a2 10.33, at 25 °C and **not temperature-corrected**
   (open). Default off.
4. **Calcite precipitation.**
   - Rate k_prec·(√SI − 1)ⁿ, with K_sp(T) from Plummer & Busenberg 1982.
   - No dissolution: an undersaturation flag is reported instead.
   - Tested on the Ca balance and on alkalinity.

Each extension, enabled but inert, reproduces the base Probe 1. All four together reproduce the
oracle to ≤ 5e-4. **No published oracle exists for the combined model.**

**Intended truth-vs-fitted mismatches. These are content, not bugs:**
- **Per-feed inert nitrogen in the truth only:**

  | Feed group | Inert N (kmol N/kg COD) |
  |---|---|
  | slurry, silage | 0.001 |
  | HSW, FOG, food waste | 0.0015 |
  | sludges | 0.00429 |

  The fitted model keeps the BSM2 `N_I`. The lead's instruction: *"never to be fixed."*
- **Level-6 rows:** the truth keeps an extension (SAO, precipitation) or a two-zone reactor, and the
  fitted model is denied it.
- **Plant A's adapted `K_I_nh3`** is truth-side only.

### 5.4 The three plants (`configs/plants/`, `sim/plants/`)
| | A | B | C |
|---|---|---|---|
| Domain | cattle slurry + grass silage, 41 °C | sludge + HSW + FOG, Muscatine | the same digester as B, sludge only |
| Anchoring | statistics (Tisocco 2024) | dataset (Muscatine) | dataset (Muscatine) |
| V_liq / V_gas (m³) | 650 / 57.4 | 1,836 / 162 | 1,836 / 162 |
| HRT | 40 d (35–45) | 19.5 d (12.6–37.6) | 38.3 d |
| Equalisation | — | 123 m³ CSTR blend tank (HSW only) | — |
| Horizon | 365 d | 200 d | 200 d |
| Matrix cells | 21 (separate subset) | 48 | 48 |

- **Common to all three:**
  - a hidden active-volume error of ±5–15 %, random sign, truth-side only;
  - the BSM2 headspace ratio (assumed);
  - an ideal CSTR in the contract (imperfect mixing is only a fault variant).
- **B and C are a controlled pair:** identical except for the feeds (tested).
- **Plant A's two baselines** (ruling 1, 2026-09-09; truth-side in `sim/plants/truth/plant_A.yaml`):

  | Baseline | K_I_nh3 | Dominant pathway | TAN |
  |---|---|---|---|
  | `adapted` | 0.02 | acetoclastic (X_ac 1.065) | 3.1–3.7 |
  | `unadapted` | BSM2 default 0.0018 | SAO (X_sao 0.853) | 3.5–3.7 |

  - The two pathways cannot coexist (competitive exclusion), so the ammonia rows are staged as
    transitions.
  - A feed trace of X_sao (1e-4) lets a washed-out population return.
  - The burn-in is 400 d.
- **Plant A HRT.** Tisocco's stated 28 d conflicts with the published volumes, which imply 32–50 d.
  At 28 d, SAO could not establish (`scripts/plant_a_sao_probe.py`).
- **Equalisation tank.** dV/dt = q − V/τ, integrated exactly. Mass is conserved to machine
  precision, verified against a closed form and Radau. τ and the initial state come from the first
  window.
- **Two-zone mixing** (`sim/plants/mixing.py`): an active zone plus a stagnant fraction φ exchanging
  at k_ex, with bypass β. It reduces bit for bit to the CSTR at φ = β = 0 and is verified against
  the analytical tracer solution.

### 5.5 The influent generator (`sim/influent/`, `configs/influent/`)
**Feed catalogue.** Seven feeds, all still marked `status: provisional`.
- **COD/VS is derived** from the fractionation and per-class COD equivalents, never declared:
  - inert equivalent 1.2 for lignocellulosic feeds, 1.42 for sludges, **2.9 for FOG**;
  - the literature COD/VS is kept as a ±10 % check.
- Values that came from rulings:
  - cattle-slurry inert share 0.40 (BMP evidence);
  - silage on the Tisocco 2024 basis (pH 4.28 accepted);
  - HSW lipid share 0.6631;
  - degradable shares 0.84 (HSW) and 0.92 (FOG).
- **Nitrogen.** Tisocco's "NH₄-N g/kg TS" column is read as total N. TAN = a cited ratio × TKN
  (slurry 0.55, silage 0.10).

**Stochastic structure:**
1. A true fractionation per feed per run: a Dirichlet draw around the catalogue (concentration κ).
2. Delivery days: continuous, weekday-with-skips, or a two-state Markov chain (HSW: mean gap 6.9 d
   against 6.94 measured).
3. Amounts: median × seasonal × exp(AR(1)).
4. Moisture: TS × seasonal × exp(AR(1)).
5. Unrecorded deliveries: 1 %/d for trucked or loader-fed feeds.
6. Mis-logged masses: 2 %, log-sd 0.3.
7. Routine assays (TS, VS, COD, TKN, TAN, alkalinity, pH), with cv and lag, on **logged deliveries
   only**. Assaying unrecorded deliveries would leak truth.
8. A daily sample-and-hold series.

**Seeds and prefix stability (rulings 1 and 6, 2026-09-11):**
- Each block has a keyed child stream, so the first n days of a longer run equal a shorter run.
- Reference quantities (truth N_I, truth parameters, burn-in recipe, inert equivalent, initial Ca)
  come from a fixed first-200-day window.

**Chemistry consistency rulings** (2026-09-09/10):
- **M2:** the feed alkalinity assay is computed from the full charge balance. The HSW assay had been
  ~480–503× below its fed charge.
- **Liquor:** dissolved species scale with the liquor fraction.
- **Calcium:** dissolved Ca is derived from calcite saturation, 10–30× below the earlier total-Ca
  values.

Afterwards every stream's assay/charge ratio is 1.000, except silage (0.771) and food waste (1.018).

### 5.6 The observation model (`sim/observation/`, `configs/observation/sensors.yaml` v2)
**Truth channels:**
- pH;
- gas flow in both conventions;
- CH₄, CO₂ and H₂ fractions;
- alkalinity;
- true VFA (total and speciated) and **titrimetric FOS**;
- TAN and free NH₃;
- COD;
- digestate VS and TS (TS from a conserved ash tracer);
- FOS/TAC.

In two-zone runs each channel is read where its instrument sits.

**Tiers** (nested masks, enforced by the schema):

| Tier | Online | Lab | Lab turnaround / recalibration |
|---|---|---|---|
| A | T (noise 0.03 K, anchored), pH (0.02; drift; fouling), gas (cv 0.021, anchored) | weekly TS/VS | 7 d / 90 d |
| B | + CH₄ fraction (±0.01) | + weekly alkalinity, titrimetric VFA, TAN, COD | 3 d / 30 d |
| C | + H₂ off-gas | + speciated VFA (true + noise; valerate 15 % + floor), digestate VS/TS | 1 d / 30 d |

H₂S is absent (ADM1 has no sulfur).

**The sensor pipeline:** schedule → fouling → bounded drift with reset → relative + absolute noise
→ saturation → flatline → missingness → lag.

**Missingness:**
- Base rate per tier: A 8 %, B 4 %, C 2 %.
- Stress multipliers on the hidden overload and foaming flags: ×4 and ×3 online, ×1.5 lab.
- A **plant-level historian dropout** shared by all online sensors, because in the anchor whole rows
  drop together. Tier C 0.000966 is measured; A and B are assumed.
- Composite online loss: 8.92 / 4.48 / 2.09 %.

**Streams.** One keyed stream per sensor block, `SeedSequence([obs_seed, sha256(name), block])`.
A shared instrument therefore reads identically at every tier that carries it, and the visible
record is prefix-stable.

### 5.7 Fault injection (`sim/faults/`)
17 fault types, each with a unit, an admissible range and a **layer**:

| Layer | Types |
|---|---|
| influent | feed_mislabelled, unrecorded_delivery, moisture_drift |
| parameter | ammonia_inhibition_shift (× K_I_nh3, 0.1–10), hydrolysis_regime_change |
| state | biomass_misinitialised |
| structure | omitted_sao, omitted_precipitation, imperfect_mixing |
| observation | gas_meter_scale, ph_electrode_drift, ch4_analyser_flatline, sensor_noise, random_gaps, informative_missingness |
| workflow | tool_failure, adversarial_log_note |

- Parameter faults split the integration into segments at onset.
- **The fault layer has its own seed**, so a faulted run differs from its clean twin only by the
  fault (tested).
- The card's fault table is generated from code and compared verbatim by a test.

### 5.8 The run harness (`sim/run/`)
**Flow:** plan → hidden geometry → influent → equalisation → **400-d burn-in** → truth in segments
→ channels → tier mask → notes.

Health check after 30 settling days: median pH ≥ 6.5 and mean CH₄ ≥ 0.55. Runs are labelled sound
or soured.

**Layout (ruling H1, 2026-09-04):**

| Tree | Contents |
|---|---|
| `runs/<id>/` | observations, a **redacted** manifest (built by allow-list), the visible `calls.jsonl`, and later the workflow outputs |
| `truth_store/<id>/` (separate top-level) | full manifest, parameters, influent, fractionation, geometry, states, channels, faults (the answer key), full `calls.jsonl` |
| `truth_store/` root | `index.jsonl` and a 0600 secret `salt` |

**Leak controls, each added after a review found a route:**
- run id = HMAC-SHA256 with the per-store salt, so ids are not invertible (1,440 unkeyed hashes had
  been brute-forced);
- the redacted manifest hides scenario id, level, seeds, fault layers, target feed and baseline;
- a projected visible log;
- fixed mtimes;
- a salt-keyed generation order;
- no visible timestamps or runtimes;
- the run view returns contents, never paths, with its root kept in closures.

**Seeds.** `SeedSequence([base, plant, replicate])` gives five streams in a fixed order: geometry,
influent, fault, observation, notes. The tier is excluded. Golden values are pinned, and
determinism is tested under different `PYTHONHASHSEED`s.

**Matrix.** Truth is integrated once per (plant, scenario) and shared across tiers. 117 cells; a
regeneration takes about 13 min (786 s at the final regeneration).

### 5.9 Simulator limitations (recorded)
- No kinetic temperature correction: Plant A runs 35 °C kinetics at 41 °C.
- The truth temperature is a constant setpoint; it varies only as sensor noise.
- pK_a2 is not temperature-corrected.
- No calcite dissolution; divalent ions are not in the ionic strength.
- Headspace volumes are assumed.
- No sulfur.
- The VFA model is bistable, and a 1.52× titrimetric gap remains.
- Most observation rates are ASSUMED.
- Valerate reads negative 17 % of the time (the LOQ question is undecided).
- Plants B and C have no declared design OLR.
- One stiffness pocket in the fitted model.

---

## 6. The real-data anchor and gate G1

Sources: `docs/anchor_datasets.md`, `docs/g1_anchor_report.md`, `anchor/`, `docs/vfa_gap.md`,
and `tests/test_g1_anchor.py` (marker `g1`).

### 6.1 The dataset search (2026-09-02)
- **Where.** DataCite, the Zenodo API, figshare, the OSF API, DBFZ DataLab, GitHub, and the
  proposal's §8 leads. 17 candidates were characterised. Publishers such as MDPI, IWA and
  ScienceDirect could not be read through the egress policy.
- **Chosen: Muscatine WRRF.** Schroer & Just 2024, doi 10.25820/data.006715, **ODC-By 1.0**:
  - daily lab data 2020–2023 (1,103 rows) and 1-minute SCADA 2022–2023 (500,400 rows, 88.8 MB);
  - a full-scale 5.5 MGD plant with two 485,000-gal (≈ 1,836 m³) CSTRs at 36 °C;
  - feeds: primary sludge, TWAS, trucked HSW and FOG.
  - The companion MIT-licensed forecasting code provides a published MLP baseline: adjusted R² 0.78, MAPE 13.4 %.
- **Also fetched: ILRI farm-scale digesters** (CC BY 4.0), used for Tier-A sampling irregularity only.
- **Rejected or not available:**
  - Tisocco et al. 2023/2024/2026: an exact Plant A match, but the data are not deposited.
  - Dittmer 2021 and Meola & Weinrich 2025: data not available.
  - Chiguer 2026: no licence.
  - BSM2: simulated, so it is ring-test use only. A test forbids simulated data as an anchor.
  - Eight others: not CSTR, not daily, not full scale, or not time series. ecoTrace Kiambu is kept as a Phase-3 candidate.
- **Manifest.** `anchor/MANIFEST.json` records URL, SHA-256, size and kind for 3 fetched datasets
  and 12 `not_fetched` entries with reasons.
- **Fetching.** `python -m anchor.fetch` streams, verifies the checksum and size, then renames.
  It honours the proxy and never disables TLS.
- **What is committed.** Only small files that may be redistributed: LABS-raw.csv (125 KB), the
  data dictionaries and the README. The SCADA file is git-ignored. A derived 60-day SCADA window
  (`anchor/derived/muscatine-scada-window.csv.gz`) plus a statistics JSON are committed so the
  noise anchor can be re-derived offline.

### 6.2 The anchoring ruling (the lead, 2026-09-02)
- **Plants B and C are dataset-anchored** to Muscatine.
- **Plant A is statistics-anchored** to Tisocco's published summaries for all of Phase 1, with no
  author data request.
- Plant A runs a reduced subset and is reported separately.
- The factorial core is **B and C only**.
- The card must use the exact phrases "statistics-anchored" and "dataset-anchored".

### 6.3 What was ingested
- **Daily records** (`anchor/ingest_muscatine.py`) are converted to SI and flagged
  `biogas_reference_conditions_known=False`: the provider never states the gas T or P.
- **Delivery statistics** cover zero fractions (overall and by weekday), indicator and amount
  lag-1, zero-run lengths, log-σ, and seasonal amplitude.
  - Pinned values: HSW zero fraction 111/1,103, mean gap 6.94 d, median 23.6 m³/d per digester.
- **Plant summary:**

  | Quantity | Value |
  |---|---|
  | pH | 7.25 ± 0.16 |
  | Temperature | 35.3 °C |
  | VFA | 1,276 ± 582 mg/L |
  | Alkalinity | 5,039 mg CaCO₃/L |
  | FOS/TAC | 0.25 |
  | Biogas | ≈ 4,220 m³/d plant |
  | SRT | 24.7 d |

- **SCADA statistics:**
  - Robust noise σ = 1.4826·MAD(Δx)/√2: biogas cv 0.0208; temperature sd 0.0524 °F (0.029 K).
  - Flatline fractions.
  - Row gaps: 19 in 347.8 d, missing fraction **0.000966**.

  These anchor `configs/observation/sensors.yaml`. **Everything else in the observation model is
  marked ASSUMED.**
- **Data-dictionary defect.** The provider's dictionary swaps the PS and TWAS VS descriptions. The
  ingestion maps by column name instead.

### 6.4 Gate G1: method
- **Tolerances are declared before comparing** (`TOLERANCES` in `anchor/compare_generated.py`).
  - Each row carries a rationale.
  - Bounds inherited from other tests are read out of those tests' literals, so silently widening
    one fails a test.
  - `test_a_tolerance_actually_bites` shows a bound rejects.
- **Influent side:** a 730-day generator draw for Plant B.
- **Output side:** a **24-run clean Plant B panel** (seeds 1000–1023, 200 d, first 30 d dropped),
  scored as medians.
- **Calibrated rows** (fitted to their own anchor column) are labelled and excluded from the match
  count (lead's ruling M1).
- **Reproducibility.** The report's generated block is recomputed by the test and compared
  verbatim. The panel runs nightly in CI and on PRs that touch `sim/`, `configs/`, `scenarios/` or
  the comparator.

### 6.5 Gate G1: history
1. **First pass (09-03).** Plant B soured (pH 4.6–5.0) on 5 of 12 seeds, so the lead declared
   "G1 not passed". Three rulings followed:
   - **Ruling 1:** a declared 65,000-gal HSW blend tank (123 m³ per modelled unit, CSTR,
     mass-conserving) in the plant contract.
   - **Ruling 2:** Plant A gets a declared adapted ammonia constant, `K_I_nh3` 0.02, and a 400-d
     burn-in.
   - **Ruling 3:** feed strong cations are calibrated to the anchor's alkalinity (HSW `S_cat` 0.03
     → 0.225), giving alkalinity 5.12 against 5.04 and pH 7.29 against 7.27.

   Either ruling 1 or ruling 3 alone fixed the souring. With both: 24/24 sound.
2. **The VFA / FOS-TAC gap.** Simulated VFA came out far below the anchor (FOS/TAC gap 17.5×).
   - **Ruling A (09-09)** replaced true VFA with a **titrimetric FOS transfer function**: the
     Nordmann/Kapp two-point titration, computed from the truth model's own constants, κ = 1.0,
     frozen, nothing fitted. The gap fell to **1.52×**. About 90 % of a titrimetric reading is
     bicarbonate carry-over.
   - `docs/vfa_gap.md` shows that no `k_m_ac` value closes the rest. The model is **bistable**:
     ×0.40 gives VFA 0.18 at pH 6.95, ×0.35 gives 10.1 at pH 4.60. The anchor lies between the
     branches.
   - Fitting κ was rejected, because it would turn the row into a calibration. Missing acids such
     as lactate are deferred to Phase 2.
   - Finding recorded: *the titrimetric convention masks VFA dynamics.*
3. **Feed chemistry consistency (09-09 → 09-10).**
   - M2: the HSW alkalinity assay was ~480× below its fed cation charge, so the visible assay
     became full charge-balance alkalinity.
   - Dissolved Ca is derived from calcite saturation (supersaturation 2.5, assumed); it is no
     longer total Ca, which was 10–30× too high.
   - Dissolved species scale with the liquor fraction.
4. **Biogas (09-11).** `biogas_mean` was 1.52–1.54× the anchor, against a band of [0.6, 1.5].
   - **Ruling 5:** HSW and FOG degradability centres set to their cited values (0.84 and 0.92, from
     0.95 and 0.98). **Answer A:** the FOG inert COD equivalent becomes 2.9. **Answer B:** the
     clean-run CH₄ margin is re-declared at 0.60.
   - Widening the band was refused: *"the width is a declaration, not a dial."*
5. **Prefix stability (rulings 6–7, 09-11 and 09-14).** Runs at different horizons must agree on
   their common prefix, so that changing a horizon does not re-roll every realisation (§5).
6. **Final regeneration at `7637f7a` (09-20):** 117/117 cells sound, 786 s. The fresh review gave
   **FREEZE**. PR #15 merged at `9f635df` on 09-21.

**No kinetic parameter or geometry was changed at any point to pass G1.**

### 6.6 G1 results (the generated block, current)
**22 of 22 independent rows pass, plus 1 calibrated row (alkalinity). 24/24 runs sound.**

| Row | Generated vs anchor |
|---|---|
| Delivery medians | PS 31.5 vs 30.3; TWAS 17.2 vs 17.4; HSW 23.8 vs 23.6; FOG 33.6 vs 33.3 (±15 %) |
| Total feed | 1.12× (the closest to its bound) |
| Organic loading rate (OLR) | 2.171 vs 1.885 (1.15×, ±30 %) |
| `biogas_mean` | 2,899 vs 2,111 m³/d per digester, **1.37×** (band 0.6–1.5) |
| pH | 7.232 vs 7.27 |
| Titrimetric VFA | 0.64× (band 0.25–4) |
| FOS/TAC | 0.65× (band 0.5–2) |

**Conditional-missingness triggers**, on the hidden state:
- **Overload:** true VFA > 2× its 30-d trailing median. It fires on B 7.55 %, C 9.82 %,
  A-unadapted 1.02 % and A-adapted 0.22 % of days. The anchor's FOS/TAC p92 exceedance is
  8.25 % / 9.18 %.
- **Foaming:** gas > 1.8× its trailing median and VFA above its trailing median. B 6.60 %.

**Finding.** On the same feed, Plant A's SAO pathway triggers 4.6–4.9× more VFA excursions than
the acetoclastic one. This was possible only because per-plant cut-offs were forbidden.

### 6.7 G1 caveats (recorded or found)
- **"22 of 22 independent" is generous.** The HSW COD row's own rationale calls it "partly
  circular"; two zero-fraction rows are trivially 0 = 0; many influent rows share bounds with the
  tests the generator was built to pass.
- **Biogas basis.** The anchor's cubic feet have an unknown basis, while simulated flow is STP dry.
  Part of the 1.37× may be basis rather than process.
- **Plant C has no output anchor**, and Plant A has no time series at all.
- **The `g1-frozen` tag was planned but never created.**
- **§8 step 3 is not built**: the forecasting-only check of the simplified ADM1 and P0 on real
  Muscatine data, against the published MLP. Step 2 (variability, missingness, noise) is done.

---

## 7. The scenario library

Sources: `scenarios/*.yaml`, `scenarios/schema.py`, `scenarios/README.md`,
`tests/test_scenario_schema.py`, `tests/test_scenarios_library.py`.

### 7.1 The schema
Pydantic models, all `extra="forbid"` and `frozen=True`:
- **`Scenario`** — `id` (pattern `^S\d+-\d{2}$`, frozen), plant, tier, level (0–8),
  `duration_days`, `truth_label` (a set over the six classes), `faults`, `correct_conclusion`,
  `budget`, `baseline` and `seed`.
- **`Fault`** — `type` (a closed enum of **17** types), `onset_day`, `magnitude` (unit fixed by the
  type in `sim/faults/schema.py`) and an optional duration.
- **`CorrectConclusion`** — `flag_sensor`, `estimate_scale_factor`, `kinetic_update_allowed`,
  `abstain_on` (validated against `configs/abstentions.yaml`), `revise_influent_mapping` and
  `recommend_structural_review`.

Validation rules:
- `none` is never combined with another label and is forbidden at Level ≥ 2.
- **A purely structural scenario may not allow a kinetic update.** This is how "Level 6 is never
  scored on parameter recovery" is enforced in the schema. The evaluator also blanks recovery at
  Levels 6–8.

Conventions:
- **Workflows never read these files.** The simulator reads the recipe and the evaluator reads the
  answer key. Run ids are opaque HMACs (§5).
- **Seeds** are 1000 + 10·level + index.
- **Horizons belong to the plant:** 200 d on B and C, 365 d on A (ruling 3, 2026-09-11, after the
  F2 de-anonymisation finding).
- **Budgets** follow ruling A, 2026-09-21:
  - simulator evaluations = allowance × 60 / 12 s → **450 / 600 / 750** for the 90 / 120 / 150-min
    cells on B and C, and **225 / 300 / 375** on Plant A;
  - assay units 2 / 4 / 6.
  - These replace the proposal's 4,000–8,000, which the wall clock could never reach.

### 7.2 The matrix
**117 cells:**
- 16 rows × 3 tiers × 2 plants (B, C) = 96;
- plus 21 Plant A cells: the Level 2–5 rows at Tier A, and the **four** ammonia rows (S5-01,
  S6-01, S6-04, S7-02) at all three tiers.

### 7.3 Every scenario
B/C rows run on Plant B by default at 200 d. Plant A rows run at 365 d.

| Id | Level: what it tests | Injection | Truth | Answer key (essentials) |
|---|---|---|---|---|
| S0-01 | 0: clean, the false-positive control. The background still has mislogs, stray deliveries, a hidden 5–15 % volume error and base-rate sensor drift and loss. | — | none | no flag, no abstention |
| S1-01 | 1: noise and gaps | sensor noise ×2, random gaps ×2 | none | as S0-01 |
| S2-01 | 2: pH electrode drift | −0.01 pH/d from d45, reset at recalibration | sensor | flag pH, no kinetic update |
| S2-02 | 2: CH₄ analyser flatline | 6 d from d90 | sensor | flag ch4_fraction; abstain `ch4_fraction_claims`, `ch4_yield` |
| S2-03 | 2: gas-meter scale error (the proposal's Appendix B example) | ×1.08 from d60 | sensor | flag gas, estimate the factor |
| S3-01 | 3: feed mislabelled | Dirichlet κ = 5 redraw of the co-substrate, d60–120 | influent | revise the mapping |
| S3-02 | 3: unrecorded delivery | 3 × median delivery at d90 | influent | flag the log, not the model |
| S3-03 | 3: wetter season | TS −30 % ramp, d30–180 | influent | revise the solids trend |
| S4-01 | 4: biomass mis-initialised | all biomass ×0.25 at t = 0 | state | no kinetic update |
| S4-02 | 4: informative missingness | conditional-loss multipliers ×3 | state + sensor | abstain `transient_response`, `peak_load_behaviour` |
| S5-01 | 5: loss of ammonia adaptation (Plant A, adapted baseline) | K_I_nh3 ×0.1 at d120 (0.02 → 0.002) | parameter | kinetic update allowed |
| S5-02 | 5: hydrolysis slowdown | k_hyd_ch/pr/li ×0.6 at d120 | parameter | hydrolysis only |
| S6-01 | 6: SAO omitted from the fitted model (Plant A, **unadapted**, SAO-dominated) | omitted_sao | structural | recommend review; abstain on speciation and pathway split |
| S6-02 | 6: precipitation omitted | omitted_precipitation | structural | review; abstain alkalinity and inorganic-carbon budgets |
| S6-03 | 6: imperfect mixing | stagnant fraction 0.30 (two-zone RTD) | structural | review; abstain effective volume and RTD |
| S6-04 | 6: **the abstention row** — the same omission on the **adapted** baseline, where SAO carries no flux | omitted_sao | structural | `recommend_structural_review: false`; abstain |
| S7-01 | 7: compound, sensor + influent | S2-01 + S3-01 | sensor, influent | both attributed, no kinetic move |
| S7-02 | 7: compound, structural + parameter (Plant A, adapted) | omitted SAO + K_I_nh3 ×0.1 at d120 | structural, parameter | partial attribution; explicit abstention |
| S8-01 | 8: tool failure | `bayes_mcmc` returns non-converged chains (p = 1), over S2-03's gas fault | sensor | flag gas; abstain `posterior_intervals` (an earned credit, ruling D2) |
| S8-02 | 8: adversarial operator note at d75 ("slower hydrolysis, raise the rates") over the gas fault | — | sensor | note treated as evidence; no kinetic update |

**Design details worth knowing:**
- **The S6-01 / S6-04 pair** (lead's ruling 1, 2026-09-09) makes abstention scorable and blocks a
  reflexive "always say structural" answer. S6-01 had been inert on a single baseline.
- **Every run carries benign operator notes** (Bernoulli per day), so the mere presence of a note
  does not reveal S8-02.
- **Level-8 rows carry an underlying gas-meter fault**, because the schema needs a non-`none`
  label. They are scored on two axes.
- **Measured pathway shifts.** In S5-01, X_sao reaches 0.60 on d298. In S7-02 it does so on d348
  (on 365 d). The 2026-09-03 claim of "0.60 in 240 d" was **not reproducible at any commit** and
  was corrected.
- **Known gaps:**
  - **One answer key per scenario, not per tier.** S2-02 at Tier A has no CH₄ analyser, so its key
    is unreachable there.
  - S4-02 on Plant A fires its triggers on < 1 % of days.
  - S5-01's injected K_I_nh3 lies **outside the fitted model's [0.2, 5] multiplier box**, so its
    parameter recovery is unreachable by any bounded update, though its attribution is not.
  - S6-02 shows no Level-6 signature at Tier B.

---

## 8. The tool registry, the jail and the budgets

Sources: `tools/` (registry, server, transport, client, sandbox, privileged, fitted, assays,
background, `impl/*`), `state/`, `configs/tools/*.yaml`, `docs/tool_registry_design.md`,
`tests/tool_contracts_v1.json`. Delivered as Milestone 4, PR #17, merged at `21424f2` on
2026-09-21; registry and tools at version "1.0".

### 8.1 Architecture: two sides, one interface
- **The privileged side.** `tools.open_registry(run_id)` is the only code that reads the truth
  store. It reads:
  - the index;
  - the full manifest;
  - the Level-8 directive in `faults.json`;
  - `fitted_extensions`;
  - `channels.npz` for assays.

  It builds a `Registry` with the scenario's budget, a keyed registry seed, the fitted model and
  the assay server. Only `privileged.py`, `fitted.py` and `assays.py` import `sim`. Importing
  `tools` does not.
- **`RegistryServer`.** One daemon thread on one AF_UNIX socket, serial by design.
  - Ops: `tools`, `describe`, `remaining`, `reserves`, `call`, `run` (read-only run-view methods
    plus the one write, `write_output`), and `llm` (only when a model gateway is attached).
  - Errors are returned without paths.
  - Writes go through `OutputSink`: plain relative names under `runs/<id>/workflows/<wf>/` only,
    ≤ 16 MB per file. `llm_calls.jsonl`, `launch.json` and `spend.json` are reserved for the
    privileged side.
- **Transport.** An 8-byte length prefix plus UTF-8 JSON. Arrays travel bit-exact as base64. The
  responses are Pydantic dumps, validated again on the client.
- **The workflow side.** A client stub is staged into the jail *as* `tools`, with
  `tools.call(name, _role=None, **args)`, `remaining()`, `reserves()`, `describe()`, `last_call()`,
  `llm()` and `tools.run.*`.

### 8.2 The jail (`tools/sandbox.py`)
**Why it exists.** Static AST checking proved insufficient across three hardening rounds on
2026-09-12. Then two live routes reached the truth:
- **The child-interpreter route.** A plain child interpreter ran `site`; the editable install's
  `.pth` resolved `sim`; and `sim.__file__` led to `truth_store/index.jsonl`.
- **Review finding B1 (DO NOT MERGE).** `/usr/bin/python3` called by name reached the host hook,
  and `/proc/<ppid>/cwd` and `/environ` leaked the repository.

**How it works.**
- `unshare --user --map-root-user --mount --pid --fork --kill-child` builds a private tmpfs root,
  switched in with `pivot_root`. It holds:
  - `/usr/lib`, read-only, with every site-packages masked;
  - the interpreter binary alone;
  - a dedicated venv (numpy, scipy, pydantic, pinned to the host's versions);
  - the box (stub, script, socket);
  - four devices and a fresh `/proc`.
- The bootstrap runs `python -I -S`. It refuses to start if any of `sim`, `scenarios`, `anchor`,
  `eval` or `state` resolves, or if `tools` is not the stub. It also spawns a plain child of every
  interpreter it can find and refuses if any of them resolves a forbidden module.
- **It fails closed:** there is no unjailed mode.
- **Package staging** (option A, 2026-10-26, used by P2): opt-in via a marker file. It refuses
  symlinks, non-`.py` files and forbidden names, and records the staged tree's sha256 in a
  privileged `launch.json`.
- **CI** relaxes the Ubuntu 24.04 AppArmor user-namespace restriction. Since 2026-11-02 (PR #47) it
  also installs `/sbin/pivot_root`, after the runner image lost it.
- **Stated limits:** not a kernel-exploit boundary; no CPU or memory limits; a container is
  deferred to release.
- **Found for this report:** there is **no network namespace** (`--net` is absent). The jailed
  process has no DNS, but can reach TCP by IP address and abstract unix sockets. No test covers
  network egress, and the limitation is not stated anywhere.

**The isolation tests.**
- `tests/test_truth_isolation.py`:
  - a structural check;
  - an **allow-list** AST checker over `workflows/` (stdlib, numpy, scipy, pydantic, `tools`,
    `workflows`, `state.run_view`, with dynamic imports, dunders and obfuscated literals denied),
    exercised on synthetic violators first;
  - an adversarial runtime suite against the loader, **with a negative control**.
- `tests/test_tool_sandbox.py` runs a jailed script that tries every route (imports, opens, tree
  walks, child interpreters, `/proc/<ppid>`, the repository, the run store) and asserts each one
  fails. Its negative control, in the same process, makes real tool calls and reads.

### 8.3 The tool catalogue
19 frozen tools, plus `declared_background` added beside them. Cost is the declared bound on
simulator evaluations. Every tool has a known-answer test (`tests/test_tools_known_answers.py`).

| Tool | Method | Cost | Known-answer test |
|---|---|---|---|
| `describe_model` | names, defaults, bounds, units, outputs | 0 | Level-6 interface = Level-0 |
| `simulate` | one evaluation; `initial_state`, `biomass_scale`, `t_end` | 1 | reproducible; near truth on clean |
| `feed_loads` | daily loads of the feed log through the declared catalogue | 0 | 0.6–1.4× true COD |
| `data_qc` | flatline (≥ 4 equal), spike (> 5·1.4826·MAD vs rolling median 7), drift (Theil–Sen, excursion/sd > 3), event missingness (ratio > 2), units, monotone time | 0 | planted defects found |
| `mass_balance` | COD closure (gas × CH₄ × 2.857 + effluent COD; admissible ≤ 0.20), N closure in [0.05, 0.65], charge consistency of the implied strong-ion difference | 0 | balanced closes; unrecorded delivery opens |
| `gsa_morris` | own implementation, Morris/Campolongo trajectories, p = 4; μ, μ*, σ | r(k+1) | linear-additive; interaction σ > 0 |
| `gsa_sobol` | Saltelli 2010 design on scrambled Sobol; Jansen first/total; Saltelli 2002 second order; bootstrap CIs | N(2k+2) | Ishigami closed form; scipy cross-check |
| `profile_likelihood` | Raue 2009; grid ≤ 21; warm plus LHS multistart; χ²₁(0.95) threshold; flat detection | n_grid·n_starts·(nfev+1) | flat ridge; OLS interval |
| `fisher_info` | JᵀJ by central differences; eigen-decomposition, null directions, condition number; correlations from a regularised inverse | 2k | rank-one FIM, correlation −1 |
| `fit_lsq` | scipy `least_squares` (trf), LHS multistart; covariance σ²(JᵀJ)⁻¹ | n_starts(nfev+2k+1)+2k | recovers OLS |
| `fit_de` | scipy differential evolution (best1bin, no polish) | (g+1)·pop·k+2k | recovers OLS |
| `fit_cmaes` | Hansen `cma` | max_evals+pop+2k | recovers OLS |
| `bayes_mcmc` | emcee ensemble; Gaussian, heteroscedastic or AR(1) likelihood; **split R-hat and Stan-style multi-chain ESS**; converged = R-hat < 1.1 and ESS > 100 | walkers·(steps+1) | N(ȳ, σ²/n) posterior; nominal coverage |
| `filter_enkf` / `filter_mhe` | stochastic EnKF with parameter augmentation; moving-horizon estimation with arrival cost | n_ens·n_steps | tracks a Kalman filter; recovers a slow parameter |
| `residual_diag` | ANOVA η² per covariate; lag-1 ρ; Durbin–Watson; runs test; trend; `most_explanatory` | 0 | names load; white noise unstructured |
| `voi_assay` | nested Monte Carlo expected information gain (Ryan 2016) per unit cost | n_outer+n_inner | Gaussian closed form |
| `validate` | MAE, RMSE, nRMSE, bias; coverage 50/90; interval score; CRPS; constraint violations | 0 | hand-computed; Gaussian CRPS |
| `request_assay` | truth channel plus the lab sensor's noise, keyed by day | 0 evaluations; 1–2 units | — |
| `declared_background` | per (plant, tier) null band (§12) | 0 | run-independent, with negative control |

**Library choices.** emcee and cma are dependencies. SALib was rejected for its weight (pandas,
matplotlib), so Morris and Sobol are hand-written. emcee's own ESS was rejected because it reports
about n·m for walkers jittering in place.

**The filters are unusable in practice.** No run registers a state-space model, and the ADM1
state-space adapter was never built. No workflow calls them.

### 8.4 The fitted model (`adm1_fitted`, `tools/fitted.py`)
- **What it is.** BSM2 ADM1 plus the plant's truth-model extensions *less* those a Level-6 row
  removes, applied silently by the privileged side.
- **What it is fed:**
  - the operator's **feed log** through the **declared** catalogue at catalogue solids, day by
    day (sample-and-hold);
  - Plant B's declared blend tank;
  - the declared geometry;
  - a 400-day burn-in at the evaluated parameters, counted inside the one evaluation.
- **Calibratable parameters:** 20 base-ADM1 **multipliers** of the BSM2 defaults.

  | Group | Bounds |
  |---|---|
  | disintegration, hydrolysis | 0.25–4 |
  | k_m, K_S, K_I_h2_pro, k_dec | 0.33–3 |
  | K_I_nh3 | 0.2–5 |
  | Y_ac, Y_h2, f_li_xc | 0.5–1.5 |

  The parameter list and the outputs are identical on every rung, so the interface cannot leak the
  scenario.
- **What it deliberately lacks** — the source of the "background":
  - the true fractionation and its drift;
  - the true solids;
  - unrecorded deliveries;
  - the active-volume error;
  - per-feed inert N;
  - the Level-6 mechanism.
- **Speed.** About 0.8 s per evaluation at 40 d; 11–12 s at 200 d; one stiffness pocket of
  274–290 s, recorded and not patched because the solver config is frozen with G1.

### 8.5 Budgets
- **What the registry budgets** (from the scenario): simulator evaluations, wall clock and assay
  units. LLM turns, tokens and USD are enforced in the privileged gateways (`tools/llm.py`,
  `tools/p2_live.py`), not in the registry.
- **The counting rule:** one model call on one parameter vector = one evaluation, burn-in included.
- **Enforcement, in order:**
  1. Pydantic validation.
  2. **Pre-refusal** when the wall clock is spent, the declared cost exceeds the evaluations left,
     or the assay price exceeds the units left. This is logged as `budget_exceeded`, and nothing
     runs.
  3. A shared `EvaluationMeter` that raises *before* charging, so an overrun stops mid-call and is
     charged for what it made; its result is discarded. `cancel()` stops an in-flight call on a
     kill.
- **Wall clock** runs from `registry.open`, so agent thinking counts. It is checked only at call
  start; the runner's timeout is the backstop. **P2 has no wall-clock limit** (ruling of
  2026-10-13).
- **Reserves** (ruling B). The verifier's 80 evaluations and 1 assay unit sit on top of the
  envelope. Untagged calls keep the whole envelope. The per-tag spend is in `spend.json`.
- **The cost of record comes from the meter, never from the state's self-report.**
- **Assays.** Eight priced assays (DESIGN values): alkalinity, VFA total, TAN, digestate TS and VS,
  and free ammonia at 1 unit; COD at 2; VFA speciation at 2 units with 3 d turnaround. Draws are
  keyed by (seed, assay, channel, day), so repeating a request cannot average the noise away.
  Turnaround is reported, not enforced.

### 8.6 Logging and provenance (`state/provenance.py`)
Every call writes two records.
- **Visible** `runs/<id>/calls.jsonl`: seq, name, version, args_hash (the first 16 hex characters
  of a sha256 over canonical JSON; arrays as shape, dtype and hash), outcome and detail.
  - No timestamps, runtimes or counts. Earlier versions leaked the generation order and marked the
    two-zone row.
  - An injected failure is written `ok`; any `converged=False` result gets
    `detail="not_converged"`.
- **Truth-side** `truth_store/<id>/calls.jsonl`: the full record with time, runtime, evaluations,
  assay units and the true outcome.
- Every envelope returns the visible line's seq, args_hash, version and outcome, so the task state
  matches the log line for line.
- **Argument values are not logged**, only their hash. This deviates from proposal §6.2, which says
  the arguments are logged.

### 8.7 Task state and abstentions
- **`state/task_state.py`** (§6.6) records, frozen and `extra="forbid"`:
  - data quality per sensor and the mass balance;
  - the classification (label from the six classes + `abstain`, secondary labels, confidence, rule,
    and evidence items tied to `call_index`);
  - the screening trail and the approved subset;
  - residuals;
  - actions (with seq and args_hash) and tool failures;
  - budget, validation, assay checks and abstentions;
  - the final result (with interval method);
  - the plan;
  - notes seen (day, author and length only);
  - free-text annotations, which never replace structured fields.
- **Writing it.** The workflow writes JSON through `run.write_output`; the privileged runner
  validates it.
- **The abstention vocabulary** (`configs/abstentions.yaml`, ruling A3): 15 terms plus two
  templates.

### 8.8 Freezing
- `tools/impl/` is frozen. `tests/tool_contracts_v1.json` pins every frozen tool's input and output
  field names and its version.
- The numerical freeze is behavioural: P0's two-head test, plus a bit-equal same-seed test on five
  tools.
- **Additions made after the freeze**, each claimed byte-neutral for P0 and P1:
  - `declared_background`;
  - reserves and the role tag;
  - package staging;
  - `wall_clock_enforced`;
  - `run.write_output`;
  - meter fields on truth-side records.

### 8.9 Defects found for this report (not recorded in the decisions log or milestones)
Each was reproduced or read in code by the reviewer of this area; three were re-confirmed in code
for this report.

| # | Defect | Effect |
|---|---|---|
| a | **Declared cost bounds undercount `least_squares`-based tools.** SciPy's `trf` does not count finite-difference Jacobian evaluations against `max_nfev`. Measured: `fit_lsq` (k = 5, 2 starts, 20 nfev) declared 72, charged 112 | The pre-refusal can pass a call that then overruns and ends as `budget_exceeded`, its result discarded. The design's "never more than the declared bound" does not hold, and no test asserts actual ≤ declared. The same applies to `profile_likelihood` and `filter_mhe` |
| b | **`profile_likelihood` raises at `n_starts=1`.** `latin_hypercube(0, …)` on an empty sample. Re-confirmed in code | P0's config sets `profile_starts: 1`. It is latent, because P0's plan never reaches profiles within the ruled budgets, and the known-answer test uses 2 starts |
| c | `filter_mhe` reports the cumulative registry meter as its own `n_evaluations` (91 against a charge of 41) | Cosmetic: the log's charge is computed as a delta and is correct |
| d | **The Level-8 injected MCMC failure is identifiable from its output.** It returns the config's 8 walkers × 40 steps whatever was asked, `n_evaluations=0`, `log_prob_max=NaN`, and an unchanged budget. Re-confirmed in code | The project took care to make the *log line* indistinguishable, but the payload reveals the S8-01 row to a workflow that inspects it |
| e | `data_qc` threshold overrides are unbounded, though the config says workflows "may tighten but not loosen" | A workflow can loosen QC |
| f | `bayes_mcmc` raises n_walkers to 2k when fewer are asked, but charges the requested count in the pre-check | Pre-refusal undercount |
| g | **The jail shares the host network namespace** (no `--net`). Re-confirmed in code | Not a truth leak in itself (the truth is not served on the network), but an unstated limit |
| h | `mass_balance` accepts `charge_in_keq_d`, `V_liq_m3`, `T_op_K` and `pK_a_co2` but never uses them | Misleading interface |

**Documentation drift in this area:**
- The design note says newline-delimited JSON frames; the transport uses length prefixes.
- The design note lists a `configs/tools/budget.yaml` that does not exist.
- The Fisher docstring says pseudo-inverse; the code uses a regularised inverse.
- The MCMC docstring says emcee ESS; the code uses a Stan-style ESS.
- The server docstring omits the `reserves` op.
- `validate` is "verifier only" in the proposal but not role-restricted in the registry. It is
  restricted in P2's role views.

---

## 9. P0: the scripted baseline

Sources: `docs/p0_design.md`, `workflows/p0_scripted/pipeline.py` (1,845 lines),
`configs/workflows/p0.yaml`, `tests/test_p0_pipeline.py`, `tests/test_p0_freeze.py`, and
`reports/p0_*`.

### 9.1 Principle and freeze
- **Rule 5:** P0 is built and frozen before any agent code, and it is never weakened to make agents
  look better. It is meant to be "what a competent engineer would script today".
- **Approval.** The lead approved the rules on 2026-09-21 as proposed at `5099c18`, with the
  amendments of rulings A (budgets) and B (thresholds). PR #18 merged at `77508ca`.
- **The only later code change is A1** (2026-09-24): residual-derived evidence now cites its tool
  calls. No rule, threshold or verdict changed.
- **How the freeze is guarded.** `tests/test_p0_freeze.py` (marker `p0_freeze`, about 2 h) runs
  S0-01 B/A at the base and at the head **back to back on the same machine**. It requires an equal
  label, equal `calls.jsonl` projections and equal normalised states.
  - It replaced a stored golden that proved machine-bound: 202 against 271 evaluations, because
    P0's runtime guard reads the measured evaluation rate.
  - Recorded passes: 09-29, and 10-03 (7,685 s).

### 9.2 The algorithm
Every threshold, size and seed is in `configs/workflows/p0.yaml`. The calibration window is
`[0, 0.75 T)`; the hold-out is the last quarter, never read before validation.

0. **Read.** `describe_model`, `feed_loads`, and a `simulate` at the defaults.
1. **QC (`data_qc`) on every sensor.**
   - A flatline of ≥ 3 d quarantines the window, flags the sensor (R1a) and abstains on
     `<sensor>_claims`.
   - Spikes are dropped.
   - Drift flags the sensor only beyond 1.0 × its *declared* drift bound.
   - Informative missingness is recorded and adds `missing_transient`.
   - A sensor needs ≥ 8 calibration samples.
   - Weights come from the declared noise: sd = √((cv·|v|)² + sd_abs²), floored at 2 % of the
     median.
2. **Mass balance.** COD, N and charge over 30-d windows. Three or more inadmissible windows are
   R2 evidence.
3. **Morris** on all 20 interface parameters: r = 4 (84 evaluations), seed 101. Keep μ*/max ≥ 0.10,
   at most 4.
4. **Sobol** on that subset: N = 8 with second order (80 evaluations), seed 102. Keep ST ≥ 0.05,
   at least 2.
5. **Identifiability.** `fisher_info` drops a parameter whose CRLB sd > 0.5 × its bound width. The
   survivors are the *approved subset*. Profiles (grid 5) never fit the ruled budgets (they cost
   1,005 evaluations).
6. **Fit.** `fit_lsq` (1 start, 40 nfev, seed 104), then `fit_de` (pop 4, 2 generations, seed
   105); the lower χ² wins. Fisher intervals are σ²(JᵀJ)⁻¹, z = 1.645.
7. **MCMC.** `bayes_mcmc` (emcee), 8 walkers × 10 steps, Gaussian likelihood, seed 106.
   Non-convergence (real or injected) is a recorded failure: Fisher intervals stand, P0 abstains on
   `posterior_intervals`, and there is no retry.
8. **Residual diagnostics** per channel: bias_z, rmse_z, the best step split (step_z, step_day),
   and early/late bias (30 d). `residual_diag` adds serial structure and the most explanatory
   covariate with its η².
9. **Second pass.** If a single offending channel exists, exclude it and refit once.
10. **Assays.** At the day of the largest gas residual: VFA speciation, or else alkalinity, then
    TAN; at most 2 requests. A disagreement above 3 σ is structural evidence only.
11. **Validate.** An ensemble of 8 draws on the hold-out, falling back to 2 and then to a point
    prediction.
12. **Attribute** (`classify`, a pure function). The rules run in the order R1 sensor → R2
    influent → R5 state → R4 parameter → R3 structural → R6 none. The first rule to fire is the
    primary label; the others become secondary labels.

    | Rule | Fires when |
    |---|---|
    | R1 | a QC flag; or exactly one channel with \|bias_z\| ≥ 3 or step_z ≥ 3, all others clean, balance admissible |
    | R2 | ≥ 3 inadmissible COD windows, or a feed covariate with η² ≥ 0.15 |
    | R5 | early \|bias\| ≥ 3 and late \|bias\| ≤ 1.5 |
    | R4 | ≥ 2 channels with step_z ≥ 3 within 30 d of each other, balance admissible, no feed structure |
    | R3 | no common change point; ≥ 2 channels with rmse_z ≥ 2, serially structured and explained by load or time |
    | R6 | nothing else fired |

    Confidence is 0.8 when the fired rules agree, 0.5 when they disagree, 0.6 for R6.
    `kinetic_update` is set for both `parameter` **and `none`**, which is why a `none` on a faulted
    cell scores a false kinetic update.

**Plan sizing.** Sizes are deterministic, at an assumed 12 s per evaluation, with fallback ladders
(halve Morris, then switch to Fisher only; skip Sobol; halve MCMC, then skip it). A single runtime
guard at the *measured* rate is the one non-deterministic element. It is why MCMC was skipped on
26 sweep cells and never ran on Plant A.

### 9.3 Pilot (10 development cells)
- **Round 1, at the original budgets (4,000–8,000 evaluations).**
  - The wall clock bound first: only 4–7 % of the evaluations were used.
  - MCMC was never reached.
  - **2/10 labels right.** Two rule paths fired on the plant's background on 8 and 9 of 10 cells.
- **Rulings A and B (09-21)** followed:
  - budgets re-declared as 450/600/750;
  - a smaller plan that reaches MCMC;
  - the R5 QC-missingness path dropped;
  - R1c folded into R1b;
  - `balance_windows_min` 3;
  - `step_day_tolerance_d` 30.

  Two conditions came with them:
  - (i) these are development cells; the held-out variants are the evaluation set;
  - (ii) **the background misfit is a recorded benchmark property, not to be tuned away**, and a
    `none` where P0 cannot resolve a fault is the honest baseline.
- **Round 2: 5/10 right, no false fault.** MCMC was reached on 8/10 and converged on none (R-hat
  1.9–96). The S8-01 injected failure was handled by rule.
- **Scored pilot** (evaluation container; MCMC reached on 4/10):
  - 5/10 exact;
  - false drift 1/9;
  - false kinetic update 5/5;
  - gas 90 % coverage 0.00–0.08.

### 9.4 The Level 0–5 sweep (PR #20)
**Setup.** 78 cells, single seed, three in parallel, 31 h 20 min wall time, 100.4 runner-hours,
23,688 evaluations (14.2 s/eval on B, 13.8 on C, 25.4 on A). **78/78 completed** inside their
allowances. MCMC was reached on 52 cells and converged on 0.

**Exact attribution: 17 of 78 (22 %).**

| Level | Exact | False kinetic drift | False kinetic update |
|---|---|---|---|
| 0 clean | 5/6 | 1/6 | – |
| 1 noise | 5/6 | 2/6 | – |
| 2 sensor | 5/21 | 7/21 | 14/21 |
| 3 influent | **0/21** | 8/21 | 17/21 |
| 4 state | **0/14** | 4/14 | 13/14 |
| 5 parameter | 2/10 | – | – |

**By tier** (exact): A 7/32, B 6/23, C 4/23. False drift at Tier C: 0/20.

**Overall:**
- 44 of 66 faulted cells read `none`; 2 false faults on clean cells.
- False drift 22/68, always `k_dec_X_ac`, `k_m_ac` or `k_m_h2` pushed to a bound.
- False kinetic update 44/56.
- **Correct abstention 0/7**, a vocabulary gap.
- Unsupported claims 13/273, then **0/273 after A1**.
- Mean gas 90 % coverage **0.04**.
- 136/204 parameter intervals cover the truth; 64 estimates sit at a bound.
- The sensor flag is correct on 4/21 sensor cells.
- QC flags `digestate_ts` at Tier C on both clean and faulted cells.

**Recorded P0 limitation (the lead: no change).** S2-01 at Tier A ends with an *empty objective*.
QC excludes pH, then the second pass excludes gas, so the refit and validation are refused.

**Post-baseline rulings (2026-09-24, "Merge and implement your recommendations"):**
- **A1:** evidence must cite its calls.
- **A3:** one controlled abstention vocabulary (`configs/abstentions.yaml`): 15 literal terms plus
  two templates, 47 terms in all. Synonyms are decided by meaning before any re-score. Two scenario
  spellings were rewritten in place, with byte-identity proofs for every visible file.
- **A4:** 15 cells re-run and all 78 re-scored. No label moved; exact stays 17/78.
- **D1:** `abstention_extra` and `abstention_precision` measure over-abstention. The P0 baseline has
  extra 2.13 and precision 0.011.
- **D2:** the S8-01 `posterior_intervals` credit must be **earned** from the logs (the last logged
  `bayes_mcmc` call failed), never from the workflow's self-report.
- **D3:** `claim_sources` means "the call the number rests on".
- **The P1 prompt rule:** no scenario ids, no P0 rule ids, no label frequencies, no per-cell
  outcomes in any prompt.

**Not run for P0:** Levels 6–8 (beyond two pilot cells), seeds, and the held-out variants.

---

## 10. The evaluation suite

Sources: `eval/` (12 modules), `configs/eval.yaml`, `docs/eval_design.md`, `tests/test_eval_*`.

### 10.1 Architecture
- **Entry point.** `python -m eval` writes the per-run table (129 columns), and a per-cell
  aggregate when several runs share a cell.
- **Inputs are records only:**
  - the truth-store manifest;
  - `faults.json` (the answer key);
  - `parameters.json`;
  - both `calls.jsonl` logs;
  - `state.json` and `summary.json`;
  - the optional `admissible.json`.

  Free text (`report.json`, annotations) is never read.
- **Evidence trail.** An evidence item names a `call_index`. That maps to the state's action, then
  to the visible log line with the same seq, name, args hash and outcome. If any link fails, the
  claim is unsupported.
- **Isolation in both directions:**
  - the rule-1 checker forbids any workflow from importing or reading `eval`;
  - `eval/` imports only from an allow-list;
  - the jail makes `eval` unimportable in a workflow process.
- **Thresholds.** Every threshold is in `configs/eval.yaml`.

### 10.2 Metrics
**Family B: attribution and epistemic discipline**
- **Exact attribution.** The final label set equals the truth set. Partial credit is the Jaccard
  overlap. `primary_in_truth` is also reported.
- **Admissible attribution.** The primary label is in A ∪ truth, where A is the
  distinguishability set (§11.2). It only ever *adds* credit.
- **False kinetic drift.** In scenarios without a `parameter` label, any `group: kinetics`
  parameter (17 of 20) whose estimate falls outside the central 90 % of its uniform prior box.
- **False kinetic update.** A kinetic update offered where the answer key forbids it.
- **Correct abstention.** Exact-name match on the controlled vocabulary; also fraction, extra and
  precision (D1). The D2 credit must be earned.
- **Unsupported claims (D3).** An evidence item is unsupported if:
  - it names no calls; or
  - a named call does not resolve to an `ok` line; or
  - none of the resolved calls is an allowed source tool for its value key or rule.

  Unmapped claims count as unsupported by default.
- **Flag correct.** The flagged sensor equals the key.

**Family A: calibration and prediction**
- Channels: gas, CH₄ fraction, pH, titrimetric VFA, TAN.
- Metrics: MAE, RMSE, nRMSE, bias, coverage at 50/90 %, interval score at α = 0.1 (Gneiting &
  Raftery), CRPS (energy form), and a posterior CRPS.
- Accepted only from a logged `validate` call on the frozen window.
- Mass/charge balance error.
- Parameter recovery against the truth's *last* segment, **Levels 0–5 only**.

**Family C: efficiency**
- Simulator evaluations, assay units and calls come from the **registry meter** on the truth-side
  log, never from the workflow's self-report.
- Wall clock, log span, tool runtime and tokens.
- `self_report_mismatch` flags a state that misreports its own spend.
- Uncertainty reduction per assay unit (RQ4).

**Family D: reliability**
- Completed, invalid actions, budget refusals, tool errors, injected failures, retries (repeated
  name and args hash), fallbacks and guard trips.
- Variance across seeds is the aggregate's sd.
- A launched run with no valid state is a **miss in the denominator**.

**Aggregate**
- Grouped by (scenario, plant, tier, workflow).
- Mean, sd, and a percentile-bootstrap 90 % interval (2,000 resamples, seed 20260922).
- Every committed aggregate is single-seed, so its intervals are empty.

### 10.3 What is not built
- **Family E (ablations)** has no evaluator code.
- **The statistical plan** of proposal §7 is not implemented: mixed-effects models with scenario
  and seed as random effects, paired within-cell comparisons, bootstrap effect sizes. No power
  analysis exists. `reports/p2_power/` is a code-only floor, not statistical power.
- **Pre-registration is not filed.**
- **Family A verifies but does not recompute.** The prediction series is not in the record, and
  the window checked is the state's own declared one. Proposed fix: persist `validate`'s window and
  output on the truth side.
- **`verifier_rejections` is unwired.** It counts records named `verifier.reject`, and nothing
  writes one (verified for this report with a grep over `workflows/` and `tools/`). H6 needs this
  metric.
- **Latent issue, found for this report.** `runs/<id>/calls.jsonl` carries no workflow field, and
  several workflows can run on one run. Families C and D take the records after the *last*
  `registry.open`, and the D2 credit scans *all* visible `bayes_mcmc` lines. Scoring two
  workflows that ran on one run could therefore cross-charge cost and credit. The pilots avoided
  this with separate stores per arm; nothing in the code enforces it.
- `completed` is half self-report: the state's flag AND exit code 0.

---

## 11. Validity studies around P0

These ran after the sweep, on the lead's ruling of 2026-09-24. The question was whether P0's 22 %
reflects a broken harness, a hard problem, or an indistinguishable record.

### 11.1 The positive-control ladder (PR #23; pre-registered in `docs/positive_control.md`)
Each rung removes one handicap on cells P0 missed. Pass criteria were written before any run.

- **R1, budget:** 3× and 10× the evaluations and wall clock.
- **R2, the true feed:** the visible feed log is rewritten to the true delivered mass, keeping the
  injected fault. Cells: S3-02 at B/C × tiers B/C. Negative controls: the composition faults S3-01
  and S3-03.
- **R3, the candidate set:** a new hook, `screening.force_include`, forces the fault's parameters
  into the fit.

| Rung | Verdict |
|---|---|
| Hook-off identity check | Passed: 6/8 identical; 2 differ only on the MCMC wall-clock guard |
| R1 ×3 | **Fail** (as predicted): 0/10 parameter and 0/4 sensor/state cells moved; 8 cells used the same evaluations at 3× as at 1× |
| R1 ×10 | No move: 5–11 % of the budget used |
| R2 | **Fail**: 0/4 cells and 0/4 controls moved; the feed was exactly true on all 8 |
| R3 | **"Not run" as registered**: P0's own guard refused the larger fit on 2 of 10 cells, so the parameters were fitted on 8/10 against a criterion of 10/10. On those 8: 0 exact moves; recovery improved on 4 S5-02 cells |

65.7 runner-hours. **Conclusion: no lever changed any label where a fit ran.** The remaining
explanations are P0's attribution rules, feed *composition* (a composition-exact R2 is designed but
not built), and distinguishability.

### 11.2 Distinguishability (PR #25; `docs/distinguishability.md`, `distinguish/`)
**Purpose.** For each Level 0–5 cell, compute the **admissible label set** A: the labels whose best
explanation of the visible calibration-window record is statistically as good as the best.

**Method v4.** The coordinator's decision, after v1–v3 failed in review. Under v3, a
default-parameter null made `sensor` the only admissible label on clean cells.
- **Reference.** Every class starts from the **truth simulation with the injected fault removed**,
  reproduced exactly, and adds one candidate from a fault library:
  - **sensor:** scale, offset or ramp; flatlines;
  - **influent:** unrecorded delivery, fractionation redraw, TS ramp;
  - **state:** biomass × 0.1–4;
  - **parameter:** change points on K_I_nh3 or k_hyd;
  - **structural:** SAO, ionic strength or carbonate switched off. Precipitation cannot be switched
    off without a `sim/` change.
- **Likelihood.** The observation model's own: white noise plus the drift-walk covariance at each
  candidate's level, with flatline flags. The data are cut at P0's calibration end.
- **Score.** Deviance + a Bonferroni χ² penalty + 2 ln N for the search. A label is admissible
  within a margin of 2 (10 for sensitivity).
- **Calibration.** `none` is admissible on 0.9825 of 400 records drawn from the model's own noise.
  Under AR(1) noise this falls to 0.96 at ρ = 0.3 and 0.79 at ρ = 0.6, a stated limit for real
  plants.
- **Scope.** This is **explicitly an optimistic upper bound**. S4-02 cannot be represented.

**Results** (78 cells, 19.7 runner-hours):
- **Every admissible set is a singleton.**
- **The truth is admissible on 60/78 cells.** On the other 18, no workflow could be expected to
  name the truth from the calibration window:
  - S2-02 at Tier A, ×3 (no analyser);
  - S3-02 A/A;
  - **all 7 S5-02 cells** (the d120 shift is invisible by d150);
  - S4-02, ×7 (not representable).
- **P0's second score: 25/71 admissible against 17 exact.** All 8 gains are cells where the record
  admits only `none`.
- **P0's 43 decisive misses are P0's own.**

### 11.3 The F2 horizon study (`docs/f2_horizon_report.md`, §1–§25)
**F2 was a finding in the final G1 review.** The public `duration_days` partitioned the ladder:
180 d for Levels 0–4 and 8, 240 d for Levels 5–7. Together with a timestamp leak (F1), this
amounted to de-anonymising the scenarios.

The investigation found and fixed, in order:
1. **The SAO-takeover claim was not reproducible.** At 240 d, S7-02's structural half was close to
   absent.
2. **The influent generator was not prefix-stable.** It drew `n_days`-long blocks from one stream,
   so every horizon re-rolled the panel and `biogas_mean` jittered by ±5 %.
3. **`biogas_mean` sat above its band**, which led to ruling 5 (literature degradability).
4. **Rulings 3–7:**
   - per-plant horizons (B/C 200 d, A 365 d);
   - S7-02 kept at onset d120;
   - a fixed 200-day reference window for derived quantities;
   - every visible stream keyed `SeedSequence([seed, key, block])`.
5. **A regeneration made while CI was red was voided.**

The final state is 117/117 cells sound and the record prefix-stable on both the truth and the
visible side.

---

## 12. The declared background and the null rule (P2 deliverables 0–1)

### 12.1 Why
The P1 knowledge audit (§13.5) showed both P1 models reading the plant's background as a fault:
- gas +11–25 % at the defaults;
- COD closure −0.14 to −0.19;
- 5–19 σ after-fit biases.

**Decision 1 (2026-09-30).** Serve a per-plant, per-tier **null reference** through a new registry
tool, rather than through prompts. No existing tool changed, so P0 and P1 are untouched.

### 12.2 The tool and the band (PR #30)
- **The tool.** `declared_background(plant, tier)` v1.0 charges no evaluations and is a pure
  function. It serves `configs/background.yaml` (FINAL, computed 2026-10-05, 16,360 evaluations).
- **Procedure.**
  - S0-01 at seeds **900001–900010**, all tiers, both Plant A baselines pooled: **120 clean runs**.
  - Each run uses P0's ruled screening (Morris 4, Fisher), then `fit_lsq` (1 start, 40 nfev).
  - Recorded per run: per-sensor `mean_z` and `rms_z` at the defaults and after the fit; COD
    closure; worst window; inadmissible count.
- **The band rule** (the lead, fixed before results). A **min–max envelope, N = 10, no margin**,
  final for this version. Development cells are not inputs; a development cell outside the band is
  a finding, never a reason to widen it.
- **A driver bug** let the two Plant A baselines share a run id, so the adapted state was never
  measured. It was fixed and 18 runs were regenerated.
- **Development-cell placement** (statistics outside the band / total): S0-01 B/A 0/12, B/B 3/35,
  B/C 12/63; S1-01 B/B 11/35.

### 12.3 The null rule (PR #31; frozen 2026-10-07)
A channel's null **fails** when all three hold:
- `mean_z` is outside the band at the defaults;
- `mean_z` is outside after the fit, on the same side;
- the after-fit `rms_z` is above the band maximum.

Scatter alone never fails a channel.

The three components:
- **NB (balance)** fails when the closure mean and the worst window are both outside on the same
  side, or the inadmissible count is above the maximum.
- **NM** fails when two or more channels fail.
- **NS** fails when exactly one channel fails and every other channel is inside.

The null is rejected if NB, NM or NS fails.

**Leave-one-out clean false-alarm rates** (each run judged against the others' envelope):

| Rule | Clean runs flagged |
|---|---|
| NB | 8/120 |
| NM | 10/120 |
| NS | 5/120 |
| **Null rejected** | **19/120 = 0.16** (Wilson 95 % CI 0.10–0.23; target < 0.20) |
| "Any statistic outside" | 0.75 |
| "Any channel mean outside" | 0.55 |

- **Frozen** by the sha256 of `scripts/null_rule_loo.py` (`fb8e8891…`) and its JSON
  (`de537c45…`).
- The design discloses that the rule was written after its author had seen the development cells'
  placement.

**Admission: each label needs a failed null case plus a coded signature.**
- **sensor:** NS on that channel, plus the coupled-channel (S1) table.
- **influent:** NB, plus a dated onset or a feed covariate with η² ≥ 0.15.
- **state:** an early/late fade, plus improvement from a biomass-scale pair.
- **parameter:** NM, with NB standing, plus a common change point on ≥ 2 **failed** channels
  **after the first HRT** (rulings of 2026-10-08, marked *development-informed*).
- **structural:** NM, plus R3 on ≥ 2 failed channels and a failed hold-out.

A failure that no signature explains concludes `none`, at lower confidence.

**Other rulings of 2026-10-07:**
- **(b) Go/no-go:** stop only if *both* S0-01 B/B seeds are non-`none` (joint false-alarm ≈ 0.03).
- **(c)** A run with no null table **abstains**, and is never counted as `none`.
- **(d)** Model: `gpt-5.6-luna`.

---

## 13. P1: the single constrained agent

Sources: `docs/p1_design.md`, `workflows/p1_single_agent/agent.py` (2,501 lines), `tools/llm.py`
(1,158), `configs/workflows/p1*.yaml` and prompts, `docs/p1_knowledge_audit*.md`,
`reports/p1_pilot*`.

### 13.1 Design
- **Same environment as P0.** One LLM agent in the same jail, with the same registry, budgets,
  record and task state. Only who chooses the next call differs.
- **"The harness plumbs, the model decides."** The harness:
  - resolves data and calls;
  - seeds every stochastic call (base 20260925 + call index);
  - **restricts every tool and view to the calibration window `[0, 0.75 T)`**, half-open;
  - rounds results to five significant figures and summarises long arrays.
- **20 tools.** 16 registry tools; `inspect_record`; and three workspace actions:
  `set_sensor_status`, `record_evidence`, `conclude`.
  - **`validate` is not an agent tool.** The harness runs it once, after `conclude`, and never shows
    the result. This was the fix for a "peekable hold-out" review finding.
  - The filters are not offered: no state-space model is registered.
- **"Constrained" means the harness refuses, before the registry:**
  - schema violations;
  - **numbers no cited call produced** (relative 1e-3, with sensor tags respected);
  - **estimates and intervals no estimator produced** (posterior only from a converged sampler;
    Fisher only at a whole optimum; a fit optimum within 1 % of an agent-narrowed bound is not an
    estimate);
  - abstentions outside the vocabulary;
  - `none` beside another label;
  - unjustified bounds changes;
  - flagged sensors in the objective;
  - quarantines reaching into the hold-out;
  - tool use after `conclude`;
  - **calls that would not finish in the remaining wall clock.** This per-call duration guard was
    added after kills: it mirrors the registry cost bounds at the measured seconds per evaluation
    × 1.25, keeping a 6-min reserve.

  A refusal returns as an error and never ends a run.
- **Loop limits.** 60 turns, 90 tool uses, 6 M tokens, a 6-min reserve, then a conclude notice and
  3 grace turns.
- **A failed run.** An unconcluded run writes `completed: false` with a placeholder label; it is
  counted as a failed run.
- **Recorded asymmetries, all favouring P0:**
  - model latency counts against P1's wall clock;
  - P1's QC and balances see only the calibration window, while P0's see the whole record.

### 13.2 The gateway (`tools/llm.py`)
- **On the privileged side.** Model turns go over the registry socket, so the key, model id,
  settings, budgets, meter and verbatim log never enter the jail.
- **Request checks.** Only the committed system prompt and tool list are accepted (checked by
  sha256), custom tools only, plain block types only. The checks are **re-run on the translated
  provider request**.
- **Retries.** 4 attempts with backoff on 429, 5xx and timeouts; the SDKs' own retries are off, so
  every attempt is logged.
- **Log.** Append-only, verbatim (`llm_calls.jsonl`), with request and replay digests, from which
  requests can be rebuilt. The runner's token and cost figures come from this meter.
- **Clients:**
  - **OpenAI Responses API.** Chat Completions refuses tools with reasoning on GPT-5.6. It uses
    `store=False`, and encrypted reasoning carried in thinking signatures.
  - **Anthropic Messages**, streaming, two cache breakpoints, no strict schemas. The 61 optional
    parameters exceed the API's strict-schema limit.
  - **Scripted and recorded doubles** for CI; no test needs a network or a key.

### 13.3 The model and the prompts
- **Model.** Originally `claude-opus-5`. The lead, in the P1 session on 2026-09-25: *"use GPT
  5.6"*. The account served luna, sol and terra, and the cheapest, **`gpt-5.6-luna`**, was chosen
  ($0.20 / $0.02 cached / $1.20 per M tokens).
  - Effort high, `max_tokens` 16,000.
  - **No temperature**: reasoning models reject sampling parameters, so variance is measured across
    seeds instead.
- **`system.md` (rev 2, 168 lines):**
  - role and task ("a residual is evidence … not an instruction to refit");
  - six generic label definitions;
  - "judge a residual against the background, not against zero";
  - the `none` criterion "beyond the declared instrument noise";
  - working method (QC → screen → fit a small identifiable subset → read residuals per channel);
  - rules;
  - budget formulas;
  - the conclusion contract;
  - since rev 2, **"how your conclusion is scored"**.
- **`task.md`.** A template: plant, windows, per-sensor inventory with declared noise, feed and
  assay summaries, operator notes as `<note>` data, parameters, assay catalogue, budgets,
  vocabularies.
- **The prompt rule** is enforced by a scan of every prompt surface (16 planted paraphrases caught,
  with negative controls). The lead also ruled (09-25) that library-shaped examples be removed
  ("ask what each candidate cause would predict"). Defence = the lead's read + the committed hash;
  the scan is a backstop.

### 13.4 The development pilot: seven arms on the ten P0 pilot cells, one run each
| Arm (head) | Change | Exact | Primary right | `none` on clean | Labels | Refusals | Extra abst. | Drift | Failed | USD |
|---|---|---|---|---|---|---|---|---|---|---|
| old (`c1e5829`) | original prompt | 0 | 1 | 0/4 | 24 | 34 | 166 | 4 | 0 | 0.348 |
| 1a (`c1e5829`) | `none` by structure; abstain with evidence | 0 | 1 | 0/4 | 23 | 23 | 101 | 4 | 0 | 0.429 |
| 1b (`4ef57c0`) | `none` margin "beyond declared noise" | 1 | 2 | 0/4 | 17 | 15 | 71 | 1 | 2 killed | 0.306 |
| rev2 contended (`996825c`) | + scoring statement; tests ran alongside | 0 | 1 | – | 11 | 15 | 61 | – | 5 | 0.278 |
| **rev2 (`cc256fd`) — frozen** | same, uncontended, with the guard | 1 | **4** | 0/4 | 16 | 54 | 92 | **0** | 0 | 0.419 |
| rev2 + expert brief (`06896dd`) | + 351-line literature brief | 0 | 3 | 0/4 | 16 | 19 | 61 | 4 | 0 | 0.474 |
| rev2 on Claude (`4801f36`) | `claude-opus-5-5` | **2** | 2 | 0/4 | 10 | 25 | 31 | 0 | 0 | **9.863** |

**Notes on the arms:**
- No arm produced an unsupported claim or a kinetic-update error.
- **The frozen arm's one "exact" (S2-01) flagged the wrong sensor.** It flagged TAN; the truth is pH
  drift.
- **The Claude arm** labelled `influent` on 9 of 10 cells.
- **The first live cell** (09-25; $0.036, 472 k tokens) found the hold-out quarantine hole.
- **The kills in 1b and the contended arm** came from `fit_lsq` calls that started with 30–60 min
  left and ran 77–134 min, because the registry checks the clock only at call start. Orphaned fits
  then kept computing 29–84 min after the kill. A container reboot also raised evaluation cost from
  11.5 to about 20 s.
  - Fixes: the duration guard, cancel-on-kill, and one process per cell.
- **The brief arm's first attempt died at turn 0 on every cell.** The client hashed `system.md`
  alone, not the joined text.

**The freeze (the lead, 2026-09-30, "Freeze P1").**
- What is frozen: revision 2 on `gpt-5.6-luna`, no brief; `prompt_sha256` `c80a3752…`.
- How: `check_frozen` runs before every run.
- Reason: rev2/luna was best on primary labels and kinetic discipline, and further revision would
  tune on the development cells. *"Every revision so far moved what the agent declines and how many
  labels it gives, not the one-sided failure (`none` unreached)."*

### 13.5 The knowledge audit (2026-09-30)
A fresh session graded the 20 rev2 runs against eight process signatures (S1–S8) on a rubric
(LC / LM / NPB / UNS).

| | luna | Claude |
|---|---|---|
| Literate-correct | 3 of 57 (5 %) | 10 of 41 (24 %) |
| Misapplied | 39 % | 73 % |
| Not process-based | 51 % | 0 % |
| Runs testing the null case before labelling | 0 | 0 |

- **Verdict:** *"Mixed, and split cleanly by arm."*
  - Claude is process-literate but read the background as an influent fault.
  - Luna labelled from QC housekeeping.
- **The null case (S7) was unreachable** because the background exceeds the declared noise. This is
  the finding that led to §12.
- **Side findings:**
  - S5-01's magnitude is outside the box;
  - S6-02 is invisible at Tier B;
  - QC labels the S4 transient as spikes;
  - P1 never called MCMC, so S8-01's tool-failure half was never exercised.

### 13.6 P1 open items
- **The evaluator scores an unconcluded run's placeholder.** One killed run scored as an exact
  `none`; the fix is applied by hand.
- MCMC inside agent-narrowed bounds has no rule.
- Harness refusals are invisible to `invalid_actions`.
- Not authorised: held-out variants, sweep scoring, a P1-vs-P0 table, further arms.
- The `declared_background` asymmetry with P2 is to be disclosed; a matched P1 arm is to be decided
  after P2's pilot.

---

## 14. P2: the procedural "decision points only" arm (PRs #31–#36)

### 14.1 Design (`docs/p2_design.md`; `workflow_version 0.3-live-wiring`)
- **Coordination is a fixed state machine:** QC → BALANCE → REFERENCE → SCREEN → FIT → PROFILE →
  PROPOSE → VERIFY, with one REVISE round on `fail`.
- **Reference fit.** The band's own procedure, so the null comparison is like-for-like.
- **Roles** (data quality, influent, identifiability, calibration, design, verification) have
  per-role tool allow-lists.
- **Typed messages:** Task, Finding, Table, DecisionRecord, Proposal, Verdict. No free text.
- **Where the model speaks: twelve decision points** (`dq.trust`, `dq.coupled`, `influent.onset`,
  `ident.subset`, `cal.split`, `verify.differential`, …).
  - Each is a one-paragraph template with a fixed schema, declared inputs and a **P0 fallback**.
  - The model chooses within bounds that code enforces. For example, `dq.trust` may narrow but
    never widen a quarantine; `verify.differential` picks from an enum of admitted labels plus
    `none` and cannot admit a label.
  - A template scan forbids label names, thresholds and ids.
- **Model and caps.**
  - `gpt-5.6-luna`, pinned field for field to P1.
  - Caps: 60 requests, 6 M tokens, USD 0.25 per run.
  - Enforced in `tools/p2_live.py`: each attempt is projected before sending, and a failed attempt
    is booked at its worst case.
  - Live is off by default: it needs `--live` plus the lead's approval record.
- **Ablation switches** exist: verifier, coordinator, each specialist, persistent state,
  self-correction.

### 14.2 The offline power run (PR #32; `reports/p2_power/`)
**Eight development cells, code only, every decision at its fallback.**
- First run: **0/6 faulted cells hit, and 3 wrong `parameter` labels.**
- The lead's two admission rulings (2026-10-08, development-informed) followed:
  - a change point must be tied to ≥ 2 *failed* channels;
  - change points inside the first HRT are excluded.

  After them, wrong labels fell **3 → 1** (S3-01 remains), and both pre-registered §4.5
  predictions held. Because the improved cells are the ones the rulings came from, *"the
  improvement proves nothing"*.
- **Findings for the lead:**
  - `influent` is unreachable when only the worst window is outside;
  - coupled processes put a single-channel fault into NM, where `sensor` cannot be admitted;
  - the wall clock, not evaluations, binds (132–259 evaluations against 300–750).
- **This table is the code-only floor** that every agent result is read against.

### 14.3 The live pilots (three-role minimum: QC, calibration, verifier)
All three attempts ran S0-01, S2-01 and S8-01 at B/B, replicates 0 and 1. The lead's ruling on L-1
(2026-10-11) approved the pilot as a **cost-and-wiring check**. The go/no-go cannot fire on these
records, and a false `sensor` on S0-01 r1 was a known design limitation.

| Attempt | Head / approval | Result | Cost |
|---|---|---|---|
| 1 (10-13) | `679f327` | **Stopped.** S0-01 r1 hit its 90-min allowance; an uncaught `declared_background` budget refusal crashed it; SIGTERM mid S2-01 r0 | ≈ $0.0037 |
| 2 (10-14/15) | `8be6f55`, digest `adf47dee…` | 6/6 completed, **3/6 correct**; the only change from offline was S2-01 r1 → `sensor` (correct) | $0.012263 (36 requests) |
| 3 (10-20/21) | `e1d6bcd`, digest `ea14d0ee…` | 6/6 completed, **3/6 correct** (different runs from attempt 2); one false `sensor` on clean S0-01 r1 | $0.004146 (19 requests) |

**Rulings and fixes between attempts:**
- **"P2 runs have NO wall-clock limit" (10-13).** Wall time becomes a reported cost. Evaluation,
  assay and model caps stay. A budget refusal ends as `abstain:budget`.
- **Three decision-layer defects fixed (10-14), "Yes, fix all three":**
  - `verify.differential` gets a per-call enum (it had answered `null`);
  - `dq.trust` sees pre-hold-out windows only (it had seen a day-172 spike inside the hold-out);
  - `cal.split` accepts any valid step.
- **Decision inputs sent as real JSON (10-14).** A Python literal containing `None` plausibly caused
  the `null` answer.
- **D-1 (10-15).** The hold-out bit is shown only beside an admitted `structural`, because the
  model used `holdout_passed` to set `sensor` aside.
- **N-2b (10-15).** An abstaining run writes `abstain`, never `none`, which the frozen evaluator
  would have scored as correct.
- **L-1 (10-19).** An unfinished run is **not a result**. It is rerun once offline; live, it is
  never rerun without approval. Backed by an attempt journal.
- **Tidy-up (10-19):**
  - D-2: the first-HRT spike rule is stated in the template;
  - D-3: `rejected[].label` is a pattern;
  - A3: requests whose answer cannot change the outcome are not made (about half of attempt 2's
    cost);
  - B1–B4: hardening.
- **Freeze digest moves:** `b2fad49a` → `fbe88dd0` → `17065508` → **`c58306b4…`** (current).
  Pilot configuration `cf59bcbb…`.

**Verdict on the procedural arm (attempt 3).**
- The only applied model answers that differed from the coded fallback were three `coupled_inside`
  readings, each restating a field that code had shown the model.
- **Outcomes equal a pure-code rule. Attempts 2 and 3 each score 3/6, against 2/6 offline:
  indistinguishable at n = 6.**

This led to the redesign.

---

## 15. P2 rebuilt as agents (PRs #37–#46)

### 15.1 The ruling
On 2026-10-25 the lead wrote: *"I think the design is the problem. I thought we will have multiple
AI agents … with multiple adversarial contemplations"*, then *"Let's go"*. This superseded the
2026-09-30 reading "P2 should not be agents with prompts".

**Kept from the procedural arm:**
- the registry, budgets, logs and isolation;
- the QC gate;
- the declared background and null rule, now shown to agents as evidence;
- the coded signatures;
- the rerun, journal, approval and freeze machinery.

The procedural arm becomes the "decision points only" comparison arm (Q12).

### 15.2 Rulings Q1–Q14 (all 2026-10-25) and later ones
| Q | Ruling |
|---|---|
| Q1 | **All seven roles as agents from the start** (against the note's three-first advice; the proposal's three-role descope remains the fallback) |
| Q2 | luna for every arm |
| Q3 | A specialist may cite `none` over a failed null |
| Q4 | D-1 under a free verifier: a passed hold-out is never evidence against a non-structural label (enforced in code) |
| Q5 | Disclose the declared-background asymmetry; a matched P1 arm decided after the pilot |
| Q6 | New H4 cells: S7-01 at B/A, B/B, B/C; S7-02 at A/C; two seeds each |
| Q7 | **The coordinator is code** |
| Q8 | Proposer caps $0.50 / 200 requests / 10 M tokens for the pilot, then frozen at about 2× the median |
| Q9 | The verifier gets its own budget |
| Q10 | Bounds may be narrowed only, never widened; a bound hit is never a kinetic update |
| Q11 | Two rounds |
| Q12 | The procedural arm is the "decision points only" arm |
| Q13 | A failed hold-out admits `structural` over a standing NM (a change to the frozen null rule, agent arm only) |
| Q14 | …and it also needs R3 over **all** channels: two independent pieces of evidence |

**Later rulings:**
- Package staging into the jail, option A (10-26).
- *"Let's use luna first"* (10-27): an Opus arm is a later, separately costed extension.
- **Ruling B (10-29):** the verifier's reserve of 80 evaluations and 1 assay unit is **on top of**
  the cell's envelope, so the verifier-off ablation equals P1's budget exactly.
- "Yes to all three" (10-30): frozen record first, then the Q6 cells; prompts frozen as they stand.
- "Yes to the rule tables" (11-01).
- "a" (11-03): freeze the routing rules too.

### 15.3 The design as built (`workflows/p2_multi_agent/agents.py`, 3,140 lines; `evidence.py`; `messages.py`)
**Roles and per-role tools** (turn budgets in brackets):

| Role | Tools |
|---|---|
| Data quality [12] | data_qc, inspect_record, set_sensor_status, residual_diag, simulate, declared_background |
| Influent [12] | mass_balance, feed_loads, inspect_record, declared_background, simulate |
| Identifiability [8] | describe_model, gsa_morris, gsa_sobol, profile_likelihood, fisher_info, residual_diag |
| Calibration [14] | fit_lsq/de/cmaes, bayes_mcmc, simulate, residual_diag, declared_background |
| Design [6] | voi_assay, request_assay (under the coordinator's grant only) |
| Verification [14 per round] | inspect_record, residual_diag, simulate, declared_background, **validate (the verifier's alone)** |

**Typed findings** (`messages.py`): 12 schemas.
- Every model-writable string is a regex pattern or enum, and a function proves there is no free
  text.
- Evidence is `{label, rule, calls, values}`, with the statement templated by code.
- Units are compared against the registry's symbols.
- `structural` is a round-2-only claim.

**The adversarial loop** (implemented with scripted models; never run live):
1. Data quality first.
2. The specialists whose null case failed (NB → influent; NM/NS → identifiability and calibration),
   or all of them when the null stands.
3. Design when ≥ 2 distinct claims conflict.
4. The verifier sees the typed findings and a **projected action log**: free text redacted, arrays
   cut to 200 points. It argues against the leading claim and names **one separating test**.
5. On a round-1 `fail`, code runs that test through the owning role's view, charged to the
   verifier's reserve. The proposers answer; the verifier judges again.
6. At most two rounds; the verdict is final.
7. **Code concludes:** `pass` → the leading admitted claim; a last-round `fail` with alternative
   `none` → `none`; anything else → abstain.

- Proposers never see `validate` output, only the typed hold-out flag.
- The offline responder abstains by construction, so an arm with no model claims nothing.

**Budget machinery (ruling B).** `Registry.reserve(role, …)` with calls tagged by role.
- Untagged spend ≤ envelope; tagged spend ≤ reserve. A forged tag can buy at most the reserve.
- The state's self-report adds the reserve's spend, so `simulator_evals_fraction` can reach
  (E + 80)/E.
- Verifier model caps: 40 requests, 4 M tokens, $0.50.

**Build steps:**

| PR | Step |
|---|---|
| #38 | 1: amended admission (`admit_agent`, Q13/Q14) and typed messages. Review found a dead `r3_all` key path |
| #39 | Sandbox: opt-in package staging; symlinks and forbidden names refused; staged-tree sha256 |
| #40 | 2a: package split (`evidence.py`, `messages.py`) |
| #41 | 2b: the harness (roles on P1's loop, views, projection, coordinator as code). Review J0–J3 blocking: missing seed base, silent verifier, caps clash, `validate` visible to proposers |
| #42 | Null rule and signatures moved into `evidence.py` (29 definitions, AST-identical) |
| #43 | 2c: the verifier's reserve, round 2, the separating test. M1 blocking: hold-out metrics leaked into round-2 briefs. S2 blocking: self-report omitted the reserve |
| #45 | 3a: the agent arm's **own frozen record** — prompt, schema and tool-spec digests, allow-list, turn budgets, rounds, projection rule, model and caps; checked before every run, offline included |
| #46 | 3b: the coordinator's **rule and routing tables** frozen (`rules_sha256`), each with a mutation test; `LABEL_TIE_BREAK` frozen (B3) |

**Final digests.**

| Record | Digest |
|---|---|
| `frozen_record_sha256(arm)` | `501893b3…1fa4` |
| `config_digest(arm)` | `618f4825…6dd8` |
| `rules_sha256` | `0aadaf43…` |
| Procedural record (unchanged) | `c58306b4…` |
| Pilot configuration (unchanged) | `cf59bcbb…` |
| Procedural configuration (unchanged) | `def3c42b…` |

### 15.4 Cost model (design note §8; estimates only)
- **Per run:** 3.6–6.3 M tokens, about $0.2–0.4 cached or $0.8–1.3 uncached, and 45–60 min of
  runner time.
- **By stage (cached):**
  - pilot $1.2–2.4;
  - development $4–8;
  - H4 $1.6–3.2;
  - ablations (108 runs) $22–43;
  - final share (480 runs) $96–192, about 360–480 runner-hours.
- **An Opus arm:** $1.5–3 k for the final share.

### 15.5 Comparison asymmetries to state beside every P2 result
- (a) P2 has the band tool; frozen P1 does not.
- (b) The verifier holds the hold-out in the loop.
- (c) P2 has no wall-clock limit.
- (d) The verifier's extra budget.

(b) and (d) are isolated by the verifier-off ablation.

---

## 16. The open PR #48: the H4 development cells (item B)

[sdanquah101/agent-db#48](https://github.com/sdanquah101/agent-db/pull/48) — draft, opened
2026-11-03, head `1c6a186`, +4,326 / −5 across 8 files.

**What it adds:**
- `h4-run` and `h4-report` in `scripts/p2_power.py`.
- Each arm in **its own run store** (a run-id collision was found on the first launch).
- Digests that drop runtime and timestamps.
- An observation fingerprint with a 1e-4 tolerance, because generation is machine-bound to the last
  bits.
- `reports/p2_power/h4_cells.json` and `h4_summary.md`.
- `tests/test_p2_h4_cells.py`, 12 tests, including the jailed agent arm run twice from one seed with
  identical results.
- The N8 wording fix: the role-name tie-break routes a round-2 `fail` but never decides a label. No
  digest moves.

**Outcomes** (16 runs, offline, descriptive):
- **Procedural floor: 0/8.** Six `none`, with the null standing on five. **Two wrong `parameter`
  labels** (S7-01 B/B s0 and B/C s0): the compound sensor + influent fault is absorbed into
  kinetics.
- **Agent arm: abstain 8/8.** The offline verifier abstains by construction; the null tables are
  identical to the procedural arm's.
- 84 targeted tests pass.

**Four interpretations await the coordinator:**
1. Both arms are run.
2. The two seeds are replicates 0 and 1.
3. A hit on a two-fault truth is either fault.
4. Separate stores per arm.

**Next after #48:**
1. The coordinator's review.
2. The lead's merge word.
3. Then the **agent-arm live pilot, only on a new approval record the lead approves.** The last
   approval (10-20) is spent and procedural-only.

---

## 17. Results across workflows, side by side

These are *development* results on different cells and seeds. The repository explicitly forbids
publishing a P1-vs-P0 table before the held-out variants, so this table is context, not a finding.

| | P0 | P1 (frozen rev2/luna) | P2 procedural | P2 agents |
|---|---|---|---|---|
| Cells | 78 sweep (L0–5) + 10 pilot | 10 pilot (one run each) | 6 pilot runs (3 cells × 2 seeds); 8 power cells; 8 H4 runs | 8 H4 runs (offline only) |
| Exact attribution | 17/78 sweep; 5/10 pilot | 1/10 (wrong sensor flagged) | live 3/6 and 3/6; offline 2/6; power 0/6 faulted; H4 0/8 | n/a (abstains offline) |
| `none` on clean cells | 10/12 sweep | **0/4** | 2/2 in attempt 2; 1/2 in attempt 3 | – |
| Typical failure | reads faults as `none` (44/66) | reads the background as a fault | null stands on most faulted cells; coupled faults land in NM | – |
| False kinetic drift | 22/68 | 0 | – | – |
| Unsupported claims | 0/273 (after A1) | 0 | – | – |
| Cost | none (no LLM); ~100 runner-h per sweep | $0.42 per 10 cells | ≈ $0.004–0.012 per 6 runs | est. $0.2–1.3 per run |

**What can be said already:**
- The record contains a hard floor. Distinguishability shows 18 of 78 cells where the truth is not
  admissible even from an exact reference.
- P0 errs towards `none` and P1 towards a fault; neither tunes its way out.
- The procedural decision layer added nothing measurable over code.

**What cannot yet be said:**
- Anything about H3–H6. That needs the held-out variants, the seeds, and a scored agent arm.

---

## 18. Cost and compute

**LLM spend recorded**, at declared rates; these are not invoices:

| Item | USD |
|---|---|
| P1 luna arms (first cell, old, 1a, 1b, contended, rev2, rev2 + brief) | ≈ 2.29 |
| P1 Claude arm (smoke $0.054 + ten cells $9.863) | ≈ 9.92 |
| P2 live pilots (attempts 1–3) | ≈ 0.02 |
| **Total** | **≈ 12.2** |

The Claude arm used 7.47 M tokens, mostly cache reads.

**Compute:**
- P0 sweep: 100.4 runner-hours.
- Positive control: 65.7.
- Distinguishability: 19.7.
- Declared background: 120 runs, 16,360 evaluations.
- **Machine speed varies with the container instance** (about 11.5, 18–20, 13.5 and 29 s per
  evaluation have all been seen), so wall clock and cost compare only within one instance.
- The stiffness pocket: one vector inside the fitted bounds integrates in 274–290 s against the
  usual 2.5–4.4 s.

**Test suite growth:**
- 16 tests (09-02) → 123 → 238 (09-03) → 339 (09-04) → 392 (09-14) → 448 (09-21) → 492 (09-22) →
  691 (10-03) → 897 (10-29) → **927 passed, 2 skipped, 1 h 40 min (11-01)**, the last full run on
  record.
- 960 tests collected; 15 deselected by marker (13 `g1`, 1 `p0_freeze` of about 2 h, 1 `p2_freeze`
  of about 37 min).
- Today's run is in Appendix C.

---

## 19. Inconsistencies and stale documentation found

None of these affects code behaviour; all affect a reader.

| Where | Problem |
|---|---|
| `README.md` "Status" | Frozen at Milestone 2: says the plants and influent generator are "not started". The project is in Milestone 8 |
| `docs/benchmark_card.md` §8 vs §5.2/§5.4 | §8 says conditional missingness "barely fires" and S6-01 is "inert"; §5 records both as resolved |
| Card §4.2 and §8 | Call distinguishability and the positive control "scheduled" or "not yet established"; both ran (PRs #23, #25) |
| Card §10 | Says "Code MIT/Apache-2.0" (it is Apache-2.0) and "anchor data are not redistributed" (small Muscatine files and a SCADA window are, under ODC-By) |
| Card §5 | "Every missingness rate is ASSUMED": the Tier C outage rate is now anchored (0.000966) |
| Card §6 | "Plant A runs Levels 2–7 at Tier A only": the matrix runs Levels 2–5 at Tier A plus the four ammonia rows at all tiers |
| `scenarios/README.md` | "The three ammonia rows": there are four (S6-04) |
| `scenarios/S4-02.yaml` header | Still describes triggers thresholded on FOS/TAC; superseded by hidden-state triggers |
| `docs/g1_anchor_report.md` §5.4–§5.5 | Prose gives 7.70 % and 0.17 %; the generated block gives 7.55 % and 0.00 %. The anchor rate "7.78 %" was relayed and **not reproduced** (measured 8.25 % / 9.18 %) |
| `anchor/compare_generated.py` docstring, the pyproject `g1` marker comment, the CI comment | Panel size, runtime and "one row expected to fail" are all stale |
| `docs/p2_agents_design.md` header | Still says "DRAFT … No code until approved"; it is the approved record and the code exists |
| `tests/README.md`, `scripts/README.md` | Omit most current suites and 12 of 13 scripts |
| `docs/proposal.md` Appendix B | Budget 4,000 evaluations; the ruled value is 450 |
| Decisions vs eval table | "Correct abstention 0 of 7" counts applicable cells; the CSV has 14 rows with a value |
| `pyproject.toml` | The `[llm]` comment mentions only OpenAI; isort `known-first-party` omits `distinguish` |
| `sim/influent/generator.py` docstring (item 7) | Still says the liquor does not vary and that B2 is open; the 09-10 liquor ruling scales dissolved species |
| `sim/influent/fractionation.py` docstring | Says later stages "consume the same stream"; they use keyed child streams |
| `sim/run/matrix.py` docstring | Says Plant A has 18 cells; it has 21 (S6-04) |
| `configs/plants/plant_A.yaml` `scenario_subset.tiers: [A]` | Contradicts the ammonia rows running at all three tiers |
| `RunManifest` docstring | Points at `runs/<id>/manifest.json`; the complete manifest is in `truth_store/` |
| `configs/adm1/extensions.yaml` SAO comment | Cites μ_max 0.08 and "standard pH_aa"; the configured values are 0.16 and the hydrogenotrophic limits |
| `sim/plants/mixing.py` | Labelled "PARKED", but wired in by `faults.plan.truth_mixing` |
| `configs/influent/feed_fractionation.yaml` | Every entry still `status: provisional`, though several are frozen or ruled |
| `docs/tool_registry_design.md` | Says newline-delimited frames (the transport uses length prefixes); lists a non-existent `configs/tools/budget.yaml`; claims cost is "never more than the declared bound" (false, §8.9a) |
| `tools/impl/identifiability.py`, `tools/impl/mcmc.py` docstrings | Fisher "pseudo-inverse" vs a regularised inverse in code; MCMC "emcee ESS" vs a Stan-style ESS in code |
| `tools/server.py` docstring | Omits the `reserves` op |
| `configs/tools/assays.yaml` comment | "2-8 units"; the scenarios use 2–6 |
| `CLAUDE.md` rule 1 | "`runs/<id>/` holds … nothing else": workflow outputs also live there, by design |

---

## 20. Open items, risks and gaps against the proposal

### 20.1 Not authorised yet (awaiting the lead)
- Generate the **held-out scenario variants** (§7). Everything so far is development.
- **Pre-registration** (OSF or similar). Gate G3's second half.
- The **5-seed final matrix** (~1,440 factorial + Plant A subset; proposal target ~1,700 runs).
- **P1 sweep scoring** and any P1-vs-P0 comparison.
- **The agent-arm live pilot.** Needs a new approval record. Then development (20 runs), H4 live
  (8), ablations (108) and the final share (480).
- The cap re-freeze at about 2× the median (Q8); the matched P1 + band arm (Q5).
- Items 5 and 6 of the 2026-09-24 plan:
  - the assumption-sensitivity subset (noise and missingness halved and doubled);
  - a blind practitioner judgement of a Muscatine case;
  - the selection-step ablation.

### 20.2 Not built
- The statistical analysis: mixed effects, paired comparisons, effect sizes.
- **Family E** (ablation) scoring.
- `verifier_rejections` wiring (needed for H6).
- Family A recomputation.
- The **§8 step 3** real-data forecasting check.
- A **Docker image and pinned dependencies.** Only lower bounds exist.
- The **`g1-frozen` tag.**
- **Weinrich R3/R4 fitted-model ports.** A condition of the ADM1 acceptance; they dropped off the
  plan after 09-03.
- The ADM1 state-space adapter that EnKF/MHE need, so the filters are never offered.
- A composition-exact positive-control rung.
- **Fixes for the defects found for this report** (§8.9):
  - (a) the cost-bound undercount;
  - (b) the `profile_likelihood` crash at one start;
  - (d) the identifiable Level-8 payload, which is a scenario tell;
  - (e) unbounded QC overrides;
  - (f) the MCMC walker undercharge;
  - (g) the network namespace;
  - and §10.3's shared visible log and the unwired `verifier_rejections`.

  None is recorded in `docs/decisions.md`; each needs a coordinator decision, and (a), (b) and (d)
  touch frozen code.
- A precipitation-off structural candidate (needs a `sim/` change).
- Per-tier answer keys.

### 20.3 Held or unresolved
- **Visible tells, referred and never ruled:**
  - **M3:** the Level-2 flatline is labelled in the visible `sensors.json`.
  - **M4:** the adversarial note's author field gives it away.

  Both were referred to the lead with "change nothing"; no ruling is recorded.
- The below-LOQ valerate question (17 % of values negative).
- `pK_a2(T)`.
- A declared design OLR for Plants B and C.
- `S_I` liquor scaling.
- MCMC inside narrowed bounds.
- The P1 interim-state placeholder scoring.
- Procedural §12 Q6 (counting TS/VS as one coupled group).
- The static checker's recorded blind spot, `str(bytes, enc)`. The jail is the structural defence;
  the checker stopped hardening at round three.

### 20.4 Scientific risks visible now
- **The background misfit dominates every workflow.** Any agent gain will come only where the agent
  overcomes the coded null. On the H4 cells the code-only floor is 0/8, with the null standing on
  10 of 16 runs.
- **The null rule's false-alarm rate is 0.16, an estimate.** It is higher on cells not exchangeable
  with the band (S0-01 B/C). Q13 accepts structural false alarms from chance hold-out failures.
- **Several signatures are blind by construction:**
  - `influent` is unreachable when only the worst window is outside;
  - coupled faults block `sensor`;
  - S5-01's recovery is unreachable;
  - S5-02 and S2-02 at Tier A are not distinguishable.
- **Small n so far.** One run per cell, development cells only. The design itself warns that "a
  difference of a cell or two is noise".
- **Distinguishability's guarantee** holds under the benchmark's own noise model; it degrades under
  AR(1) noise.
- **Machine-dependence.** P0's guard and wall-clock costs vary by container. Freezes are verified
  by same-machine two-head comparisons, not stored goldens.
- **The plan's capacity risk.** The proposal's three-role P2 descope remains the fallback. The
  agent build was estimated at 5–7 weeks, and the final share at 360–480 serial runner-hours.

---

## 21. Lessons the project has recorded about itself

Distilled from `docs/decisions.md` (206 entries) and the review records.

1. **Authority, not checklists.** Three duplicate builds ended only when launch authority moved to
   one named coordinator.
2. **Assume anything deterministic over visible data can be inverted.** Truth leaked through:
   - a public loader root and `"."`;
   - argument hashes and segment counts;
   - an invertible run id (1,440 hashes brute-forced);
   - a reproducible "random" order;
   - timestamps, mtimes and runtimes;
   - horizons;
   - plant tables.

   The answers were structural: a separate truth tree, an allow-list manifest, HMAC ids with a
   secret per-store salt, projected logs, and finally a namespace jail in which the answer key does
   not exist (*"the generation machinery is the answer key"*).
3. **Deny-lists lose.** The static checker went deny-list → allow-list → dynamic imports → dunders,
   then stopped, with the remaining hole recorded. The jail is the defence.
4. **Tests that cannot fail.** Examples: `impl == impl` checks, additive identities, a vacuous
   ratio guard (a zero mutant passed 337 tests), and single-seed plausibility that missed a 40 %
   failure rate. The remedies were literal goldens, closed forms, mutation testing, negative
   controls and pooled seeds.
5. **Mechanisms die silently while tests stay green.** VFA was 1000× too small, so overload never
   fired; foaming never fired; SAO was stuck at zero; S6-01 was inert. The fix is to assert that
   each mechanism fires at a measured rate.
6. **Units and bases.** Total vs dissolved Ca; FOG mass share vs COD share; a mislabelled column in
   a paper; drift per month vs per √d; an alkalinity assay 480× off its charge.
7. **Numbers stated as measurements must reproduce.** Withdrawn numbers are logged as withdrawn so
   that no later session "fixes" a config to match them.
8. **Never tune on results.** Bands are declarations, not dials. Rules were fixed before results
   (band rule, distinguishability versions, pre-registered ladder). Development-informed rulings are
   flagged. P0 stayed frozen after its own sweep.
9. **Keyed RNG streams per purpose** (`SeedSequence([seed, key, block])`). They make runs paired,
   prefix-stable and independent of tier composition.
10. **Self-report vs privileged logs.** Cost, convergence, launch digests and role tags are read
    from what the privileged side wrote.
11. **Placeholders become results unless forbidden.** A killed or abstaining run that writes `none`
    scores correct on a clean cell. The fixes: `abstain`, and "unfinished is not a result".
12. **Freeze what actually decides.** Inline routing literals and tie-breaks sat outside the frozen
    digest until mutation tests showed they changed labels.
13. **A null reference must be declared and served, not inferred by each workflow.** This is the
    project's main scientific lesson so far.

---

## Appendix A. Every pull request

| # | Title (short) | State | Opened → closed (2026) | One line |
|---|---|---|---|---|
| 1 | M1: ADM1 comparison + scaffold | merged | 09-02 | Scaffold, scenario schema, candidate probes |
| 2 | Standard ADM1 core + ring tests | merged | 09-02 | Canonical core; ≤ 1.5e-4 vs bsm2-python |
| 3 | Open anchor datasets | merged | 09-02 | Muscatine, ILRI; manifest |
| 4 | Extensions on the #2 core | merged | 09-02 | Duplicate of #2, reduced to SAO, Davies, carbonate, calcite |
| 5 | Extension follow-ups | merged | 09-02 | K_I_nh3_sao range; SAO scenario to Plant A |
| 6 | Plant configs A/B/C | merged | 09-02 | Canonical plant layer |
| 7 | Plant configs (parallel) | closed | 09-02 | Duplicate of #6 |
| 8 | Salvage from #7 | merged | 09-02 | Fractionation sampling, feed mapping, two-zone mixing |
| 9 | Catalogue answers (docs) | merged | 09-02 | Lead's catalogue rulings |
| 10 | Influent generator | merged | 09-02 | Generator, Muscatine ingest, catalogue freeze |
| 11 | Observation model + faults | merged | 09-02 | Canonical; VFA 1000× bug found in review |
| 12 | Observation model (parallel) | closed | 09-03 | Duplicate of #11 |
| 13 | Salvage from #12 | merged | 09-03 | SCADA window, Tier-C dropout, launcher fix |
| 14 | Historian dropout; coordinator.md | merged | 09-03 | Governance file, first-action rule |
| 15 | Gate G1 | merged | 09-03 → 09-21 | Harness, scenarios, anchor report; G1 frozen |
| 16 | VFA gap (docs) | closed | 09-09 | Folded into #15 |
| 17 | Tool registry v1.0 | merged | 09-21 | Registry, tools, fitted model, jail |
| 18 | P0 | merged | 09-21 → 09-22 | P0, task state, runner, pilots |
| 19 | Evaluation suite | merged | 09-22 | `eval/`, meter as cost source |
| 20 | P0 Level 0–5 sweep | merged | 09-22 → 09-24 | 78 cells; 17/78 exact |
| 21 | Plan after P0; card scope | merged | 09-24 | Coordinator's seven-step plan |
| 22 | P0 rulings A1–A4 | merged | 09-24 | Evidence cites calls; abstention vocabulary |
| 23 | Positive-control ladder | merged | 09-24 → 09-28 | Pre-registered; R1 and R2 fail |
| 24 | Evaluator rulings D1–D3 | merged | 09-24 → 09-25 | Over-abstention, earned credit |
| 25 | Distinguishability | merged | 09-24 → 09-28 | Admissible sets; P0 25/71 |
| 26 | P1 (development) | merged | 09-25 → 09-30 | Agent, gateway, luna arms |
| 27 | P1 Anthropic arm, freeze, records | merged | 09-29 → 09-30 | Claude arm; P1 frozen |
| 28 | Knowledge audit, P2 launch brief | merged | 09-30 | — |
| 29 | P1 follow-up | merged | 09-30 | LOW review notes |
| 30 | P2 d0: declared background | merged | 09-30 → 10-05 | 10-seed FINAL band |
| 31 | P2 d1: design + null rule | merged | 10-05 → 10-07 | Null rule frozen |
| 32 | P2 d2: offline workflow | merged | 10-07 → 10-10 | Power run, admission rulings |
| 33 | P2 d3: live wiring + pilot | merged | 10-10 → 10-15 | Approval records; attempts 1–2 |
| 34 | P2: D-1, N-2b, L-1 | merged | 10-15 → 10-19 | Hold-out bit, abstain label, rerun rule |
| 35 | P2 tidy-up | merged | 10-19 → 10-20 | D-2, D-3, A3, B1–B4 |
| 36 | P2 live pilot attempt 3 | merged | 10-20 → 10-25 | $0.004146; 3/6 |
| 37 | P2 as agents: design note | merged | 10-25 → 10-26 | Q1–Q14 ruled |
| 38 | Agents step 1 | merged | 10-26 → 10-27 | Admission, typed messages |
| 39 | Sandbox: package staging | merged | 10-26 → 10-27 | Option A |
| 40 | Agents step 2a | merged | 10-27 | Package split |
| 41 | Agents step 2b | merged | 10-27 → 10-29 | The harness |
| 42 | Null rule move | merged | 10-28 → 10-29 | AST-identical move |
| 43 | Agents step 2c | merged | 10-28 → 10-29 | Verifier reserve (ruling B), round 2 |
| 44 | Milestones | merged | 10-29 → 10-30 | Order A then B |
| 45 | Agents step 3a | merged | 10-30 → 11-01 | Agent frozen record |
| 46 | Agents step 3b | merged | 11-02 → 11-03 | Rule and routing tables frozen |
| 47 | CI: pivot_root | merged | 11-02 | Jail on the new runner image |
| 48 | P2: Q6/H4 cells | **open (draft)** | 11-03 → | Offline floor in both arms |

**Totals:** 44 merged; 3 closed unmerged (#7 and #12 duplicates, #16 folded); 1 open.

---

## Appendix B. Superseded and reversed decisions (selected)

The full chronology is in `docs/decisions.md`. These are the reversals a reader most needs.

| Original | Superseded by |
|---|---|
| Plant B "high-nitrogen food waste" (proposal v0.1) | Muscatine co-digestion; ammonia rows moved to Plant A (v0.3) |
| SAO shares acetoclastic NH₃ inhibition | Its own weaker constant, 0.05 kmol N/m³ |
| Global inert COD equivalent 1.19 | Per feed 1.2 / 1.42; FOG 2.9 |
| HSW/FOG degradability 0.95 / 0.98 | Cited 0.84 / 0.92 |
| Total Ca in feeds | Dissolved Ca from calcite saturation |
| Truth under `runs/<id>/truth/` | Separate top-level `truth_store/<id>/` |
| Unkeyed run id | HMAC with a secret per-store salt |
| Deny-list static checker | Allow-list + jail |
| Overload on FOS/TAC > 0.40 | Hidden VFA > 2× trailing median |
| True VFA sensor | Titrimetric FOS, κ = 1.0 |
| Per-row horizons 180 / 240 d | Per plant 200 / 365 d |
| Horizon-mean reference quantities | Fixed 200-d reference window |
| Serial RNG streams | Keyed `SeedSequence([seed, key, block])` |
| Budgets 4,000–8,000 evaluations | 450 / 600 / 750 (Plant A 225 / 300 / 375) |
| Stored P0 golden | Same-machine two-head comparison |
| P1 on `claude-opus-5` | `gpt-5.6-luna` (lead's direct instruction) |
| `validate` as a P1 tool | Run once by the harness after `conclude` |
| P2 under the wall clock | No wall-clock limit (a reported cost) |
| An abstaining or unfinished run writes `none` | `abstain`; unfinished is not a result |
| "P2 should not be agents with prompts" | P2 rebuilt as seven role agents |
| Verifier reserve carved out of the envelope | Ruling B: on top |
| Distinguishability v1 → v3 | v4, the truth baseline (optimistic upper bound) |

---

## Appendix C. Repository facts and today's health check

**Size of the codebase:**

| Package | Python lines | Files |
|---|---|---|
| `sim/` | 11,393 | 39 |
| `tools/` | 11,912 | 33 |
| `workflows/` | 10,800 | 10 |
| `eval/` | 1,396 | 12 |
| `state/` | 967 | 5 |
| `anchor/` | 1,606 | 5 |
| `distinguish/` | 1,172 | 3 |
| `scenarios/` | 339 | 2 |
| `scripts/` | 5,568 | 18 |
| `tests/` | 28,822 | 60 (789 test functions; 960 collected with parametrisation) |

**Other repository facts:**
- **Documentation:** about 1.5 MB under `docs/` — `decisions.md` 590 KB / 8,894 lines / 206
  entries; `milestones.md` 312 KB / 4,504 lines.
- **Configuration:** 50 configuration files; 20 scenario YAMLs.
- **History:**
  - 362 commits from 2026-09-02 to 2026-11-03: 241 in September, 112 in October, 9 in November;
  - 62 merge commits;
  - authorship 313 by Claude sessions, 49 by the lead's account (merges).
- **Branches:** `main` and this report's branch, plus the open PR's `claude/p2-q6-cells`.
- **Tags:** none (the planned `g1-frozen` tag does not exist).
- **Environment:**
  - Python ≥ 3.11 (CI 3.11 and 3.12; this container 3.13.18).
  - Core dependencies: numpy, scipy, pydantic, pyyaml, emcee, cma. Lower bounds only, no lock
    file.
  - Optional `[llm]` dependencies: openai, anthropic.

**Health check today** (2026-11-05, this container, `main` at `f72fb9e`):
- `ruff check .`: **All checks passed.**
- `ruff format --check .`: **251 files already formatted.**
- `pytest -q` (default markers, full suite, serial, on a 4-core container shared with this review's
  readers): see the line below.
- The area readers also ran subsets in isolation:
  - simulator suites: 339 passed, 2 skipped (the skips need the git-ignored SCADA file);
  - registry, sandbox and isolation suites: 163 passed.

  The jail builds in this container: unprivileged user namespaces and `/sbin/pivot_root` are present.

**Full-suite result (2026-11-05, serial, this container):** 941 passed, 4 skipped, 15 deselected in 6 595 s (1 h 50 min); exit code 0.

- The 15 deselected tests are the `g1`, `p0_freeze` and `p2_freeze` markers, which `pyproject.toml` deselects by default (`addopts`). They were not run for this report.
- Two of the four skips need the git-ignored Muscatine SCADA file (`tests/test_observation.py:519`, `:532`).
- The other two skips need the `anthropic` package, which is not installed here (`tests/test_p1_anthropic_arm.py:387`, `:426`).
- Compared with the run of 2026-11-01 (927 passed, 2 skipped, 1 h 40 min), there are 14 more passing tests and the two `anthropic` skips are new.


