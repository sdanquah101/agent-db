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
  proposal §8). Not started this session.
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
