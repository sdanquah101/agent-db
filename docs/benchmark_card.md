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

| | Visible to a workflow | Hidden truth (`truth_store/<id>/`) |
|---|---|---|
| Plant | Declared geometry, temperature set point, feed catalogue, hydraulics | Realised active-volume error, realised mixing structure |
| Influent | Operator feed log (with unrecorded deliveries and mis-logs), scheduled assays with method noise and turnaround | True per-feed composition and its drift, true COD fractionation, true inert N |
| Digester | Sensor records at the run's tier | Full ADM1 state trajectory, true parameters |
| Faults | Nothing | Fault type, layer, onset, magnitude, target |

CLAUDE.md rule 1 is the hard boundary: **nothing under `workflows/` may import from or
read `truth_store/<id>/`**, and it is enforced three times over — by the layout, by a
static scan of `workflows/`, and by an adversarial suite that drives the workflow-facing
loader `state.run_view.open_run` on a real generated run and asks it for truth by relative
path, traversal, `"."`, `""`, absolute path, symlink, listing, every public attribute it
exposes, and manifest field. That suite carries a **negative control** — a legitimate read
that must still succeed — because a sandbox that refuses everything passes every refusal
test ever written. Evaluation reads `runs/<id>/calls.jsonl` and the truth store; workflows
read neither.

A generated run is **two trees**, so a workflow rooted at the first has nothing to escape
to:

```
runs/<id>/                     <id> is an opaque hash of the cell, not its scenario name
  manifest.json                the REDACTED manifest: plant, tier, horizon, seasonal
                               phase, config versions, git SHA. Written redacted.
  calls.jsonl                  one line per tool call (rule 3); append-only, shared by the
                               harness now and the tool registry later
  observations/
            sensors.json       the tier's record, with units, flags and report times
            feed_log.csv       the operator's feed log (mis-logs applied)
            feed_assays.csv    the assays the tier's mask permits
            operator_notes.json  the operator's log, including any Level-8 false note

truth_store/<id>/              a SEPARATE TOP-LEVEL TREE (lead's ruling, 2026-09-04)
            manifest.json      complete provenance: scenario, seeds, fault layers, config
                               hashes, git SHA
            parameters.json    true parameters per integration segment, truth N_I
            influent.npz       true deliveries, true solids, the true influent series
            fractionation.json true COD fractionation, unrecorded and mis-logged days
            geometry.json      realised volume error, realised mixing, digester health
            states.npz         the full state trajectory and the burn-in state
            channels.npz       every observable channel and the condition flags
            faults.json        the fault plan, the truth label, the answer key
truth_store/index.jsonl        opaque run id -> its cell, for the evaluator
```

**The manifest is redacted at write time, not at read time.** The complete manifest is
hidden truth — the scenario id would leak the row of the ladder (proposal §10), the seeds
would let a workflow regenerate the truth for itself, and the declared fault layers *are*
the uncertainty class §6.7 B scores — so it is written to the truth store, and the file
under `runs/<id>/` never carried any of the three. `truth_store/index.jsonl` is in the
truth store for the same reason: it names the scenario of every run.

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
FOS/TAC overload threshold (0.40) is **percentile-matched** to the anchor — see §5.2 — but
the foaming rule is assumed.

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

### 5.2 What gate G1 caught, fixed, and did not fix

Gate G1 (2026-09-03, `docs/g1_anchor_report.md`) found that a clean Level-0 run on **Plant
B acidified on 5 of 12 seeds** under the then-frozen configuration. Two corrections were
made on the lead's rulings, and **either one alone is sufficient**:

- **The blend tank the plant always had.** `plant_B.yaml` had described the high-strength
  waste as "trucked deliveries blended in a 65,000-gal tank" and the simulator had never
  implemented it, so arrivals reached the biomass as acid pulses. It is now part of the
  **declared contract** (`sim/plants/equalisation.py`), visible to workflows.
