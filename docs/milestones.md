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
  as a finding: the high-strength waste supplies **91 % of the `S_cat` increment the
  calibration added** — the basis the lead ruled this is reported on (2026-09-09), stated
  wherever the number appears. The other two bases (78 % of absolute cation charge, 86 % of
  the alkalinity produced) stay in the report as the measurement record.
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
  on 24 sound Plant B runs against the anchor's 7.78 %, nothing tuned. Cross-plant on
  24 seeds per row, same cut-off, **four rows because Plant A is two digesters**: **B 7.92 %,
  C 9.96 %, A-`unadapted` 2.54 %, A-`adapted` 0.52 %** — the last reproducing the
  coordinator's independent figure exactly. Recorded, not tuned away, and accepted by the
  lead as the physical answer.
- **The four-row table separates two effects.** The feed pattern is the larger — B and C take
  trucked batches, Plant A is fed steadily — but **within Plant A, on the same feed, the
  SAO-dominated baseline fires nearly five times as often** (2.54 % in 24/24 runs against
  0.52 % in 11/24). The pathway matters, not only the feed.
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

**Settled since**

- **`S6-04` keeps its name and the id pattern stays frozen** (the lead, 2026-09-09). The flag
  was the right call; the question is closed in the scenario header, `scenarios/README.md`
  and the decisions log.
- **Plant A's low trigger rate is accepted as the physical answer.** Its exposure is smaller
  than an earlier draft of this entry implied: the §7 factorial is B and C only, so `S4-02`'s
  six factorial cells all sit where the trigger fires in every run. Plant A runs S4-02 as one
  Tier-A cell in its separately-reported subset, and that cell is thin.
- **`docs/g1_anchor_report.md` §6.1 now says what closing the remaining 1.52× would take** —
  non-VFA titratable species ADM1 does not carry; a fitted κ (rejected: ruling M1 would then
  exclude the row from the match count) or a new extension (Phase 2). The g1 guard caught
  that this was missing after the rewrite; **the report was fixed, not the test**.

**Still open**

- The unadapted baseline's TAN band (3.5–3.7 measured against the ruling's 3.7–4.3), the two
  relayed anchor numbers that did not reproduce, and M2/M3/M4.

**Recorded as a follow-up for the next session that touches the plant configs**: Plants B and
C need a **declared design organic loading rate** from Muscatine's design or permit figures.
Nothing depends on it today — the trigger uses the VFA signal alone — and no design OLR is to
be invented in the meantime.

**Next session should start on** the lead's answers to the flagged items, then the tool
registry (§6.2).

---

### Session 2026-09-09 (close-out) — the lead's remaining rulings; G1 PASSES CONDITIONALLY

**Status: G1 passes conditionally.** The lead's close-out is under way; the merge waits on an
independent fresh-context engineering review of the branch, which was still running when this
entry was written. Not merged, not tagged, no session spawned.

**Done**

- **The unadapted baseline's TAN is settled.** 3.5–3.7 kg N/m³ **accepted as measured**; the
  earlier 3.7–4.3 **withdrawn**. `configs/plants/plant_A.yaml`'s `source:` note no longer
  reads `FLAGGED ... with the coordinator` — it records the ruling, so the log and the plant
  contract stop disagreeing. Same disposition, and same reason, as the adapted baseline's
  3.1–3.7 earlier the same day. No code change.
- **The HSW buffering share is reported on one declared basis: 91 % of the `S_cat` increment
  the calibration added**, with the basis stated in the sentence carrying the number, in the
  report, this file and the decisions log. Not the absolute-charge 78 %, and never a bare
  percentage — the three bases genuinely disagree and a percentage without its basis cannot
  be checked. The three-basis table stays as the measurement record.
- **The pathway effect is written up as a finding**, not a table row: `docs/g1_anchor_report.md`
  §5.4 now carries a controlled within-plant comparison. Same geometry, feed, schedule, seeds
  and 2.00× cut-off; one declared difference (`K_I_nh3`, and so which community carries the
  acetate flux). **2.54 % of days in 24/24 runs against 0.52 % in 11/24 — 4.9×.** Because the
  trigger measures a *relative* excursion, this is not the SAO baseline sitting at a higher
  VFA level: the same load fluctuations move the residual acetate pool further relative to
  where it has been when it drains through the slower syntrophic route. It also means the
  S6-01 / S6-04 pair differs in the observable record and not only in the answer key.
- **§7 of the report states which commit the shipped manifests carry**: the final
  **branch-head** SHA, not the merge commit, with the reason (the merge commit does not exist
  until after the merge, and regenerating afterwards means regenerating on `main`) and the one
  condition under which the record goes stale.
- **The matrix is regenerated at the final head as the last action before the merge**, so
  every manifest's `git_sha` is the code that produced it.
- **M2, M3 and M4 stay referred and unchanged**, recorded as a decision so a later session
  does not fix them on sight: M3 in particular is a design question (whether a Level-2 row is
  labelled in its own metadata), not a tidy-up.
- **Nothing further on H1**: the closure residual is accepted as stated.

**Still open**

