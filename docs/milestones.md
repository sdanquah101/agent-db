# Milestones

Progress against proposal §9.3. Updated at the end of every session with what was done,
what is blocked, and what the next session should start on. Resource cost is tracked
per session (wall-clock, notable compute, disk) because cost is itself a benchmark
metric (§6.7 C) and a deployment constraint (§2).

---

## Milestone 1 — Base ADM1 implementation selected; open datasets identified (weeks 1–2)

Exit criterion: stiffness tests pass; licence cleared; anchor dataset(s) chosen.

### Session 2026-09-02

**Done**

- Repository scaffold per CLAUDE.md §9.2: all packages with role docstrings,
  `pyproject.toml` (Python ≥ 3.11, ruff + pytest configured), GitHub Actions CI (ruff
  check, ruff format, pytest on 3.11/3.12), Apache-2.0 `LICENSE` + `NOTICE` (CC-BY-4.0
  for scenarios/results), `.gitignore` excluding `runs/`.
- `scenarios/schema.py`: Pydantic v2 contract for Appendix B, closed enums, unit-bearing
  field descriptions, consistency validators; `scenarios/S2-03.yaml`; 16 schema tests.
- `tests/test_truth_isolation.py`: AST check that nothing under `workflows/` imports a
  `truth` module or references a `truth/` path, with a self-test on a synthetic
  violating file.
- ADM1 candidate evaluation (`scripts/adm1_candidates/`, `docs/adm1_comparison.md`):
  installed and probed PyADM1, bsm2-python, QSDsan/EXPOsan and ADM1F (both source
  variants); installed PyADM1ODE and ran its test suite; inspected the Weinrich
  ADM1-R1…R4 MATLAB/Simulink sources. Four implementations agree to three significant
  figures on both probes; recommendation written up with reasons.
- `docs/decisions.md` (eight entries), `README.md`.

**Decided at end of session**

- ADM1 recommendation **accepted** by the lead with three conditions (time-box to
  weeks 3–6 with a bsm2-python-fork fallback; QSDsan/ADM1p as equation reference only,
  never a dependency; Weinrich R3/R4 ported from the published equations as fitted
  models). Recorded in `docs/decisions.md`.

**Blocked / open**

- **Open datasets not yet identified** (second half of the Milestone-1 exit criterion,
  proposal §8). Not started this session. → Done in the second session of 2026-09-02,
  below.
- ADM1F could not be built as its README describes (PETSc external downloads are
  blocked in the sandbox; the shipped makefile is incompatible with PETSc ≥ 3.15). It
  built against Ubuntu's `petsc-dev` 3.19 + `libadolc-dev` by compiling the source
  directly. Recorded as a deployability finding, not a blocker.

**Next session should start on**

1. Anchor-dataset search (§8): Tisocco et al. co-digestion data, Weinrich-group
   agricultural plant data, Zenodo/Mendeley AD time series; record candidates and
   licences. This closes Milestone 1.
2. Milestone 2 — `sim/adm1/` skeleton: state vector, Petersen matrix as data
   (`configs/`), rate function, gas phase, algebraic pH; ring test against
   `scripts/adm1_candidates/results/bsm2python.json` (primary oracle) and
   `adm1f.json` on Probes 1 and 2, **plus the BSM2 dynamic influent case** (add a
   bsm2-python probe run on PyADM1's `digester_influent.csv` to the harness first, so
   the oracle values are recorded). Acceptance: 3 s.f. agreement on all three by end of
   week 6, else fall back to a bsm2-python fork.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Session total | ≈ 1 h 40 min | — | one agent session; 4 vCPU / 15 GB container |
