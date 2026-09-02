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
