# configs/

Frozen configuration: budgets per (scenario, tier) cell, solver settings and numerical
tolerances, agent prompts, LLM model versions, temperature and retry policy.

Nothing numerical is hard-coded in `sim/`, `tools/` or `workflows/` — it lives here and
is versioned, so that a run can be reproduced from a tag (proposal §7, §13).

- `adm1/petersen_matrix.yaml` — standard ADM1 stoichiometry as data: 26 components with
  units and COD/C/N/charge contents, 19 processes with expression-valued entries, and the
  gas-transfer pairings. Loaded by `sim.adm1.load_matrix`; conservation is tested.
- `adm1/params_bsm2.yaml` — the BSM2 default parameter set (Rosen & Jeppsson 2006), units
  in comments and in the Pydantic schema `sim/adm1/schema.py`.
- `adm1/plant_bsm2.yaml` — BSM2 digester volumes and temperature.
- `adm1/solver.yaml` — `solve_ivp` method and tolerances, pH root-find bracket and
  tolerances, negative-state clipping flag.
- `adm1/extensions.yaml` — the §6.1 extensions as additional components, processes
  (same expression format as the base matrix), parameters and speciation switches:
  `sao` (X_sao, acetate oxidation + decay, own NH₃ inhibition), `ionic_strength` (Davies
  activity correction with A scaled to T_op; no new states), `carbonate` (second
  carbonic-acid dissociation in the balance; own switch, default off) and
  `precipitation` (S_ca, X_caco3, SI-based calcite rate; K_sp from Plummer & Busenberg
  1982 at T_op, in code, not a parameter). `shared_parameters` holds constants used by
  more than one extension (pK_a2). Loaded by `sim.adm1.load_extensions`; each extension
  is switchable independently.
- `plants/plant_{A,B,C}.yaml` — the three virtual plants as *declared* to workflows,
  including Plant B's `equalisation` block (lead's ruling of 2026-09-03: the 65,000-gal
  blend tank its trucked high-strength waste passes through, without which arrivals reached
  the biomass as acid pulses and 5 of 12 clean seeds acidified) and Plant A's two declared
  community states (`baselines`, lead's ruling 1 of 2026-09-09), declared **qualitatively
  only**: what constant the acclimated community carries and what each state measures at
  are in the truth-side record `sim/plants/truth/plant_A.yaml`, which the harness reads and
  a workflow cannot (lead's ruling B5, 2026-09-10). Everything here is declared, not hidden
  (schema `sim/plants/schema.py`): geometry, temperature, feed catalogue, hydraulics,
  anchoring with sources, truth-model extensions, scenario subset, and the
  *distribution* of the hidden active-volume error (its realisation is sampled per run
  and is hidden truth). B and C are re-derived from the Muscatine daily file by
  `tests/test_plants.py`. Frozen by the lead's answers of 2026-09-02 (decisions log,
  "Plant configurations A/B/C — frozen").
- `influent/feed_fractionation.yaml` — the feed-fractionation catalogue of the influent
  generator (schema `sim/influent/schema.py`), keyed by the plants' feed ids: TS, VS/TS,
  six-way COD fractionation and its Dirichlet spread, the per-feed inert COD equivalent
  (1.2 lignocellulosic / 1.42 sludge-derived, lead's freeze), a literature COD/VS as a
  *check* on the value derived from the fractionation (±10 %, enforced), pH, TAN/TKN, per-feed
  inert N (applied by the truth model only), inorganic C, strong ions, calcium, with
  sources. **Provisional** (decisions log, "Feed fractionation values are provisional";
  revised on the lead's consistency answers, "Feed catalogue consistency"): every value
  is `# DESIGN` and `status: provisional`. Loaded by `sim.influent.load_feed_fractionation`.
- `influent/generator.yaml` — the influent generator's statistics (schema
  `sim/influent/generator.py`): per plant and feed, the delivery-day model (continuous /
  weekday / Markov), the lognormal AR(1) amount with its seasonal term, the moisture
  AR(1), unrecorded-delivery and mis-log rates, the assay schedule; and the shared assay
  noise and lag. Plant B/C values are re-derived from the Muscatine daily file by
  `tests/test_generator.py` through `anchor/ingest_muscatine.py` (seasonal amplitudes
  are bounded by the monthly-mean statistic rather than equal to it); assumed values
  are marked `ASSUMED`. Loaded by `sim.influent.load_generator_config`.
- `adm1/initial_state_rj2006.yaml` — the Rosen & Jeppsson (2006) Table-5 steady state as
  data, so `sim/` can reach it without importing the disposable probe code in
  `scripts/adm1_candidates/`. Loaded by `sim.adm1.load_initial_state`; only the run
  harness's burn-in starts there, and no scenario does.
- `runs/harness.yaml` — how the run harness stages a scenario (schema
  `sim/run/harness.py::HarnessConfig`): burn-in length and output cadence, the scenario's
  output cadence, the extension states the burn-in starts from (X_sao must be seeded or
  the SAO extension is silently inert), and the health thresholds that label a generated
  run sound or soured, and the trace of syntrophic oxidisers the feed carries (ADM1 has no
  immigration, so without it a washed-out pathway can never return and the Level-6/7 rows
  are inert). The burn-in is 400 d and is **measured** to converge on all three plants.
- `faults/log_notes.yaml` — the operator log notes placed in **every** run (a handful of
  true, diagnostically useless ones) plus the Level-8 note that asserts a false cause. If
  only the adversarial run had notes, the file's existence would be the answer. All
  DESIGN: no open dataset of operator notes exists. Loaded by `sim.run.notes`.
- `faults/injection.yaml` — constants that shape a fault beyond the single magnitude a
  scenario row carries (schema `sim/faults/schema.py::FaultInjectionConfig`): for the
  Level-6 mixing variant, the bypass as a share of the stagnant fraction and the
  stagnant-zone exchange rate. Loaded by `sim.faults.load_fault_config`.
- `observation/sensors.yaml` — the observation model (schema `sim/observation/schema.py`),
  version 2, frozen by the lead's answers of 2026-09-02 (decisions log, "Observation
  defaults, and missingness as a tier policy"). Three blocks: the **condition thresholds**
  that raise the overload and foaming flags; the **missingness policy** — a base rate per
  tier (8/4/2 % at A/B/C) and stress multipliers per instrument kind (4× overload and 3×
  foaming online, 1.5× for lab assays); and **15 sensors** with their schedule, noise,
  drift, fouling, flatline and saturation. The three instrumentation tiers of §6.4 are
  nested masks and also carry the plant's monitoring capability: laboratory turnaround
  (7/3/1 d) and recalibration cadence (90/30/30 d). What is *intrinsic to an instrument*
  is the sensor's; what is a *property of the plant* is the tier's. Digester temperature
  and biogas noise and flatline rates are re-derived from the Muscatine 1-minute SCADA
  file by `tests/test_observation.py`; the overload threshold is the 92nd percentile of
  the plant's own FOS/TAC column; everything else is marked `ASSUMED`, including every
  missingness rate (the SCADA file is pre-cleaned, so no dropouts exist to fit). Loaded by
  `sim.observation.load_observation_config`.
- `plant_a_statistics.yaml` — the published operating envelopes Plant A is anchored to
  (Tisocco et al. 2024, 2026), the published HRT inconsistency and the chosen 35–45 d,
  with `todo` nulls where the tables are not yet transcribed (the lead transcribes the
  ammonia envelope).