| Install: QSDsan + EXPOsan | ≈ 8 min (background) | 1.0 GB | largest dependency tree |
| Install: bsm2-python | ≈ 2 min (background) | 0.7 GB | numba, matplotlib pulled in |
| Install: PyADM1ODE | ≈ 1 min | 0.5 GB | test suite 790 tests / 20 s |
| Install: PyADM1 | < 1 min | — | git clone only |
| Build: ADM1F | ≈ 5 min | 0.6 GB | PETSc-from-source failed (network policy, 1.5 min); apt `petsc-dev` 45 s; 2 compiles ≈ 30 s each |
| Probes: all candidates | < 3 min compute | 32 KB results | PyADM1 ≈ 50 s/run ×3; bsm2-python ≈ 10 s; QSDsan ≈ 8 s; ADM1F ≈ 2 s/variant |
| CI (GitHub Actions) | 2 runs × 3 jobs, ≈ 25 s each | — | first runs on the branch |

Totals: ≈ 3.3 GB scratch disk (all outside the repo), no GPU, no external services.

No LLM-agent compute was spent inside the benchmark (no workflows exist yet); the
figures above are development cost only.

### Session 2026-09-02 (second session) — open anchor datasets for §8

**Exit criterion "open datasets identified": done.** Datasets are identified,
characterised and (where openly licensed) fetched with checksums, and the lead has fixed
the anchor: Plants B and C dataset-anchored to Muscatine WRRF; Plant A
statistics-anchored to Tisocco et al. (2024, 2026) for all of Phase 1, with a reduced,
separately reported scenario subset. Full write-up: `docs/anchor_datasets.md`; decision
and consequences: `docs/decisions.md`, proposal v0.2.

**Done**

- Searched the sources named in §8 plus DataCite, Zenodo, figshare, OSF, DBFZ DataLab
  and GitHub; 17 candidates characterised from pages/files actually read (table in
  `docs/anchor_datasets.md`).
- Fetched and checksummed three openly licensed datasets into `anchor/raw/`:
  Muscatine WRRF daily + 1-minute SCADA (ODC-By 1.0; 5 files, 88.9 MB), the matching
  MIT code archive from Zenodo (12.6 MB), and the ILRI farm-scale digester + weather
  set from Mendeley Data (CC BY 4.0; 12 MB).
- `anchor/MANIFEST.json` (schema `anchor/manifest.py`), `anchor/fetch.py` (reproduce
  and verify; pure I/O), `tests/test_anchor_fetch.py` (10 tests, offline, local HTTP
  server), `.gitignore` rules keeping only the < 1 MB ODC-By files in git with an
  `ATTRIBUTION.md`.
- Read both Tisocco et al. papers in full (2024 FESE; 2026 ESE + supplement): neither
  deposits its plant data. Recorded their operating envelopes as the Plant-A summary
  statistics.

**Decided at end of session**

- Anchor recommendation **accepted with amendments** by the lead: no author data
  request in Phase 1; Plant A statistics-anchored permanently for this phase; the §7
  factorial plants are B and C; Plant A runs Levels 2–5 at Tier A and is reported
  separately; benchmark card and paper describe A as statistics-anchored and B/C as
  dataset-anchored. Proposal copy bumped to v0.2. Recorded in `docs/decisions.md`.

**Blocked / open**

- Three pages could not be read from this environment (MDPI, IWA, ScienceDirect return
  403); their data statements are recorded as unknown, not guessed.

**Next session should start on**

1. Milestone 2 truth model: `sim/adm1/` skeleton (state vector, Petersen matrix as data
   in `configs/`, rate function, gas phase, algebraic pH) ring-tested against
   `scripts/adm1_candidates/results/bsm2python.json` on Probes 1 and 2, then the three
   extensions of §6.1 (ionic-strength correction, syntrophic acetate oxidation,
   precipitation / inorganic-carbon sink).
2. `anchor/ingest_muscatine.py`: parse the daily and SCADA files into the unit-explicit
   schema (°F → °C, gallons → m³, cfm → m³ d⁻¹ with an explicit "reference conditions
   unknown" flag), then compute the §8 step-2 statistics (feed-batch variability,
   missingness-by-event, SCADA noise and dropout) for Plants B and C.
