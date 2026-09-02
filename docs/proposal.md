# AD-AgentBench: An Open Benchmark for Agent-Supported Calibration and Discrepancy Diagnosis of Industrial Anaerobic-Digestion Models

**Research proposal — Phase 1 (synthetic benchmark and first publication)**
Ruthie Armah, KNUST–TUM SEED Centre
Draft v0.3 — September 2026

*Revision note (2026-09-02).* v0.2 fixes the anchoring status of the three plants
(§6.1, §7, §8, §12, §13): Plants B and C are dataset-anchored; Plant A is
statistics-anchored for all of Phase 1 and runs a reduced, separately reported
scenario subset. v0.3 (same day) fixes the plant definitions (§6.1, §6.3, §7): Plant B
is Muscatine-anchored co-digestion with load swings and makes no high-nitrogen claim;
Plant C is the same digester fed only its sludge streams (a controlled pair); the
ammonia scenarios move to Plant A; mixing is ideal in the plant contract and imperfect
mixing is a fault-injection truth variant. See `docs/decisions.md`.

---

## 1. Summary

Anaerobic-digestion (AD) process models such as ADM1 are routinely calibrated to sparse industrial data in which influent composition, latent states, sensor bias, kinetic parameters and structural error compensate for one another. No published study applies AI agents to this task, and no benchmark exists that could tell us whether agents help. Real plant data cannot settle the question, because the true parameters and the true cause of any model–data mismatch are unknown.

This proposal describes a nine-month project to build and publish **AD-AgentBench**: an open, reproducible simulated-plant environment with known ground truth, a frozen registry of conventional calibration tools, a library of injected faults and structural mismatches, three instrumentation tiers, and an evaluation protocol that measures not only fit but *whether a workflow attributes a discrepancy to the correct cause*. A scripted pipeline, a single constrained agent and a task-specialised multi-agent system are compared under identical tools, data and budgets. Everything — simulator, scenarios, prompts, logs, seeds — is released.

The deliverable is a benchmark paper and an open repository. The scientific result is secondary to the instrument: whether agents win or lose, the field gains a controlled way to find out. The environment also becomes the synthetic-test infrastructure for the later plant-based phases of the PhD.

---

## 2. Motivation and gap

The literature review (Part 1) established four constraints that shape this work:

1. **Calibration is a joint inverse problem.** Routine measurements (gas flow, methane fraction, pH, temperature, occasional lab assays) identify only a low-dimensional combination of inputs, states and parameters. Better fit can mean worse parameters when structural error is ignored.
2. **Mismatch has several possible causes.** A residual can originate in a sensor, a feed batch, a latent state, a kinetic parameter or an omitted mechanism. Existing workflows send every mismatch to the optimiser; the first question — *where did this error enter?* — is rarely asked and never scored.
3. **Agent evidence is indirect.** Multi-agent calibration exists for activated sludge (against an uncalibrated baseline); RL calibration exists for turbofans; tool-using agents run laboratory instruments but deviate from instructions. Nothing exists for AD, and nothing anywhere holds the numerical tools constant while varying only orchestration.
4. **Ground truth is unavailable on real plants.** This makes synthetic data the *only* setting in which parameter recovery, uncertainty-class attribution and correct abstention can be scored.

The gap is therefore not "an agent that calibrates ADM1." It is the absence of an environment in which that claim, or its negation, could be tested at all.

---

## 3. Objectives

**O1.** Build a simulated industrial AD plant with a hidden truth model, realistic influent variability, an explicit observation model and controllable fault injection.

**O2.** Assemble a frozen, versioned registry of conventional tools (sensitivity, identifiability, optimisation, Bayesian inference, state estimation, physical checks) accessible identically to all workflows.

**O3.** Define a scenario library that encodes the joint-inverse-problem argument: each scenario has a labelled ground-truth cause and a correct conclusion.

**O4.** Implement and compare three workflows — scripted (P0), single agent (P1), multi-agent (P2) — under equal tools, data, compute and assay budgets.

**O5.** Define and publish an evaluation protocol covering calibration quality, uncertainty-class attribution, information efficiency, workflow reliability, safety and cost.

**O6.** Anchor the simulator's statistics to at least one open full-scale dataset so the environment is defensibly realistic.