- **M2** (the 480× between the HSW's visible alkalinity assay and its fed cation charge) — the
  decisions entry is with the lead verbatim; they rule after reading it. **M3** and **M4**
  likewise. Change nothing.
- The two relayed anchor numbers that did not reproduce (Dig2 max 0.636 not 0.80; exceedance
  8.25 / 9.18 % not 7.78 / 8.59 %). Every percentile the rulings turn on agrees to the third
  decimal, so no ruling is affected.
- **Plants B and C still need a declared design organic loading rate**, for the next session
  that touches the plant configs. Nothing depends on it and none is to be invented.

**Next session should start on** the tool registry (§6.2), once the review comes back and the
merge lands.

---

### Session 2026-09-09 (M2) — the assay and the fed charge now describe the same stream

**The lead ruled on M2** as an amendment to ruling 3 of 2026-09-03, and as an approved change
to a frozen config. Sequence set by the lead: the coordinator's fresh-context review verdict,
then this fix, then the matrix regeneration at the final head, then the merge and the tag.
The merge and the tag are the coordinator's; this session does neither.

**Done**

- **Part 1 — the feed alkalinity assay is computed from the full charge balance**, on every
  catalogue stream. `total_alkalinity` reports what a titration to the CO₂ end point measures
  at the stream's own pH — bicarbonate, free acetate, water — in the **same convention as the
  effluent channel** `alkalinity_total`. Its pair `feed_cation_charge` is what ADM1's charge
  balance must balance, `S_cat − S_an + [NH₄⁺]`. Electroneutrality makes the two equal exactly
  when a stream's declared pH is consistent with its composition.
- **The guard covers every stream**, names the stream and both numbers on failure, and was
  **checked against the pre-fix catalogue first**: it fails there on `high_strength_waste`
  (4.00×, and 503× against the pre-ruling assay) and on `food_waste` (0.33×, the same defect
  with the sign reversed). Mutation-measured: of the 12 ±50 % `s_cat` perturbations on the
  **six** fed streams, **10 fail, 1 is skipped by the floor and 1 survives** (cattle slurry
  at half its cations moves towards the centre of the band); `s_ic` and pH perturbations are
  caught only near the band edge. **This entry first claimed "10 of 10 on five streams" and
  the review of 2026-09-09 corrected it** — it was 9 of 10 on five, and there are six.
- **Part 2 — the HSW's implied pH was 13.04**, so the ruling's condition was met and the
  redistribution was made: `S_IC` 0.01 → **0.1607** kmol C m⁻³, declared pH 5.0 → **7.0**,
  **`S_cat` unchanged at 0.225**. `S_IC` is not fitted — it is the carbon that closes the
  charge balance at the declared pH. The visible assay goes 0.0214 → **10.75**, meeting the
  fed charge of 10.75 exactly.
- **Reconfirmed where ruling 3 put the digester**: alkalinity **5.125** (target ~5.0), median
  pH **7.262** (target ~7.3), **24 of 24 sound**. Alkalinity barely moves because the
  strong-ion difference sets it and that was held fixed.
- **`food_waste` fixed too** (`s_cat` 0.05 → 0.152, the assumed field; the cited pH kept). No
  plant feeds it, so nothing generated moves.
- **What moved, measured, nothing tuned to compensate** — Plant B only: biogas ratio
  1.41 → **1.45**, CH₄ fraction 0.722 → **0.700**, pH 7.293 → **7.262**, alkalinity
  5.12 → **5.125**, `vfa_median` 0.7753 → **0.7778**, `fos_tac_median` 0.1495 → **0.1501**,
  residual gap 1.52× → **1.51×**, trigger 7.92 % → **7.70 %**, operator overload
  0.17 % → **0.19 %**. **All 23 rows stayed inside their declared bounds and no tolerance was
  touched.** The report, the benchmark card, the sensor config and the channel docstring were
  updated to the new numbers rather than left stale.

**Flagged to the lead**

- **`biogas_mean` is now 1.45 against an upper bound of 1.5** — inside, but the least margin
  anywhere in the report, and the next thing that raises gas will breach it. The extra gas is
  CO₂, not methane, which is the expected consequence of putting the missing inorganic carbon
  in.
- Three catalogue streams sit at 1.35–1.47× inside the 1.5× band (`thickened_was`,
  `cattle_slurry`, `primary_sludge`). They pass as they stand and were **not** touched: their
  pH values carry sources, and moving a frozen config value that passes is the lead's call,
  not this session's.

**Still open**: M3 and M4, unchanged and with the lead. The two relayed anchor numbers that
did not reproduce. Plants B and C still need a declared design organic loading rate.

**Next**: the matrix regeneration at the final head once the review clears, then the tool
registry (§6.2) in a later session.

---

### Session 2026-09-09 (M2 review) — M2 is NOT closed; B3 fixed, B1 and B2 with the lead

An independent fresh-context review of the M2 fix (`d5fe13c`) found **three blockers**. The
coordinator confirmed every other number in that commit by independent recomputation. The
matrix regeneration and the merge are **held**.

**Fixed here: B3 — the M2 ratio guard was vacuous.** Two mutants were built and run, not
reasoned about, and both passed the whole 337-test suite: both functions returning `0.0`
(every stream falls under the guard's floor and is skipped), and `total_alkalinity`
returning `feed_cation_charge(...)` — which is exactly the strong-ion-difference definition
the decisions entry claims to reject because a test of it "could not fail". Nothing pinned
the absolute value of the feed alkalinity assay. The new guard pins both quantities on every
stream to the numbers the report quotes, asserts that `s_ic` moves one and `s_cat` the
other, and reproduces one stream from the ADM1 constants without calling the implementation.
**Both mutants were rebuilt and both now fail.**

**Open, with the lead, nothing changed:**

1. **B1 — `feed_cation_charge` omits the fed calcium.** The truth model's balance carries
   `+ 2 × S_ca`, the extension declares it with charge 2, all three plants enable it and the
   harness feeds it. Counted properly, **four of seven streams breach 1.5×** (primary sludge
   2.94, thickened WAS 2.71, cattle slurry 1.83, grass silage 1.69). **M2 is reduced from
   503× to about 2.9×, not closed.** The honest fix may mean redistributing the sludge
   streams — a further change to a frozen config.
2. **B2 — the invariant holds at catalogue TS, not for the assay a workflow reads.** The
   acetate term scales with a delivery's solids and the charge side does not scale at all.
   On real assay records the HSW's reported alkalinity ranges 6.1–38.0 against a fed charge
   of 10.75; primary sludge is outside 1.5× on 45 % of records, cattle slurry on 27 %.

**Also corrected, and it was this session's error:** the mutation claim "10 of 10 on five
fed streams" is **10 of 12 on six** — FOG is a Plant B feed, and cattle slurry at half its
cations survives by moving towards the centre of the band. Fixed in the test, the decisions
log, this file and the report. A claim stated as a measurement has to be reproducible.

`primary_sludge` at 1.470 against the 1.5 limit is now named in the report as a row to
watch, beside `biogas_mean` at 1.45.

**Next**: the lead's ruling on B1 and B2. Nothing is regenerated, merged or tagged until
then.

---

### Session 2026-09-10 — the calcium ruling; B1 closed against derived calcium; M2 closed

**The lead's three rulings of 2026-09-10 are done**, on `claude/g1-b1-redistribution`; PR #15's
head is unchanged until the coordinator confirms the pre-regeneration report. Nothing merged,
tagged or regenerated.

**Done**

- **`s_ca` is dissolved calcium and is DERIVED.** Unit check first: 0.05–0.15 g Ca/L is
  0.00125–0.00374 kmol/m³; the catalogue carried 0.4–1.6 g/L, i.e. total-calcium numbers
  in a dissolved-calcium field — a reduction of 10–30×, confirmed against the coordinator's
  conversion before editing. For the three calcite-buffered streams `s_ca` is the
  calcite-saturated value at the declared pH (truth model's `pK_sp_calcite`, `pK_a2` 10.33,
  γ = 1 ASSUMED, supersaturation 2.5× ASSUMED in the ruled 2–3×), solved jointly with the
  `s_ic` that closes the stream's own charge balance; mechanism Hjorth et al. 2010. Silage,
  HSW, FOG (and `food_waste`) are declared assumptions, flagged. Plausibility: Plant B 0.083
  and Plant C 0.138 g/L inside the sewage-liquor range; Plant A 0.026, below it, as calcite
  control at pH 7.5 predicts.
- **B1 redone against the corrected calcium, and both of the lead's tests passed with
  nothing tuned towards them**: `biogas_mean` **1.489** against 0.6–1.5 (was 1.532 in the
  first attempt), and the B/C control pair **restored** (C 7.252 > B 7.238; was inverted).
  All 23 anchored rows inside their declared bounds; Plant B 24/24 sound; alkalinity 5.116
  and pH 7.232 where ruling 3 put them.
- **Ruling 2 (liquor scaling) and the invariance-plus-physics guard approved as landed.** B2
  on real assay records is now 0.00 / 0.31 / 0.00 / 0.88 % outside 1.5× (slurry, primary
  sludge, WAS, HSW); the HSW remainder is the true-fractionation draw, a finding.
- **Ruling 3 (silage at 4.28) recorded as accepted**; with its assumed calcium the balance
  would close at 4.20 and at 4.28 the ratio is 0.771×, inside the band — reported, not moved.
- **Four trigger rows re-measured**: B 7.67 %, C 9.22 %, A-unadapted 1.49 %, A-adapted
  0.28 %. Both Plant A rows fell with the deeper slurry buffer and the pathway ratio widened
  4.9× → 5.3×; the finding survived a feed change that moved both its numbers.
- **M2 is closed**, and the report, the decisions log, the benchmark card, the sensor config
  and the channel docstring say so with the numbers of this round.

**Flagged, not decided here**

- `biogas_mean` at **1.489** against 1.5 — 0.7 % of margin, the row to watch.
- Primary sludge's derived calcium (0.20 g/L) sits just above the plausibility range; at
  pH 6.0 carbonate is scarce. Reported as-is.
- Plant A's baseline tables in `plant_A.yaml` were measured on the old slurry feed and not
  re-measured; both baselines ran 24/24 sound with pH 7.62–7.76.
- `S_I` still scales with the COD, not the liquor (previous entry).

**Next**: the coordinator confirms the pre-regeneration report → matrix regeneration at the
final head as the last action → the coordinator's review verdict → merge and tag by the
coordinator. Then the tool registry (§6.2).

---

### Session 2026-09-10 (final close-out) — M2 accepted closed; Plant A re-measured; rows to watch; regeneration next

**The lead accepted the pre-regeneration report and closed M2 at `c8c048f`.** The side branch
was a clean fast-forward onto PR #15's branch (merge-base `fd76983`, checked), so the PR now
carries every ruling. Final steps in the lead's order.

**Done**

- **Plant A's two baseline tables re-measured on the current feed** (full harness, 400-d
  burn-in, 180 d, seed 1000): adapted X_ac 1.129 → 1.065, X_sao unchanged, TAN 3.695 → 3.703;
  unadapted X_sao 0.910 → 0.853, X_ac 9.9e-05 → 0.0019, TAN 3.605 → 3.614; pH down 0.07 and
  CH₄ down 6 points on both, the slurry's newly present inorganic carbon leaving as CO₂. SAO
  shares 0.000 and 0.998 — **both baselines are still the communities they declare**, so the
  lead's stop condition was not met and `K_I_nh3` was not touched. `plant_A.yaml` updated
  with the old numbers beside the new; recorded in the decisions log.
- **The rows to watch, as ruled**: anchor side **`biogas_mean` 1.489** against its unchanged
  0.6–1.5 band; catalogue side re-checked — **`grass_silage` at 0.771×** is now the nearest a
  band edge (its accepted pH 4.28 kept while its assumed calcium fell); `primary_sludge` is
  exactly on the balance. Named in the report and the log.

**Next, in order**: commit and push; CI green; **regenerate the matrix at that head as the
last action** and report the SHA, cell count, wall-clock, index line count, the four trigger
rows and the operator-visible rate on the regenerated matrix; then **stop** — nothing pushed
after the regeneration, so every manifest's `git_sha` matches the merged head. The
coordinator reruns the independent whole-branch review at that head (the earlier one covered
`f8b27c4`), the verdict goes to the lead, and the coordinator merges and tags `g1-frozen`.
Then the tool registry (§6.2).

---

### Session 2026-09-10 (second review) — regeneration HELD; five blockers verified, two fixed, three with the lead

The independent whole-branch review at `f8b27c4` found **five blockers** in code no later
commit touched, two of which change what a regeneration writes. **The matrix was not
regenerated**; the wait armed for it was killed. Steps 1–3 of the close-out stand at `0cf564a`.
Everything below is on `claude/g1-review-blockers` (branched at `0cf564a`), not pushed to PR #15.

**Verified at the source, awaiting the lead's ruling, untouched**

- **B1** — the run id is the SHA-256 of a repo-literal salt and a fully public tuple; the
  review brute-forced two ids back to their scenarios. Needs a ruling on the id scheme; it
  changes every run id, so it must land before regeneration.
- **B3** — the foaming flag compares the titrimetric FOS/TAC (0.14–0.18 on every sound run)
  with 0.30, so it never fires and the foaming stress is dead in every cell. Needs a ruling on
  the trigger; the obvious shape is the hidden-state one the lead chose for overload.
- **B5** — redacting `baseline` does not hide it: the plant contract publishes per-baseline
  tables, the scenarios publish baseline → answer, and the Tier-C `vfa_ac` sensor reads true
  acetate (5.3× between S6-01 and S6-04 through `open_run`). Needs a ruling on the
  visible-information contract.

**Fixed, no ruling needed, mutation-checked**

- **B2** — the visible `calls.jsonl` hashed the scenario id, and *every* other harness call's
  real arguments too (derived seeds, fault plans, mixing structure, segment spans). The
  record is now kept twice: the full log truth-side, and a visible projection hashed over
  nothing the redacted manifest does not state, with the segments collapsed to one record;
  both logs start fresh on each generation (which also ends the append-on-regeneration).
  Tests reproduce every visible hash from public facts alone, with the truth-side log as
  the negative control.
- **B4** — the static checker now flags any import from `sim.run.layout`, the
  truth-reaching names, and any `truth…` attribute; the review's three-line bypass is
  planted and caught, seven routes one per line (the first draft missed
  `from sim.run import layout` — the test caught it), and the loader-only module stays clean.
- Four mutants built and run, all four fail their test.

**Non-blocking, done**: seeded shuffle of the matrix execution order (results still in cell
order); atomic `write_index_entry`; two stale notes corrected; the equalisation tank's
whole-horizon-mean initialisation recorded in code and the log as dormant-but-fault-sensitive,
behaviour unchanged.

`pytest -q` 345 passed, 2 skipped; `-m g1` 13 passed; ruff clean.

**Next**: the lead's rulings on B1, B3 and B5 → apply them (B1 and B3 both change what a
regeneration writes) → merge the side branch into PR #15's branch → CI green → regenerate at
that head as the last action → the review is rerun at that head → merge and tag by the
coordinator.

---

### Session 2026-09-10 (rulings applied) — B1, B3, B5 landed; four rows measured; regeneration pending CI

