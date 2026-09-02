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

---

## 2026-09-02 — ADM1 state vector: 26 liquid states + 3 headspace states, ions algebraic

**Decision.** The `sim/adm1` state vector is the canonical Rosen & Jeppsson (2006) order
of the 26 liquid states (`S_su … X_I, S_cat, S_an`) followed by `S_gas_h2, S_gas_ch4,
S_gas_co2` (29 states). The six ion states (`S_va⁻ … S_nh3`) are **not** states; they are
algebraic functions of pH. Influent flow `Q` is an input, not a state. The order is
fixed in `sim/adm1/schema.py` (`STATE_NAMES`) and the Petersen-matrix file must list
its components in the same order (validated on load).

**Reason.** The liquid order matches every reference implementation (bsm2-python,
PyADM1, QSDsan) and the candidate harness, so ring tests compare positionally without
a mapping. Keeping Q out of the state avoids the BSM2 42-vector's dummy slots.

**Alternatives.** bsm2-python's 42-vector with Q, T and dummies (rejected: not a model
state); QSDsan's component ordering (rejected: differs from the BSM2 report).

---

## 2026-09-02 — Acid–base system is algebraic; pH by bracketed root-find

**Decision.** pH is obtained at every right-hand-side evaluation by solving the charge
balance `S_cat + NH4⁺ + H⁺ − HCO3⁻ − Ac⁻/64 − Pro⁻/112 − Bu⁻/160 − Va⁻/208 − S_an − OH⁻ = 0`
with SciPy's Brent method in pH units over the bracket in `configs/adm1/solver.yaml`
(default [0, 14], `xtol` 1e-12 pH). Ion fractions follow from the same root. The residual
is monotone in pH, so the root is unique; an absent sign change raises rather than
returning a guess.

**Reason.** The BSM2 "ODE implementation" integrates the ions with acid–base kinetic
constants of 1e10 m³ kmol⁻¹ d⁻¹, which adds six stiff states and makes the reported pH
depend on the initial ion values: bsm2-python reports pH 8.49 at t = 0 from the
four-decimal R&J table before the ions relax (the ring test documents this artefact).
The algebraic form has no such states, is what the DAE variants of R&J 2006 and QSDsan
use, and is equivalent at equilibrium (tested against the BSM2 quadratic in φ). The
tight tolerance is needed so that finite-difference Jacobians stay smooth.

**Alternatives.** Ions as ODE states (bsm2-python; rejected as above); Newton iteration
on S_H⁺ with a warm start (PyADM1; rejected: needs carried state and is not bracketed).

---

## 2026-09-02 — S_h2 is an ODE state

**Decision.** Dissolved hydrogen is integrated, not solved algebraically.

**Reason.** Both oracle implementations (bsm2-python, QSDsan by default) do this and BDF
handles the stiffness (Probe 2 needs ≈ 260 steps for 20 d). The R&J "DAE2" variant
(algebraic S_h2) would need a nested Newton solve inside the pH solve.

**Alternatives.** Algebraic S_h2 (PyADM1); rejected for complexity, revisit only if a
stiffness problem appears in the extended model.

---

## 2026-09-02 — Petersen matrix is data; rates are code; expressions are walked, not eval'd

**Decision.** `configs/adm1/petersen_matrix.yaml` holds the 26 components (with unit and
COD, C, N, charge content) and the 19 biochemical processes, each stoichiometric entry
an arithmetic expression over parameter names (`"(1 - Y_su)*f_bu_su"`). The S_IC and
S_IN entries are written out explicitly rather than derived from conservation, so
`tests/test_adm1_petersen.py` is a genuine check of transcription in both directions
(all four balances close to < 1e-12 with BSM2 defaults). Expressions are evaluated by a
restricted AST walker (`sim/adm1/petersen.py`: numbers, names, `+ − * /`, unary sign);
no `eval`. Rate expressions live in `sim/adm1/rates.py` as pure functions in the same
process order (checked on compile); the `rate:` strings in the YAML are documentation.
Gas transfer is a separate block (it carries the plant volume ratio, not stoichiometry).

**Reason.** This is the structure the Milestone-1 comparison chose so that SAO, ionic
strength and precipitation become added rows and components rather than hand edits
(`docs/adm1_comparison.md` §6). Explicit S_IC/S_IN entries and a conservation test are
what catch transcription errors; deriving them would make the test tautological.

