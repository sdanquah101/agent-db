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
- The seven design questions were answered by the lead the same day and the configs
  are **frozen** (`docs/decisions.md`, "Plant configurations A/B/C — frozen"):
  `k_m_sao` 4.0 (μ_max 0.16 d⁻¹, Westerholm et al. 2019), Plant A HRT 35–45 d with the
  feed derived from it, B as Muscatine co-digestion with load swings, C as the
  sludge-only controlled pair of B, BSM2 headspace ratio, ideal CSTR with imperfect
  mixing as a fault-injection truth variant, and the Plant-A ammonia envelope left to
  the lead. Proposal copy at v0.3. SAO takeover at Plant A is now a test (12 plant
  tests; full suite 139 at the time; 141 after the engineering review below).

- The lead transcribed the Plant-A ammonia envelope (digestate TAN 2.3–4.3 kg N m⁻³,
  feed TAN/TS, the paper's adapted acetoclastic K_I of 1.0 kg m⁻³) into
  `configs/plant_a_statistics.yaml`; the SAO test now reads its midpoint. Plant A
  hydraulics are AFBI-anchored only; Foulum is the thermophilic envelope.

**Blocked / open**

- Plant A digestate pH (plotted only in Tisocco 2024) and hence free ammonia remain
  untranscribed.

**Next session should start on**

1. Influent generator (§6.1) with `anchor/ingest_muscatine.py` for Plants B/C and the
   Tisocco feedstock tables for Plant A.
2. Fault-injection API, including the imperfect-mixing truth variant.
3. Weinrich R3/R4 ports as fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Literature search | ≈ 25 min | — | Consensus abstracts + web search; every full-text host blocked |
| Code + tests + docs | ≈ 35 min | — | 2 fast test runs, 1 full run |

No LLM-agent compute inside the benchmark; development cost only.

### Session 2026-09-02 (fifth session) — salvage from PR #7 into the #6 contract

PR #6 merged (5237ac7). A parallel session had built a second plant layer (PR #7, draft,
different schema); the lead kept #6 as the design authority and asked for #7's
engineering to be salvaged with no design re-decision (`docs/decisions.md`, "Duplicate
plant layer — salvage"). Branch `claude/milestone-2-salvage-pr7` from `main`; PR #7
closed as superseded.

**Done**

- `sim/influent/` (new package; the home of the §6.1 influent generator, whose
  stochastic dynamics are a later session): `schema.py` (`CODFractionation`,
  `FeedFractionation` keyed by the plants' feed ids with kind cross-check, units on every
  field), `fractionation.py` (seeded Dirichlet draw of the hidden true fractionation,
  one `default_rng(seed)` stream in sorted feed order, order-independent and
  deterministic), `mapping.py` (recipe → 26-state ADM1 influent, flow-weighted; OLR and
  COD loading; TKN implied vs declared; `nominal_mass_rates` from a `PlantConfig`),
  `defaults.py` (loader).
- `configs/influent/feed_fractionation.yaml`: PR #7's seven feed compositions with
  their sources and "assumed" notes verbatim, every value `# DESIGN` and
  `status: provisional` (decisions log, "Feed fractionation values are provisional").
  The plant-level `N_I` override #7 used is recorded per feed as
  `inert_N_I`, not applied anywhere.
- `sim/plants/mixing.py` (parked): the two-zone imperfect-mixing structure from #7's
  `reactor.py`, compiled on a `PlantGeometry` (true volume from `true_geometry`); the
  Level-6 truth variant for the fault-injection API, not part of the plant contract.
  Bitwise reduction to `simulate` and `simulate_extended` at β = φ = 0; analytical
  tracer solution; fast-exchange limit (gas bookkeeping); the contract is asserted to
  stay CSTR-only.
- Tests: `tests/test_influent.py` (14) and `tests/test_mixing.py` (7), 21 new; full suite
  162 passed (see the resource table). Duplicates of #6's tests dropped.
- Not carried from #7: `PlantDeclared`/`PlantTruth`, its plant YAMLs, hidden-volume
  sampler, 100-day plausibility table, parameter-override field, `dilution_water`.

**Blocked / open**

- ~~Pending: Plant A ammonia envelope from the lead~~ **Resolved with the PR #8
  review**: the lead's envelope is identical to the block PR #6 committed
  (`configs/plant_a_statistics.yaml` unchanged; addendum in `docs/decisions.md`).
  `test_sao_establishes_at_plant_a` reads the TAN midpoint from the file and carries
  no envelope literal.
- The catalogue values are provisional; the influent generator cannot be frozen until
  the lead reviews them. A first read against Tisocco 2026 Table 1 and the sludge/FOG
  literature is posted on PR #8: the fractionations and the declared COD/VS are not
  mutually consistent for high-strength waste (−20 %), primary sludge (−15 %) and FOG
  (−12 %), and the cattle-slurry inert share (0.24) is at the degradable end of the
  literature; to settle at the freeze.
- **Inert nitrogen decided** (lead, `docs/decisions.md` "Per-feed inert nitrogen in the
  truth model"): the truth model applies the per-feed `inert_N_I`, the fitted model keeps
  the ADM1 default, an intentional structural mismatch. Implementation belongs to the
  influent-generator session.
- The 100-day plant plausibility check of #7 returns with the influent generator, once
  the recipes and the `N_I` question are settled.

**Decided after the merge (lead, recorded in `docs/decisions.md` "Feed catalogue
consistency").** (1) COD/VS is derived from the fractionation, the literature value
becomes a ±10 % check field enforced by a test; FOG's mass/COD-share mix-up is fixed and
the HSW and primary-sludge splits adjusted and cited. (2) The cattle-slurry hidden-truth
Dirichlet is centred at inert 0.40 with spread 0.30–0.50 (κ ≈ 100). (3) Tisocco 2024
Table 1 N is g N per kg TS (silage 25.6 / 21.8); the untraced 7.28 g/L is traced or
dropped. The entry records that the 2024 column reads as total N (it reproduces the
ESM's slurry `S_IN`), which the session must settle before deriving `tan`.

**Next session (influent generator) should start on, in this order**

1. `inert_N_I` in the truth model: COD-weighted mean of the fed feeds' values as a
   hidden truth parameter; fitted model keeps the ADM1 default (decision "Per-feed inert
   nitrogen in the truth model").
2. Catalogue consistency (1): derived `cod_per_vs`, literature check field, ±10 % test;
   FOG, HSW and primary-sludge adjustments cited in the YAML.
3. Catalogue consistency (2): cattle-slurry fractionation re-centred at inert 0.40,
   κ ≈ 100, with the BMP citation.
4. Catalogue consistency (3): silage (and slurry) TAN/TKN from the 2024 Table 1 basis
   once the column's meaning (ammoniacal vs total N) is settled; trace or drop 7.28 g/L.
5. Then the generator dynamics (§6.1) on `sim/influent`: delivery process from the
   `FeedStream` schedules and `zero_days_fraction`, assay noise and lag, seasonal drift,
   mis-logged deliveries; `anchor/ingest_muscatine.py` for the B/C statistics.
6. Fault-injection API; the imperfect-mixing scenario picks up `sim/plants/mixing.py`
   and owns the `(β, φ, k_ex)` distribution that #7 had as a plant prior.
7. Weinrich R3/R4 ports as fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Reading #6, #7, decisions, proposal | ≈ 15 min | — | |
| Code + tests + docs | ≈ 40 min | — | 2 fast runs of the new tests (≈ 2 s), 1 full run |
| Review round (envelope check, inert-N decision, composition read) | ≈ 20 min | — | 1 fast run, 1 full run |
| Full suite (`pytest -q`) | ≈ 2 min 40 s, 162 passed | — | dominated by the sample-and-hold ring test, as before |

No LLM-agent compute inside the benchmark; development cost only.

### Session 2026-09-02 (sixth session) — influent generator (§6.1)

PRs #8 and #9 merged (41ffdd4). Branch `claude/milestone-2-influent-generator` from
`main`. The lead's four catalogue answers were applied first, then the generator.

**Done**

- **Per-feed inert N in the truth model** (`sim/influent/nitrogen.py`): the truth `N_I`
  is the inert-COD-weighted mean of the fed feeds' `inert_N_I`, a hidden truth parameter
  derived from catalogue + recipe; `truth_parameters` returns a copy of the BSM2 set, the
  file and the loaded default are untouched (tested); `feed_tkn` is the assay TKN. The
  mismatch is documented as intentional; a test shows it is real for Plants A and B and
  absent for C (both sludges carry the BSM2 value).
- **Catalogue consistency (1)**: `cod_per_vs` is derived from the fractionation
  (`1 / Σ f_i/e_i`, equivalents 1.19 / 1.42 / 2.90 / 1.07, inerts at 1.19);
  `cod_per_vs_literature` is a check within `cod_per_vs_tolerance` (10 %), enforced by
  the schema and by tests. FOG fixed (lipid COD share 0.95 → 2.72), HSW re-split (lipid
  0.75 → 2.15 vs the measured 2.23), primary sludge re-split (lipid 0.35, inerts 0.33 →
  1.56 vs 1.60), each with its reason beside the value. Total COD now follows the true
  fractionation (a different composition carries a different COD per VS).
- **Catalogue consistency (2)**: cattle slurry at inerts 0.40 (particulate 0.38 +
  soluble 0.02), κ 100 (sd 0.049 on the inert share, 2.5–97.5 % ≈ 0.30–0.50, tested);
  carbohydrate 0.18, not the entry's 0.16, so the shares sum to one.
- **Catalogue consistency (3)**: both Tisocco papers read in full (Springer PDF + ESM;
  Europe PMC). The 2024 Table 1 "NH4-N [g/kg TS]" row is total N (it equals XP/6.25 for
  silage; the ESM feeds it as `S_IN`; the Foulum measured NH4-N is 0.49 of it); silage
  and slurry `tkn` on that basis at the catalogue TS, `tan` by cited TAN/TKN ratios
  (0.10, 0.55); the 2026 "7.28 g/L" cannot be traced and is dropped.
- **Generator** (`sim/influent/generator.py`, `configs/influent/generator.yaml`):
  delivery days (continuous / weekday with skips / two-state Markov), lognormal AR(1)
  amounts with a seasonal factor, per-delivery TS with its own AR(1) and season,
  unrecorded deliveries and mis-logged masses, routine assays with noise, lag, unit and
  basis, and a daily sample-and-hold `Influent`; one `default_rng(seed)` per run in a
  documented order after the true-fractionation draw. Hidden truth (`InfluentTruth`)
  and the visible `OperatorRecord` are returned to the run layer; nothing is written.
- **`anchor/ingest_muscatine.py`**: unit-explicit parsing of the daily file (gallons,
  °F, cfm with a "reference conditions unknown" flag) and the §8 step-2 delivery and
  assay statistics; the generator's Plant B/C blocks are re-derived from it by tests
  (zero fractions, weekday patterns, nonzero medians, log spreads, lag-1, seasonal
  amplitudes; HSW's mean no-delivery run 6.9 d reproduced by the Markov chain).
- Tests: `tests/test_influent.py` 19 (was 14), `tests/test_generator.py` 12,
  `tests/test_ingest_muscatine.py` 4. Four decision-log entries.

**Blocked / open**

- Engineering review of PR #10 (coordinating session) applied the same day: weekly
  assay schedules anchored to the first eligible day (a weekend start produced none);
  assays sample logged deliveries only (no hidden-truth leak); the 30-day Plant C
  integration now runs the truth parameters and asserts methane per COD fed (0.55,
  band 0.40–0.70) and linear scaling with the load; the stream-order test now changes
  the first-sorted feed's variate count; moisture log sds by quadrature; unit
  descriptions tested on every generator model; docstring corrections (decisions log
  addendum).
- **Freeze answers applied** (lead, same day; `docs/decisions.md`, "FREEZE ... silage on
  the Tisocco 2024 basis; the inert COD equivalent is per feed"): grass silage moved to
  the 2024 basis (TS % FM, composition per kg TS, VS = TS − ash), `inert_cod_equivalent`
  became a per-feed field (1.2 lignocellulosic, 1.42 sludge-derived, FOG and food waste
  at the sludge value by instruction). Cattle slurry moved to the same basis because the
  mixed basis put Plant A's OLR at 1.17 against the published 1.4–2.1 (1.78 with both on
  2024) — flagged for the lead in the decision entry and on the PR.
- The rest of the catalogue stays `provisional` until the lead freezes it; every changed
  value is listed in the PR checklist.
- Assay noise and lags, mis-log and unrecorded-delivery rates, feed pH values and the
  Plant A moisture statistics are assumed (marked `ASSUMED` in `generator.yaml`).
- Temperature seasonality is left to the plant heating / observation model; the
  Level-3 "feed mislabelled" scenario is a fault injection on the mapping, not part of
  the generator.
- The 1-minute SCADA file is not ingested (the observation model's job).

**Next session should start on**

1. Fault-injection API (§6.1): scenario YAML → truth variants (imperfect mixing via
   `sim/plants/mixing.py`, feed mislabelling on the mapping, unrecorded-delivery and
   moisture-drift scenarios on the generator's parameters, the SAO/precipitation
   omissions on the fitted model); the run layer that writes `runs/<id>/truth/`.
2. Observation model (§6.1) with the SCADA noise and dropout statistics.
3. Weinrich R3/R4 ports as fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Reading (CLAUDE.md, decisions, milestones, proposal, sim/influent, plants, tests) | ≈ 15 min | — | |
| Literature (Tisocco 2024 PDF + ESM via Springer; 2026 via Europe PMC) | ≈ 15 min | 10 MB scratch | PyMuPDF for the PDF (pdfminer/pypdf broken by the container's `cryptography`); the 2026 supplement (mmc1.docx) unreachable on PMC and Elsevier |
| Tasks 1–4 (code, YAML, tests) | ≈ 30 min | — | 3 fast runs |
| Generator + ingest + tests | ≈ 45 min | — | generator ≈ 0.05 s per 365-day plant run |
| Docs | ≈ 15 min | — | |
| Full suite (`python -m pytest -q`) | ≈ 2 min 44 s, 182 passed | — | dominated by the sample-and-hold ring test |
| Review round (M1–M3, L1–L7 of the coordinating session) | ≈ 25 min | — | 2 fast runs, 1 full run (see the PR for the count) |

No LLM-agent compute inside the benchmark; development cost only.

### Session 2026-09-02 (seventh session) — observation model and fault injection

PR #10 merged (2204dcf), including the lead's freeze answers. Branch
`claude/milestone-2-observation-fault-injection` from `main`.

**Done**

- **Observation model** (`sim/observation/`, `configs/observation/sensors.yaml`;
  `docs/decisions.md`, "Observation model"): 20 truth channels with units and
  conventions; the declared sensor model (schedule, fouling, bounded drift with
  recalibration, noise, saturation, flatline, conditional missingness, lag); 15 sensors
  and the three tier masks, with tier containment enforced by the schema. Digestate VS
  comes from the COD states and the influent's own inert equivalent; TS adds a
  conserved-ash tracer, so the frozen ADM1 core gains no state. One seeded stream per
  run, consumed per sensor in sorted order.
- **Anchored sensor values**: digester-temperature noise (0.029 K) and biogas-flow noise
  (2.1 % relative) plus both flatline occupancies are re-derived from the Muscatine
  1-minute SCADA file (89 MB, fetched and checksum-verified) by
  `anchor.ingest_muscatine.scada_noise_statistics`. The FOS/TAC overload threshold (0.40)
  is the 92nd percentile of the plant's own column, which the channel reproduces to
  r = 0.99. Every missingness rate is ASSUMED — the SCADA file is pre-cleaned and 100 %
  finite, so no dropout statistics exist.
- **Fault-injection API** (`sim/faults/`): magnitude semantics for all 17 fault types
  (unit, range, target, layer) with the benchmark-card table rendered from the same
  table; `build_plan()` routing into six per-layer directive objects; appliers for the
  parameter segmentation, the state corruption, the truth reactor's mixing structure and
  the fitted model's extension list. The influent and observation layers consume their
  directives inside `generate_influent()` and `observe()`.
- **The fault layer has its own random stream**, so a faulted run differs from its clean
  twin only by the fault (tested on both layers).
- **Level-6 imperfect mixing wired in**: the parked two-zone reactor is now the truth
  variant. It is the CSTR bit for bit at magnitude 0; at a stagnant fraction of 0.30 the
  gas deficit is 24.7 / 41.2 / 57.9 m³ d⁻¹ at 0.6× / 1.0× / 1.4× the feed — proportional
  to the load, the hydraulic signature the row asks for.
- **`tests/test_plausibility.py`**: the Milestone-2 exit criterion as a test (published
  ranges and the anchor's own biogas). It caught the FOG solids content — see below.
- Tests: 15 observation, 11 fault, 4 plausibility; two decision entries.

**Domain findings for the lead (flagged, not silently absorbed)**

- **FOG solids were an order of magnitude too high.** At the assumed 10 % TS, FOG alone
  was 5,813 of Plant B's 10,965 kg COD d⁻¹ (OLR 5.97 kg COD m⁻³ d⁻¹); the truth model
  produced 4,395 m³ d⁻¹ of biogas against the 2,111 m³ d⁻¹ per digester the Muscatine
  file measures, and under the generator's swings **the digester collapsed** (pH 4.50,
  CH₄ 0.9 %, acetate 10 kg COD m⁻³ over 180 d). Set to the anchor-derived **2.0 %**: the
  same run sits at pH 6.93, CH₄ 67 %, biogas 2,582 m³ d⁻¹ (+22 % on the measured value,
  inside the uncertainty of the conversion). Pinned by the plausibility test.
- **Sensor specs and the missingness rule** are the lead's to review: two values anchored,
  everything else assumed, and no dropout statistics exist in the anchor at all.

**Blocked / open**

- H₂S is not modelled (no sulfur in ADM1), so §6.4's Tier-C off-gas H₂S has no truth to
  observe; declared rather than faked.
- Reactor temperature varies only as sensor noise: the truth model integrates at a fixed
  set point, and the heating model that would use the plant's `day_sd_K` is not built.
- Workflow-layer faults (`tool_failure`, `adversarial_log_note`) are routed and typed but
  applied by the run harness, which does not exist yet.
- The requested-assay budget of §6.4 (assays beyond the tier's schedule, at a cost) is
  not implemented; it belongs with the tool registry.

**Self-review of PR #11 (same session, at the lead's request)**

Six findings, all fixed on the branch and recorded in `docs/decisions.md`: the correlated
noise draws (real, one sensor affected), the ash tracer ignoring the hold convention
(latent), the mixing constants hard-coded rather than configured, the implicitly ordered
fault target, one dead helper and one untyped result. The rule-1 hygiene check now covers
`sim/faults` and `sim/observation`. The conditional-missingness test was re-sized after a
flake: pooled over forty seeds the estimator is 2.055 ± 0.088 and 1.981 ± 0.061 against
an expected 2.0, so it was sample size and not bias. Stated plainly: this is a
self-review, not an independent one.

**Next session should start on**

1. The run harness: `runs/<id>/truth/` and `calls.jsonl`, wiring generator → truth model
   → observation record → scenario, with the workflow-layer faults applied.
2. The remaining scenario YAMLs (19 of them, v0.3) with their answer keys.
3. Weinrich R3/R4 ports as the fitted models.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Freeze answers + merge of PR #10 | ≈ 25 min | — | 1 full suite run |
| SCADA fetch | ≈ 4 min | 89 MB (git-ignored) | checksum-verified by `anchor.fetch` |
| Observation model + config + tests | ≈ 55 min | — | SCADA statistics ≈ 20 s per channel |
| Fault API + wiring + tests | ≈ 45 min | — | mixing runs ≈ 2 s each |
| Plausibility investigation (FOG) | ≈ 20 min | — | 8 steady-state runs |
| Docs | ≈ 15 min | — | |

No LLM-agent compute inside the benchmark; development cost only.

---

### Session 2026-09-02 (seventh session, continued) — the lead's freeze applied to PR #11

Same branch. The lead answered the two flags raised above (sensor specs, missingness rule)
and approved the three domain findings; PR #11 is now the Milestone-2 observation and
fault-injection component, reviewed and marked ready.

**Done**

- **Missingness restructured as a tier policy** (`MissingnessPolicy`), because the lead
  gave the base rate per tier (8/4/2 % at A/B/C) and the multipliers per instrument kind
  (4× overload and 3× foaming online, 1.5× lab). Two more values moved with it by the same
  argument — a tier is the plant's monitoring capability, not the instrument's: laboratory
  turnaround (7/3/1 d) and recalibration cadence (90/30/30 d). `SensorSpec` lost
  `missingness` and `lag_d`; `DriftModel.recalibration_interval_d` became the boolean
  `recalibrated`. Tiers are still masks on identical truth.
- **Sensor defaults set to the lead's figures** (`configs/observation/sensors.yaml`,
  version 2), with the two per-month drifts converted to random-walk scales — pH
  0.05–0.1 pH/month → `sd_per_sqrt_d` 0.0137 (the midpoint of 0.0091–0.0183), CH₄
  0.5 %/month → 0.0009 — and the CH₄ tolerance read as ±1 *percentage point* of methane
  content rather than 1 % of the reading.
- **`docs/benchmark_card.md` written**: intended use, the explicit non-claims, the
  anchoring status of each plant, the hidden/visible table, known limitations, and §5.1
  "corrections the anchor caught", where the FOG solids error is recorded at the lead's
  instruction.
- **Tests follow the restructuring** (19 in `tests/test_observation.py`): the tier
  properties as declared, and observed — Tier A loses ~4× the samples of Tier C on the
  tiers' shared sensors and identical truth; the weekly assay's lag is the tier's; and
  with only the cadence varied (same stream, same draws) the pH walk's rms offset scales
  as the √3 the reset interval predicts, resetting at every boundary and only there.
- Decisions entry, `configs/README.md` and this file updated.

**Flagged to the lead (interpretations where the answer was silent)**

- The single lab multiplier (1.5×) is applied to **both** flags, not overload alone.
- The tier's recalibration cadence applies to every sensor declaring `recalibrated: true`,
  so the CH₄ analyser is now recalibrated monthly at B/C and quarterly at A.
- **TAN** (cv 5 %) and the **H₂ cell** (cv 15 % + 1 ppm floor) were not in the lead's list
  and keep the branch's assumptions. The 8 % VFA figure is applied to all four speciated
  assays; valerate sits near the quantification limit, so 8 % is probably optimistic there.

**Blocked / open**

Unchanged from the entry above (H₂S, reactor temperature, workflow-layer faults, the
requested-assay budget). The missingness rates remain **assumed** and unfittable: the only
open SCADA file is pre-cleaned.

**Next session should start on**

1. The run harness: `runs/<id>/truth/` and `calls.jsonl`, wiring generator → truth model
   → observation record → scenario, with the workflow-layer faults applied.
2. The remaining scenario YAMLs (19 of them, v0.3) with their answer keys.
3. Weinrich R3/R4 ports as the fitted models.

**Resource cost (this continuation)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Schema/config/model restructuring | ≈ 20 min | — | |
| Test updates and re-sizing | ≈ 20 min | — | 3 suite runs + a 40-seed convergence check |
| Benchmark card and decisions entry | ≈ 20 min | — | |

---

### Session 2026-09-02 (seventh session, review pass) — PR #11 reviewed and merged

The lead approved #11 with one change (valerate assay cv 15 % plus a 0.05 g/L floor) and
asked for an independent review before merging.

**Done**

- **Valerate** at cv 0.15 with `sd_abs` 0.05 kg m⁻³; the other three speciated acids stay
  at 8 %. Flagged: with a floor the size of the quantity, 17 % of reported values are
  negative (565 samples, mean 0.0494, sd 0.0497, min −0.102). Left unclipped; the three
  options and their costs are in the decisions log for the lead.
- **Independent review** (fresh context, instructed to verify rather than trust and to try
  to construct broken implementations that pass each test). Nine real defects, all fixed.
- **The one that mattered: every VFA channel was 1000× too small.** `kmol/m3 × kg/kmol`
  already gives kg/m3; the extra `/1000` had no dimensional justification. FOS/TAC was
  therefore 1000× small, and the overload and foaming flags are thresholded on it — so
  `condition_flags` returned all-`False` on every real run and **conditional missingness,
  the §6.1 property this component exists to deliver, never fired**. The test that claimed
  to check the arithmetic restated the implementation and passed under any scale error.
- Eight more: sub-interval episode durations inflated the anchored flatline occupancies
  2.5–5×; `scada_noise_statistics` mis-marked runs (re-measured 0.0765 % and 0.0144 %);
  `random_gaps` was not MCAR; `ph_electrode_drift` never produced its drift-then-step
  signature; `cod_total`/`vs` excluded the extension states, so SAO biomass — the Level-5
  signal — was missing; a `saturated` flag could contradict its own reading; the benchmark
  card was not actually tied to `benchmark_card_rows()`; plus a float off-by-one, an
  unvalidated over-long horizon and two `x or Default()` traps.
- Two found in this session's own pass first: `channels_from_two_zone` mixed liquids in
  FOS/TAC, and `ash_trajectory` ignored the influent's declared `interpolation`.
- `condition_flags` was O(n²) and had become the suite's bottleneck; now a binary search,
  with a test against the definition it replaced on an irregular grid.
- Tests 215 → **233**.

**Flagged to the lead (needs a decision, not fixed)**

- **The simulated FOS/TAC distribution sits well below the plant's.** With the units right,
  a healthy simulated digester is at 0.01–0.07 against the anchor's median 0.23; at 2.5×
  feed Plant B reaches 0.15. The 0.40 threshold is reachable under load, but it will fire
  on far fewer simulated days than the anchor's "~8 % of days". Closing the gap is a
  feed-catalogue or kinetics change, not a threshold change.
- Whether below-LOQ valerate should be clipped, censored, or left negative.

**Recorded, not fixed** (decisions log): `hazard_per_d` typed as a fraction; repeated
observation faults on one sensor overwrite rather than compound; `tool_failure` cannot name
a tool; `UnrecordedDelivery` truncates a fractional onset; a first-sample `flatlined` flag
is reported but nothing is held.

**Next**

Scenario generation for gate G1: all 19 scenarios at three tiers on Plants B and C, the
Level 2–5 Tier A subset plus the three ammonia scenarios on Plant A, hidden truth written
only to `runs/<id>/truth/`, and an anchor-comparison report within a declared tolerance.
That needs the run harness (`runs/<id>/truth/`, `calls.jsonl`) built first.

**Resource cost (this pass)**

| Item | Wall-clock | Notes |
|---|---|---|
| Valerate change | ≈ 10 min | |
| Independent review (subagent) | ≈ 15 min | 53 tool calls, fresh context |
| Applying nine findings + tests | ≈ 70 min | 4 full suite runs |
| Docs, PR body | ≈ 20 min | |

### Session 2026-09-03 — duplicate PR closed, its anchor salvaged, and the launcher fixed

A parallel session had built the observation model and the fault-injection API a second
time (PR #12, `sim/observe/` + `sim/faults/`, CI green). The lead ruled PR #11 canonical
and closed #12, keeping three things from it. Branch
`claude/salvage-scada-anchor-offline` from `main` at b469317.

**Done**

- **The SCADA anchor is now reproducible from a fresh clone.**
  `anchor/derived/muscatine-scada-window.csv.gz` (days 240–300 of the record, 86,400 rows,
  three columns, 629 KB, ODC-By with attribution) and
  `anchor/derived/muscatine-scada-sensor-statistics.json` (full-record statistics, the
  window's, the row-dropout statistics and the parent's SHA-256), written by
  `scripts/muscatine_scada_observation.py`. `scada_noise_statistics` reads the gzipped
  extract, so the two anchored **noise** values are re-derived in CI instead of skipping;
  the config is checked against the committed JSON always, and the JSON against the 88.8 MB
  parent when it is present. The window was picked by measuring candidates against the year
  on the tolerances the test already used (temperature exact, gas cv within 0.0013).
- **Tier C online missingness is measured**: 0.00097 per sample, from 19 row gaps in
  347.8 d of SCADA (`scada_row_gap_statistics`). The earlier "the anchor carries no
  dropouts" was true of the file's cells and false of its rows. Carried as a narrow
  `base_rate_overrides[tier][kind]`; Tiers A/B and every laboratory rate stay assumed and
  the tier structure stays, with a test asserting `("C", "online")` is the only exception.
- **Temperature saturation** is the data dictionary's 85–150 °F (302.594–338.706 K) instead
  of an assumed 273–353 K; the record sits at the floor on 0.066 % of its minutes.
- **`CLAUDE.md` opens with who may start a component session**: the routine never launches
  one; the lead sends `launch: <component>` to the coordinator after the previous PR
  merges. Two decision entries record the ruling and the process change.
- Tests 233 → **238** (five added, three of #11's updated where the contract changed, not
  around it). Two of the five need the git-ignored SCADA parent and skip without it; the
  window test — the one that closes the gap — runs everywhere.

**Blocked / open**

- Unchanged from the previous session: the simulated FOS/TAC distribution sits below the
  plant's, and the below-LOQ valerate question is still open.
- The window cannot carry the flatline occupancies (rare events) or the dropout rate
  (unrepresentative over 60 days); both stay full-record figures in the JSON.

**Next session should start on**

Nothing is launched automatically any more. The next component — scenario generation for
gate G1 — starts when the lead sends `launch: scenario generation (G1)` to the
coordinating session, after this salvage merges. It still needs the run harness
(`runs/<id>/truth/`, `calls.jsonl`) first.

**Resource cost this session (rough)**

| Item | Wall-clock | Disk | Notes |
|---|---|---|---|
| Establishing the duplication and reporting it | ≈ 15 min | — | diff against `main`, comparison of both implementations |
| Window selection (13 candidates scored) | ≈ 10 min | 88.8 MB parent (git-ignored) | one full parse per candidate |
| Salvage code, config and tests | ≈ 45 min | 629 KB committed | |
| Docs (decisions, milestones, CLAUDE.md) | ≈ 20 min | — | |
| Full suite | ≈ 5 min per run | — | |

No LLM-agent compute inside the benchmark; development cost only.

---

## Milestone 3 — Observation model and fault-injection API (weeks 7–9)

### Session 2026-09-03 (eighth session) — the run harness, the 19-scenario library, gate G1

Branched from `main` at `b469317` (PR #11 merged). This is the gate-G1 session: build the
`runs/<id>/` layer, write the other 18 scenarios, generate the §7 matrix, and compare the
generated statistics with the Muscatine anchor inside tolerances declared in advance.

**Done**

- **The run harness** (`sim/run/`, `state/`). `generate_run` wires every frozen component
  together — `build_plan` → hidden geometry → `generate_influent` → a burn-in on the
  plant's median recipe → the truth model, segmented where a parameter fault has an onset
  → channels → the tier's mask → files. Two writers, one per region, so the rule-1
  boundary is structural rather than procedural. `generate_cells` integrates the truth
  **once** per (plant, scenario) and masks it three times, which is how §6.4's "tiers are
  masks on identical truth" becomes a guarantee rather than a hope.
- **`state/provenance.py`**: the append-only `calls.jsonl` of rule 3, with an argument
  *fingerprint* rather than the arguments (a trajectory is not a log line). A second
  writer continues the sequence, which is what the tool registry will do.
- **`state/run_view.py`**: the workflow-facing loader. Hidden truth is not refused, it is
  unnameable — the view is rooted at `observations/` and every path is resolved and
  required to stay inside it. `tests/test_truth_isolation.py` now drives that on a real
  run, after first asserting the truth *is* on disk.
- **The manifest is redacted, not truncated.** Written complete (scenario, seeds, fault
  layers, config hashes, git SHA) because reproducibility needs it; a workflow gets a
  projection with no field for any of the three. `REDACTED_FIELDS` and a test partition
  the manifest exactly, so a new field cannot be forgotten on one side.
- **All 19 scenarios**, each with its answer key and a `notes` field saying what a workflow
  should notice and what the characteristic failure is. Every magnitude is inside the range
  `sim/faults/schema.py` publishes and its choice is argued in the file's own header.
- **The §7 matrix generates end to end: 114 of 114 cells**, 44 distinct truth integrations,
  13 min wall-clock, 40 MB. 96 factorial cells on B and C, 18 on Plant A.
- **`docs/g1_anchor_report.md`** plus `anchor/compare_generated.py` and
  `tests/test_g1_anchor.py`, which recomputes the report's generated block verbatim.
- Tests 233 → **296** at the time this entry was first written; the entry's own numbers
  were left at their first-pass values and are corrected below (L2 of the 2026-09-04
  review).

**Gate G1: the stated criterion is met, and there is a blocking finding underneath it**

*Met.* Every scenario generates; hidden truth is written only to `runs/<id>/truth/` and is
unreachable through the workflow API; **every influent statistic is inside its declared
tolerance** — per-stream delivery medians (ratios 0.95–1.00), spreads (1.01–1.08), zero
fractions, total feed flow (1.08), the VS fractions, the HSW COD and the organic loading
rate (1.13). Biogas is **1.41×** the plant's measured mean, inside the inherited 0.6–1.5
band. *(This entry originally said 1.37×, the first-pass figure measured before the lead's
rulings 1 and 3 of the same day moved it; corrected 2026-09-04.)*

*Blocking.* **Plant B acidifies on 5 of 12 clean Level-0 seeds** (pH 4.6–5.0, 0–0.31
methane) under the frozen configuration. It reproduces with declared geometry, the
published initial state and no burn-in, so it is not the harness.
`test_plant_b_survives_the_generator_swings` missed it because it tests one seed — and that
seed is one of the seven that survive. Across the matrix: 87 of 114 cells sound, all 27
that are not being Plant B. The likeliest cause is that `plant_B.yaml` documents the
high-strength waste as "blended in a 65,000-gal tank" (~6 d of hold-up) and the generator
feeds truck arrivals straight to the digester. **Not fixed** — it changes the frozen
generator — but every run is now labelled sound or soured and the rate is pinned by a test
that fails if it goes to zero as well as if it gets worse.

*Three output rows fail their declared tolerance,* and they are one finding: VFA 0.054
against 1.178 kg m⁻³, alkalinity 2.78 against 5.04 kg CaCO₃ m⁻³, FOS/TAC 0.021 against
0.232. This is the realism gap the PR-#11 review recorded, now measured on a panel. Its
consequence is worse than the rows: the overload flag fires on 0 % of days in five of the
seven sound runs, so conditional missingness — and with it the Level-4
`informative_missingness` row — has nothing to act on in most healthy Plant B cells.

**Flagged to the lead (needs a decision; none of it was changed here)**

1. **Plant B's stability** and the missing HSW/FOG buffer tank (above).
2. **The VFA/FOS-TAC gap** and what closing it would take (`g1_anchor_report.md` §6). Two
   of the five options actually change the answer: the acetate-uptake kinetics, and the
   buffer tank.
3. **Plant A never reaches a steady state.** Its SAO succession completes at ~800 d with
   the acetoclastic methanogens washed out entirely, at which point all three ammonia
   scenarios are inert (doubling `K_I_nh3` moves gas by 0.002 %). The burn-in is therefore
   set to leave a mixed community at 200 d, and the succession is documented rather than
   hidden. Either `k_m_sao` is too fast, or Plant A's ammonia envelope is too high, or
   Plant A is defined as a digester in transition — the third is implemented.
4. **There is one answer key per scenario, not one per tier**, so S2-02 (methane-analyser
   flatline, a Tier-B instrument) has an unreachable conclusion at Tier A.
5. **Level-8 rows now carry an underlying fault**, because the frozen schema requires a
   truth label and forbids `none` above Level 1 — and the constraint turns out to improve
   the rows.
6. **Plant A's ammonia rows run at all three tiers** (§7 pins Tier A only for its Level 2–5
   subset and is silent on these).
7. **Budgets** are a three-band proposal (4,000/6,000/8,000 simulator evaluations by level);
   the proposal fixes only the Appendix-B example.

**Changed, with the reason stated**

- `tests/test_scenario_schema.py` asserted `S2-03.seed is None`. The Appendix-B example now
  carries seed 1023, because rule 4 forbids an implicit seed and the matrix refuses a
  scenario without one. Nothing else about the example changed and the test still pins the
  rest of it.
- `configs/adm1/initial_state_rj2006.yaml` is new: the published steady state as data, so
  `sim/` need not import the disposable probe code. A test asserts the two agree.

**Next session should start on**

1. The lead's answers to items 1–3 above. Item 1 in particular gates the factorial: until
   Plant B is reliably stable, roughly a third of its cells are crashed digesters.
2. The tool registry v1.0 (§6.2, weeks 10–13), appending to the same `calls.jsonl` and
   enforcing the budgets the scenarios declare — and applying the Level-8 `tool_failure`
   directive the harness hands it in memory.
3. The Weinrich R3/R4 ports as the *fitted* models, which is what makes the Level-6 rows
   scoreable; `fitted_extensions` is computed and written to truth but nothing consumes it
   yet.

**Resource cost**

| Item | Wall-clock | Notes |
|---|---|---|
| Run harness, provenance, run view | ≈ 70 min | |
| 18 scenario YAMLs | ≈ 40 min | |
| Full matrix generation | 13 min | 114 cells, 44 integrations, 40 MB |
| Diagnosing the Plant B souring | ≈ 35 min | seed sweeps, cause isolation |
| Anchor comparison, report, tests | ≈ 60 min | |
| Docs | ≈ 30 min | |
| Test suite | ≈ 8 min per full run | 4 full runs |

### Session 2026-09-03 (eighth session, continued) — the lead's three rulings on G1

The lead read the G1 status and ruled: **G1 not passed — the infrastructure criterion is
met, the plant criterion is not.** Three rulings, all implemented on the same branch. The
five interpretations of the first pass were approved.

**Ruling 1 — Plant B's blend tank.** Added to the *plant contract* as a declared, well-mixed
buffer (`configs/plants/plant_B.yaml`, `sim/plants/equalisation.py`): 123.02 m³, holding the
trucked high-strength waste, about 4–5 d of hold-up. The influent generator is untouched, as
ruled. Mass closes to machine precision and at zero volume it is a pass-through exactly.

**Ruling 3 — feed alkalinity calibrated.** The Muscatine feeds' strong cations calibrated to
the anchor's own digester alkalinity: 2.78 → **5.12** kg CaCO₃ m⁻³ against the plant's 5.04,
with pH landing at **7.29** against 7.27 at the same time. Inert-N untouched; no kinetic
parameter touched.

**The acceptance condition is met, and either change alone would have met it.** Measured on
the twelve-seed panel with the other held back — original cations/no tank 7/12 sound (min pH
4.50), tank alone 12/12 (6.53), calibration alone 12/12 (7.06), both 12/12 (7.13). On the
twenty-four-seed panel with both: **24 of 24 sound**, and **all 114 matrix cells sound**.

**Ruling 2 — Plant A.** The 200-d burn-in workaround and its guard test are gone; the burn-in
is 400 d and converges on all three plants. `PlantConfig` gains a declared `adaptation` block
and Plant A declares `K_I_nh3 = 0.02` kmol N/m³ (the **bottom** of the ruled 0.02–0.05: the
frozen ×0.1 fault magnitude reaches below the pathway-exchange threshold from 0.02 and not
from the midpoint). S5-01 and S7-02 are redesigned as loss-of-adaptation transitions and
both now produce strong, correctly-signed signals through the full harness.

**Two things ruling 2 asked for could not be delivered, and both are measured, not asserted.**
Coexistence of acetoclasts and SAO is impossible at *any* adapted K_I — they compete for one
substrate, so one always excludes the other, and the exchange point is at K_I ≈ 0.003, an
order of magnitude below the ruled range; the stochastic feed does not change it. The
ruling's fallback, reducing `k_m_sao` towards 3.0, has the **wrong sign**: it weakens SAO and
moves the exchange point down. `k_m_sao` was therefore not changed.

**One change beyond the rulings, flagged.** A trace of syntrophic oxidisers in the feed
(`influent_extension_states: {X_sao: 1e-4}`). ADM1 has no immigration, so a population at
zero can never return: without it a loss of adaptation produces no pathway shift at all and
the Level-6/7 rows stay inert. It is not a kinetic change, it is physically standard, and
it is flagged in the config, the decisions log and the PR.

**Open, needing the lead**

1. **S6-01 is inert.** The pure structural omission has no transition by construction, so at
   Plant A's adapted acetoclastic baseline the truth's SAO carries no flux and omitting it
   produces no residual. Three ways out are written into the scenario file; this session
   recommends setting Plant A's adapted K_I to the ~0.003 exchange point, or rescoring the
   row as an abstention row, and changed nothing.
2. **The VFA gap.** 0.067 against 1.178 kg m⁻³, so FOS/TAC 0.013 against 0.232 — the
   alkalinity half is closed, the VFA half is the coordinator's list. The overload flag now
   fires on no day at all in most sound runs, so S4-02 is close to a duplicate of Level 1.
3. **Plant A's baseline TAN is 3.1–3.7 kg N/m³**, above the 2.3–2.8 the ruling named and
   inside Tisocco et al. 2024's published 2.3–4.3. Nothing was adjusted to move it.

**CI.** The G1 panel is behind a `g1` marker, deselected by default, run nightly and on any
PR touching `sim/`, `configs/`, `scenarios/` or the comparison module.

**Next session should start on** the two open items above, then the tool registry (§6.2).

---

### Session 2026-09-04 (ninth session) — the G1 remediation: five rulings and four defects

Continues PR #15 on `claude/g1-scenario-generation`. An independent review of the gate-G1
work found nine defects; the lead ruled on five and left four as pure test/correctness work.
This session applied all nine and referred three design questions back. **No plant ruling was
redone** — the blend tank, the adapted `K_I_nh3` and the alkalinity calibration are as the
previous session left them, and no generated number moved.

**Done**

- **H1 — hidden truth is structurally unreachable.** The review broke `state/run_view.py`
  twice on a real run without writing the string `truth`, so the AST checker saw neither:
  `view.root` was a public field, and `view.path(".")` resolved to the observations
  directory whose `.parent` is the run root. Truth now lives in a **separate top-level
  tree**, `truth_store/<id>/`, with the complete manifest and the run index; `runs/<id>/`
  holds the observations, the **redacted** manifest (written redacted, not redacted on the
  way out) and `calls.jsonl`. Defence in depth on top: private root, contents-not-paths,
  `""`/`"."`/traversal/symlinks rejected. An adversarial bypass suite drives every route
  including the attribute one, **with a negative control**.
- **H3 — per-sensor RNG streams.** `observe()` consumed one serial stream over
  `sorted(tier.sensors)`, so a shared instrument's realisation changed with the tier and
  §6.4's tier comparison was confounded. Each sensor's stream is now derived from
  `(observation_seed, sensor_name)`. The new test generates the tiers **separately** and
  carries a different-seed control; the old one compared a shared object with itself.
- **H2 — the blend tank's guard.** `sum(a) - sum(b) == sum(a - b)` is an identity of
  addition and was true for any `load_out`. Replaced by a per-component comparison against
  the closed-form solution of `dV/dt = q - V/tau`. The implementation is correct (Radau
  cross-check, 1.2e-13); mutation confirms `load_out[t] = load_in[t]` now fails four tests
  and failed none before.
- **M1 — the alkalinity row is a calibration, not a match.** Labelled *calibrated to
  anchor*, excluded from the anchor-match count (now stated in the report: 20 of 22
  independent rows), rationale corrected, and the pH-corroboration claim withdrawn. Recorded
  as a finding: the high-strength waste supplies 78 / 91 / 86 % of the buffering on three
  different bases — the ruling's ~95 % is not reproduced on any of them.
- **M7 — the gap list is merged**, which also brings the branch up to `main` (PR #13's
  offline SCADA anchor and PR #14's historian dropout).
- **M5** golden pins on the seed derivation and the run ids; **M6** two determinism
  regressions, one in-process and one across two `PYTHONHASHSEED` values in a subprocess;
  **L7** `write_index_entry` no longer duplicates a regenerated cell's line; **L2** stale
  numbers corrected in the report and here, with the correction marked in place.
- Three existing observation tests asserted a realisation rather than a property and are
  **re-expressed, not relaxed** — the drift reset, the flatline hold and the
  conditional-missingness rate. Each is now measured over seeds or against an expectation
  derived from the config.
- Tests 305 → **339** (327 in the default suite, 12 in the `g1` panel, 2 skipped without the
  git-ignored SCADA parent).
- **The matrix regenerates end to end into the new layout: 114 of 114 cells, 114 of 114
  sound**, 44 truth integrations, ~10 min wall-clock, 25 MB under `runs/` and 17 MB under
  `truth_store/`. Verified on the generated store rather than asserted: every `runs/<id>/`
  contains exactly `observations/`, `manifest.json` and `calls.jsonl`; no visible manifest
  carries a redacted field; no truth directory lacks its complete manifest; `index.jsonl` is
  in the truth store with 114 unique lines and no duplicates.
- **Regenerated a second time from a clean tree**, because the first pass was not one: its
  114 manifests carried **five different `git_sha` values, three of them `-dirty`**, having
  been generated across three commits while docstrings were still being edited. Proposal §13
  wants final runs from a clean tree and the manifest marks `-dirty` exactly so that is
  visible; all 114 now carry the single clean `d57546c`. Checking one's own provenance record
  is cheap and this is what it is for.
- **CI: the paths filter needed `pull-requests: read`.** `does this change touch sim/?`
  failed on every pull_request event while passing on push for the same commit —
  `dorny/paths-filter` asks the pull-request Files API, and declaring a `permissions:` block
  sets every unlisted scope to none. The consequence was worse than a red check: the G1 panel
  is gated on that job's output, so it was silently **skipped** on every PR run. Fixed; both
  event types now run the panel and all ten checks are green.
- **The G1 report's generated block is byte-identical apart from the M1 relabelling and the
  new match-count line.** The remediation changed where truth is written and how a sensor is
  realised, not what the digester does.

**Referred to the lead, unchanged — all three independently re-measured and confirmed**

1. **M2.** The HSW's visible alkalinity assay is 0.0214 kg CaCO₃ m⁻³ while the strong-cation
   charge the simulator feeds is 10.26 — a factor of **480**. The other streams agree to
   within 2.4×. It is specifically the stream ruling 3 calibrated.
2. **M3.** `observations/sensors.json` flags the methane analyser `flatlined` on exactly the
   samples the Level-2 fault injected, so the visible record labels that row.
3. **M4.** The adversarial note is the only entry authored by a `process_engineer`; every
   benign note is an `operator`'s, so the field alone identifies it without reading it.

**Still open from the previous session:** S6-01 is inert; the VFA gap (`docs/vfa_gap.md`);
Plant A's baseline TAN sits above the range the ruling named.

**Next session should start on** the lead's answers to M2/M3/M4 and to S6-01, then the tool
registry (§6.2).

---

### Session 2026-09-09 (continued) — the lead's four rulings on S6-01, TAN, the titrimetric convention and the gap

**Done**

- **Ruling 1 — Plant A declares two baselines, and S6-01 bites.** The row was inert:
  acetoclasts and syntrophic oxidisers compete for one substrate, so Plant A is one or the
  other, and at its adapted constant it was acetoclastic with the omitted pathway carrying
  no flux. The contract now declares `adapted` (K_I 0.02, X_ac 1.129, acetate 0.038) and
  `unadapted` (ADM1 default, X_sao 0.910, acetate 0.240) — both sound digesters, measured —
  and each scenario names the one its answer key assumes. **S6-04** is new: the same
  omission on the adapted baseline, scored on **abstention**, so the pair distinguishes a
  diagnosis from a workflow that always answers "structural". Matrix 114 → **117 cells**.
  The X_sao feed trace is recorded as **approved**, not flagged.
- **Ruling 2 — baseline TAN 3.1–3.7 accepted**, the earlier 2.3–2.8 recorded as withdrawn.
- **Ruling 3 — the titrimetric transfer function is approved in principle and NOT built.**
  `sim/observation/channels.py` is untouched pending its form and band. What is in force
  meanwhile is stated in three places rather than left implicit.
- **Ruling 4 — the gap is a finding, the threshold is percentile-matched.** No kinetic
  parameter moved. The bistability stays in `docs/vfa_gap.md` and is referenced as a
  property of the model. The 0.40 threshold is now pinned to the anchor's own 92nd
  percentile (0.402 / 0.408, n = 861 each), and the 92nd is the *closest* percentile to
  0.40 of any between the 50th and the 99th — the old guard only required 5–15 % of days
  above it and would have accepted 0.35 or 0.45 equally.
- **The overload firing rate is in the generated block**, per-run and pooled as ruling 4
  requires: **0.14 % of days pooled, no day at all in 23 of 24 sound runs**, 3.31 % in the
  one that fires, against the plant's 8.25 % and 9.18 %.
- Benchmark card gains **§5.3, "Two FOS/TAC conventions, and which one each number is in"**.
- Tests 339 → **342** (330 default + 12 in the `g1` panel, 2 skipped without the SCADA
  parent). Matrix regenerated from a clean tree: **117 of 117 cells, 117 of 117 sound**,
  9 min 43 s, every manifest on one clean SHA, 0 visible manifests carrying a redacted
  field, index 117 lines / 117 unique.

**Flagged to the coordinator, not decided here**

1. The new row is filed as **`S6-04`, not `S6-01b`**: the frozen id pattern `^S\d+-\d{2}$`
   admits no letter suffix and the id feeds the opaque run-id hash. A one-line schema
   change plus a rename if the lead wants the literal id.
2. The unadapted baseline's digestate TAN is **3.5–3.7, not the ruled 3.7–4.3**. The
   unadapted constant does not raise TAN — it is slightly *lower* than the adapted
   baseline's — and reaching that band would move Plant A's frozen feed nitrogen. The
   mechanism the ruling needs is delivered in full by the constant alone.
3. Two relayed anchor numbers did not reproduce: Dig2 max 0.80 (measured 0.636) and the
   exceedance fractions 7.78 / 8.59 % (measured 8.25 / 9.18 %), on the same n = 861. The
   percentiles the ruling turns on agree to the third decimal, so the ruling is unaffected.

**Next session should start on** the titrimetric transfer function once the coordinator
brings its form and band, the still-open M2/M3/M4 findings, and then the tool registry
(§6.2).

---

### Session 2026-09-09 (continued) — rulings A–E: the titrimetric convention and the hidden-state trigger

**Done**

- **Ruling A — the titrimetric FOS transfer function, κ frozen at 1.0.** The `vfa_total`
  *sensor* reports what a two-point Nordmann/Kapp titration would report; `fos_tac` is
  computed from that reading; **true VFA stays the hidden channel and no sensor sees it**.
  No fitted parameter: every equilibrium constant is the truth model's own. Re-derived
  independently and matching the relay exactly — pK_a(ac) 4.760, pK_a(CO₂) 6.305, carry-over
  0.0349 of S_IC, f_ac 0.3309, scale-up ×3.022. Measured FOS 0.775 against the anchor's
  1.178, FOS/TAC 0.150 against 0.233, **90 % of the reading bicarbonate carry-over**; the gap
  falls **17.5× → 1.52×** with nothing fitted.
- **The consequence is that `vfa_median` and `fos_tac_median` now PASS — 20 of 22 independent
  rows became 22 of 22.** No bound was moved and the model did not change; the row now
  compares like with like. The test that pinned those rows as *failing* in both directions
  did exactly what it was written to do: it failed, and now pins the **residual 1.52× gap**
  just as hard.
- **Ruling B — conditional missingness triggers on the hidden state**: true VFA > 2.00× its
  30-day trailing median, the window excluding the current day. Measured **7.92 %** of days
  on 24 sound Plant B runs against the anchor's 7.78 %, nothing tuned. Cross-plant, same
  cut-off: **B 7.92 %, C 9.96 %, A 0.55 %** — recorded, not tuned away.
- **S4-02 is given back** on B and C: the flag now fires in every sound run, where before it
  fired on no day at all in 23 of 24.
- **Ruling C** — FOS/TAC > 0.40 stays operator-facing only; both rates are reported in one
  table so they cannot be confused.
- **Ruling D** — the "variance deficit" diagnosis is **withdrawn**. True VFA is *more*
  variable than the anchor's FOS/TAC (2.06 against 1.74); what is flat is the titrimetric
  reading, because most of it is carry-over. The paper's finding is that **the titrimetric
  convention masks the VFA dynamics it is meant to report**.
- **Ruling E** — the run root moves into closures; `RunView` holds no instance attribute at
  all, and `view.files` now filters through the resolver so the listing cannot advertise what
  a read would refuse.
- Tests 342 → **349** (336 default + 13 in the `g1` panel, 2 skipped).

**Flagged to the coordinator**

1. **Plant A's trigger rate is 0.55 %**, an order of magnitude below B and C, because it is
   fed continuously while they take trucked deliveries. Plant A hosts **S4-02**, the row this
   trigger exists to give content to. The cut-off is not adjusted, as ruled.
2. Carried forward and still open: the `S6-01b`/`S6-04` id, the unadapted baseline's TAN
   band, the two relayed anchor numbers that did not reproduce, and M2/M3/M4.

**Recorded as a follow-up for the next session that touches the plant configs**: Plants B and
C need a **declared design organic loading rate** from Muscatine's design or permit figures.
Nothing depends on it today — the trigger uses the VFA signal alone — and no design OLR is to
be invented in the meantime.

**Next session should start on** the lead's answers to the flagged items, then the tool
registry (§6.2).