The lead's rulings on all five review blockers arrived at 03:32 UTC and are applied on
`claude/g1-review-blockers`, mutation-checked, documented in `docs/decisions.md` ("The lead's
rulings on the five review blockers, applied").

- **B1** — run ids are HMAC-SHA256 over the public cell keyed with a per-store secret salt
  (`truth_store/salt`, gitignored). Three required tests: two salts → different ids for every
  cell; no visible file carries salt, scenario or seed in any form; the brute-force inversion
  recovers nothing without the salt and finds the cell exactly once with it. Plus the lead's
  B2 addition: S0-01 and S5-01 visible logs are indistinguishable in structure.
- **B3** — foaming is a hidden-state trigger (gas > 1.80× its 30-d trailing median AND true
  VFA > its 30-d trailing median, current sample excluded from both); FOS/TAC > 0.30 stays
  visible, unwired, and its structural deadness is written up as a measurement-model finding
  in the report (§5.4) and the card (§5.4). Six mutants killed.
- **B5 option two** — Plant A's baseline tables and `K_I_nh3` moved to the truth-side record
  `sim/plants/truth/plant_A.yaml`; the visible contract is qualitative (no truth-side name,
  no digit in a baseline's prose; tested); `scenarios/` is barred by the AST checker and the
  loader; the card's §4.1 states what a workflow may and may not see. Five mutants killed.
- **Measured, recorded, not tuned** (24 seeds × B, C, A-adapted, A-unadapted): overload
  7.67 % / 9.22 % / 0.28 % / 1.49 %; foaming 7.20 % / 7.67 % /
  0.25 % / 0.14 %; operator FOS/TAC > 0.40 on Plant B 0.17 %.

**Next, in order**: merge the side branch into `claude/g1-scenario-generation`; push; CI green;
**regenerate the matrix at that head as the last action** and report the SHA, cell count,
wall-clock, index line count, the four-row overload table, the four-row foaming table and the
operator-visible rate; then **stop pushing**. The coordinator reruns the whole-branch review
at that head, then merges and tags.

---

### Session 2026-09-10 (final review) — F1/F3/F4/F5/F6 fixed; regeneration stopped and HELD for F2

The coordinator's final whole-branch review at `99a8947` found a leak that changes what a
regeneration writes; the regeneration was stopped a few cells in and its output discarded.

- **F1** — the seeded generation-order shuffle was a public permutation, so the visible
  timestamps mapped position to cell. Fixed both ways: the order is keyed with the store's
  secret salt, and `created_utc`, `t_utc`, `runtime_s` and real mtimes are gone from
  everything under `runs/<id>/`. Tests on the order (unit and end-to-end, salt-predicted)
  and on the absence of any visible timestamp; the decisions entry that claimed the leak
  closed is corrected.
- **F3** — no runtime in the visible projection (the burn-in's wall-clock marked S6-03).
- **F4** — the shared integration's calls are copied into every tier's logs; tested on all
  three tiers.
- **F5** — a no-write generation creates nothing, not even the salt; the salt is 0600.
- **F6** — `scenarios/README.md` known gaps and baseline table settled; report §5.4 numbers
  current and its stray row back in the table; the superseded table in the decisions log
  annotated.
- Nine mutants built, nine killed (one no-op survivor explained in the decisions log).

**F2 is with the lead** (the public horizon partitions the ladder; durations cannot change
after the tag). No `duration_days` was touched. **Do not regenerate until the coordinator
says so.** Next: push, CI green, report to the coordinator; then regenerate on instruction,
as the last action.


---

### Session 2026-09-11 (G1 remediation, the lead's §15 rulings) — C0–C4 on `claude/g1-review-blockers`

Four rulings, one commit each, on top of the F2 investigation (§1–§16 of
`docs/f2_horizon_report.md`; attribution corrected at `e688535`: the common-horizon
question is review finding F2, not the lead's):

- **Ruling 1 (`1353341`)** — the influent generator is prefix-stable in the horizon (child
  streams per (seed, feed, block) and per (seed, feed, assay)), so a longer run is the same
  realisation extended; the blend tank's hold-up and day-0 state come from the first 30
  days of arrivals. Prefix-stability test with a negative control; tank-window test; the
  fourteen equalisation tests unchanged. **One test left red at the band edge**:
  `test_plant_b_survives_the_generator_swings` (seed 11, 180 d, biogas ratio 1.5004) — the
  `biogas_mean` excess on one seed, recorded, not weakened.
- **Ruling 2 (`7d1554d`)** — `biogas_mean` investigated read-only (§16): the anchor column is
  total metered biogas (burner + boiler), so the basis is right in kind; the hidden HSW /
  FOG degradability centres (0.95 / 0.98) sit above the cited literature (~0.84 / ~0.92,
  an estimated ~7 % of gas). Band, basis and feed centres unchanged; the row to watch. The
  g1 gate is red at 1.54.
- **Ruling 3 (`3ec7bb8`)** — the horizon is the plant's: `horizon_days` A 365, B and C 200;
  every scenario at its own plant's horizon; `at_plant_horizon` in the matrix (mutation
  tested). Four-row trigger tables re-measured at the matrix horizons: overload B 7.12 %,
  C 9.82 %, A-unadapted 1.02 %, A-adapted 0.22 %; foaming 6.63 / 8.50 / 0.09 / 0.20 %.
  Expected regeneration cost of the 365-d Plant A cells: under two minutes on ~13 min.
- **Ruling 4 (`a91e71a`)** — S7-02 stays at onset 120 on 365 d; the takeover completes:
  X_sao 0.60 / X_ac 0.46 by day 348 / 350 (S5-01: 298 / 302), SAO 65 % / 85 % of the
  acetate-consuming biomass at the end. Record corrected to what is reached (§17).

**Done, in the coordinator's order:** PR #15 fast-forwarded to `a91e71a`; CI there is ruff
green, the default suite red on the one recorded band-edge test (both Pythons), the g1 gate
red on the two `biogas_mean` tests (1.536; 21 of 22 independent rows) and nothing else; the
117-cell matrix **regenerated at `a91e71a`** as the last action — 117/117 generated,
117/117 sound, 748 s wall-clock, 117 index lines, every manifest at the clean head, every
Plant A cell 365 d and every B/C cell 200 d, salt absent from every visible file
(`docs/f2_horizon_report.md` §18). This entry is a docs-only commit on the side branch so
the PR head stays that SHA. **That regeneration is VOID** (the coordinator, 13:22 UTC: the
sequence was fast-forward → CI green → regenerate, and CI was red on the band edge); it is
redone only at the head the lead's next ruling produces, on the coordinator's word. No
merge, no tag. Open for the lead: `biogas_mean` (band, basis or feed centres); the
coordinator's recommendation is HSW's hidden degradability to the cited 0.84, FOG left; the
read-only measurement of both options is in `docs/f2_horizon_report.md` §19.

---

### Session 2026-09-11 (continued) — rulings 5 and 6; the regeneration at `a91e71a` void

- **Sequence breach recorded** (the coordinator): the regeneration at `a91e71a` was made
  while CI was red on the band edge; it is void and is redone only at the final head on the
  coordinator's word.
- **§19** (`650e54b`): the HSW / FOG degradability corrections measured read-only, alone and
  together.
- **Ruling 5** — HSW 0.84 and FOG 0.92 as feed-centre corrections, band unchanged. Applied
  and measured at the head: `biogas_mean` 1.355 pass, 23/23 rows, both edge tests pass, the
  gate's CH₄-margin assertion trips at 0.643 (untouched; with the lead). Two derived check
  values re-derived (`tkn` of HSW and FOG) and one golden pin refreshed (the HSW alkalinity
  assay). **Held**: `test_cod_per_vs_is_derived_and_checked_against_the_literature` pins FOG
  COD/VS to the lead's 2.7–2.9, which the ruled centre cannot reach at the fixed inert
  equivalent (ceiling 2.677; derives 2.593) — question to the coordinator (`docs/f2_horizon_report.md` §20).
- **Ruling 6** — whole-run prefix stability from a fixed 200-day reference window; built,
  tested (bit-equal bar the last output point), mutation-checked; ruling 4 and the Plant A
  tables re-verified with no recorded number changed (§21).

- **The lead's answers A and B** (20:04 UTC): FOG's inert COD equivalent 2.9 (lipid-like,
  superseding 1.42) inside the ruling-5 commit — `biogas_mean` 1.373 pass, 23/23 rows,
  both edge tests pass, B 7.55 % / 6.60 %, leanest-seed CH₄ 0.6437; the gate's CH₄ margin
  re-declared at 0.60 in its own commit (`docs/f2_horizon_report.md` §22). Ruling 6 was
  committed first on its own at `f7a3e79` (the coordinator, 15:27 UTC).

**Next:** pytest, ruff and the g1 gate at the final head with the exact result; fast-forward; CI; STOP if red only on the CH₄-margin gate test; no
regeneration until told the head is final and CI is green.

---

### Session 2026-09-12 — the G1 regeneration at `49e9477`; stopped for the whole-branch review

**Done.** The lead's answers A (FOG inert COD equivalent 2.9, lipid-like) and B (the gate's
CH₄-fraction margin re-declared at 0.60) landed as `892bbb8` (ruling 5 with answer A) and
`49e9477` (answer B) on top of ruling 6 (`f7a3e79`). At `49e9477`: ruff clean, `pytest -q`
374 passed / 0 failed, `pytest -m g1` 13 passed / 0 failed; PR #15 fast-forwarded there and
CI green on every check (ruff, pytest 3.11 and 3.12, the sim/ gate, the gate G1 anchor
panel). On the coordinator's word the **117-cell matrix was regenerated with the tree at
`49e9477`**: 117/117 generated, 117/117 sound, 953 s wall-clock, 117 index lines, every
manifest carrying `49e9477`, every Plant A cell 365 d and every B/C cell 200 d, the salt in
no visible file (`docs/f2_horizon_report.md` §23, with the anchored rows, the three-plant
trigger tables and the leanest-seed CH₄ fraction). The regeneration writes nothing that is
committed; this docs-only commit on top of `49e9477` is the review head, and PR #15 is
fast-forwarded to it. **Stopped**: no merge, no tag, nothing further pushed.

**The review at `99b0547` found two blockers** (the coordinator, 2026-09-12 15:05 UTC).
Blocker 1 (the workflow-side checker was a deny-list; a module using only the public
generator recovered a run's answer key) is fixed as the tests-only commit `bc7b73f` — an
allow-list checker with the reviewer's module as a must-fail fixture — and the assay-noise
test gap is closed at `b808939` (both mutants caught). Blocker 2 (the visible record was
not prefix-stable; the truth was) awaits the lead's choice: option (b), per-block keyed
observation and note streams, is built, tested (375 passed, gate 13 passed, truth bit-equal)
and documented in a scratch worktree, uncommitted; option (a), a docs-only correction, is
drafted (`docs/f2_horizon_report.md` §24). PR #15 stays at `99b0547`.

**Blocked on.** The lead's choice for blocker 2, relayed by the coordinator; then one commit,
pytest/ruff, fast-forward, CI, regeneration on the coordinator's word (needed under b), and
the fresh review — not this session's to merge or tag.

**The next session starts on:** hold for the lead's `launch: tool-registry` to the
coordinating session (proposal §9.2, `tools/`: the registry every workflow must use, with
budgets enforced there — CLAUDE.md rule 2). Nothing in `runs/` or `truth_store/` is
committed; a later regeneration is made only at a reviewed head on the coordinator's word,
never while CI is red (the void regeneration of 2026-09-11 is the record of why).

### Session 2026-09-14 — ruling 7: the visible record made prefix-stable (blocker 2, option b)

**Done.** Blocker 1's hardening closed at `875fa2b` (three rounds; the checker's limit and
the structural defence recorded in the decisions log and card §4.1). The lead chose option
(b) for blocker 2 as **ruling 7** (2026-09-14): every stream of the visible record is keyed
`SeedSequence([seed, key, block])` — each sensor's six blocks by `sensor_block_rng`, the
historian's onsets and lengths by `historian_block_rng` with a key hashed from the
historian's own domain (the integer offset retired), the operator log's note days by a
per-day Bernoulli draw and its texts by a keyed permutation, both keyed `(seed, stage)` —
landed as ONE commit on `claude/g1-review-blockers` on top of `875fa2b`. Truth channels,
state, ash and flags of an S3-03/B/tier-C cell bit-equal to `875fa2b`'s (27 keys); all 15
visible series changed. `tests/test_visible_prefix.py` covers one Plant B cell (200 v 210 d)
and one Plant A cell (365 v 375 d): every sensor series, missingness, historian dropout,
note days and texts, feed log and assays equal over the shared prefix, with negative
controls. Ruling-6 entry, `REFERENCE_WINDOW_D` docstring, F2 §21/§23/§24 and the benchmark
card §9 now say a whole run — truth and visible record — is prefix-stable, which is true.

**Blocked on.** In order: CI on the fast-forwarded PR #15 head; the coordinator's word for
the regeneration at that head (the last action; §25 of the F2 report and this file as one
docs commit on top); then the coordinator's review and, only on the lead's say-so, the
merge of #15 and the `g1-frozen` tag — neither is this session's to do.

**The next session starts on:** unchanged — hold for the lead's `launch: tool-registry`.

### Session 2026-09-20 — the G1 regeneration at `7637f7a` (ruling 7); stopped for the fresh review

**Done.** Ruling 7 landed as `7637f7a` on 2026-09-14 (local: `pytest -q` 392 passed / 2
skipped / 0 failed, `ruff check .` clean, `pytest -m g1` 13 passed / 0 failed) and PR #15
was fast-forwarded to it the same day. CI at that head was red for six days for a reason
outside the PR — every job on all three runs failed within two seconds with no runner and
no log, on the repository's side; the lead cleared it (the repository is public now) and on
2026-09-20 every check is green on all three runs: ruff, pytest 3.11, pytest 3.12, the sim/
gate, the gate G1 anchor panel. On the coordinator's word the **117-cell matrix was
regenerated with the tree clean at `7637f7a`**: 117/117 generated, 117/117 sound, 786 s
wall-clock, 117 index lines and unique ids, 117 run dirs and truth dirs, every manifest
carrying `7637f7a`, every Plant A cell 365 d and every B/C cell 200 d, redacted manifests
without scenario id / seeds / baseline, `calls.jsonl` in every run, the salt in no visible
file. Every truth-side figure re-measured at this head equals §23's to the printed digit
(23/23 anchored rows inside; `biogas_mean` 1.373 / 1.397 / 1.091 / 1.743; leanest-seed CH₄
0.6437; B 7.55 / 6.60 %, C 9.82 / 8.50 %, A unadapted 1.02 / 0.09 %, A adapted 0.22 /
0.20 %), as it must with the truth bit-equal under ruling 7; every visible record is new.
`docs/f2_horizon_report.md` §25 has the full tables. The regeneration writes nothing that is
committed; this docs-only commit on top of `7637f7a` is the review head, and PR #15 is
fast-forwarded to it. **Stopped**: no merge, no tag, nothing further pushed.

**Blocked on.** The coordinator's fresh whole-branch review at the review head, the verdict
to the lead, and — only on the lead's say-so — the merge of #15 and the `g1-frozen` tag,
neither of which is this session's to do.

**The next session starts on:** hold for the lead's `launch: tool-registry` to the
coordinating session (proposal §9.2, `tools/`: the registry every workflow must use, with
budgets enforced there — CLAUDE.md rule 2; its structural defence for the truth store is a
recorded design requirement, decisions 2026-09-12 round two). Nothing in `runs/` or
`truth_store/` is committed; a later regeneration is made only at a reviewed head on the
coordinator's word, never while CI is red.

### Session 2026-09-20 (docs fix on the lead's approval) — FREEZE with two non-blocking findings fixed

**Done.** The coordinator's fresh whole-branch review at `8909772` returned FREEZE with no
blocking findings; the lead's word was "Approved, fix the docs" — one docs-only commit, then
the coordinator merges #15 and tags `g1-frozen` on green. Fixed, docs only, no code or test
change, no regeneration (the tree still differs from `7637f7a` in `docs/` alone and every
manifest carries `7637f7a`): (1) `docs/g1_anchor_report.md` presented the pre-ruling-5
`biogas_mean` 1.489 as current in the intro, the §3.3 history table and §5 — the table has a
fourth column with the at-head values (1.373, CH₄ 0.681, pH 7.232, alkalinity 5.051, VFA
0.7564, FOS/TAC 0.1508, 24/24 sound, the B/C control pair at the declared median feed
re-measured), and the least-margin statement is re-derived from the current table
(`total_feed_flow_median` at 1.12 against ± 15 %, then `biogas_mean` at 1.373, then
`fos_tac_median`); 1.489 stays only where it is historical. (2) The checker's recorded limit
(decisions, round three; card §4.1) names `str(<bytes>, <encoding>)` as an unnamed sibling of
the denied `.decode`/`.fromhex`, demonstrated by the reviewer of 2026-09-20 reading the
truth store through a runtime-assembled path — the recorded blind spot, not a new class;
`tests/test_truth_isolation.py` untouched, hardening stopped at round three by decision.

**Blocked on.** The coordinator's merge of #15 and the `g1-frozen` tag on green, on the
lead's approval — not this session's to do.

**The next session starts on:** hold for the lead's `launch: tool-registry`.

---

## Milestone 4 — Tool registry v1.0, frozen (weeks 10–13)

Exit criterion: every tool unit-tested; call logging complete; budgets enforceable.

### Session 2026-09-21 — the tool registry (`claude/tool-registry`, draft PR)

Gate G1 frozen at `9f635df` (PR #15 merged 2026-09-21; tag pending on the lead). Launched
by the coordinator on the lead's "Lets move to the next task", read as
`launch: tool-registry` (decisions, first entry of 2026-09-21). Branched from `9f635df`;
nothing under `sim/`, `scenarios/`, `state/` or the frozen configs is touched.

**Done.**

- **Part A, the core** (`tools/registry.py`, `tools/models.py`, `tools/schemas/`,
  `tools/config.py`): `Registry.call(name, **args)` validates against a Pydantic input
  with a unit on every numeric field, checks the budget (declared evaluation bound,
  wall clock since opening, assay units) and refuses with `budget_exceeded` before
  running, meters every model evaluation inside the tool and stops an overrun mid-way,
  applies the Level-8 directive in memory (`bayes_mcmc` returns non-converged chains:
  R-hat > 1.1, ESS below the floor, `converged=False`, a warning, a return value not an
  exception; truth-side outcome `injected_failure`, visible outcome `ok`), logs one
  record per call through `state.provenance.CallLog` in projection mode continuing the
  harness's sequence (and a full record truth-side), and reports the remaining budget for
  the task state. Every stochastic tool takes a seed; same seed, bit-equal output.
- **Part B, the process boundary** (`tools/transport.py`, `tools/server.py`,
  `tools/client/`, `tools/sandbox.py`; `docs/tool_registry_design.md` §4): proposed and
  built as a socket server in the privileged process and a workflow subprocess in which
  `sim`, `scenarios`, `anchor`, `eval` and `state` do not resolve (`-I -S`, a staged stub
  as `tools`, a fail-closed bootstrap, an empty cwd). `tests/test_tool_sandbox.py` drives
  every named route and a negative control. **Accepted by the coordinator** under the
  lead's delegation (2026-09-21) with one required hardening (the child-interpreter
  route: a plain child of the host interpreter ran `site` and the editable install's
  hook resolved `sim`), built as a dedicated sandbox venv; then the fresh-context review
  at `b9ca487` returned DO NOT MERGE on the host-interpreter route (B1: `/usr/bin/python3`
  by name or `PATH`, and `/proc/<ppid>` of the privileged process) and the sandbox became
  a **user + mount + pid namespace with a private root** in the one fix round: nothing of
  the host but `/usr/lib`, the bare interpreter binary, the venv, the box and a fresh
  `/proc` exists inside; fail closed; C1 (probes inheriting `PYTHONPATH`) fixed; CI
  enables unprivileged user namespaces on the Ubuntu 24.04 runner.
- **Part C, requested assays** (`tools/assays.py`, `configs/tools/assays.yaml`): eight
  assays priced and timed, served from the truth channels with the lab sensor's noise
  model, keyed by day, charged from `assay_units`.
- **Part D, the tools of §6.2**, each a pure function of its validated input, a metered
  model and a seed, each with a known-answer test (`tests/test_tools_known_answers.py`):
  `data_qc` (planted flatline, spike, drift, event gaps), `mass_balance` (a balanced
  digester closes at 0; an unrecorded delivery opens it; charge consistency from pH,
  alkalinity, VFA, TAN), `gsa_morris` (linear-additive: μ = μ* = coefficient × range,
  σ = 0), `gsa_sobol` (Ishigami closed form and scipy's estimator), `profile_likelihood`
  (flat on the ridge y = a + b, closed on y = at + b with the OLS interval),
  `fisher_info` (rank-one FIM, null direction (1, −1)/√2, correlation −1),
  `fit_lsq`/`fit_de`/`fit_cmaes` (the OLS optimum from synthetic data), `bayes_mcmc`
  (posterior N(ȳ, σ²/n) recovered; 90 % intervals cover at the nominal rate over 16
  seeds; three likelihoods agree), `filter_enkf` (tracks the Kalman filter on a linear
  system through a gap), `filter_mhe` (recovers a slow parameter of a driven system),
  `residual_diag` (names the load covariate; white noise unstructured; AR(1) serially
  structured), `voi_assay` (the Gaussian closed form ½ ln(1 + σ²ₚ/σ²ₙ)), `validate`
  (hand-computed MAE/RMSE/bias/coverage/interval score/CRPS, the Gaussian CRPS constant),
  plus `describe_model`, `simulate`, `feed_loads`, `request_assay`. Every numerical
  setting is in `configs/tools/*.yaml` (twelve files) behind Pydantic schemas.
- **The fitted model** (`tools/fitted.py`, `tools/privileged.py`): `adm1_fitted` from
  declared quantities only, the extensions declared as fitted applied silently, twenty
  multiplier parameters with the same interface on a Level-0 and a Level-6 cell; ~0.8 s
  per evaluation at 40 d on Plant C including the 400-d burn-in. `open_registry(run_id)`
  reads the cell through the truth-side index, the directive from `faults.json`, the
  fitted extensions from `parameters.json`, the seed as a keyed child of the observation
  stream, and continues both logs (`tests/test_tool_fitted_model.py`).
- **Records**: six decisions entries (the launch reading; the process boundary; the
  libraries; the fitted model; the eval-counting rule, wall clock and visible outcome;
  the assays); the benchmark card §4.1; `configs/README.md`; `tests/README.md`;
  `pyproject.toml` (emcee, cma; the three new sub-packages).

**Measured.** `ruff check .` and `ruff format --check .` clean; the four new test files:
59 tests. Full default suite (no `PYTHONPATH`) at the jail commit: 448 passed, 2 skipped
(the pre-existing Muscatine SCADA skips), 13 deselected, no warnings, 7 min 49 s; the g1
panel: 13 passed, 4 min 32 s (nothing under `sim/` or the frozen configs changed; CI
runs it because `configs/tools/` is new). CI on the GitHub runner builds the jail
through the sysctl step and passes the same tests.

**Not done / limits, stated plainly.** (1) The process boundary is proposed, built and
tested, not ruled on; the container form is deferred to release. (2) The fitted model is
not exercised through a full-horizon fit in the tests (a 200-d evaluation is ~4 s and a
Morris screen of 100 trajectories over 20 parameters is 2,100 of them); P0 will be the
first full-horizon user and the budgets of the scenario files were set before the cost
per evaluation was measured. (3) `filter_enkf`/`filter_mhe` run on registered
state-space models; the ADM1 state-space adapter (one-day transitions of the fitted
model with augmented slow parameters) is not built — the Level-4 row can be answered
with `simulate(biomass_scale=…)` and the fitters until it is. (4) `mass_balance`'s charge
check is the digestate's implied strong-ion difference, not a full charge closure of feed
against effluent, because the feed's charge is declared only as strong cations minus
anions.

**Decided under delegation** (`docs/tool_registry_design.md` §6; the lead may overrule at
the gate): the process boundary; the fitted model's visible contract; the `(tool,
probability)` reading of the Level-8 directive; wall clock as time since opening, with the
clock start written as the registry's first record (`registry.open`) to both logs.

**The next session (P0, §6.5) starts on:** `workflows/p0_scripted/`, a workflow script
run through `tools.sandbox.launch` against `tools.open_registry(run_id)`: QC → balance
check → Morris → Sobol → profiles → screened fit (LSQ then DE) → MCMC on the screened
subset → validate, with its thresholds declared in `configs/` before any agent code;
first task, a pilot on one Plant C cell to measure the cost of a full-horizon
evaluation against the frozen budgets (§7: "chosen from pilot runs so P0 completes
comfortably"). If the ADM1 state-space adapter is wanted for the Level-4 row, it is a
registry follow-up, not P0's.

---

## Milestone 5 — P0, the scripted pipeline (weeks 14–16)

Exit criterion: completes all Level 0–5 scenarios at all tiers; results plausible.

### Session 2026-09-21 — P0 built, tested through the jail, and piloted (`claude/p0-scripted`, draft PR #18)

Milestone 4 (tool registry v1.0) merged at `21424f2`, 2026-09-21. Launched by the
coordinator on the lead's "Launch now", read as `launch: p0-scripted` (decisions, first
entry of this session). Zero open PRs at launch; branched from `21424f2`; nothing under
`sim/`, `scenarios/` or the frozen configs touched; the registry's tested behaviour
(budgets, logging, the jail, the fitted model, the tool numerics) unchanged.

**Done.**

- **The three jail-review nits** (`96489ba`): the sandbox test's own probe runs in a
  scrubbed environment; a workflow's exit 111 is told from a jail failure by a marker
  file the jail script writes just before it starts the interpreter (tested with a
  workflow that exits 111 and a second launch in the same directory); the `launch`
  docstring says a sandbox directory is single-use.
- **The design note** (`docs/p0_design.md`, before any pipeline code): the fixed sequence,
  every threshold as a key of `configs/workflows/p0.yaml`, the ordered attribution rule,
  the abstentions, the deterministic plan with its fallback ladders, the output contract,
  the open points for the lead. **APPROVED by the lead via the coordinator** (points 1–3, 2026-09-21; the budgets are ruled after the pilot).
- **The task state** (`state/task_state.py`): one Pydantic schema for P0/P1/P2 — data
  quality per sensor, tier, candidate model, the classification with evidence and
  confidence, the screening trail, residual summaries, every action named as the call
  log names it (seq, args hash, version), tool failures, the budget left, validation,
  abstentions, the final label and estimates with intervals and their method, the plan
  and its fallbacks, the notes seen (day, author, length). Validated on the privileged
  side; a workflow builds the JSON to it.
- **Two registry additions** (decisions): `run.write_output` (`tools.server.OutputSink`,
  restricted to `runs/<id>/workflows/<workflow>/`, traversal / absolute / symlink /
  directory / empty refused, tested directly and over the wire with a negative control;
  `launch(workflow=...)`), and the visible log line's `seq`, `args_hash` and version in
  every call envelope (`tools.last_call()`).
- **The pipeline** (`workflows/p0_scripted/pipeline.py`, inside the jail; the rule-1
  checker reports nothing): QC on every sensor → the exclusion rules (a flatline ≥ 3 d
  flags; a drift flags only beyond the instrument's declared drift bound; spikes dropped;
  informative missingness abstains) → mass balance over 30-day windows → Morris on the 20
  declared parameters → Sobol with second order on the Morris subset → Fisher at the
  defaults (profiles when the plan allows) → LSQ multistart then DE → MCMC on the approved
  subset → residual diagnostics by feed batch, load, temperature, time → the assay spend
  at the day of the largest gas residual → validation on the frozen last quarter with a
  predictive ensemble → the attribution rule (R1 sensor → R2 influent → R5 state → R4
  parameter → R3 structural → R6 none, a pure function of the evidence) → `state.json`
  and `report.json`, checkpointed after every step. The plan is deterministic (a declared
  12 s per evaluation, set from measurement; declared ladders and replacements, each
  recorded); a non-converged
  sampler is a recorded failure with no posterior and no retry; notes are data.
- **The runner** (`tools/runner.py`): `run_workflow` and the CLI for one run or a batch
  over the truth-side index, `summary.json` per cell, one row per cell to
  `reports/p0_pilot.csv`.
- **Tests** (`tests/test_p0_pipeline.py`, `tests/test_workflow_output.py`): 13 tests —
  the checker on every workflow module; the sandbox document carries nothing of a run;
  a 30-day S0-01 cell of Plant C with a 40-evaluation budget completes through the
  fallbacks (schema, output contract, budget accounting, the action/log match line for
  line, no truth-side token in the outputs); the same cell twice gives the same state;
  the Level-8 row on a short S8-01 cell (one `bayes_mcmc` call, failure recorded, no
  posterior, truth-side `injected_failure` vs visible `ok`); the attribution rule on
  constructed evidence; the runner's selection and table; the write op's refusals.
- **Records**: eight decisions entries (the launch reading, the rules, the two registry
  additions, the stiffness pocket, the lead's approval, the round-1 pilot findings, the
  lead's rulings A and B, the round-2 outcome; the 12 s measurement is recorded inside
  the rules entry and `configs/workflows/p0.yaml`), card §4.2,
  `configs/README.md`, `scenarios/README.md`, this entry.

**Measured.** `ruff check .` and `ruff format --check .` clean; `python -m pytest -q`
without `PYTHONPATH`: 462 passed, 2 skipped (the pre-existing Muscatine SCADA skips), 13
deselected, 14 min 49 s. A 200-day evaluation of `adm1_fitted` on a generated cell costs
11.4–11.8 s (the daily feed log caps the integrator step at one day; 2.5–4.4 s on a
constant log, 2.1 s at 30 days; one constant-log vector, `k_dis` × 2 with `k_m_aa` × 0.5
on Plant B, 274 s); a 365-day Plant A evaluation 22–25 s. The
117-cell matrix regenerated at `5099c18` (12 min 38 s; 117/117 generated and sound;
every manifest carries `5099c18`; nothing committed).

**The pilot** (`reports/p0_pilot.csv`; ten cells at their FROZEN budgets on the matrix
regenerated at `5099c18`, three cells in parallel on this 4-core machine, 11:00–15:08 UTC;
"flag" is P0's flagged sensor against `correct_conclusion.flag_sensor`; "recovery" is
estimate / truth multiplier / whether the interval covers it, Levels 0–5 only):

| cell | truth | P0 label (rule) | flag | ok | wall min / allow | evals / declared | assays | fallbacks | guards | intervals | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0-01 B/A | none | state (R5) | - vs - | yes | 55 / 90.0 | 266 / 4000 | 2 / 2 | 6 | 1 | fisher | Y_ac:0.500/1.000/out Y_h2:0.500/1.000/in |
| S0-01 B/B | none | sensor (R1) +influent+state | ph vs - | yes | 50 / 90.0 | 235 / 4000 | 2 / 2 | 7 | 1 | fisher | Y_ac:1.052/1.000/in k_dec_X_ac:0.885/1.000/in |
| S0-01 B/C | none | sensor (R1) +influent+state | ph vs - | yes | 55 / 90.0 | 251 / 4000 | 2 / 2 | 9 | 1 | fisher | Y_ac:1.126/1.000/out Y_h2:1.427/1.000/in k_m_h2:0.809/1.000/in k_m_pro:1.108/1.000/out |
| S1-01 B/B | none | sensor (R1) +influent+state | ph vs - | yes | 60 / 90.0 | 280 / 4000 | 2 / 2 | 8 | 1 | fisher | Y_ac:0.500/1.000/in Y_h2:0.500/1.000/in k_dec_X_ac:0.536/1.000/in |
| S2-01 B/B | sensor | sensor (R1) +influent+state | ph vs ph | yes | 52 / 90.0 | 251 / 4000 | 2 / 2 | 7 | 0 | fisher | Y_ac:0.836/1.000/in Y_h2:0.833/1.000/in k_dec_X_ac:0.780/1.000/in |
| S3-01 C/B | influent | sensor (R1) +state | ph vs - | yes | 71 / 120.0 | 337 / 6000 | 3 / 4 | 5 | 0 | fisher | Y_h2:1.500/1.000/in k_m_ac:0.527/1.000/out |
| S4-01 B/B | state | sensor (R1) +state | ph vs - | yes | 68 / 120.0 | 331 / 6000 | 3 / 4 | 5 | 0 | fisher | Y_ac:0.761/1.000/in k_m_ac:0.667/1.000/out |
| S5-01 A/A | parameter | none (R6) | - vs - | yes | 85 / 120.0 | 214 / 6000 | 3 / 4 | 9 | 4 | fisher | Y_ac:0.816/1.000/in Y_h2:1.484/1.000/out |
| S6-02 B/B | structural | sensor (R1) +state | ph vs - | yes | 94 / 150.0 | 449 / 8000 | 3 / 6 | 5 | 0 | fisher | - |
| S8-01 B/B | sensor | sensor (R1) +state | ph vs gas_flow | yes | 89 / 150.0 | 413 / 8000 | 3 / 6 | 4 | 0 | fisher | - |

**Budget findings for the lead** (point 4 of the sign-off; no scenario's budget block
edited). (1) **The evaluation count is not the binding constraint at these allowances**:
at the measured 11.8 s per 200-day evaluation (22–25 s per 365-day Plant A evaluation;
three cells in parallel on four cores) a 90-minute allowance buys ~450 evaluations, 120
minutes ~600, 150 minutes ~750, against the declared 4,000 / 6,000 / 8,000. The ten cells
used 214–449 evaluations — 4–7 % of their evaluation budgets — while using 56–71 % of
their wall clock. **Proposed re-declaration**, so the two envelopes say the same thing:
`simulator_evals` = allowance × 60 / `eval_seconds_assumed` (12 s), rounded down to 50:
**450 / 600 / 750** for the 90 / 120 / 150-minute cells; for Plant A, whose evaluations
cost twice as much, either the allowance doubles or the count halves (225 / 300 / 375).
The alternative is raising the allowances: P0's declared plan at full size (Morris 8,
Sobol 32, 3 LSQ starts, DE 8, MCMC 8 × 30, ensemble 8 ≈ 1,060 evaluations) needs ~3.5 h
per 200-day cell at 12 s. (2) **P0 completed inside every frozen allowance** (10/10 cells,
50–94 min of 90–150), but only through the declared fallbacks: **no cell reached MCMC**
(the smallest sampler, 8 walkers × 10 steps = 88 evaluations, never fitted the plan's
share after the fit), so every cell reports Fisher intervals and abstains on
`posterior_intervals`, and **the Level-8 directive of S8-01 was never exercised** — a
tool failure can only be met by a workflow that reaches the tool, which at 12 s per
evaluation needs either a larger allowance or a smaller declared plan (e.g. Morris 4,
Sobol 8, one LSQ start, DE 2, MCMC 8 × 10 ≈ 330 evaluations ≈ 66 min). Sobol ran at
N = 8–16 of 32, LSQ with one start, DE with 2–8 generations; 8 guard trips across 5 cells
(DE, LSQ and Sobol at the measured rate under parallel load, 4 of them on the Plant A
cell). Profiles never fitted. (3) **Attribution at the approved thresholds**: 2/10 primary
labels match the truth (S2-01: sensor with pH correctly flagged; S8-01: sensor, but pH
flagged instead of the gas meter), 8/10 do not, and the misses are systematic rather than
random. Two rule paths read the plants' background and set the primary label: **R1c**
(`charge_consistent` false with a serially-structured pH residual) fired on 8/10 cells —
every Plant B and C cell at Tiers B and C, the three clean S0-01 cells included — and the
**QC informative-missingness path of R5** fired on 9/10 (every Plant B and C cell): the
observation model makes gaps 4× likelier during overload on every run, so the ratio
measures the plant, not a fault. **R2's COD path** (exactly 2 of 6 windows inadmissible)
fired as a secondary on 4 Plant B cells, S2-01 among them — the background's unrecorded
deliveries. Behind all three: after a fit of 2–4 parameters every calibrated channel keeps
a bias of 5–19σ (χ²/n of 10–100; the declared instrument noise is far below the model's
background misfit), so the post-fit rules that need "the others clean" (R1b) or "still
structured" (R3) cannot separate a fault from the background, and R4 saw S5-01's change
points (gas day 229, pH day 251, z 6.9 and 11) 22 days apart against its 20-day
tolerance. Proposed for the lead's ruling (a decisions entry, not made here: the
thresholds are frozen): (a) drop the QC-missingness path from R5 (keep the early-window
bias path) or require `event_missing_ratio` above a declared multiple of the tier's
declared stress multiplier; (b) fold R1c into R1b (the pH residual must be the single
offender) or raise `charge_drift`'s band above the background's 0.30–0.32; (c)
`balance_windows_min` 3; (d) `step_day_tolerance_d` 30. With (a)–(c) the ten primary
labels would have been `none` on every cell but S8-01 — the honest statement that at the
frozen budgets P0's residual rules see nothing through the background, which is what a
scripted baseline is for and what §6.7 B scores. (4) **Parameter recovery** (Levels 0–5,
20 approved-parameter estimates): the Fisher interval covers the truth multiplier 1.0 in
14 of 20; the estimates range 0.50–1.50 and 5 sit at a bound; intervals are wide because
the residual variance is the background's, not because the estimates are close.
**The pilot, round 2 — at the lead's rulings A and B** (`reports/p0_pilot.csv` now holds
this round; the round-1 table above is the record the rulings were made on). The same ten
cells on the matrix regenerated at `f4c5b03` (the four groups a stopped first attempt had
touched regenerated again at `5602f3f`, fresh logs, same ids), the ruled budgets (450 /
600 / 750; Plant A 300), the ruled plan (Morris 4, Sobol 8, one LSQ start, DE 2, MCMC
8 × 10) and thresholds, `plan.step_share` 0.75 (see the ruling's decisions entry: at
0.35 the ruled sampler was refused after the fit of a 90-minute cell), three cells in
parallel, 17:25–21:5x UTC:

| cell | truth | P0 label (rule) | flag | ok | wall min / allow | evals / declared | assays | MCMC | fallbacks | guards | intervals | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S0-01 B/A | none | none (R6) | - vs - | yes | 58 / 90.0 | 271 / 450 | 2 / 2 | run, not converged | 0 | 0 | fisher | Y_ac:0.500/1.000/out Y_h2:0.500/1.000/in |
| S0-01 B/B | none | none (R6) | - vs - | yes | 69 / 90.0 | 323 / 450 | 2 / 2 | run, not converged | 0 | 0 | fisher | Y_ac:1.052/1.000/in k_dec_X_ac:0.885/1.000/in |
| S0-01 B/C | none | none (R6) | - vs - | yes | 65 / 90.0 | 307 / 450 | 2 / 2 | skipped | 1 | 1 | fisher | Y_ac:1.126/1.000/out Y_h2:1.427/1.000/in k_m_h2:0.809/1.000/in k_m_pro:1.108/1.000/out |
| S1-01 B/B | none | none (R6) | - vs - | yes | 72 / 90.0 | 349 / 450 | 2 / 2 | run, not converged | 0 | 0 | fisher | Y_ac:0.500/1.000/in Y_h2:0.500/1.000/in k_dec_X_ac:0.536/1.000/in |
| S2-01 B/B | sensor | none (R6) | - vs ph | yes | 71 / 90.0 | 337 / 450 | 2 / 2 | run, not converged | 0 | 0 | fisher | Y_ac:0.836/1.000/in Y_h2:0.833/1.000/in k_dec_X_ac:0.780/1.000/in |
| S3-01 C/B | influent | none (R6) | - vs - | yes | 69 / 120.0 | 329 / 600 | 3 / 4 | run, not converged | 0 | 0 | fisher | Y_ac:1.500/1.000/in k_m_ac:0.348/1.000/out |
| S4-01 B/B | state | none (R6) | - vs - | yes | 72 / 120.0 | 335 / 600 | 3 / 4 | run, not converged | 0 | 0 | fisher | Y_ac:0.504/1.000/out k_dec_X_ac:0.872/1.000/in |
| S5-01 A/A | parameter | parameter (R4) | - vs - | yes | 93 / 120.0 | 243 / 300 | 3 / 4 | skipped | 1 | 0 | fisher | Y_ac:0.805/1.000/in Y_h2:1.500/1.000/out |
| S6-02 B/B | structural | none (R6) | - vs - | yes | 72 / 150.0 | 350 / 750 | 3 / 6 | run, not converged | 0 | 0 | fisher | - |
| S8-01 B/B | sensor | none (R6) | - vs gas_flow | yes | 54 / 150.0 | 250 / 750 | 3 / 6 | run, not converged (INJECTED, handled) | 0 | 0 | fisher | - |

What changed, and what did not. **P0 completes comfortably inside every allowance**
(54–93 min of 90–150; 33–81 % of the ruled evaluation counts — the 33 % is S8-01, 250 of
750, whose injected MCMC call charges nothing, the 81 % S5-01, 243 of 300; one guard trip
in ten cells). **MCMC is reached on 8 of 10 cells** (skipped on S0-01 B/C, where the guard tripped
at the measured rate, and on the Plant A cell, whose 24 s evaluations do not fit the
ruled sampler in 120 min); it converged on none (R-hat 1.9–96 at 8 × 10), so every cell
still reports Fisher intervals and abstains on `posterior_intervals` — the rule the Level-8
row exercises. **The Level-8 directive of S8-01 was exercised**: one `bayes_mcmc` call,
the injected payload (truth-side `injected_failure`, visible `ok`), the failure recorded,
no posterior, no retry. **Attribution: 5 of 10 primary labels match** (the three clean
S0-01 cells and S1-01 read `none`; S5-01 reads `parameter` through R4 at the 30-day
tolerance) and **no cell reports a false fault**; the five misses are all `none` where a
fault exists (S2-01 sensor, S3-01 influent, S4-01 state, S6-02 structural, S8-01 sensor):
after the fit every channel keeps its 5–19σ background bias, so a fault that shows in one
channel is never the *single* offender (S2-01's pH is 18σ off with the gas 14σ off), the
burn-in the fitted model runs at every evaluation absorbs S4-01's mis-initialised
biomass (early-window bias 0.2σ), S3-01's gas residual is explained by load rather than
by a feed covariate, and S6-02's residuals do not clear the structural rule's two-channel
condition. That is the honest scripted baseline of rule 5 at the recorded background
property. **Parameter recovery** (Levels 0–5, 20 estimates): the Fisher interval covers
the truth in 14; 7 estimates sit at a bound (Y_ac and Y_h2 at 0.5 or 1.5 on five cells);
the intervals are wide because the residual variance is the background's.

**Not done / limits, stated plainly.** (1) P0's rules are approved and frozen at the
lead's rulings of 2026-09-21: the four threshold changes the round-1 pilot suggested were
applied at `f4c5b03` by ruling B, and any later change is a decisions entry with the
lead's approval. (2) The full Level 0–5 sweep is not
in this PR: 78 cells at Levels 0–5 (Plants B and C: 15 + 15 at 90 min, 18 + 18 at 120 min; Plant A: 3 at
90, 9 at 120); at the measured 52–60 min per 90-minute B/C cell, ~70 min per 120-minute
B/C cell and ~85 min per Plant A cell that is ~88 h of runner time serial, ~29 h with
three cells in parallel on this 4-core machine (~22 h with four, at the cost of the
guard trips the measured rate then causes). The batch runner does it in one command
(`python -m tools.runner --workflow p0 --all --level 0-5`), resumable by table.. (3) MCMC at the sizes the wall clock allows does not converge on
ADM1, so P0 reports Fisher intervals by the same rule the Level-8 row exercises. (4) The
profile likelihood never ran inside the allowances (its registry bound is
`n_grid · n_starts · 201` = 1,005 evaluations at the declared grid, above every ruled
budget, so inside the ruled budgets profiles can never run and every cell's intervals are
Fisher or nothing). (5) The checker forbids the bare token `state`
in workflow code, so the label vocabulary is read from the configuration.

**Follow-ups recorded, not done** (from the gate review of `040c6d5`; for the evaluation
and P1 sessions, none of them a change to P0's frozen rules):
- (a) **Rule precedence is untested.** Mutants that swap R4 and R3, move R4 before R5,
  shift `step_day_tolerance_d` by one day, fold the charge evidence on a non-pH offender,
  or disable the wall-clock guard all survive the current tests. Each needs a constructed
  evidence case in `tests/test_p0_pipeline.py`.
- (b) **The second-pass edge case.** After a refit the excluded offender leaves the
  calibrated set, so `classify` can flag a second sensor, the pH charge fold can never
  attach after a second pass, and `flag_sensor` is the first flagged sensor in alphabetical
  order (`workflows/p0_scripted/pipeline.py`, the second pass and the attribution step).
- (c) QC-missingness and charge-drift evidence are still tagged R5 and "balance" in
  `classification.evidence` although, after ruling B, neither can fire a rule; they are
  evidence lines only and the tag should say so.
- (d) `summary.json`'s cost fields are the workflow's self-report copied from `state.json`,
  not the registry's meter, and neither log carries a per-call evaluation count. Adequate
  for P0; to be fixed before P1, when "evaluation reads logs only" (rule 3) has to hold
  against a workflow that could misreport.
- (e) No test pins a `configs/workflows/p0.yaml` value, and the determinism test pops
  `guards_tripped` before asserting it empty, which is flaky under load.
- (f) Profiles can never run inside the ruled budgets (limit (4) above); the design note
  §7 says so.

**The next session (milestone 6, the evaluation suite, §6.7) starts on:** `eval/`
reading `truth_store/<id>/` and `runs/<id>/workflows/<workflow>/state.json` only —
the label against `truth_label` (primary and secondary), the false kinetic-drift rate
from `final.parameters` and `kinetic_update`, correct abstention against `abstain_on`,
unsupported claims as report lines not traceable to an action's `seq`, parameter recovery
from the truth's segment parameters for Levels 0–5 only, the information-efficiency
counters from the truth-side log (runtimes) and `summary.json`, completion from
`final.completed`; and, on the lead's ruling, the budgets per (scenario, tier) from the
pilot table. P1 starts after the lead's budget ruling and, if any, the threshold rulings
of the pilot's proposal (rule 5: P0 is frozen before any agent code).
## Milestone 6 — The evaluation suite (weeks 17–20)

Exit criterion: every metric of §6.7 families A–D computed from records only, by code no
workflow can reach; the first scored P0 baseline table.

### Session 2026-09-22 — the evaluation suite built, tested, and the pilot scored (`claude/eval-suite`, draft PR)

Milestone 5 (P0) merged at `77508ca`, 2026-09-22. Launched by the coordinator on the
lead's literal `Launch: eval-suite` (decisions, first entry of this session). Zero open
PRs at launch; branched from `77508ca`; nothing under `sim/`, `scenarios/`,
`workflows/p0_scripted/` or the frozen configs touched.

**Done.**

- **The meter as the source of cost** (follow-up (d) of milestone 5; decisions): the
  truth-side call record carries what the registry's meter charged each call
  (`n_evaluations`, `assay_units`; the projection carries neither); `summary.json`'s cost
  fields come from the registry object after the launch (`cost_source: registry_meter`),
  the state's numbers kept beside them as `self_reported_*`, and `tokens_used` added for
  an LLM workflow's runner. A misreporting state changes nothing scored (tested).
- **`eval/`** (`docs/eval_design.md`): `records.py` (the eight records and nothing else;
  a failed run is a result with `problems`, never an exception), `trail.py` (a claim's
  path back to the log: `calls` → `actions[call_index]` → the visible line by `seq`,
  name, hash and outcome), `attribution.py` (B), `prediction.py` (A), `efficiency.py`
  (C), `reliability.py` (D), `score.py` (one row per run, 127 columns), `aggregate.py`
  (per (scenario, plant, tier, workflow); mean, rate, sd, seeded percentile bootstrap),
  `tables.py`, `__main__.py` (`python -m eval --workflow p0 --all --out …`). Every
  threshold, window, mapping and seed in `configs/eval.yaml` (`eval/config.py`).
- **The rule-1 checker** flags `eval` as a path segment and a module in workflow code;
  `tests/test_eval_isolation.py` shows a workflow reaching `eval/` caught, a workflow
  merely evaluating a model left alone, every `eval/` import on its allow-list, and the
  check catching a module that imports a workflow.
- **Tests** (30 new: `test_eval_metrics.py`, `test_eval_isolation.py`,
  `test_eval_end_to_end.py`, `test_runner_meter.py`, plus the extended checker): every
  metric on a constructed pair with a positive and a negative case; Level-6 recovery
  never scored, with the same estimates scored on Level 0 as the control; the short
  S0-01 cell of Plant C run through the jail once per session (fixtures moved to
  `conftest.py`) and scored from its records; the scorer writes nothing into the stores.
- **Records**: `docs/eval_design.md`; three decisions entries (the launch reading, the
  meter, the ten interpretations); card §7; `configs/README.md`; `tests/README.md`; this
  entry.

**Measured.** `ruff check .` and `ruff format --check .` clean; `python -m pytest -q`: 492 passed, 2 skipped
(the pre-existing Muscatine SCADA skips), 13 deselected, 19 min 24 s — measured while one
pilot cell held a core (milestone 5 measured 14 min 49 s on a quiet machine; the suite gained
30 tests and no second jail launch, so the quiet-machine time is CI's to report).

**The scored pilot** (`reports/p0_pilot_scored.csv`, `.json`, and the aggregate beside
them): the same ten cells as milestone 5's rounds, regenerated into this container's
store (run ids are store-specific), run through the runner three cells in parallel,
04:09–09:14 UTC, 63–115 min per cell (round 2 on the previous machine: 54–93; this
container is slower and the test suite ran beside the last three cells), then scored:

| cell | truth | final | exact | partial | drift | abstain | claims unsup. | gas nRMSE | pH nRMSE | gas cov90 | recovery cov (n) | evals / budget | wall / allow (min) | assays | MCMC | guards | mismatch |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S0-01 B/A | none | none | yes | 1.00 | no | - | 0/1 | 0.56 | 1.99 | 0.04 | 0.50 (2) | 271 / 450 | 72 / 90 | 2 / 2 | not converged | 0 | no |
| S0-01 B/B | none | none | yes | 1.00 | no | - | 0/4 | 0.55 | 1.12 | 0.02 | 1.00 (2) | 235 / 450 | 63 / 90 | 2 / 2 | skipped | 1 | no |
| S0-01 B/C | none | none | yes | 1.00 | no | - | 0/2 | 0.56 | 1.07 | 0.00 | 0.50 (4) | 307 / 450 | 81 / 90 | 2 / 2 | skipped | 0 | no |
| S1-01 B/B | none | none | yes | 1.00 | no | - | 0/2 | 0.31 | 0.87 | 0.07 | 1.00 (3) | 280 / 450 | 74 / 90 | 2 / 2 | skipped | 0 | no |
| S2-01 B/B | sensor | none | no | 0.00 | no | - | 0/5 | 0.84 | 2.53 | 0.02 | 1.00 (3) | 251 / 450 | 66 / 90 | 2 / 2 | skipped | 1 | no |
| S3-01 C/B | influent | none | no | 0.00 | yes | - | 0/5 | 0.46 | 1.14 | 0.02 | 0.50 (2) | 329 / 600 | 84 / 120 | 3 / 4 | not converged | 0 | no |
| S4-01 B/B | state | none | no | 0.00 | no | - | 0/4 | 0.47 | 1.57 | 0.00 | 0.50 (2) | 335 / 600 | 88 / 120 | 3 / 4 | not converged | 0 | no |
| S5-01 A/A | parameter | parameter | yes | 1.00 | - | - | 1/1 | 0.59 | 2.31 | 0.08 | 0.50 (2) | 243 / 300 | 115 / 120 | 3 / 4 | skipped | 0 | no |
| S6-02 B/B | structural | none | no | 0.00 | no | no* | 0/4 | 0.50 | 0.82 | 0.02 | - (-) | 350 / 750 | 90 / 150 | 3 / 6 | not converged | 0 | no |
| S8-01 B/B | sensor | none | no | 0.00 | no | yes | 0/4 | 0.54 | 0.72 | 0.00 | - (-) | 250 / 750 | 67 / 150 | 3 / 6 | injected, handled | 0 | no |

`abstain` is scored where the scenario declares `abstain_on` (`*`: a structural or
compound truth); `claims unsup.` is unsupported / total evidence items; `gas cov90` the
empirical 90 % coverage of the predictive ensemble on the hold-out; `recovery cov (n)`
the fraction of the n reported parameters whose interval covers the truth, Levels 0–5
only; `mismatch` whether the state's self-reported cost differs from the meter.

**What the scored table shows.** (1) **Family B.** Attribution exact on 5 of 10 (the three S0-01
cells, S1-01 and S5-01), partial credit identical (no compound cell among the ten); the
five misses are `none` where a fault exists, as in round 2. **False kinetic drift on 1 of
9 applicable cells**: S3-01 (an influent truth) drove `k_m_ac` to 0.348, below the prior's
central 90 % interval [0.46, 2.87] — exactly the behaviour the metric exists to catch.
**False kinetic update on 5 of 5 cells** whose answer key forbids it: every `none` verdict
offers the calibration as a kinetic update (R6 sets `kinetic_update`), so a fault P0
cannot see becomes an offered parameter change; the metric makes that cost visible.
Correct abstention: S8-01 yes (`posterior_intervals`), S6-02 no (P0 abstained on
`posterior_intervals` and `missing_transient`; R3 did not fire, so `alkalinity_budget`
and `inorganic_carbon_balance` were never declined). **Unsupported claims: 1 of 32
evidence items** — S5-01's R4 item, built with `calls=[]` (the P0 finding above); every
QC, balance and missingness item names its call and resolves through the log. The flagged
sensor is right on 8 of 10 (the two sensor cells flag nothing). (2) **Family A.** The
forecast block verified on 10 of 10 (a logged `validate` on the frozen last quarter). Gas
nRMSE 0.31–0.84; pH nRMSE 0.72–2.53 (worse than the observed spread on 7 cells). **The 90 %
coverage of the predictive ensemble is 0.00–0.08 on every cell** and the interval scores are
correspondingly large: the Fisher ensemble around the optimum is far narrower than the
5–19σ background misfit milestone 5 recorded — the same property, now as a coverage
number. CRPS is reported from that ensemble; `crps_posterior` is empty everywhere (no
posterior converged). Constraint violations 0. COD closure error 0.01–0.15 with 2
inadmissible windows on the four Plant B clean-ish cells (the background deliveries),
not evaluable at Tier A; `charge_consistent` false on every Tier B/C cell (the
background of ruling B(b)). Parameter recovery on the 8 Level 0–5 cells: 14 of 20
intervals cover the truth, 8 of 20 estimates at a bound (round 2 counted 7); withheld on
S6-02 and S8-01. (3) **Family C.** The meter, the summary and the state agree on every
cell (P0 is honest; the check is live for P1). Evaluations 33–81 % of the ruled counts,
wall clock 44–95 % of the allowances (S5-01 at 95 %: 115 of 120 min on this slower
machine); the log's span equals the runner's wall clock within a second and the summed
tool runtime equals it too — P0 spends its whole allowance inside tools, which is the
baseline an agent's thinking time is measured against. Uncertainty reduction 0–0.73 (zero
where the Fisher interval is wider than the prior's 90 % interval), 0–0.37 per assay
unit; tokens empty. (4) **Family D.** 10 of 10 completed, 0 invalid actions, 0 tool
errors, 1 injected failure (S8-01: truth-side only, the visible log says `ok`), 0
verifier rejections. `retries` 0–3 are P0's identical re-simulations of one parameter
vector (the point prediction is simulated for the residuals and again for validation),
not retries after a failure — the metric counts repeated (name, hash) pairs as §6.7 D and
the provenance docstring define it; recorded. **MCMC reached on 4 of 10** (round 2: 8):
the deterministic plan skipped it on five cells and the guard tripped on two, because
this machine is slower than the 12 s per evaluation the plan assumes (63–115 min per cell
against 54–93). The aggregate has one run per cell, so no bootstrap interval is filled.

**Not done / limits, stated plainly.**
1. Family A's forecast metrics are the `validate` tool's values as the state carries
   them, verified by the trail (a logged `validate` with outcome `ok` on the frozen window),
   not recomputed: the prediction series is not in the record. Follow-up: the registry
   persisting `validate`'s output on the truth side would let the scorer recompute.
2. P0's residual-derived evidence items carry no call reference (`classify` builds them
   with `calls=[]`), so its unsupported-claim rate is high wherever R1b/R2/R5/R4/R3 fire —
   a P0 finding recorded for the lead (rule 5: not changed here), with a one-line fix.
3. `abstain_on` vocabularies: the scorer matches names exactly; S6-01/S6-04/S7-02's
   `acetate_speciation`, `methanogenic_pathway_split`, S2-02's `ch4_yield` and S4-02's
   `transient_response` have no counterpart in P0's §3.8 list, so those cells can never
   score a correct abstention under P0 (S6-02's two names do match). A contract question
   for the scenario owner and P1.
4. The full Level 0–5 sweep is not run (the plan is in the PR body, for the lead).
5. The aggregate's bootstrap needs more than one run per cell; the matrix carries one
   replicate, so every interval in the pilot aggregate is empty by construction.

**Follow-ups recorded, not done.** (a) Persist `validate`'s output on the truth side so
family A can be recomputed rather than verified (registry, privileged). (b) P0's
residual-derived evidence items should name the `residual_diag` call (one line in
`classify`'s callers; rule 5: the lead's call). (c) The `abstain_on` vocabulary of
S6-01/S6-04/S7-02, S2-02 and S4-02 has no P0 counterpart (limit 3). (d) A machine-speed
record beside every pilot table: the plan's 12 s assumption decides whether MCMC runs,
and this container needs ~14 s under three loads.

**Review round 1 (the coordinator's independent review of `2caa5f3`, 2026-09-22 ~11:45
UTC: MERGE AFTER FIXES; both blockers verified on the branch and fixed in the next push).**
B1: the per-call meter count in the truth-side log was the metered models' own tally
(`context.evaluations_used`) and missed every evaluation a tool charges to the meter
directly — the filters charge per ensemble transition, so `filter_enkf` logged 0 against
a meter of 15,600. Now `Registry.call` snapshots the meter before the call and logs the
difference on every path; `tests/test_runner_meter.py` calls `filter_enkf` and asserts the
log sums to the meter. P0 never calls a filter, so the pilot table is unchanged. B2: an
evidence item whose rule and value keys were all unregistered in `claim_sources` counted
as supported if it cited any ok call; `unmapped_claim: unsupported` is now a declared
`eval.yaml` key (the default) and the case is tested both ways; P1's contract says so.
The coordinator's reading on a launched run with no valid state — an attribution miss,
in the denominator, with `attribution_exact_n` beside the rate — is implemented and
recorded (decisions). Nits in the same push: `meter_agrees_with_summary` compares the
call count too; the loader's message names the unreadable answer-key file; `OUTPUTS_DIR`
is declared beside the task-state schema (`state/task_state.py`, re-exported by
`tools.server`) so the scorer imports no registry module for it; `configs/eval.yaml` is
caught by the checker's path rule (with a probe); the design note says the forecast
window is the state's own declaration, that `completed` is half self-report, and what
follow-up (a) must persist; and the arithmetic above is corrected (false kinetic update
5 of 5; 8 of 20 at a bound — round 2 counted 7).

**The next session starts on:** the lead's answer on the sweep (run it with
`python -m tools.runner --workflow p0 --all --level 0-5` in three processes and score with
`python -m eval`), and P1 (the single constrained agent, §6.5), which needs the
evaluator's contract above: the state's `actions` name log lines, evidence items name
calls, abstentions use the scenario vocabulary, and the runner fills `tokens_used`.


### Session 2026-09-22/24 — the Level 0–5 sweep: the scored P0 baseline over 78 cells (`claude/p0-sweep`, draft PR #20)

PR #19 (the evaluation suite) merged at `b715fc2`, 2026-09-22. The lead ruled on the
sweep the same day (decisions: single-seed, now, three in parallel, its own PR); the run
plan of PR #19 was followed without a code change. Nothing under `sim/`, `scenarios/`,
`workflows/` or the frozen configs touched; nothing tuned on the table.

**Done.**

- **The sweep**: the 78 Level 0–5 cells of the matrix in this container's store (the 8
  Level 0–5 pilot cells taken as done at the same frozen P0 and budgets; 70 run), three
  detached driver processes with fixed lists ordered longest first, one runner
  invocation per cell, a cell with an existing `summary.json` skipped; 2026-09-22
  17:01 → 2026-09-24 00:20 UTC (31 h 20 min wall; 100.4 runner-hours; a fourth process
  took list b's last cell at 22:16 because the skipped pilot cells had not been
  discounted when the lists were dealt). **78/78 completed**, no runner error, no cell
  run twice. Ten checkpoints pushed the partial tables (`ac16561` … `2ec0be0`).
- **The tables**: `reports/p0_sweep.csv` (the runner's table), `reports/p0_sweep_scored.csv`
  / `.json` (one row per cell, the 127 columns of `python -m eval`) and
  `reports/p0_sweep_scored_aggregate.csv` / `.json` (one run per cell: means only, no
  bootstrap interval, by construction of a single-seed sweep).
- **Machine speed** (tool runtime of evaluating calls over evaluations charged, three
  in parallel on this 4-core container): 14.2 s per evaluation on Plant B, 13.8 s on
  Plant C, 25.4 s on Plant A (365-day cells); 23,688 evaluations in all. Per cell:
  60–90 min on B (mean 72), 64–87 on C (76), 73–115 on A (94), against allowances of
  90 / 120 min; 59 % of the ruled evaluation counts and 72 % of the wall clock on average.

**The scored baseline** (from `reports/p0_sweep_scored.json`; `exact` is the final label
set against `truth_label`, `false drift` a kinetic estimate outside the prior's 90 %
interval on a non-parameter truth, `false update` a kinetic update offered where the key
forbids it, `abstention` scored where the truth is structural or compound, `gas cov90`
the 90 % coverage of the predictive ensemble on the hold-out, `recovery cov` the fraction
of reported parameters whose interval covers the truth):

78 cells; 78 completed; 17 exact; 10 with guard trips; 52 reached MCMC; 0 converged

| level | cells | completed | exact | primary in truth | false drift | false update | abstention (applicable) | unsupported claims | gas cov90 (mean) | recovery cov (mean) | guard trips | MCMC reached | MCMC converged | wall / allow (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 6/6 | 5/6 | 5/6 | 1/6 | - | - | 0/20 | 0.03 | 0.71 | 2 | 3 | 0 | 0.79 |
| 1 | 6 | 6/6 | 5/6 | 5/6 | 2/6 | - | - | 1/27 | 0.04 | 0.69 | 0 | 1 | 0 | 0.80 |
| 2 | 21 | 21/21 | 5/21 | 6/21 | 7/21 | 14/21 | - | 4/68 | 0.04 | 0.62 | 5 | 12 | 0 | 0.79 |
| 3 | 21 | 21/21 | 0/21 | 0/21 | 8/21 | 17/21 | - | 3/70 | 0.05 | 0.68 | 1 | 18 | 0 | 0.65 |
| 4 | 14 | 14/14 | 0/14 | 0/14 | 4/14 | 13/14 | 0/7 | 2/59 | 0.04 | 0.71 | 1 | 12 | 0 | 0.69 |
| 5 | 10 | 10/10 | 2/10 | 2/10 | - | - | - | 3/29 | 0.05 | 0.70 | 1 | 6 | 0 | 0.73 |

| tier | cells | completed | exact | primary in truth | false drift | false update | abstention (applicable) | unsupported claims | gas cov90 (mean) | recovery cov (mean) | guard trips | MCMC reached | MCMC converged | wall / allow (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 32 | 32/32 | 7/32 | 7/32 | 12/28 | 20/24 | 0/3 | 10/52 | 0.06 | 0.67 | 5 | 21 | 0 | 0.72 |
| B | 23 | 23/23 | 6/23 | 6/23 | 10/20 | 13/16 | 0/2 | 2/94 | 0.05 | 0.78 | 3 | 17 | 0 | 0.71 |
| C | 23 | 23/23 | 4/23 | 5/23 | 0/20 | 11/16 | 0/2 | 1/127 | 0.02 | 0.59 | 2 | 14 | 0 | 0.76 |

| plant | cells | completed | exact | primary in truth | false drift | false update | abstention (applicable) | unsupported claims | gas cov90 (mean) | recovery cov (mean) | guard trips | MCMC reached | MCMC converged | wall / allow (mean) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 12 | 12/12 | 1/12 | 1/12 | 0/8 | 6/8 | 0/1 | 4/15 | 0.04 | 0.61 | 6 | 0 | 0 | 0.84 |
| B | 33 | 33/33 | 8/33 | 9/33 | 7/30 | 21/24 | 0/3 | 5/95 | 0.04 | 0.70 | 2 | 25 | 0 | 0.69 |
| C | 33 | 33/33 | 8/33 | 8/33 | 15/30 | 17/24 | 0/3 | 4/163 | 0.04 | 0.68 | 2 | 27 | 0 | 0.72 |

| truth | final label sets (count) |
|---|---|
| influent | none (16), sensor (2), state (1), sensor+structural (1), parameter (1) |
| none | none (10), parameter (1), sensor (1) |
| parameter | none (5), sensor (2), parameter (2), state (1) |
| sensor | none (12), sensor (5), parameter (2), sensor+structural (1), structural (1) |
| state | none (5), parameter (1), sensor (1) |
| state+sensor | none (6), parameter (1) |

**What it shows, in words.**

1. **Attribution: 17 of 78 exact (22 %).** P0 is right on the clean cells (10 of 12
   Level 0–1) and on 2 of 10 parameter cells (S5-01 A/A, S5-02 C/A, both through R4);
   it names the sensor on 5 of 21 sensor cells (the four CH₄-analyser flatlines of
   S2-02 at Tiers B/C, and S2-01 at Tier A on both plants — where the flag is wrong, see
   4); **no influent cell (0 of 21) and no state cell (0 of 14) is ever attributed**.
   The confusion is one-directional: 54 of the 66 faulted cells read `none`, the honest
   scripted baseline of rule 5 at the recorded background misfit. **Two false faults on
   clean cells**: S1-01 C/A reads `parameter` (R4: a common change point in the
   background) and S0-01 C/C reads `sensor` (`digestate_ts` flagged by QC at Tier C).
2. **False kinetic drift: 22 of 70 applicable cells (31 %)**, always `k_dec_X_ac`,
   `k_m_ac` or `k_m_h2` driven to a bound; **Tier C never drifts (0/20)** while Tier A
   drifts on 12 of 28 — with fewer channels the screened fit compensates a fault with
   kinetics; Plant C drifts twice as often as Plant B (15 vs 7 of 30).
3. **False kinetic update: 47 of 56 cells** whose key forbids it — every `none` verdict on
   a faulted cell offers the calibration as an update (R6 sets `kinetic_update`).
4. **Correct abstention: 0 of 7 applicable** (the S4-02 compound cells): their
   `abstain_on` names (`transient_response`, `peak_load_behaviour`) have no counterpart
   in P0's vocabulary, so the metric cannot be met by P0 (the contract finding of PR #19).
5. **Unsupported claims: 13 of 273 evidence items (4.8 %)** — exactly the residual-derived
   items P0 builds without a call reference (R4: 8, R3: 3, R5: 2; the PR #19 finding);
   every QC, balance and missingness item resolves through the log. The flagged sensor
   is right on 4 of 21 sensor cells.
6. **Family A.** The forecast block verified on 76 of 78 (see 8); mean gas nRMSE 0.62,
   pH nRMSE 1.49; **the 90 % coverage of the Fisher predictive ensemble averages 0.04**
   — the background misfit as a coverage number on every level, tier and plant.
   Parameter recovery on all 78 (Levels 0–5): 136 of 204 intervals cover the truth
   (67 %), 64 of 204 estimates at a bound.
7. **Family C/D.** The meter, the summary and the state agree on every cell; 197 assay
   units spent (uncertainty reduction per unit 0.16 on average); 4 invalid actions (see
   8), 0 tool errors; MCMC reached on 52 of 78 (never on Plant A: 25 s per evaluation
   does not fit the ruled sampler) and **converged on none**; 10 guard trips.
8. **A P0 finding (not changed, rule 5): S2-01 at Tier A on both plants ends with an
   empty objective.** QC flags the drifting pH probe (correctly) and excludes it; the
   post-fit single-offender rule then flags gas flow — the only remaining channel — and
   the second pass excludes it too, so the refit and the validation are refused
   (`fit_lsq`/`fit_de`: "data: tuple should have at least 1 item"; two invalid actions
   per cell), the first fit's bound-sitting estimates stand, no forecast is scored, and
   the reported flag is `gas_flow` (milestone 5's follow-up (b): the first flagged sensor
   in alphabetical order). The label `sensor` is exact; the flag is wrong.

**Measured.** `ruff check .` and `ruff format --check .` clean on the final head; the
branch carries no code change over `b715fc2` (reports and docs only), and the full
`python -m pytest -q` was run on the final head before the last push — its result is in
the PR body's Checks line.

**Not done / limits.** (1) Single seed: no bootstrap interval and no seed variance in
the aggregate; the 5-replicate matrix is the pre-registered runs' (§7). (2) The machine
is slower than the plan's 12 s per evaluation, so the deterministic plan skipped MCMC
on 26 cells and never ran it on Plant A; a faster machine gives a different P0 (the
`fallbacks` and `guards_tripped` columns say where). (3) The four-hour launch delay and
the two harness "container restarted" notices (the host never restarted) are in the PR
body.

**The next session starts on:** P1 (the single constrained agent, §6.5), against this
table as the baseline and the evaluator's contract (`docs/eval_design.md`): actions
name log lines, evidence items name calls and use registered rules and value keys,
abstentions use the scenario vocabulary, the runner fills `tokens_used`. The two P0
findings (empty objective at Tier A on S2-01; residual-derived evidence without a
call) and the `abstain_on` vocabulary gap are the lead's to rule on before P1 is scored
against P0.
