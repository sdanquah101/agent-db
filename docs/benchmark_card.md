# AD-AgentBench — benchmark card

*Living document. Started 2026-09-02, at Milestone 2 (weeks 7–9 of the plan in
`docs/proposal.md` §9.3). Sections marked **NOT YET BUILT** describe components that are
designed but not implemented; they are listed here so that the card grows with the
benchmark rather than being written at the end, when the omissions are hardest to
remember. The card is the place where the benchmark says what it does **not** claim.*

Proposal: `docs/proposal.md`. Decisions log: `docs/decisions.md`. Progress:
`docs/milestones.md`. Anchor datasets: `docs/anchor_datasets.md`.

---

## 1. What this benchmark is

A ground-truth benchmark for **agent-supported calibration and discrepancy diagnosis** of
anaerobic-digestion (AD) process models. A simulator generates plants whose true
parameters, true influent composition and true fault labels are known and hidden; a
workflow sees only what an instrumentation tier would let it see; evaluation compares what
the workflow concluded against what was actually done to the plant.

The question is not "can a model be fitted" but "does an agent-supported workflow reach
the *right diagnosis* — the right layer of the model, the right parameter, the right
statement about what it cannot identify — from a realistic observation window."

## 2. Intended use

- Comparing calibration/diagnosis **workflows** (scripted, single-agent, multi-agent) on
  identical scenarios, budgets and observations.
- Measuring how diagnosis quality degrades with **observation quality** (the three
  instrumentation tiers of §6.4) and with **discrepancy level** (Levels 0–8, §6.3).
- Measuring whether a workflow **knows what it cannot know**: identifiability statements,
  refusals and calibrated uncertainty count for as much as point estimates.
- Studying identifiability of ADM1 parameters under realistic sampling, as a by-product
  (§12, secondary output i).

## 3. Out-of-scope uses, and explicit non-claims

- **Not a claim about real plants.** Performance here does not establish that a workflow
  will diagnose a real digester. The truth model is ADM1 with four extensions, not a
  digester; a workflow that scores well has done well against *this* structure.
- **Not a model-accuracy benchmark.** ADM1's own adequacy is not under test.
- **Not a control benchmark.** No workflow operates a plant; nothing here is validated for
  process control, safety interlocks or dosing decisions.
- **Not an LLM leaderboard.** Model versions, prompts and temperatures are frozen config
  (`configs/`), and a change to any of them invalidates a run rather than producing a new
  entry.
- **Not evidence of general agentic capability.** The task is narrow, the tool registry is
  fixed, and the budgets are tight by design.
- **No claim of anchor-equivalence.** The anchor (§5) shows the *statistics* of the
  simulated influent and sensors are of the right kind and size. It does not show that a
  simulated run would be mistaken for a real one.

## 4. What is generated, and what is hidden

| | Visible to a workflow | Hidden truth (`runs/<id>/truth/`) |
|---|---|---|
| Plant | Declared geometry, temperature set point, feed catalogue, hydraulics | Realised active-volume error, realised mixing structure |
| Influent | Operator feed log (with unrecorded deliveries and mis-logs), scheduled assays with method noise and turnaround | True per-feed composition and its drift, true COD fractionation, true inert N |
| Digester | Sensor records at the run's tier | Full ADM1 state trajectory, true parameters |
| Faults | Nothing | Fault type, layer, onset, magnitude, target |

CLAUDE.md rule 1 is the hard boundary: **nothing under `workflows/` may import from or
read `runs/<id>/truth/`**, and a test enforces it. Evaluation reads
`runs/<id>/calls.jsonl` and the truth record; workflows read neither.

**Instrumentation tiers are masks on identical truth** (§6.4). Tier C contains Tier B
contains Tier A — the schema validates the containment and the tests check it. Two runs at
different tiers with the same seed are the same digester seen through different windows,
never different digesters. Tier A additionally loses more samples (8 % against 2 %), waits
longer for laboratory results (7 d against 1 d) and recalibrates less often (quarterly
against monthly), because those are properties of a plant's monitoring capability rather
than of an instrument.

