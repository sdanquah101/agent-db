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

**Blocked / open**

- **Domain sign-off on the ADM1 recommendation** (`docs/adm1_comparison.md` §6) is
  required before Milestone 2 starts. The recommendation is to write our own
  Petersen-matrix ADM1 in `sim/`, validated against bsm2-python and ADM1F, using
  QSDsan's `ADM1`/`ADM1p` process definitions as the structural reference for the
  SAO / ionic-strength / precipitation extensions.
- **Open datasets not yet identified** (second half of the Milestone-1 exit criterion,
  proposal §8). Not started this session.
- ADM1F could not be built as its README describes (PETSc external downloads are
  blocked in the sandbox; the shipped makefile is incompatible with PETSc ≥ 3.15). It
  built against Ubuntu's `petsc-dev` 3.19 + `libadolc-dev` by compiling the source
  directly. Recorded as a deployability finding, not a blocker.

**Next session should start on**

1. Get the ADM1 recommendation reviewed; record the decision in `docs/decisions.md`.
2. Anchor-dataset search (§8): Tisocco et al. co-digestion data, Weinrich-group
   agricultural plant data, Zenodo/Mendeley AD time series; record candidates and
   licences.
3. If the recommendation is accepted: `sim/adm1/` skeleton — state vector, Petersen
   matrix as data (`configs/`), rate function, gas phase, algebraic pH — with a
   ring test against `scripts/adm1_candidates/results/bsm2python.json` and
   `adm1f.json` as the first `tests/` for `sim/`.

**Resource cost this session (rough)**

| Item | Wall-clock | Notes |
|---|---|---|
| Session total | ≈ 1 h 35 min (00:49–~02:25 UTC) | one agent session, 4 vCPU / 15 GB container |
| Candidate installs | ≈ 12 min aggregate, mostly overlapped in background | QSDsan ≈ 6 min (largest: ~1.0 GB venv), bsm2-python ≈ 2 min (0.7 GB), EXPOsan ≈ 2 min, PyADM1ODE ≈ 1 min (0.5 GB), PyADM1 clone < 1 min |
| ADM1F | ≈ 5 min total | PETSc-from-source attempt failed after 1.5 min (network policy); `apt-get petsc-dev libadolc-dev libcolpack-dev` ≈ 45 s; two direct compiles ≈ 30 s each; PETSc source clone 0.6 GB (unused) |
| Probes | < 3 min aggregate compute | PyADM1 ≈ 50 s per full run (×3 runs incl. two adapter fixes); bsm2-python ≈ 10 s; QSDsan ≈ 8 s incl. warm-up; ADM1F ≈ 2 s per variant; PyADM1ODE test suite 20 s (790 tests) |
| Disk | ≈ 3.3 GB scratch | five venvs + PETSc source; all under the session scratchpad, nothing in the repo |
| CI | not yet run | first run will be on the branch push |

No LLM-agent compute was spent inside the benchmark (no workflows exist yet); the
figures above are development cost only.