**O7.** Publish the benchmark, code, scenarios, prompts, logs and results under an open licence, with a preprint establishing priority.

---

## 4. Research questions and hypotheses

**Central question.** Under what data conditions and fault types does agent discretion — with or without multi-agent decomposition — improve the reliability, correctness or efficiency of AD model calibration and discrepancy diagnosis relative to a scripted pipeline using identical tools?

**RQ1.** Which quantities are practically identifiable at each instrumentation tier under each scenario class? *(establishes the ceiling any workflow could reach)*

**RQ2.** Does agent discretion improve correct attribution of discrepancy to sensor, influent, state, parameter or structural causes?

**RQ3.** Does multi-agent decomposition add reliability or efficiency beyond a single agent once tools and budgets are equal?

**RQ4.** Can a value-of-information agent select the assay that most reduces predictive uncertainty per unit cost, relative to fixed schedules?

**RQ5.** What does agent orchestration cost in simulator calls, wall-clock time and tokens, and how does that vary with tier?

**Hypotheses** (directional, with stated moderators so each is falsifiable):

- **H1.** Identifiability-screened calibration achieves better out-of-sample prediction and interval coverage than all-parameter calibration at every tier; the gap is largest at Tier A.
- **H2.** Workflows that explicitly triage discrepancy cause before fitting show lower false kinetic-drift rates than fit-first workflows; the effect is largest in sensor-fault and feed-bias scenarios.
- **H3.** The single agent outperforms the scripted pipeline on attribution accuracy in scenarios where the correct tool sequence is conditional on intermediate diagnostics, and matches it elsewhere.
- **H4.** The multi-agent system outperforms the single agent only in scenarios with two or more simultaneous fault types; in single-fault scenarios it incurs overhead without gain.
- **H5.** The value-of-information agent reduces predictive interval width per simulated assay by more than fixed-schedule sampling, at Tier A and B.
- **H6.** Agent workflows exhibit non-zero rates of invalid actions and unsupported claims, and an independent verifier reduces the rate at which these propagate to final outputs.

---

## 5. Scope and non-goals

**In scope.** Synthetic plant environment; conventional tool registry; P0–P2 comparison; value-of-information for simulated assays; evaluation protocol; open-data anchoring; benchmark paper.

**Out of scope for Phase 1.** Real-plant calibration; RL/HMARL policies (P3 — deferred to Phase 2 with a genuine sequential task defined); operator studies; FEW ledger; any plant actuation. These remain in the PhD plan; excluding them here is what makes Phase 1 finishable.

**Explicit non-claims.** The benchmark does not claim that a workflow that succeeds in simulation will succeed on a plant. It claims to measure properties — attribution correctness, calibrated uncertainty, abstention, cost — that no real dataset can measure, and to provide the environment in which future methods can be compared fairly.

---

## 6. System design

### 6.1 Simulator layer

**Truth model.** An extended ADM1 including at minimum: ionic-strength correction, syntrophic acetate oxidation, and a simplified precipitation/inorganic-carbon sink. The extension exists so that the *fitted* model (standard or simplified ADM1) is structurally wrong by design. Candidate base implementations to evaluate in week 1: PyADM1, the BSM2 ADM1 reference implementation, ADM1F, and the Weinrich ADM1-R3/R4 simplified family. Selection criteria: numerical stability under stiff transients, licence, ease of wrapping, and existence of published validation.