3. `configs/plant_a_statistics.yaml`: the Tisocco et al. operating envelopes and
   feedstock tables as the Plant-A anchor, with citations.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Session total | ≈ 1 h 15 min | — | one agent session; most publisher/repository hosts blocked for the first ~40 min, then allow-listed |
| Web search + page reads | ≈ 40 min | 20 MB scratch | ~45 searches; PMC, Springer, Zenodo, Mendeley, DataCite, OAI-PMH reads |
| Downloads | ≈ 2 min | 113 MB in `anchor/raw/` (88.8 MB SCADA CSV) | all verified by SHA-256 |
| Chromium attempt (Esploro page) | ≈ 3 min | — | failed through the proxy (TLS tunnel reset); file URLs obtained from OAI-PMH instead |
| Tests + lint | < 1 min | — | `pytest -q`: all green; `ruff check`, `ruff format --check`: clean |

No LLM-agent compute was spent inside the benchmark.

---

## Milestone 2 — Truth model with extensions; three plants; influent generator (weeks 3–6)

Exit criterion: reproduces published steady-state ranges; stochastic influent statistics
match anchor. Acceptance test of the ADM1 decision (decisions log 2026-09-02): agreement
with bsm2-python to 3 significant figures on Probe 1, Probe 2 and the BSM2 dynamic
influent by end of week 6, else fall back to a bsm2-python fork.

### Session 2026-09-02 (week 3) — standard ADM1 Petersen-matrix core

**Done**

- `sim/adm1/` — standard ADM1 in the BSM2 form (Rosen & Jeppsson 2006): 26 liquid + 3
  headspace states; Petersen matrix as data (`configs/adm1/petersen_matrix.yaml`,
  expression-valued entries evaluated by a restricted AST walker, S_IC/S_IN written out,
  COD/C/N/charge conservation tested to < 1e-12); rates and inhibition functions as pure
  functions (`rates.py`); algebraic pH by Brent root-find on the charge balance,
  van 't Hoff / Henry / vapour-pressure corrections and the BSM2 gas law (`physchem.py`);
  `simulate()` over `solve_ivp` BDF (Radau cross-check) with sample-and-hold (restart at
  every breakpoint) or linear influent interpolation, returning a typed
  `SimulationResult` with pH, ion speciation, partial pressures, q_gas in both the BSM2
  and dry-STP conventions, and solver statistics. No file I/O in the model, no
  module-level mutable state, no randomness. Pydantic schemas with units on every field;
  BSM2 defaults, plant geometry and solver tolerances under `configs/adm1/`.
- Oracle extended: `probe_bsm2python_dynamic.py` (BSM2 dynamic influent, 280 d at 15 min
  from PyADM1's `digester_influent.csv`, committed gzipped with SHA-256s), Probe 1/2
  records now carry the full final state.
- Ring tests (`tests/test_adm1_ring.py`, 3 s.f. = relative difference ≤ 5e-4):

  | Case | Quantities compared | Largest relative discrepancy vs bsm2-python |
  |---|---|---|
  | Probe 1, 100 d constant feed (BDF) | pH, q_gas, p_CH₄, p_CO₂, VFA, S_ac; all 29 states + 6 ions | ≈ 5e-7 (S_ac) |
  | Probe 1 (Radau cross-check) | summary quantities | ≈ 1e-6 |
  | Probe 2, 3× overload step (BDF) | summary; all states; pH_min, q_gas_max | 1.3e-4 (S_ac, VFA) |
  | Dynamic influent, sample-and-hold, 280 d | daily pH (days 1–280), q_gas, S_ac; final 29 states + ions | 1.5e-4 (S_ac, day 62) |
  | Dynamic influent, linear interpolation, first 30 d | daily pH, q_gas, S_ac | < 5e-4 |

  **Acceptance met on all three cases in week 3.** No tolerance was loosened. One
  documented exclusion: the oracle's pH at t = 0 of the dynamic case is 8.49, an artefact
  of bsm2-python's ODE ion states initialised from the rounded R&J table (they do not
  close the charge balance until they relax); the algebraic pH of the same state is
  7.267, and the test asserts both facts instead of comparing that one sample.