- **The feed's strong cations, calibrated to the anchor's own digester alkalinity.**
  Simulated alkalinity went 2.78 → **5.12** kg CaCO₃ m⁻³ against the plant's 5.04, and pH
  to **7.29** against 7.27. The pH is *not* independent corroboration and this card no
  longer reads it as such: in a bicarbonate-buffered digester pH is a function of
  alkalinity and pCO₂, so fixing one and observing the other land is one measurement
  reported as two. The alkalinity row is reported as **calibrated to anchor** and excluded
  from the anchor-match count.

On a twenty-four-seed panel with both in place, **24 of 24 runs are sound** and all 117
matrix cells are sound. The sound/soured labelling stays as instrumentation.

**Still open**, and stated because it bears on what the benchmark can be used for:

- **A residual VFA gap of ~1.5× remains**, and it is smaller than it looks in older
  documents. On the **true-VFA** convention the simulator carries 0.067 against the plant's
  1.178 kg m⁻³ — but the plant's column is a titration, not a chromatographic VFA, so those
  two numbers were never the same quantity. Compared like with like (§5.3) it is **0.775
  against 1.178**, and FOS/TAC **0.150 against 0.233**. **No kinetic parameter has been
  changed**, and `docs/vfa_gap.md` measured that none *could* close the true-VFA gap: the
  model is bistable in `k_m_ac` and the anchor's value lies between the branches. The
  remaining 1.5× is pinned in both directions by `tests/test_g1_anchor.py`, so it can
  neither grow nor be quietly tuned away.
- **The consequence that used to follow from it is resolved.** Conditional missingness — and
  with it the Level-4 `informative_missingness` row — had almost nothing to act on, because
  the flag read a quantity that sits far below its threshold. Since the lead's ruling B the
  trigger reads the hidden process state and fires on **7.67 % of days in every sound run**
  (§5.4), against the plant's own 7.78–9.18 %.