**Alternatives.** QSDsan's TSV with `?` placeholders solved by conservation (rejected:
tautological test); numeric matrix (rejected: not auditable, parameters baked in);
`eval` of expressions (rejected: code execution from a data file).

---

## 2026-09-02 — Parameter schema names the fractions BSM2 hard-codes

**Decision.** `ADM1Parameters` (stoichiometry / kinetics / physchem groups, Pydantic,
frozen, `extra="forbid"`, units in every field description) names the catabolic product
fractions that BSM2 hard-codes in its arithmetic (`f_ac_fa` 0.7, `f_h2_fa` 0.3,
`f_pro_va` 0.54, `f_ac_va` 0.31, `f_h2_va` 0.15, `f_ac_bu` 0.8, `f_h2_bu` 0.2,
`f_ac_pro` 0.57, `f_h2_pro` 0.43) using the ADM1 STR names, and validates that every
product-fraction group sums to one. Van 't Hoff enthalpies and the water-vapour
coefficient are parameters, not literals. The BSM2 `eps` (1e-6) in the valerate/butyrate
competition term is the kinetic parameter `eps_c4`. Acid–base kinetic constants have no
field because the system is algebraic.

**Reason.** CLAUDE.md rule 6 (no silent unit or constant choices); the fractions become
scenario-adjustable without touching the matrix file.

---

## 2026-09-02 — Solver defaults and influent handling