- Step-size collapse test on the overload probe: BDF integrates the 3× step in ≈ 260
  accepted steps / ≈ 600 RHS evaluations, smallest step 2.4e-6 d, no failure.
- 8 decision-log entries (state order, algebraic ions, S_h2, matrix-as-data, parameter
  naming, solver/influent handling, oracle data and the definition of 3 s.f.).

**Numbers worth knowing**

- RHS cost ≈ 53 µs (pure NumPy/SciPy, of which the pH root-find ≈ 20 µs); Probe 1
  (100 d) integrates in ≈ 0.06 s, Probe 2 in ≈ 0.1 s. The 280-day sample-and-hold case
  restarts the integrator 26 880 times (≈ 10 steps + 1 Jacobian each) and takes
  ≈ 150 s; the linearly interpolated variant ≈ 40 s. bsm2-python (numba) takes 62 s
  and 17 s respectively for the same runs.
- Sample-and-hold and linear interpolation of the same 15-minute series differ at the
  third significant figure (final S_ac 59.95 vs 59.99 g COD m⁻³), so the influent
  treatment is part of any future ring-test definition.

**Blocked / open**

- Open-dataset identification (Milestone-1 exit criterion, §8) is still not started.
  → Done the same day by the anchor session (Milestone 1, second session, above).
- The sample-and-hold ring test makes `pytest -q` take ≈ 3 min. Acceptable for CI; if it
  becomes a nuisance, the candidates are an analytical Jacobian (removes ≈ 30 RHS
  evaluations per restart) or a compiled RHS, not a shorter horizon.
- Not done (out of scope for this session by design): SAO, ionic-strength correction,
  precipitation sink, Plants A–C, influent generator, Weinrich R3/R4 ports.

**Next session should start on**

1. Domain review of the PR (matrix entries, rate forms, pH/gas conventions), then merge.
2. Extension rows: SAO (+1 process, +1 biomass component) as the first structural
   extension, ring-tested against QSDsan/EXPOsan equations only (no dependency); then
   ionic strength in the speciation routine; then the precipitation sink.
3. Anchor-dataset search (§8), still owed from Milestone 1.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Session total | ≈ 1 h 45 min | — | one agent session; 4 vCPU container |
| Install: bsm2-python venv (throwaway) | ≈ 1.5 min (background) | 0.7 GB | outside the repo; numba JIT warm-up on first call |
| Oracle: dynamic influent, 3 modes | ≈ 105 s compute | 0.6 MB JSON + 2.4 MB gz influent in repo | hold 62 s, shipped 24 s, linear 17 s |
| Oracle: Probes 1–2 re-record | ≈ 10 s | — | values unchanged to all digits vs Milestone 1 |
| Model runs during development | ≈ 10 min compute | — | ≈ 5 full 280-day runs + profiling |
| Test suite (`pytest -q`) | ≈ 3 min | — | dominated by the 280-day sample-and-hold ring test |
| CI (GitHub Actions) | 3 jobs per push | — | expect ≈ 4 min per pytest job |

No LLM-agent compute inside the benchmark (no workflows yet); development cost only.

### Session 2026-09-02 (third session) — truth-model extensions on the PR #2 core

**Reconciliation first.** This session initially re-implemented the ADM1 core from
`main` because PR #2 was still open (see `docs/decisions.md`, "Duplicate ADM1 core").
On the lead's instruction PR #2 was merged with `main`, its CI fixed (`tests/__init__.py`)
and merged; the extension work was rebuilt on #2's core and PR #4 was repointed at it.
The duplicate core is discarded. CLAUDE.md now carries the follow-on-session rule.

**Done**