- **`S6-01` (omitted SAO) is no longer inert** (lead's ruling 1, 2026-09-09). Plant A
  declares **two baselines**: `adapted`, acetoclastic, where the omitted syntrophic pathway
  carries no flux; and `unadapted`, at ADM1's default constant, where the acetoclasts have
  washed out and syntrophic oxidation carries the entire acetate flux. S6-01 is staged on
  the second, where the omission bites. `S6-04` is the same omission on the first, scored on
  **abstention** — the correct conclusion is that no structural residual is detectable — so
  the pair distinguishes a diagnosis from a workflow that always answers "structural".

### 5.3 Two FOS/TAC conventions, and which one each number is in

**This is the most important caveat in the card for anyone comparing a simulated FOS/TAC
with a plant's**, and since the lead's ruling A of 2026-09-09 the benchmark reports both.

| | what it is | where it appears |
|---|---|---|
| **True VFA** | the sum of the model's volatile fatty acids, as acetic acid | the hidden `vfa_total` channel and the hidden `fos_tac_true_vfa` channel. **No sensor sees it.** |
| **Titrimetric FOS** | the acid consumed between pH 5.0 and pH 4.4, reported as acetic acid | the `vfa_titrimetric` channel, the `vfa_total` **sensor**, and the `fos_tac` channel — and the anchor's own VFA column and FOS/TAC |

A titrimetric FOS counts everything titratable in that window: bicarbonate carry-over,
lactate, phenols. In a digester most of it is **bicarbonate** — measured here, **86–90 %** of
the reading — which is why it over-reads true VFA severalfold.

**The transfer function has no fitted parameter.** `sim.observation.channels.titrimetric_fos`
is declared chemistry: κ frozen at 1.0, and every equilibrium constant the truth model's own
through `sim.adm1.physchem.temperature_corrected`. At Plant B's 308.48 K it gives
pK_a(acetate) 4.760, pK_a(CO₂) 6.305, a carry-over fraction of 0.0349 of S_IC, and an
implicit scale-up of 1/f_ac = **3.02** — the Nordmann formula's own factor, derived rather
than asserted.

**What it did to the comparison.** Simulated FOS/TAC went from 0.013 to **0.150** against the
plant's 0.233, and the VFA row from a factor of 17.5 out to **1.51×**. That is a measurement
model being made correct, not a gap being closed by tuning: **no kinetic parameter has been
changed**, and `docs/vfa_gap.md` still holds — the model is bistable in `k_m_ac` and the
anchor lies between the branches, so the *true-VFA* gap cannot be closed by fitting at all.

**A finding, and it corrects an earlier diagnosis.** An earlier note called this a "variance
deficit" in the model. It is not: true VFA's day-to-day spread (p92/median ≈ 2.1) is if
anything larger than the anchor's FOS/TAC spread (1.74). What is flat is the *titrimetric*
FOS/TAC (≈ 1.1), and it is flat because most of it is bicarbonate tracking slowly-varying
alkalinity. So:

> **The titrimetric convention masks the VFA dynamics it is meant to report.**

That is a property of the measurement, not of the model, and it is why conditional
missingness triggers on the hidden state (§5.4).

### 5.4 Two thresholds that are deliberately different things

| | reads | fires on | used for |
|---|---|---|---|
| **conditional-missingness trigger** | hidden true VFA > 2.00× its 30-day trailing median | **7.67 %** of days on sound Plant B runs (per-run 2.65–16.56 %, all 24 runs) | §6.1 conditional missingness, and the Level-4 `informative_missingness` row |
| **operator-visible overload** | titrimetric FOS/TAC > 0.40 | 0.17 % of days (1 of 24 runs) | what an operator would call an overload; reported, never a trigger |

The **trigger** reads the plant, not a reading: instruments fail during the transients that
identify the process whether or not anyone has taken a measurement, and the reading it used
to use masks those transients (§5.3). Its cut-off was not tuned — 2.00× is the lead's figure
as written, and it lands on 7.67 % against the plant's own 7.78–9.18 % exceedance. Its
trailing window **excludes the current day**, so an excursion cannot drag its own reference
up and mask itself. The cut-off is 2.00× on every plant: **differences between plants are
recorded, not tuned away.**

The **threshold** is percentile-matched to the anchor: the anchor's titrimetric FOS/TAC has
its 92nd percentile at 0.402 (Dig1) and 0.408 (Dig2), n = 861 each, and the 92nd is the
closest percentile to 0.40 of any between the 50th and the 99th. It fires rarely in
simulation because the simulated distribution still sits ~1.5× below the plant's; the
threshold is not moved to compensate.

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
- **Conditional missingness barely fires on a healthy digester** (§5.2), so the Level-4
  `informative_missingness` row is close to a duplicate of Level 1 on Plant B.
- **`S6-01` is inert** (§5.2) pending a decision on Plant A's adapted inhibition constant.
- **Acetoclastic and syntrophic methanogenesis cannot coexist** at a steady state: they
  compete for one substrate, so one always excludes the other. The pathway-shift scenarios
  are therefore staged as *transitions* from an adapted state rather than as faults applied
  to a mixed community, and the truth model carries a trace re-seeding term in the feed
  because ADM1 has no immigration and a population at zero can never return.
- **One answer key per scenario, not one per tier.** A fault whose instrument the tier does
  not carry (the Level-2 methane-analyser flatline at Tier A) is unobservable there, while
  its `correct_conclusion` still names the instrument. Flagged for the lead.
- **Plant A declares an adapted inhibition constant** (`adaptation.K_I_nh3`), because a
  digester running for years above 3 kg N/m³ of ammonia does not have ADM1's sewage-sludge
  community. It is a declared plant property, not a hidden one.

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
- A run directory is **self-contained and deterministically named**: the id is a hash of
  (scenario, plant, tier, seed, replicate), so regenerating a cell overwrites its own
  directory rather than accumulating copies, and `truth_store/index.jsonl` — in the truth
  store, because it names the scenario of every run — maps ids back to cells for the
  evaluator, one line per run id however often a cell is regenerated.
- The manifest records the **declared version and content hash of every configuration file**
  the run read, plus the git commit, marked `-dirty` when the tree was not clean.
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