**Plant configurations.** Three virtual plants spanning the domains where ADM1 defaults are known to be weak:
- *Plant A* — agricultural co-digestion (cattle slurry + grass silage), mesophilic, CSTR.
- *Plant B* — municipal-sludge digester co-digesting trucked high-strength waste and FOG, mesophilic, with large day-to-day load swings (Muscatine-anchored, §8). It makes no high-nitrogen claim; the ammonia-driven scenarios run on Plant A.
- *Plant C* — sewage-sludge digester (closest to ADM1's origin; serves as an "easy" control): the same digester as Plant B fed only its sewage-sludge streams, so that B and C form a controlled pair differing only in the co-substrates.

Each has fixed geometry, a declared active volume with a hidden error (±5–15%), and heating parameters; mixing is declared ideal (CSTR) in the plant contract, and imperfect mixing (a residence-time distribution) is a fault-injection truth variant of the corresponding Level-6 scenario rather than a plant property. Plant configurations are in `configs/plants/` (decisions log, 2026-09-02).

**Anchoring status.** Plants B and C are *dataset-anchored*: their influent variability, missingness and sensor-noise statistics are fitted to an open full-scale dataset (§8). Plant A is *statistics-anchored* for all of Phase 1: its operating envelope and feedstock characteristics are taken from published summary statistics (Tisocco et al. 2024, 2026), because no open full-scale agricultural co-digestion time series exists and no author data request is made in this phase. Plant A therefore runs a reduced scenario subset and is reported separately (§7).

**Influent generator.** A stochastic batch-delivery process: feed identity per delivery (from a small catalogue per plant), delivery mass, moisture, and a *true* COD fractionation drawn from a per-feed distribution. Seasonal drift in composition and temperature. Occasional unrecorded deliveries and mis-logged masses. The generator emits both the hidden true fractions and the "routine" assays an operator would see (TS, VS, total COD, TKN/TAN, alkalinity, pH), with assay noise and lag.

**Observation model.** Every sensor has a declared model: sampling interval, noise, drift (random walk with bounds), fouling episodes, flatlining, saturation, and a wet/dry and standard-conditions convention. Lab assays have method noise, turnaround delay and schedule. Missingness is generated *conditionally* — instruments are more likely to fail during foaming and overload — so that naive interpolation destroys information.

**Fault injection API.** Any scenario is a declarative YAML file specifying plant, tier, duration, fault type(s), onset time, magnitude and the ground-truth label. The simulator logs hidden truth alongside observations, in a separate file never exposed to workflows.

### 6.2 Tool registry

All tools are pure functions with typed inputs and outputs, versioned, and called through a single interface that logs every invocation, its arguments, runtime and outcome. Workflows may call tools; they may not modify them.

| Tool | Method | Notes |
|---|---|---|
| `data_qc` | Unit/timestamp checks, flatline/spike/drift detectors, missingness-by-event analysis | Rule-based; no learning |
| `mass_balance` | COD, N and charge balance closure over windows | Physical admissibility |
| `gsa_morris` | Morris screening on declared parameter set and outputs | Breadth screening |
| `gsa_sobol` | Variance-based indices on reduced set, incl. second-order | Interaction evidence |
| `profile_likelihood` | Multi-start profiles for practical identifiability | Flat-profile detection |
| `fisher_info` | FIM / Hessian conditioning and parameter correlations | Cheap identifiability proxy |
| `fit_lsq` | Constrained multi-start least squares | Deterministic baseline |
| `fit_de` | Differential evolution (fixed seeds, population, budget) | Non-convex baseline |
| `fit_cmaes` | CMA-ES | Alternative evolutionary |
| `bayes_mcmc` | Reduced-parameter MCMC with configurable likelihood (Gaussian / AR(1) / heteroscedastic) | Uncertainty |
| `filter_enkf` / `filter_mhe` | Ensemble Kalman / moving-horizon state estimation with bounded slow parameters | Sequential updating |
| `residual_diag` | Residual structure by feed batch, load, temperature, time | Discrepancy placement evidence |
| `voi_assay` | Expected information gain of each available simulated assay | For RQ4 |
| `validate` | Hold-out forecast metrics, coverage, interval score, constraint violations | Verifier tool only |

Compute budget is enforced at the registry: each workflow receives the same maximum number of simulator evaluations and the same wall-clock allowance per scenario.

### 6.3 Scenario library

Each scenario has a ground-truth label from the set {**sensor**, **influent**, **state**, **parameter**, **structural**, **none**} and a *correct conclusion* the workflow should reach. Scenarios are grouped in a ladder of increasing difficulty.

| Level | Scenario | Injection | Truth label | Correct conclusion |
|---|---|---|---|---|
| 0 | Clean, perfect model | None; truth model = fitted model | none | Calibrate screened subset; tight intervals |
| 1 | Noise and missingness | Sensor noise, random gaps | none | Calibrate; wider intervals; no fault flagged |
| 2 | pH electrode drift | Slow negative drift, later step-recalibration | sensor | Flag pH; exclude/correct; do **not** alter kinetics |
| 2 | Gas-meter bias | +8% scale error from onset | sensor | Flag gas; estimate scale factor; no yield-parameter change |
| 2 | Flatlined methane analyser | Constant value for 6 days | sensor | Quarantine window; abstain on CH₄ claims |
| 3 | Feed mislabelled | One feed's true fractionation differs from catalogue | influent | Revise mapping for that batch; do not touch hydrolysis |
| 3 | Unrecorded delivery | Extra mass not logged | influent | Detect balance violation; flag log, not model |
| 3 | Wetter season | Moisture drift lowers VS per delivery | influent | Update fractionation trend; no kinetic drift |
| 4 | Unknown initial biomass | Biomass states mis-initialised | state | State estimation converges; parameters unchanged |
| 4 | Informative missingness | Sensors fail during overload | state/sensor | Recognise missing transient; abstain or widen |
| 5 | True ammonia-inhibition shift | Inhibition constant changes after acclimation | parameter | Detect sustained load-dependent residual; update bounded parameter |
| 5 | Hydrolysis rate regime change | Feed particle size change alters k_hyd | parameter | Bounded update of hydrolysis only |
| 6 | Omitted SAO pathway | Truth includes SAO; fitted model does not | structural | Persistent structured residual under high NH₃; recommend model revision; abstain on speciation |
| 6 | Omitted precipitation | Truth includes inorganic-carbon sink | structural | Alkalinity/pH residual unattributable to parameters; recommend structural review |
| 6 | Imperfect mixing | Truth has RTD; fitted assumes CSTR | structural | Load-dependent residual; do not fit as kinetics |
| 7 | Compound: drift + feed bias | Two simultaneous faults | sensor + influent | Both attributed; neither absorbed into kinetics |
| 7 | Compound: structural + parameter | SAO omitted and inhibition shift | structural + parameter | Partial attribution; explicit abstention on the confounded part |
| 8 | Tool failure | `bayes_mcmc` returns non-converged chains | — | Detect failure; fall back; do not report posterior |
| 8 | Adversarial log note | Operator note asserts a false cause | — | Treat note as evidence, not instruction; verify against data |

Every scenario except the three ammonia scenarios runs at Tiers A, B and C (§6.4) on Plants B and C, giving roughly 16 × 3 × 2 ≈ 96 base cases before seeds. The ammonia scenarios — the Level-5 inhibition shift, the Level-6 omitted-SAO scenario and their Level-7 compound — run only on Plant A, whose free ammonia is in the pathway-shift window; Plant A otherwise runs the Level 2–5 scenarios at Tier A (§7).

### 6.4 Instrumentation tiers

Tiers are observation masks on identical underlying truth.

- **Tier A (constrained plant):** feed mass, reactor temperature, pH (daily), corrected biogas volume (daily), TS/VS (weekly).
- **Tier B:** Tier A + continuous CH₄ fraction, weekly alkalinity, VFA (total), TAN, COD.
- **Tier C:** Tier B + VFA speciation, richer fractionation, off-gas H₂/H₂S, periodic activity tests.

Assays beyond the tier's schedule can be *requested* by a workflow at a declared cost and turnaround from a fixed budget.

### 6.5 Workflows

**P0 — Scripted pipeline.** A predeclared sequence: QC → balance check → Morris → Sobol → profiles → screened fit (LSQ then DE) → MCMC on screened subset → validate. Fixed rules for excluding flagged sensors. No conditional branching beyond thresholds declared in advance. This is the strongest fair baseline: it is what a competent engineer would script today.

**P1 — Single constrained agent.** One LLM-based agent with access to the same registry, a structured task state, and the same stopping actions. It chooses which tool to call next, with what arguments, and when to conclude or abstain. It may request assays from the budget.

**P2 — Task-specialised multi-agent.** Seven roles from the review — data quality, influent, identifiability, calibration, experimental design, verification, coordination — communicating through typed messages and shared state. The coordinator routes; it cannot approve its own output. The verifier receives the proposed result, full action log and frozen validation data and returns pass / fail / abstain.

**Common constraints for P1 and P2.** Agents may not: fabricate values, edit raw data, change parameter bounds without an explicit logged justification, bypass a failed QC gate, or call any function outside the registry. Prompts, model version, temperature and retry policy are frozen before the final run.

### 6.6 Task state and provenance

A single JSON schema shared by all workflows: data-quality status, tier, candidate model, current uncertainty classification (with confidence), approved parameter subset, residual diagnostics summary, actions taken, tool failures, remaining simulator and assay budget, validation status. Memory is this state plus the tool-call log; free-text summaries are not permitted to replace structured results.

### 6.7 Evaluation protocol

Five target families, all computed from logs by an evaluation script that no workflow can access.

**A. Calibration and prediction (model quality)**
- MAE, RMSE, normalised error and bias on a frozen forecast window for CH₄ flow, pH and, where observed, VFA/TAN.
- Interval coverage at 50/90%, interval score, CRPS.
- Mass/charge-balance error; constraint violations.
- Parameter recovery error and posterior coverage of *true* values — reported **only** for scenarios where the truth model equals the fitted model (levels 0–5), and explicitly *not* for structural scenarios.

**B. Attribution and epistemic discipline (the new metric family)**
- Attribution accuracy: does the final uncertainty-class label match the ground-truth label?
- False kinetic-drift rate: fraction of sensor/influent/structural scenarios in which a kinetic parameter was changed beyond its prior interval.
- Correct-abstention rate: in structural and compound scenarios, does the workflow decline to report quantities the data cannot support?
- Unsupported-claim rate: statements in the final report not traceable to a tool output.

**C. Information efficiency**
- Simulator evaluations, wall-clock, and tokens per scenario.
- Assays requested, and uncertainty reduction per assay unit cost (RQ4).

**D. Workflow reliability**
- Completion rate; invalid-action attempts; tool-call errors; verifier rejections; retries; variance across seeds. Failed runs stay in the denominator.

**E. Ablations (P1 and P2)**
- Remove: persistent state; verifier; coordinator; individual specialist roles; self-correction. Report deltas on families A–D.

---

## 7. Experimental design

- **Factorial core.** 16 scenarios × 3 tiers × 2 plants × 3 workflows × 5 seeds ≈ 1,440 runs. The two factorial plants are **B and C** (dataset-anchored, §8); the three ammonia scenarios are not in the factorial.
- **Plant A subset.** Plant A (statistics-anchored) runs a reduced subset — the Level 2–5 scenarios at Tier A, plus the three ammonia scenarios (Level-5 inhibition shift, Level-6 omitted SAO, Level-7 compound) that run only there — with the same three workflows and seeds, and is **reported separately**; it contributes no rows to the factorial analysis.
- **Budgets.** Identical per (scenario, tier) cell: N simulator evaluations, T wall-clock, K assay units. Chosen from pilot runs so P0 completes comfortably; agents must live inside the same envelope.
- **Development/evaluation split.** A held-out set of scenario *variants* (different onset times, magnitudes, feed catalogues) is generated after prompts and P0 rules are frozen, and used only once.
- **Pre-registration.** Hypotheses, metrics, budgets and analysis plan are registered (OSF or equivalent) before final runs.
- **Statistical analysis.** Mixed-effects models with scenario and seed as random effects; paired comparisons within cells; effect sizes with bootstrap intervals rather than p-values alone.
- **Reproducibility.** Docker image, pinned dependencies, seeds, model version strings, and a one-command re-run of any cell.

---

## 8. Real-data anchor

The simulator must not be fantasy. Before scenario generation is finalised:

1. Identify one or two open full-scale datasets (candidates: the full-scale co-digestion data associated with Tisocco et al.; agricultural-plant datasets from the Weinrich group; any Zenodo/Mendeley Data AD time series — to be verified in week 1).
2. Fit the influent generator's variability, seasonal drift, missingness rate and sensor noise to these datasets and report the match.
3. Run a **forecasting-only** check: the same simplified ADM1 and the same P0 pipeline applied to the real data, reporting comparable NSE/MAE to published values. This shows the tool chain works on real data without claiming calibration success there.

**Outcome of the week-1 search (2026-09-02; `docs/anchor_datasets.md`).** One suitable open dataset exists: the Muscatine WRRF daily (2020–2023) and 1-minute SCADA (2022–2023) datasets (Schroer & Just 2024, ODC-By 1.0), a sewage-sludge plant with heavy industrial co-digestion. Plants B and C are anchored to it (steps 2 and 3 above). No open full-scale agricultural co-digestion time series exists; the two Tisocco et al. plants match Plant A exactly but their data are not deposited. Plant A is therefore anchored to the published summary statistics of Tisocco et al. (2024, 2026) for all of Phase 1, no author data request is made, and the paper states this limitation plainly. The benchmark card and the paper describe Plant A as *statistics-anchored* and Plants B and C as *dataset-anchored*.

---

## 9. Implementation plan

### 9.1 Technology

Python ≥ 3.11; simulator core in Python with a compiled ODE backend (SciPy/JAX or Julia via bridge, decided by stiffness tests in week 2); Pydantic for schemas; a light message bus for P2 (in-process, no external services); LLM access via a provider-agnostic wrapper so model choice is a config field; MLflow or plain structured logs for run tracking; Docker for release.

### 9.2 Repository structure

```
ad-agentbench/
  sim/          truth models, plants, influent generator, observation model, fault injection
  scenarios/    YAML scenario definitions + ground-truth labels
  tools/        registry (each tool a pure, versioned function with schema)
  workflows/    p0_scripted/, p1_single_agent/, p2_multi_agent/
  state/        shared task-state schema and provenance logger
  eval/         metric implementations, statistical analysis, report generation
  anchor/       real-data ingestion and comparison scripts
  configs/      frozen budgets, prompts, model versions
  docs/         benchmark card, model cards, contribution guide
```

### 9.3 Milestones (36 weeks)

| Weeks | Milestone | Exit criterion |
|---|---|---|
| 1–2 | Base ADM1 implementation selected; open datasets identified | Stiffness tests pass; licence cleared; anchor dataset(s) chosen |
| 3–6 | Truth model with extensions; three plants; influent generator | Reproduces published steady-state ranges; stochastic influent statistics match anchor |
| 7–9 | Observation model and fault-injection API | All 19 scenarios generate; hidden truth logged separately |
| 10–13 | Tool registry v1.0, frozen | Every tool unit-tested; call logging complete; budgets enforceable |
| 14–16 | P0 scripted pipeline | Completes all Level 0–5 scenarios at all tiers; results plausible |
| 17–20 | Evaluation suite and pre-registration | Metrics computed from logs only; pre-registration filed |
| 21–25 | P1 single agent | Runs inside budget; invalid-action logging works; prompts frozen |
| 26–30 | P2 multi-agent + verifier | Role separation enforced; verifier cannot see proposer's reasoning |
| 31–32 | Held-out variants generated; final runs | 1,700 runs complete; no config changes after start |
| 33–34 | Analysis and ablations | Pre-registered analysis executed; deviations documented |
| 35–36 | Paper, benchmark card, release | Preprint posted; repo public; Docker image published |

Buffer: milestones 3–6 and 26–30 are the likely overruns; two weeks of float are held at week 20 and week 32.

### 9.4 Roles

- **Lead (RA):** design authority, scenario library, evaluation protocol, paper.
- **Simulation engineer (or RA + collaborator):** truth model, ODE backend, influent/observation models.
- **Agent engineer (or RA):** P1/P2, state schema, verifier.
- **Supervisors:** gate reviews at weeks 9, 20, 32.
- **External reviewer (optional):** one AD modeller not on the project to sanity-check scenario realism before freeze.

---

## 10. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ODE stiffness makes the evaluation budget infeasible | Medium | High | Choose backend by stiffness test; use simplified ADM1 as fitted model; cap horizon |
| Simulator judged unrealistic by AD reviewers | Medium | High | Real-data anchor (§8); external AD reviewer before freeze; report mismatch openly |
| Agent results dominated by LLM stochasticity | High | Medium | Temperature 0 where possible; 5 seeds; report variance as a finding |
| Agents leak information via prompts (e.g., scenario names) | Medium | High | Scenario IDs randomised; prompts audited; agents never see YAML |
| P0 is made deliberately weak, inflating agent gains | Low | High | P0 designed and frozen first; documented as "best scripted practice"; external review |
| LLM cost exceeds budget | Medium | Medium | Token budget per run is itself a metric; smaller models tested; cache tool outputs |
| Scope creep toward RL or real-plant calibration | High | High | §5 non-goals; supervisor gate at week 20 enforces scope |
| Team capacity (mostly one person) | High | High | P2 is descoped to three roles (QC, calibration, verifier) if week 26 is missed; paper still viable |

---

## 11. Decision gates

- **G1 (week 9).** Simulator generates all scenarios with logged truth, and influent statistics match anchor within declared tolerance. *Fail → fix realism before any workflow work.*
- **G2 (week 16).** P0 completes the ladder and its results are interpretable. *Fail → the benchmark is not yet a benchmark; do not start agents.*
- **G3 (week 20).** Evaluation suite computes all metric families from logs alone; pre-registration filed. *Fail → no final runs.*
- **G4 (week 30).** P1 and P2 run inside budget with frozen prompts. *Fail → publish P0 + P1 only; P2 becomes Phase 2.*
- **G5 (week 34).** Analysis complete. Whatever the result, proceed to publication; a null or negative agent result is reported as such.

---

## 12. Outputs and dissemination

**Primary paper.** "AD-AgentBench: a ground-truth benchmark for agent-supported calibration and discrepancy diagnosis of anaerobic-digestion models." Target venues (in order of fit): *Environmental Modelling & Software*; *Computers & Chemical Engineering*; *Water Research X*. Alternative: a datasets-and-benchmarks track (NeurIPS/ICLR) or an AI-for-science workshop if the agent-evaluation contribution is foregrounded.

**Preprint.** arXiv (cs.AI / eess.SY) or ChemRxiv at week 35 to secure priority.

**Artefacts.** Public repository (MIT or Apache-2.0 for code; CC-BY for scenarios and results); Docker image; benchmark card documenting intended use, known limitations and non-claims, including the anchoring status of each plant (Plant A statistics-anchored; Plants B and C dataset-anchored); a leaderboard-ready results format so others can submit workflows.

**Secondary outputs.** (i) A short identifiability-by-tier note (RQ1) suitable for *Water Science & Technology*; (ii) the simulator as the synthetic-test ladder for Phase 2 of the PhD; (iii) a template data contract derived from the observation model, feeding the Ghana commissioning recommendations.

---

## 13. Reproducibility, ethics and openness

- All randomness seeded; all configs versioned; final runs executed from a tagged release.
- No plant data involved in Phase 1; the real-data anchor uses only openly licensed datasets with attribution.
- LLM outputs are logged verbatim; prompts are published; any post-hoc prompt change invalidates a run.
- Negative results, tool failures and invalid actions are reported, not filtered.
- No plant data are requested from authors in Phase 1. The anchor uses only openly licensed datasets (ODC-By, CC BY) with attribution, listed with checksums in `anchor/MANIFEST.json`.

---

## 14. Relationship to the PhD

Phase 1 delivers the first publication and the infrastructure for everything after it:

| Phase | Data | Question | Depends on Phase 1 for |
|---|---|---|---|
| 1 (this proposal) | Synthetic + open anchor | Do agents help, and where? | — |
| 2 | Synthetic + first plant data | Adaptive updating; RL/HMARL for a genuine sequential task | Simulator, registry, evaluation suite |
| 3 | Plant (Ghana / partner) | Shadow deployment, operator value, FEW ledger | Validated workflow, data contract, minimum-tier findings |

The benchmark is therefore not a detour. It is the part of the thesis that can be finished without waiting on plant access, and the part that makes every later claim testable.

---

## Appendix A — Metric definitions (abbreviated)

- **Attribution accuracy** = fraction of runs whose final uncertainty-class label set equals the ground-truth set (exact match) — partial-credit variant reported separately.
- **False kinetic-drift rate** = fraction of runs, in scenarios with truth label ∉ {parameter}, where any kinetic parameter's point estimate moves outside its prior 90% interval.
- **Correct abstention** = in scenarios with a structural or compound label, the final report declines to state the confounded quantity (binary, from structured output).
- **Interval score** (Gneiting & Raftery) at α = 0.1 on the forecast window; **CRPS** where posterior predictive samples exist.
- **Unsupported claim** = any sentence in the final structured report whose referenced evidence field is empty or points to a tool call that did not return the claimed quantity.

## Appendix B — Example scenario definition

```yaml
id: S2-03
plant: B
tier: A
level: 2
duration_days: 180
truth_label: [sensor]
faults:
  - type: gas_meter_scale
    onset_day: 60
    magnitude: 1.08
correct_conclusion:
  flag_sensor: gas_flow
  estimate_scale_factor: true
  kinetic_update_allowed: false
  abstain_on: []
budget:
  simulator_evals: 4000
  wall_clock_min: 90
  assay_units: 2
```
