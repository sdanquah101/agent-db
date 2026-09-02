# Decisions log

One entry per design decision: date, decision, reason, alternatives considered. Newest
last. Proposal section numbers refer to `docs/proposal.md`.

---

## 2026-09-02 — Disposable code lives in `scripts/`, not in `sim/`

**Decision.** Non-library code (one-off probes, evaluation harnesses, migration
helpers) goes under `scripts/`. `sim/` contains only the truth-model package.

**Reason.** `sim/` is the hidden-truth layer (CLAUDE.md rule 1) and will be imported by
the tool registry; it must contain nothing that is not part of the benchmark. The
Milestone-1 ADM1 candidate harness is exactly the kind of thing that should not be
importable from there.

**Alternatives.** `sim/candidates/` (rejected: pollutes the truth-model package);
`benchmarks/` top-level (rejected: name collides with the benchmark itself).

---

## 2026-09-02 — Scenario schema lives in `scenarios/schema.py`

**Decision.** The Pydantic contract for scenario YAML (proposal Appendix B) is
`scenarios/schema.py`, exported from the `scenarios` package, next to the YAML files it
validates. The task-state schema (§6.6) will live in `state/` as CLAUDE.md says; the two
are different documents with different readers.

**Reason.** A scenario and its answer key version together; keeping the schema beside
the data makes the contract obvious and keeps `state/` about run-time state only.

**Alternatives.** `state/scenario.py` (rejected: conflates a static definition with
run-time state); `sim/scenario.py` (rejected: the evaluator reads scenarios too and must
not import `sim`).

---

## 2026-09-02 — Fault types are a closed enum

**Decision.** `FaultType` enumerates exactly the injections in the §6.3 ladder. Adding a
scenario class requires a code change and an entry in this log.

**Reason.** A free-text fault type would let a YAML file silently introduce an
injection the simulator does not implement, and would make the truth label set
un-auditable. The ladder is the benchmark's scientific content; it should not drift.

**Alternatives.** Free string with simulator-side validation (rejected: pushes the
contract into the simulator, invisible to the evaluator).

---

## 2026-09-02 — Structural scenarios cannot declare a kinetic update as correct

**Decision.** The schema rejects a scenario whose only truth label is `structural` but
whose `correct_conclusion.kinetic_update_allowed` is true.

**Reason.** Level-6 scenarios are never scored on parameter recovery (CLAUDE.md, domain
reminders; proposal §6.7 A). If a kinetic update were the correct action, the false
kinetic-drift metric (Appendix A) would be undefined for that scenario. Compound
structural + parameter scenarios (Level 7) are exempt.

---

## 2026-09-02 — Lint and test configuration

**Decision.** Ruff with `E, W, F, I, UP, B, SIM, D, ANN, RUF`, Google docstring
convention, line length 100, `py311` target; `D` and `ANN` relaxed for `tests/` and
`scripts/`. Pytest with `--strict-markers --strict-config`; deprecation warnings raised
from first-party packages fail the suite.

**Reason.** CLAUDE.md asks for type hints everywhere and docstrings on public
functions; making ruff enforce it is cheaper than reviewing for it. Tests and scripts
are held to a lower documentation bar so they stay cheap to write.

---

## 2026-09-02 — Licensing

**Decision.** Apache-2.0 for code (`LICENSE`); scenarios, results and figures under
CC-BY-4.0 (`NOTICE`, `README.md`).

**Reason.** Proposal §12 allows MIT or Apache-2.0; Apache-2.0 adds an explicit patent
grant, which matters for a benchmark others will build on. CC-BY-4.0 for data follows
the proposal.

---

## 2026-09-02 — Candidate ADM1 probes: feed, initial state and gate

**Decision.** All candidates are probed with the same constant sewage-sludge feed (the
ADM1 STR benchmark feed also used by EXPOsan's `adm` example: S_su 0.01 … X_pr 20,
X_I 25, S_cat 0.04, S_an 0.02 kg or kmol m^-3; Q = 170 m^3 d^-1; 35 °C; V_liq 3400 m^3,
V_gas 300 m^3), initialised at the Rosen & Jeppsson (2006) BSM2 steady state, for 100 d
(Probe 1) and 20 d with all feed concentrations ×3 from day 10 (Probe 2). The
plausibility gate is deliberately wide (pH 6.5–7.8, CH₄ 55–72 % dry, biogas
2200–3300 m^3 d^-1 in the BSM2 convention, total VFA 1–1000 g COD m^-3) and the
literature sources are cited in `docs/adm1_comparison.md`.

**Reason.** The published R&J steady state was produced with a different strong-ion
loading (its effluent has S_cat ≈ 0), so Probe 1 is a 100-day transient rather than a
digit-for-digit ring test; candidates are compared with *each other* and against
physically plausible ranges. A narrow gate would encode one implementation's
conventions as truth.

**Alternatives.** Use each candidate's shipped example (rejected: not comparable); use
the BSM2 dynamic influent file (rejected: not all candidates ingest time series, and a
constant feed isolates numerics from input handling).

---

## 2026-09-02 — Base ADM1 implementation for the truth model

**Decision (accepted by the lead, 2026-09-02).** Build our own Petersen-matrix ADM1 in
`sim/`, ring-tested continuously against **bsm2-python as the primary oracle** and
against the other probed implementations (ADM1F standard variant, PyADM1, QSDsan) as
secondary checks. Evidence in `docs/adm1_comparison.md`.

**Conditions.**

1. **Time-boxed to Milestone 2 (weeks 3–6).** The acceptance test is agreement with
   bsm2-python to 3 significant figures on Probe 1, Probe 2 *and* the BSM2 dynamic
   influent case (the 15-minute `digester_influent.csv` time series that PyADM1 ships,
   Q ≈ 178 m³ d⁻¹ varying). If that is not met by the end of week 6, we **fall back to
   a fork of bsm2-python** and add SAO, ionic-strength correction and the precipitation
   sink there.
2. **QSDsan / ADM1p is an equation reference only.** Its Petersen matrix
   (`process_data/_adm1.tsv`) and `_adm1_p_extension.py` are read for stoichiometry,
   speciation and precipitation formulations; QSDsan is **never a dependency** of this
   repository.
3. **Weinrich ADM1-R3 and R4 are ported from the published equations** (Weinrich &
   Nelles 2021, and the model-structure/parameter PDFs in the MIT-licensed repository)
   as the *fitted* models, and validated against the figures in Weinrich & Nelles 2021.

**Reason.** Four independent implementations agree to 3 s.f., so correctness of a
re-implementation can be established by ring tests; the three required extensions are
rows in a matrix model but hand edits in every hand-expanded port; QSDsan's model layer
is right but its simulation layer (global flowsheet state, ≈ 1 GB dependencies) is
incompatible with the pure-function registry (CLAUDE.md rule 2) and the deployability
constraint (proposal §2); ADM1F's toolchain is disproportionate and its default build is
a modified model.

**Alternatives.** Adopt bsm2-python directly (kept as the fallback); adopt QSDsan
(rejected: dependency footprint and framework state); adopt ADM1F (rejected: toolchain,
build, default variant); port Weinrich R3/R4 as the *truth* model (rejected: too
simplified to carry SAO/ionic strength/precipitation).

**Not re-run now.** Probe 1 is not re-run with the BSM2 dynamic influent at this
milestone; that case is added to the Milestone-2 ring test instead.