- `sim/adm1/model.py`: behaviour-preserving refactor exposing `integrate()` and
  `gas_exchange()` so an extended right-hand side reuses the influent handling and gas
  transfer unchanged. All base tests and the full ring test (including the 280-day
  dynamic case) pass unchanged.
- `sim/adm1/physchem_ext.py`: extended speciation with optional Davies activity
  correction and carbonate second dissociation; falls back to the base routine when
  both switches are off and S_ca = 0.
- `sim/adm1/extensions.py` + `configs/adm1/extensions.yaml`: extension declarations
  (components, processes with expression-valued stoichiometry, parameters, speciation
  switches), `compile_extended()` (validates names, rate code, overrides; embeds the
  base matrix), `rhs_extended()`, `simulate_extended()` returning an `ExtendedResult`
  with pH, activities, ionic strength and gas quantities.
- Extensions: SAO (X_sao, uptake + decay, own weaker NH₃ inhibition), ionic strength
  (Davies, A scaled to T_op), carbonate second dissociation (own switch, default off),
  calcite precipitation (S_ca, X_caco3, SI rate). Formulation, defaults and the lead's
  domain answers in `docs/decisions.md`.
- `tests/test_adm1_extensions.py`: 28 tests — conservation of every row (charge −2 for
  the calcite row by matrix convention, S_IC carrying charge 0 as a total; the calcium
  balance and the 2 eq/mol alkalinity drop are tested dynamically instead), the
  ionic-strength iteration cap raising, units on every derived quantity, state layout,
  compile-time rejections, inert
  identity against the Probe-1 oracle for all three additive extensions, the carbonate
  switch pinned as a small genuine change, SAO takeover (60-d HRT, 2.8 g N/L, 300 d)
  and washout (20-d HRT), SAO NH₃ term weaker than acetoclastic, Davies limits and
  A(T), ionic-strength pH/NH₃ shifts, calcite as a sink, all four together, determinism.
- Full suite on the combined code: 123 passed, including the dynamic-influent ring test
  (max relative discrepancy 1.5e-4, unchanged).
- Independent review round (coordinating session): ionic-strength iteration cap and
  criterion moved to `configs/adm1/solver.yaml` (`ionic_strength_solver`, relative
  criterion, non-convergence raises); a vacuous "charge balance closes" test replaced
  by calcium-balance and alkalinity-drop tests; inert tolerances tightened to the
  measured gaps (1e-5 / 1e-8 / 1e-5); washout test bounded from both sides; loader moved
  to `defaults.py`; rate table and stoichiometric matrices read-only; units table for
  every derived quantity; ionic strength reported whether or not the correction is
  applied; missing extension constants raise instead of defaulting.

**Blocked / open**

- No external oracle for the extended model; correctness rests on conservation,
  inert identity and qualitative behaviour. `k_m_sao`, `K_I_nh3_sao` and `k_prec` remain
  order-of-magnitude values for the external AD reviewer.
- With μ_max 0.08 d⁻¹ SAO cannot establish at a 40-day HRT under 250 mg/L free
  ammonia in this model; the takeover test therefore runs at 60 days. If Plant B is to
  show SAO at its HRT, `k_m_sao` needs the reviewer's number, not this one.

**Next session should start on**

1. Domain review and merge of PR #4 (extensions only).
2. Plants A–C (`sim/plants/`): geometry, temperature, feedstock definitions;
   `configs/plant_a_statistics.yaml` from the Tisocco et al. envelopes.
3. Influent generator (§6.1) with `anchor/ingest_muscatine.py` feeding the Plant-B/C
   statistics.
