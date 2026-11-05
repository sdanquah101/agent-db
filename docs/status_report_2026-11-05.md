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

<!-- SECTION 5 SIMULATOR — filled below -->

