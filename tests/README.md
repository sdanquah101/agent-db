# tests/

Run with `pytest -q` from the repository root. The suite needs only the repository's own
dependencies; oracle values from other ADM1 implementations are committed as JSON.

Two tests encode non-negotiable rules from `CLAUDE.md` rather than ordinary behaviour:

- `test_truth_isolation.py` — no module under `workflows/` may import from, or reference
  a path containing, `truth/` (rule 1). It self-checks against a synthetic violating
  file so it cannot pass vacuously while `workflows/` is still mostly empty.
- `test_scenario_schema.py` — the scenario YAML contract (proposal Appendix B) loads,
  round-trips and rejects malformed input.

The ADM1 core (`sim/adm1/`):

- `test_adm1_petersen.py` — the Petersen matrix loads from data, every process conserves
  COD, C, N and charge, spot entries match BSM2, and the expression evaluator rejects
  anything but arithmetic.
- `test_adm1_physchem.py` — temperature corrections, speciation, the pH root-find
  (residual, monotonicity, equivalence with the BSM2 quadratic) and the gas phase.
- `test_adm1_model.py` — the `simulate()` API: shapes, influent sample-and-hold vs linear
  interpolation, determinism and purity, Radau cross-check, argument validation.
- `test_adm1_ring.py` — ring tests against bsm2-python (Probes 1 and 2 from
  `scripts/adm1_candidates/common.py`; the 280-day BSM2 dynamic influent), agreement to
  3 significant figures (relative difference ≤ 5e-4), and a step-size-collapse check on
  the overload probe. The dynamic sample-and-hold case restarts the integrator 26 880
  times and takes about 2–3 minutes; it is the acceptance test of the 2026-09-02 ADM1
  decision and must not be shortened or loosened to pass.

`conftest.py` provides the default configuration, the Rosen & Jeppsson (2006) initial
state and the probe-definition module as fixtures.
