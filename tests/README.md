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
- `test_adm1_extensions.py` — the §6.1 extensions (`configs/adm1/extensions.yaml`,
  `sim/adm1/extensions.py`): every extension row conserves COD, C and N (charge too,
  except the calcite row whose −2 is a matrix convention, S_IC carrying charge 0 as a
  total; the calcium balance and the 2 eq/mol alkalinity drop are tested dynamically
  instead, since electroneutrality is enforced by the pH solver); each additive
  extension, when
  inert, reproduces the base Probe-1 oracle; the carbonate switch is pinned as a small
  genuine change; SAO takes over at a 60-d HRT under high free ammonia, washes out at
  20 d, is inhibited less than acetoclasts, and uses the hydrogenotrophic pH window;
  Davies coefficients have the right limits and A(T) the right values, and shift pH and
  NH₃; calcite is a sink for HCO₃⁻ and Ca²⁺, K_sp(T) matches Plummer & Busenberg, and
  the saturation index and under-saturation flag are reported; all four integrate
  together; determinism.

The virtual plants (`sim/plants/`, `configs/plants/`):

- `test_plants.py` — the three configurations load and match the scenario enum; the
  anchoring status and scenario subsets follow the decisions log; every dataset-anchored
  number names its source and Plants B/C's feed, HRT, SRT, temperature and zero-delivery
  statistics are re-derived from the committed Muscatine daily file; the V/Q-vs-HRT
  consistency check fires; B and C are a controlled pair (same geometry, temperature
  and hidden-error distribution, feeds differ); headspace is the BSM2 ratio and marked
  assumed; the hidden active-volume error is seeded, bounded and two-sided and never
  touches the declared config; declared vs true geometry compile with every plant's
  truth extensions; and SAO takes over at Plant A's declared geometry and 40-d HRT
  within 180 d (the condition of the SAO-scenario decision; provisional feed TAN).

- `test_mixing.py` — the parked two-zone imperfect-mixing model
  (`sim/plants/mixing.py`, the Level-6 truth variant, not the plant contract): bitwise
  reduction to `simulate` (no extensions) and `simulate_extended` (all four) at
  β = φ = 0, with a non-ideal structure shown to change the answer; the analytical
  two-compartment tracer solution on S_cat; the fast-exchange well-mixed limit (which
  also checks the stagnant zone's gas reaches the shared headspace); the plant contract
  asserted CSTR-only (schema, YAMLs, package API); a plant's true geometry compiles
  under the structure.

The influent generator (`sim/influent/`, `configs/influent/`):

- `test_influent.py` — the provisional feed-fractionation catalogue loads, covers every
  frozen plant feed with the right kind, and has every numeric leaf marked `# DESIGN`;
  units in every numeric field; the seeded true-fractionation draw is deterministic,
  order-independent, sums to one and keeps catalogue zeros (200 seeds), and is centred
  on the catalogue with the declared Dirichlet spread; the influent builder is
  flow-weighted and COD-consistent, the true fractionation conserves COD, the plant
  recipes reproduce the declared feed flows and Plant A's OLR lands in Tisocco's range;
  every entry's TKN is consistent with the ADM1 N contents under its own inert N and the
  non-sludge entries are shown inconsistent under BSM2's; nothing under `sim/influent`
  or `sim/plants` writes files or references `truth/`.

`conftest.py` provides the default configuration, the Rosen & Jeppsson (2006) initial
state and the probe-definition module as fixtures.