4. Weinrich R3/R4 ports as fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Session total | ≈ 3 h | — | ≈ 1 h lost to the duplicate core and its reconciliation |
| Duplicate core (discarded) | ≈ 1 h | — | 73 tests; not merged |
| Extensions on the #2 core | ≈ 1 h 15 min | — | worktree on the #2 branch |
| Full suite (`pytest -q`), combined code | ≈ 4.5 min per run, 4 runs | — | dominated by the sample-and-hold ring test |
| Domain-answer revision (SAO NH₃, carbonate switch, A(T)) | ≈ 40 min | — | incl. SAO takeover probes (≈ 1 min compute) |
| Review round (M1, M2, L1–L5, nits) | ≈ 35 min | — | 2 fast test runs + 1 full run (≈ 4.5 min) |
| CI (GitHub Actions) | 3 jobs per push on #2 and #4 | — | |

No LLM-agent compute inside the benchmark; development cost only.

### Session 2026-09-02 (fourth session) — extension follow-ups before the plant configs

PR #4 merged (07a7fae). The lead's three follow-ups were done on a branch from `main`:

**Done**

- (1) `K_I_nh3_sao` anchored to a cited literature range (0.02–0.1 kmol N m⁻³, from the
  pathway-shift window of Hao et al. 2017/2021, the tolerance ceiling of Westerholm
  2012 / Wang 2015 / Yan 2020 / Rocamora 2023, and the hydrogenotrophic-to-acetoclastic
  IC50 ratio of Liu et al. 2023); 0.05 is inside, so the constant and the takeover test
  stay. The ADM1–SAO modelling papers' tables could not be read (hosts blocked) and are
  listed in `docs/decisions.md` as the check that would change the constant.
- (2) SAO Level-6 scenario assigned to **Plant A**: Muscatine's SRT (mean 24.7 d,
  median 22 d) and feed-volume HRT (median 19.5 d) were computed from the daily file;
  it has no ammonia column, and a municipal digester at its pH and alkalinity sits an
  order of magnitude below the free-ammonia shift threshold. Recorded with the
  condition that the Plant-A configuration must let SAO establish (design content for
  the plant PR).
- (3) SAO pH inhibition uses the hydrogenotrophic limits; calcite's missing surface
  term, dissolution and retention are documented, with `calcite_SI` and a
  `calcite_undersaturated` flag among the derived quantities; K_sp(T) by Plummer &
  Busenberg (1982), no longer a config constant; strong-ion (monovalent) convention
  documented. 3 new tests (31 in the extension file).

**Blocked / open**

- Full texts of the four ADM1–SAO parameter papers (IWA, Elsevier, HAL, PMC) were
  unreachable from this environment; the literature anchoring rests on abstracts.
- Plant A's TAN/pH envelope is not yet in the repository; it is needed both for the
  influent generator and for the SAO-establishment condition.

**Plant configurations A/B/C — proposed in a draft PR (branch from the follow-ups
branch, since PR #5 was not yet merged).**

- `sim/plants/schema.py` (declared plant contract with units and sources; hidden
  active-volume error as a distribution), `sim/plants/__init__.py` (loader, seeded
  sampling of the hidden geometry, declared vs true `PlantGeometry`),
  `configs/plants/plant_{A,B,C}.yaml`, `configs/plant_a_statistics.yaml` (Tisocco
  envelopes as recorded; untranscribed fields null with `todo`),
  `scripts/plant_a_sao_probe.py`, `tests/test_plants.py` (9 tests; B/C statistics
  re-derived from the committed Muscatine file).
- Seven open design questions are listed in `docs/decisions.md` ("Plant configurations
  A/B/C — proposed"); the first (SAO cannot establish at Plant A's 28-d HRT with the
  current kinetics) blocks the SAO scenario.

**Next session should start on**

1. The lead's answers to the plant-configuration questions, then freeze the configs.
2. Influent generator (§6.1) with `anchor/ingest_muscatine.py` for Plants B/C and the
   Tisocco feedstock tables for Plant A.
3. Weinrich R3/R4 ports as fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Literature search | ≈ 25 min | — | Consensus abstracts + web search; every full-text host blocked |
| Code + tests + docs | ≈ 35 min | — | 2 fast test runs, 1 full run |

No LLM-agent compute inside the benchmark; development cost only.