**Decision.** `configs/adm1/solver.yaml`: `solve_ivp(method="BDF")`, rtol 1e-6,
atol 1e-8 (the oracle's settings), `max_step` unlimited, negative states clipped to zero
inside rate expressions only (BSM2 convention, a flag). Radau is the cross-check (Probe 1
agrees to 3 s.f. with the oracle under both). An `Influent` series is applied either as
**sample-and-hold** (default; the integrator is restarted at every breakpoint so the
discontinuity is exact) or **linearly interpolated** (one call, internal step capped at
the sample spacing). The two treatments differ at the third significant figure on the
BSM2 dynamic influent (final S_ac 59.95 vs 59.99 g COD m⁻³), so each is ring-tested
against an oracle run that applied the series the same way.

**Reason.** Restarting at breakpoints is the only treatment that is exact for a
discontinuous input; it costs ≈ 10 BDF steps and one Jacobian per 15-minute segment
(≈ 150 s for the 280-day series in CI). Linear interpolation is 4× cheaper and is what a
smooth influent generator (§6.1) will produce anyway.

**Alternatives.** One BDF call across the discontinuities (rejected: error control, not
the model, decides how the jump is resolved); LSODA per segment (3× slower here);
per-segment `odeint` as shipped by bsm2-python (rejected: explicit outer stepping).

---

## 2026-09-02 — Ring-test oracle data and the meaning of "3 significant figures"

**Decision.** The BSM2 dynamic influent is PyADM1's `src/digester_influent.csv`
(280 d at 15 min; original SHA-256 `df97e295…bb30`), trimmed to time + 26 states + Q + T
with the numeric text unchanged and committed gzipped under
`scripts/adm1_candidates/data/` (2.4 MB; SHA-256 of the uncompressed trimmed file is
recorded in the oracle JSON and checked by the test). Oracle values are produced only in
a throwaway venv (`probe_bsm2python.py`, `probe_bsm2python_dynamic.py`) and committed as
JSON; neither bsm2-python nor QSDsan is a dependency. "Agreement to 3 s.f." is
implemented as relative difference ≤ 5e-4 (`tests/test_adm1_ring.py`, `REL_TOL_3SF`).

**Reason.** A rounding-based definition of 3 s.f. is ill-posed at digit boundaries; a
fixed relative bound is reproducible and, for leading digits above 1, stricter than the
words. Committing the influent makes the CI test self-contained (decision-log condition
of 2026-09-02).

---

## 2026-09-02 — Anchor data are manifest-driven; raw bytes are never committed unless small and redistributable

**Decision.** Every real-plant file used by the anchor layer is listed in
`anchor/MANIFEST.json` (URL, licence, SHA-256, size, download date) and fetched by
`anchor/fetch.py`, which verifies checksums before a file is placed under its final
name. `anchor/raw/` is git-ignored except for files under 1 MB whose licence permits
redistribution, which are committed next to an `ATTRIBUTION.md`. Candidates that were
examined but not fetched are recorded in the manifest's `not_fetched` list with the
reason, so the §8 search is auditable without re-doing it.

**Reason.** Reproducibility (proposal §13) requires that anyone can re-obtain the
exact bytes; a checksum manifest is the smallest thing that guarantees that. Committing
88 MB of SCADA data would bloat the repository, but committing the 125 KB daily file
means the offline test suite and the forecasting-only check work on a fresh clone.

**Alternatives.** Git LFS (rejected: adds tooling for one file); commit nothing and
fetch in CI (rejected: makes the offline tests depend on the network); a DVC remote
(rejected: no shared storage exists yet).

---

## 2026-09-02 — Proposed anchor: Muscatine WRRF for Plants B/C, published summary statistics for Plant A

**Decision (proposed; accepted with amendments by the lead the same day — see the
next entry).** Anchor the simulator to the Muscatine WRRF
datasets (Schroer & Just 2024, ODC-By 1.0) for Plant C and, with stated caveats, for
Plant B's load-swing behaviour; anchor Plant A to the published operating envelopes and
feedstock tables of Tisocco et al. (2024, 2026) because no open full-scale agricultural
co-digestion time series exists; use the ILRI farm-scale set (CC BY 4.0) only for
Tier-A sampling irregularity and Phase-3 realism. Run the §8 step-3 forecasting-only
check on the Muscatine daily file against the published MLP baseline.

**Reason.** After searching the sources named in §8 plus DataCite, Zenodo, figshare,
OSF, DBFZ DataLab and GitHub, Muscatine is the only openly licensed, full-scale,
daily-or-finer dataset longer than six months found; it also carries a one-minute SCADA
year, which is what the observation model needs. Both Tisocco plants are exactly Plant A
but their data are not deposited. Evidence: `docs/anchor_datasets.md`.

**Alternatives.** Use the unlicensed GitHub CSV of Chiguer et al. (rejected: no licence,
provenance unclear); use BSM2 influent files (rejected: simulated); wait for the
Tisocco data before fixing the influent generator (rejected: blocks Milestone 3; request
the data in parallel instead).

**Conditions.** The lead confirms or amends the Plant-B reading; the paper's §8 states
the limitation plainly.

---

## 2026-09-02 — Simulated inputs are never listed as anchors

**Decision.** `anchor/MANIFEST.json` may list a simulated dataset (for example the
BSM2 digester influent) only under `not_fetched` with `kind: simulated`; the test suite
rejects any `datasets` entry of kind `simulated`.

**Reason.** Proposal §8 exists to show the simulator is "not fantasy"; anchoring to
another simulation would be circular. The BSM2 influent is still needed for the
Milestone-2 ring test, but that is a numerics check, not an anchor.

---

## 2026-09-02 — Plant A is statistics-anchored for all of Phase 1; the factorial plants are B and C

**Decision (by the lead).** No author data request is made in Phase 1. Plant A
(agricultural co-digestion) remains anchored to the published summary statistics of
Tisocco et al. (2024, 2026) for the whole phase; Plants B and C are dataset-anchored
to the Muscatine WRRF datasets. Consequences, applied to the proposal copy in
`docs/proposal.md`:

1. The §7 factorial's two plants are **B and C**. Plant A runs a **reduced subset —
   Levels 2–5 at Tier A —** and is reported separately, outside the factorial
   statistics.
2. The benchmark card and the paper describe **A as statistics-anchored** and **B and C
   as dataset-anchored**, in those words.
3. The week-6 "request plant data / data-use agreement" item is removed from
   `docs/milestones.md`; proposal §13 no longer expects data-use agreements.

**Reason.** A data request has an uncertain outcome and timeline and would leave the
influent generator for Plant A unfixable until it resolved, which blocks Milestone 3.
Fixing Plant A's status now makes the factorial design and the paper's claims
definite. Keeping Plant A as a separately reported subset preserves the
agricultural-domain scenarios the review motivates without letting a
statistics-anchored plant carry factorial weight it cannot support.

**Alternatives.** Request the data in parallel and decide later (rejected: leaves the
design open past the week-9 gate); drop Plant A entirely (rejected: loses the
grass-silage/slurry domain where ADM1 defaults are weakest); run Plant A in the full
factorial with a caveat (rejected: a caveat does not change what the statistics
assume).