**Missingness is conditional on the process state** (§6.1): a sample is four times more
likely to be lost from an online probe during overload and three times during foaming, so
gaps coincide with exactly the transients that identify the process, and naive
interpolation across a gap destroys information rather than merely losing precision.

## 5. Anchoring status — read this before quoting any number

| Plant | Anchoring | What that means |
|---|---|---|
| **A** — AFBI-type cattle slurry + grass silage, 650 m³, 41 °C | **Statistics-anchored** | No time series exists. Feed bases, OLR, HRT and ammonia envelopes come from the *published summary statistics* of Tisocco et al. (2024, 2026). No author data request was made (§13). |
| **B** — Muscatine-type co-digestion WRRF (sludges + high-strength industrial waste + FOG), 1,836 m³, 35.3 °C | **Dataset-anchored** | Derived from the Muscatine WRRF daily file (Schroer & Just 2024, ODC-By 1.0) and re-derived by `tests/test_plants.py`, `tests/test_generator.py`. |
| **C** — the same digester on sludge streams only | **Dataset-anchored** | As B. |

Sensor noise for two channels (digester temperature, biogas flow) and both flatline rates
are anchored to the Muscatine 1-minute SCADA file and re-derived by
`tests/test_observation.py`. **Everything else in the observation model is a design value
marked `ASSUMED`**, including every missingness rate: the provider pre-cleaned the SCADA
file, whose two channels are 100 % finite, so no dropout statistics exist to fit. The
FOS/TAC overload threshold (0.40) is anchored — it is the ~92nd percentile of the plant's
own FOS/TAC column — but the foaming rule is assumed.

Every configuration value in `configs/` carries `# DESIGN` and a source, or the marker
`ASSUMED` with the reason. A number without a source is a bug.

### 5.1 Corrections the anchor caught

Recording these is the point of anchoring: they are cases where a plausible design value
was wrong and the data said so.

- **FOG solids, Plant B (2026-09-02).** The feed catalogue assumed fat-oil-and-grease at
  **10 % total solids**, a defensible figure for a grease-trap concentrate. At that
  strength FOG carried 53 % of Plant B's COD load on 2.5 % of its volume, and the
  digester acidified in the stochastic influent generator — pH 4.50 and 0.9 % methane, a
  plant that no operator would run. The Muscatine daily file gives FOG volumes and the
  plant's own loading, from which the trucked FOG is **≈ 2.0 % TS**: a dilute, watery
  receipt, not a concentrate. The catalogue now carries `ts: 0.020` and the plant is
  stable. The error was invisible in steady-state tests with nominal feeds and only
  appeared once deliveries became stochastic; `tests/test_plausibility.py` now pins the
  operating envelope so it cannot recur silently.

## 6. Scenario ladder (§6.3)

Levels 0–8, from "the fitted model is the truth model" up to compound discrepancies:
sensor faults (Level 2), influent misreporting (Level 3), state faults, parameter shifts
(Level 5), **structural mismatch** (Level 6: omitted SAO, imperfect mixing) and their
compounds (Level 7–8). Plant A runs a reduced subset (Levels 2–7 at Tier A only) and is
reported separately; Plants B and C carry the full factorial.

**Level-6 runs are never scored on parameter recovery.** When the truth model has a
structure the fitted model does not, "the right parameter value" does not exist; the
scored quantity is whether the workflow *identified the structural mismatch* and said so.

### 6.1 What every fault magnitude means

Generated from `sim.faults.benchmark_card_rows()` and pinned by
`tests/test_faults.py::test_the_benchmark_card_carries_the_generated_fault_table`, so the
card cannot drift from the code that applies these faults. The *layer* is where the fault
is applied, and is also what its truth label means (§6.3).

