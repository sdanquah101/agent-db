# tests/

Run with `pytest -q` from the repository root. The suite needs only the repository's own
dependencies; oracle values from other ADM1 implementations are committed as JSON.

Two tests encode non-negotiable rules from `CLAUDE.md` rather than ordinary behaviour:

- `test_truth_isolation.py` — no module under `workflows/` may import from, or reference
  a path containing, `truth/` or `truth_store/` (rule 1). It self-checks against a
  synthetic violating file so it cannot pass vacuously while `workflows/` is still mostly
  empty, asserts the *layout* that makes hidden truth unreachable, and drives the
  workflow-facing loader adversarially — with a negative control, so it cannot pass by
  refusing everything.
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
  or `sim/plants` writes files or references `truth/` or `truth_store/`.

The run harness and the scenario library (`sim/run/`, `state/`, `scenarios/`):

- `test_run_harness.py` — the declared `runs/<id>/` layout; no truth file, value or
  vocabulary in `observations/`; an opaque, deterministic run id; the burn-in measured to
  have converged on all three plants; Plant A measured to be a stable *adapted* digester
  whose acetoclastic and syntrophic pathways exclude one another rather than coexisting,
  and the feed's trace re-seeding without which a washed-out pathway could never return;
  tiers as masks on
  bit-identical truth; the Level-4 biomass multiplier and the Level-5 parameter multiplier
  read back off the state vector and the segment parameters and compared with the numbers
  in the YAML; the two-zone truth reactor; operator notes in every run and the false one in
  only the adversarial run; the Level-8 tool-failure directive absent from the
  observations; one seed per stream with the tier deliberately absent from the derivation;
  every simulator call logged, a second writer continuing the sequence, a raising call
  logged before the exception escapes; and the manifest partitioned exactly into public
  and redacted fields.
- `test_scenarios_library.py` — the 19-row ladder against the §6.3 table (rows per level
  as literals from the proposal), unique explicit seeds, every magnitude inside the range
  `sim/faults/schema.py` publishes, every fault type in the closed enum exercised
  somewhere, the answer keys consistent with the truth labels, and the §7 matrix shape:
  96 factorial cells on B and C, 18 on Plant A, the ammonia rows nowhere else, 44 distinct
  truth integrations.
- `test_g1_anchor.py` — gate G1. Recomputes `docs/g1_anchor_report.md`'s generated block
  and compares it verbatim; asserts every influent statistic is inside a tolerance
  **declared before the comparison**, that the inherited bounds really are the ones the
  other test files apply (read out of those files), and that a bound actually bites. It
  carries the lead's acceptance condition — **no clean Level-0 seed sours**, on a
  twenty-four-seed panel, with a margin assertion so a run that merely scraped over the
  threshold would not pass — and it pins what is still *wrong*: the VFA and FOS/TAC rows
  fail, their size asserted in both directions so closing the gap forces the record to be
  updated, and the overload flag measured to fire on almost no day of a healthy Plant B.
  Marked `g1`, so it is deselected by default and CI runs it nightly and on changes to
  `sim/`.

`test_truth_isolation.py` (above) also drives the workflow-facing loader
`state.run_view.open_run` on a real generated run, asking it for hidden truth by relative
path, traversal, absolute path, symlink, listing and manifest field — after first asserting
the truth *is* on disk, so the refusals cannot pass vacuously.

`conftest.py` provides the default configuration, the Rosen & Jeppsson (2006) initial
state and the probe-definition module as fixtures.

The tool registry (`tools/`, `configs/tools/`; milestone 4):

- `test_tool_registry.py` — the core against analytic models: one interface that
  validates and returns typed outputs with units; one visible projection record per call
  continuing the harness's sequence (no timestamp, no runtime) and a full truth-side
  record; the budget refused before a call by its declared bound, an overrun stopped
  inside the model and charged, the wall clock against an injectable clock, assay units;
  the Level-8 directive returning non-converged chains (truth-side `injected_failure`,
  visible `ok`), inert at probability 0 and for a tool without a payload, firing at its
  rate from a keyed stream; bit-equal output under one seed on five tools; ceilings.
- `test_tools_known_answers.py` — every tool of §6.2 against a closed form or an
  independent implementation: Morris on a linear-additive function, Sobol on Ishigami and
  against `scipy.stats.sobol_indices`, profile likelihood and Fisher information on a
  ridge and on an identifiable line, the three fitters against OLS, MCMC coverage on a
  Gaussian target, the EnKF against the Kalman filter, MHE on a driven system, `validate`
  against hand-computed metrics and the Gaussian CRPS constant, `data_qc` on planted
  faults, `mass_balance` on a balanced and an unrecorded-delivery digester,
  `residual_diag` on structured and white residuals, `voi_assay` against the Gaussian EIG.
- `test_tool_fitted_model.py` — `adm1_fitted` on Plant C: declared, reproducible,
  responsive to a multiplier, product fractions rescaled, initial state and biomass scale;
  near the truth on a generated Level-0 run; `open_registry` reading the cell, the S8-01
  directive (never in the visible tree) and the budget; the same interface on a Level-6
  cell; `request_assay` with the sensor's noise, keyed by day, priced and logged.
- `test_tool_sandbox.py` — the structural defence: a workflow launched in the sandbox
  cannot import `sim`, `scenarios`, `anchor`, `eval` or `state` by any spelling, cannot
  open `truth_store/…`, `scenarios/…` or its own run's truth file by relative path, finds
  nothing walking upwards, and — the negative control — calls tools, reads the sensors
  and gets the right exceptions through the stub; the bootstrap fails closed when a
  forbidden module resolves; the staged stub equals its source; the transport carries
  arrays bit for bit.