<!-- BEGIN GENERATED: fault semantics -->
| Fault | Layer | Magnitude unit | Meaning |
|---|---|---|---|
| `adversarial_log_note` | workflow | - (ignored; the note text is scenario content) | An operator note asserting a false cause is placed in the run's log. Neither truth nor observation changes; applied by the run harness. |
| `ammonia_inhibition_shift` | parameter | - (multiplier on K_I_nh3 from the onset day) | The free-ammonia inhibition constant of the acetoclastic methanogens changes at the onset day, as an adapted community would; the run is integrated in two segments. A bounded update of that parameter is the correct action. |
| `biomass_misinitialised` | state | - (multiplier on every biomass state at t = 0) | Every biomass state starts at the given multiple of the nominal initial value, so state estimation must converge before any parameter can be identified. |
| `ch4_analyser_flatline` | observation | - (ignored; the episode length is the fault's duration_days) | The methane analyser holds its last value for the whole fault window. The magnitude is not used: the episode is defined by onset_day and duration_days. |
| `feed_mislabelled` | influent | - (Dirichlet concentration of the mislabelled batch's true fractionation) | One feed's true COD fractionation departs from its catalogue entry for the fault window: the true fractionation is redrawn with the given concentration (smaller = further from the catalogue), while the operator's log and the catalogue still say the entry. Revising the mapping is the correct action; hydrolysis is not at fault. |
| `gas_meter_scale` | observation | - (multiplicative scale factor) | Multiplies the gas-flow sensor's reading from the onset day; 1.08 is the +8 % scale error of the Appendix-B example. The digester is untouched, so the correct conclusion is to estimate the factor, never to move a yield parameter. |
| `hydrolysis_regime_change` | parameter | - (multiplier on k_hyd_ch, k_hyd_pr and k_hyd_li from the onset day) | All three hydrolysis constants change at the onset day, as a change in feed particle size would do. Only hydrolysis may be updated in response. |
| `imperfect_mixing` | structure | - (stagnant volume fraction; the bypass is a fifth of it) | The truth reactor is the two-zone structure of sim.plants.mixing with the given stagnant fraction, a bypass of one fifth of it, and the configured exchange rate; the fitted model still assumes an ideal CSTR. 0 reduces to the CSTR exactly. |
| `informative_missingness` | observation | - (multiplier on the conditional missing multipliers) | Scales the foaming and overload multipliers of every sensor, so instruments fail *during* the transients that identify the process and naive interpolation destroys information. |
| `moisture_drift` | influent | - (relative change in the feed's total solids over the fault window) | The feed's total solids ramp by the given fraction across the window (negative = wetter), lowering the VS delivered per tonne. The trend is in the influent, not the kinetics. |
| `omitted_precipitation` | structure | - (ignored; as omitted_sao, for the calcite sink) | The truth model runs with the precipitation extension on and the fitted model without it; the residual appears in alkalinity and pH. |
| `omitted_sao` | structure | - (ignored; the truth keeps the extension, the fitted model must not have it) | The truth model runs with syntrophic acetate oxidation on and the fitted model without it. No magnitude: the fault is the omission itself. |
| `ph_electrode_drift` | observation | pH units per day (signed; negative = reads low) | Adds a deterministic ramp to the pH sensor from the onset day, on top of the electrode's own random-walk drift. A calibration fault is removed by a calibration, so the ramp is reset on the tier's recalibration cadence like the intrinsic drift is: the reading walks away and jumps back, which is the drift-then-step signature of the Level-2 row. |
| `random_gaps` | observation | - (multiplier on every sensor's base missing rate) | Adds gaps at a rate of (multiplier - 1) x the sensor's base rate, on top of whatever the conditional model already drops. The added term is unconditional, so the extra gaps are missing-completely-at-random and carry no information about the state; scaling the base rate instead would scale the stressed rate by the same factor and the added gaps would be as informative as the originals, which is informative_missingness's job, not this one. |
| `sensor_noise` | observation | - (multiplier on every sensor's noise cv and sd_abs) | Scales the declared measurement noise of every sensor in the tier; 1.0 is the declared instrumentation, 2.0 a plant whose instruments are twice as noisy. |
| `tool_failure` | workflow | - (probability that the named tool returns a non-converged result) | The tool registry makes a tool fail with the given probability; the simulator and the observation record are untouched. Applied by the run harness. |
| `unrecorded_delivery` | influent | - (multiple of the feed's median delivery that arrives unlogged) | An extra delivery of the given size arrives on the onset day and never enters the feed log, so the COD balance closes only if the analyst notices. |
<!-- END GENERATED: fault semantics -->

## 7. Metrics — **NOT YET BUILT** (Milestone, weeks 17–20)

Designed in §7: diagnosis accuracy by layer, parameter recovery where it is meaningful,
calibrated uncertainty, identifiability statements, budget adherence, invalid-action rate.
Metrics are computed **from logs only** (`runs/<id>/calls.jsonl`), never from workflow
self-reports. Pre-registration (OSF or equivalent) precedes the final runs; deviations
from the analysis plan are documented rather than absorbed.

## 8. Known limitations

- **Sulfur is not modelled.** ADM1 has no sulfur, so off-gas H₂S — a Tier-C channel in
  §6.4 — has no truth to observe. It is declared absent rather than faked.
- **Reactor temperature varies only as sensor noise**, because the truth model integrates
  at a fixed set point; a temperature *excursion* is a fault, not a background process.
- **One truth structure.** Every run is ADM1 (+ SAO, ionic strength, carbonate,
  precipitation). Structural-mismatch scenarios vary what the *fitted* model omits, not
  what nature is.
- **Plant A is not dataset-anchored** (§5) and its influent statistics are the weakest
  part of the simulator.
- **The two-zone mixing variant is a caricature.** Imperfect mixing is a bypass plus a
  stagnant zone with a first-order exchange, not CFD; its signature is a gas deficit that
  grows with load.
- **Assumed missingness.** See §5. If a reviewer wants the dropout statistics fitted, a
  raw (uncleaned) SCADA export would be needed and does not exist openly.
- **No human baseline.** There is no measurement of what an experienced AD modeller would
  conclude from the same window. Workflow-to-workflow comparison is the only comparison
  the benchmark supports.

## 9. Reproducibility

- Every stochastic component takes an **explicit seed** and consumes one
  `numpy.random.default_rng` stream in a documented, fixed order (CLAUDE.md rule 4). Same
  seed, same run, bit-for-bit.
- Fault layers hold their **own** stream, so a faulted run differs from its clean twin
  only by the fault (the paired-run property; tested).
- Every tool call is logged with name, version, argument hash, runtime and outcome.
- Budgets (simulator evaluations, wall-clock, assay units) are enforced in the tool
  registry, not in workflows, so no workflow can grant itself more.
- All numerical tolerances and solver settings live in `configs/`, versioned, so a run is
  reproducible from a tag.
- Final runs execute from a tagged release; Docker image and pinned dependencies at
  release (§13).

## 10. Licensing and attribution

Code MIT/Apache-2.0; scenarios and results CC-BY (§12). Anchor data are **not
redistributed**: `anchor/MANIFEST.json` lists each source with its licence, URL and
checksum, and the ingestion scripts fetch it. The Muscatine datasets are ODC-By 1.0
(Schroer & Just 2024) and require attribution; the Tisocco et al. papers are CC BY 4.0 and
only their published summary statistics are used. No plant data are requested from
authors in Phase 1 (§13).

## 11. Ethics and reporting

No confidential or personal data are involved. LLM outputs are logged verbatim and prompts
are published; a post-hoc prompt change invalidates a run. **Negative results, tool
failures and invalid actions are reported, not filtered** — including the outcome that
agent-supported workflows do not beat the scripted P0 baseline, which is a publishable
result of this benchmark and is pre-registered as such.

## 12. Contact

Repository: `sdanquah101/agent-db`. Design authority and correspondence: the project lead.
