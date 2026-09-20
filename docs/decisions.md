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

---

## 2026-09-02 — Duplicate ADM1 core: PR #2 is canonical; PR #4 reduced to the extensions

**What happened.** The third session of the day started the truth-model extensions
from `main` without checking the open PR list. PR #2 (the `sim/adm1/` Petersen-matrix
core, 79 tests, dynamic-influent ring test passing at 1.5e-4) was open but unmerged, so
the session re-implemented a second ADM1 core with a different layout, ring-tested only
against the constant-feed oracle (73 tests, no dynamic case), and opened PR #4 on top
of it.

**Decision (by the lead).** PR #2 is canonical. Sequence: merge #2 first (after merging
`main` into it and fixing the one CI failure, `tests/` not importable as a package under
plain `pytest`); rebase the extension work onto the merged core, keeping only SAO, the
Davies ionic-strength correction, the precipitation rows and speciation switches, and
their tests; discard the duplicate core; re-run the full ring test including the dynamic
case on the combined code. PR #4 is repointed at that branch.

**Reason.** Two cores would mean two oracles, two parameter schemas and a permanent
reconciliation debt; #2 had the stronger evidence (all three acceptance cases) and had
already been through the decisions log.

**Refactors kept from the duplicate.** Two behaviour-preserving changes to
`sim/adm1/model.py` were worth carrying over because the extensions need them:
`integrate()` (the sample-and-hold / linear influent loop, now callable with any
right-hand side of the same signature) and `gas_exchange()` (the transfer terms and
headspace derivatives as a function). Probe 1/2 and the dynamic ring test pass unchanged
after the refactor.

**Rule added to CLAUDE.md.** A follow-on session confirms its predecessor's PR is merged
before starting, or branches from the predecessor's branch.

**Alternatives.** Keep the duplicate core and merge #2 later (rejected: two cores, two
oracles, a reconciliation debt that only grows); merge the duplicate and port #2's
dynamic ring test onto it (rejected: #2 had already been reviewed against the decisions
log and had the stronger evidence); keep both cores and pick by ring-test score
(rejected: the scores were not comparable, since only #2 ran the dynamic case).

---

## 2026-09-02 — Formulation of the three truth-model extensions

**Decision.** The §6.1 extensions are additive rows and components over the standard
Petersen matrix, declared in `configs/adm1/extensions.yaml` in the same expression
format as the base matrix, compiled by `sim/adm1/extensions.py` into an
`ExtendedModel` whose first 29 states are the base states (so every base ring test
applies to the extended model with all extensions inert). Each extension is independently
switchable.

1. **Syntrophic acetate oxidation (`sao`).** One biomass component `X_sao` and two
   processes: acetate uptake by SAO (`S_ac → 4 H₂ + CO₂`, yield `Y_sao`, Monod on S_ac
   with the acidogen pH function, the IN limitation, **its own free-ammonia inhibition**
   `K_I_nh3_sao` and H₂ product inhibition as for the C4/propionate degraders) and
   first-order decay to composites. Defaults `Y_sao` 0.04, `k_m_sao` 2.0 d⁻¹
   (μ_max = 0.08 d⁻¹, the fast end of the published 9–28 d doubling times);
   `K_S_sao` 0.4 kg COD m⁻³, `K_I_h2_sao` 3.5e-6 kg COD m⁻³, `K_I_nh3_sao` 0.05 kmol N m⁻³.
2. **Ionic-strength correction (`ionic_strength`).** Davies activity coefficients
   (A 0.5085 at 25 °C, b 0.3, I capped at 0.5 M) applied to the charge balance and to
   every acid–base equilibrium; pH is reported as −log₁₀(a_H⁺); the pH inhibition
   functions and free-ammonia inhibition see activities. I is solved by fixed-point
   iteration together with the charge balance. No new states.
3. **Carbonate second dissociation (`carbonate`).** HCO₃⁻ ⇌ CO₃²⁻ + H⁺ (pK_a2 10.33 at
   25 °C, a shared parameter, not temperature-corrected) in the charge balance and in
   the exact three-way CO₂/HCO₃⁻/CO₃²⁻ split of S_IC. No new states; its own switch.
4. **Calcite precipitation (`precipitation`).** Components `S_ca` (kmol m⁻³, charge +2)
   and `X_caco3` (kmol m⁻³, inert solid); rate `k_prec · (√SI − 1)^n` for SI > 1 with
   `K_sp` 10^−8.48, `n` 2, no reverse dissolution. SI uses the speciated carbonate when
   `carbonate` is enabled, otherwise the diagnostic estimate K_a2·[HCO₃⁻]/[H⁺], which
   is reported but takes no part in the balance.

**The calcite row's charge residual of −2.** The row {S_ca −1, S_IC −1, X_caco3 +1}
does not close on charge because S_IC is an *uncharged total* in the matrix (charge
content 0; its split into CO₂/HCO₃⁻/CO₃²⁻ is algebraic) while the species that actually
leaves is CO₃²⁻. The −2 is a **matrix convention**, not a tested property: that the
solution stays electroneutral is enforced by the pH solver whatever the row says, so a
"charge balance closes" test would be vacuous (one was written and removed after
review). What is tested instead: the matrix test asserts −2 for this row; a calcium
balance (S_ca + X_caco3 follows dilution only) checks the S_ca and X_caco3 entries; an
alkalinity check (the weak-acid alkalinity computed from the reported speciation drops
by 2 eq per mol CaCO₃ once the ammonium re-speciation caused by the pH drop is
accounted for) checks the speciation output against the states; the S_IC entry is
covered by the static carbon balance.

**Evidence.** Inert-identity tests: SAO, ionic strength and calcite each enabled but
inert reproduce the base Probe 1 to solver tolerance (1e-4 where extra states change
the BDF step sequence, 1e-6 where the dimension is unchanged), and all three together
reproduce the bsm2-python Probe-1 oracle to ≤ 5e-4 through the extended right-hand
side; the carbonate switch is a genuine change (pH shifts by thousandths at digester
pH) and is pinned as such. Qualitative tests: SAO takeover at a 60-d HRT under
≈ 250 mg/L free ammonia and washout at 20 d, SAO retaining > 50 % of its rate where
acetoclasts are at 50 %, Davies limits and the A(T) values, pH and NH₃ shifts under
ionic strength, calcite as a sink for HCO₃⁻ and Ca²⁺ that lowers pH, all four together,
determinism. No published oracle exists for the combined model; the formulations
follow QSDsan's ADM1p extension (read as an equation reference only) and the literature
cited in `docs/adm1_comparison.md` §6.

**Still open for domain review.** The SAO defaults (`k_m_sao`, `K_I_nh3_sao`); the
default `k_prec`; whether pK_a2 should be van 't Hoff corrected like the base
constants.

**Alternatives.** Hand-editing the base matrix per extension (rejected: this is what the
Petersen-as-data decision was made to avoid); ions as ODE states for the activity
correction (rejected: same reasons as the algebraic-pH decision); a full mineral
equilibrium module (rejected for Phase 1: calcite is the only sink §6.1 asks for).

---

## 2026-09-02 — Domain answers on the extensions (by the lead) and their consequences

**Decisions.**

1. **SAO has its own, weaker free-ammonia inhibition** (`K_I_nh3_sao`), not the
   acetoclastic function and not none. *Correction of the record:* the first draft of
   the entry above described SAO as sharing the acetoclastic NH₃ function; the code as
   first written had **no** NH₃ term on SAO. Both are superseded.
2. **The calcite rate law stays SI-based** (`k (√SI − 1)^n`).
3. **The carbonate second dissociation is its own switch, default off**, so the calcite
   extension can be enabled without changing the base speciation. Consequence: the
   calcite-inert identity tightens from 1e-2 to the same 1e-4 as the other extensions,
   and the calcite rate needs a carbonate concentration when the switch is off, hence
   the diagnostic estimate above.
4. **Davies A is scaled to the operating temperature.** The configured 0.5085 is the
   25 °C value; the model multiplies it by A(T)/A(25 °C) from the Debye–Hückel formula
   A = 1.82483e6·√ρ/(εT)^{3/2} with the Malmberg & Maryott (1956) permittivity and a
   Kell-type density polynomial (×1.017 at 35 °C, ×1.056 at 55 °C). Using the 25 °C
   constant unscaled would understate log₁₀ γ by 5.6 % in a thermophilic digester.

**Consequence of (1) for the SAO default.** With μ_max 0.08 d⁻¹ and decay 0.02 d⁻¹,
SAO must keep ≳ 70 % of its rate at 250 mg/L free ammonia to out-grow a 60-day HRT at
all; a constant a few times the acetoclastic 25 mg/L (e.g. 100 mg/L) makes SAO unable to
establish in any ammonia-stressed digester in this model, contradicting the observations
that motivate the extension (SAO dominant at TAN 3–5 g/L, HRT 40–60 d). `K_I_nh3_sao`
is therefore 0.05 kmol N m⁻³ (50 % at ≈ 700 mg NH₃-N/L, ≈ 28× acetoclastic), flagged as
order-of-magnitude for review together with `k_m_sao`. The takeover test runs at a
60-day HRT for 300 days with 2.8 g N/L feed; the 40-day, 150-day case of the first
draft is no longer reachable and was not kept with a loosened assertion.

**Alternatives.** Raise `k_m_sao` instead of weakening the inhibition (rejected: μ_max is
already at the fast end of the published range); make pK_a2 part of the base parameter
schema (rejected: the base model does not use it; a shared extension parameter keeps the
base schema frozen).

---

## 2026-09-02 — `K_I_nh3_sao` anchored to a cited literature range (stays at 0.05)

**Decision.** `K_I_nh3_sao` = 0.05 kmol N m⁻³ (50 % inhibition at ≈ 0.7 g NH₃-N L⁻¹)
is kept. The literature brackets the constant between about 0.02 and 0.1 kmol N m⁻³
(0.3–1.5 g NH₃-N L⁻¹); 0.05 lies inside, so neither the constant nor the takeover test
moves. Lead's rule: if a later, better-documented range contradicts 0.05, the constant
changes and the test moves, not the reverse.

**Evidence (abstract-level; the modelling papers' tables could not be read from this
environment, see below).**

- Pathway shift: free ammonia of ≈ 200 mg N L⁻¹ is the threshold at which acetate
  methanisation moves from acetoclastic methanogenesis to SAO plus hydrogenotrophic
  methanogenesis (Hao et al. 2017, *Water Sci. Technol.* 75, doi:10.2166/wst.2017.032);
  SAO–HM competes with acetoclasts at 200–500 mg N L⁻¹ and out-competes them above
  500 mg N L⁻¹ (Hao et al. 2021, *Water Res.* 204, doi:10.1016/j.watres.2021.117586).
  For SAO to be the winner at 500 mg L⁻¹ while acetoclasts are below 10 % of their rate
  (BSM2 `K_I_nh3` 25 mg L⁻¹), SAO must retain well over half of its rate there:
  `K_I_nh3_sao` ≳ 0.035 kmol N m⁻³.
- Tolerance ceiling: SAO-dominated reactors ran at total ammonia up to 11 g N L⁻¹
  before deteriorating (Westerholm et al. 2012, *Appl. Environ. Microbiol.* 78,
  doi:10.1128/AEM.01637-12); SAO pure strains and their methanogen partners were
  assayed at 3–7 g NH₄⁺-N L⁻¹ (Wang et al. 2015, *FEMS Microbiol. Ecol.* 91,
  doi:10.1093/femsec/fiv130); acetate-fed ammonia-tolerant consortia thrived to
  4.25 g NH₄⁺-N L⁻¹ (Yan et al. 2020, *Environ. Sci. Technol.* 54,
  doi:10.1021/acs.est.0c01945); SAO bacteria were washed out at free ammonia above
  1.5 g L⁻¹ in dry digestion (Rocamora et al. 2023, *Waste Manage.* 161,
  doi:10.1016/j.wasman.2023.02.009). A 50 % constant above ≈ 0.1 kmol N m⁻³ (1.4 g L⁻¹)
  would make SAO effectively immune where it is observed to fail.
- Relative sensitivity: the half-maximal inhibitory total ammonia for hydrogenotrophic
  methanogenesis was 18.8 g L⁻¹ against 1.74 g L⁻¹ for acetoclastic methanogenesis, an
  eleven-fold ratio (Liu et al. 2023, *Bioresour. Technol.* 390,
  doi:10.1016/j.biortech.2023.129919). Applied to BSM2's acetoclastic 25 mg NH₃-N L⁻¹
  that ratio gives ≈ 0.02 kmol N m⁻³ for the SAO–HM pair, the low end of the range;
  applied to the 0.02 kmol N m⁻³ fitted for a high-solids acetoclastic community
  (Bai et al. 2017, *J. Environ. Sci.* 52, doi:10.1016/j.jes.2016.03.004) it gives 0.2,
  above the washout ceiling, which is why the ceiling and not the ratio sets the top of
  the range.
- Growth: syntrophic acetate-oxidising co-cultures show generation times of 3–20 d,
  with ammonium up to 0.2 M *raising* the methane rate (Westerholm et al. 2019,
  *Environ. Sci. Technol.* 53, doi:10.1021/acs.est.9b00288). The configured μ_max of
  0.08 d⁻¹ (doubling 8.7 d) is inside that range; the 2016 review (Westerholm et al.,
  *Appl. Energy* 179, doi:10.1016/j.apenergy.2016.06.061) is the source of the 9–28 d
  figure quoted in the configuration.

**Not read.** The ADM1–SAO modelling papers whose parameter tables would settle this
directly — Wett et al. 2014 (*Water Sci. Technol.* 69, doi:10.2166/wst.2014.047),
Rivera-Salvador et al. 2014 (*Bioresour. Technol.* 167, doi:10.1016/j.biortech.2014.06.008),
Capson-Tojo et al. 2021 (*Bioresour. Technol.* 341, doi:10.1016/j.biortech.2021.125802)
and Yeghiazaryan et al. 2026 (*Bioresour. Technol.*, doi:10.1016/j.biortech.2026.134365)
— sit behind hosts this environment cannot reach (IWA, Elsevier, HAL, PMC all blocked
on 2026-09-02). Their values must be checked when access exists; a value outside
0.02–0.1 kmol N m⁻³ changes the constant.

**Alternatives.** Set the constant from the IC50 ratio alone (0.02; rejected: makes SAO
lose at 500 mg L⁻¹, contradicting Hao 2021); make SAO immune to ammonia (rejected by the
lead on 2026-09-02).

---

## 2026-09-02 — The SAO Level-6 scenario runs on Plant A, not Plant B

**Decision.** The "Omitted SAO pathway" structural scenario (proposal §6.3, Level 6) and
its Level-7 compound run on **Plant A** (agricultural co-digestion, statistics-anchored).
Plant B (Muscatine WRRF, municipal sludge with high-strength waste) does not get an SAO
scenario.

**Reason, from the Muscatine daily file (`anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`,
1,103 rows).**

| Quantity | Value |
|---|---|
| Reported SRT | mean 24.7 d, median 22.2 d, p10–p90 16–35 d |
| HRT from feed volumes (2 × 485,000 gal ÷ daily TWAS + PS + HSW + FOG) | median 19.5 d, p10–p90 12.6–37.6 d |
| Digester pH | mean 7.25, p10–p90 7.04–7.43 |
| Alkalinity | mean 5.0 g CaCO₃ L⁻¹ |
| Ammonia | **not measured** (no column in the daily or SCADA files) |

A municipal sludge digester at pH 7.25 and 5 g CaCO₃ L⁻¹ alkalinity carries total
ammonia of the order 1–1.5 g N L⁻¹, hence free ammonia of ≈ 15–40 mg N L⁻¹ at 35 °C
(pK_a 8.95): an order of magnitude below the 200 mg L⁻¹ pathway-shift threshold (Hao
et al. 2017, 2021 above). Without that pressure acetoclasts win on affinity (the SAO
acetate threshold is 0.4–0.45 mM, Westerholm et al. 2019), so SAO cannot be the
dominant acetate sink at Plant B whatever its growth rate. Growth alone would already
be marginal: at the median 19.5–22 d retention the dilution-plus-decay rate is
0.065–0.07 d⁻¹, which only the fastest published generation times (3–10 d, μ_max
0.07–0.23 d⁻¹) exceed, and the configured 0.08 d⁻¹ does not once any inhibition applies.

Plant A (cattle slurry + grass silage, 41 °C, 28-d HRT per reactor, AFBI Hillsborough;
Tisocco et al. 2024) is the ammonia-relevant plant: slurry/silage co-digestion runs at
free ammonia of 150–250 mg L⁻¹ even at modest loading (Xie et al. 2017, pig manure +
grass silage, *Int. Biodeterior. Biodegrad.* 123, doi:10.1016/j.ibiod.2017.07.005),
inside the shift window. Plant A's own TAN and pH envelope are entered from the
Tisocco tables when `configs/plant_a_statistics.yaml` is written.

**Condition for the plant-configuration PR.** At Plant A's frozen HRT and ammonia
envelope the truth model must actually establish SAO (a test: X_sao grows and takes
over from a small seed within the scenario horizon). With μ_max 0.08 d⁻¹, decay
0.02 d⁻¹ and `K_I_nh3_sao` 0.05, a 28-d HRT leaves a margin of only ≈ 0.01 d⁻¹ at
250 mg L⁻¹ free ammonia (dilution + decay 0.056 d⁻¹ against 0.08 × 0.73 × Monod), so
the scenario may need Plant A's upper HRT range, a longer horizon, or `k_m_sao` at the
literature's fast end. That is design content and goes to the lead with that PR.

**Alternatives.** Put SAO on Plant B with an ammonia-spiking feed event (rejected: not
what the anchor data show; would make B's "dataset-anchored" claim false for that
scenario); put it on Plant C (rejected: same ammonia argument as B).

---

## 2026-09-02 — SAO pH window, calcite simplifications and SI flag, K_sp(T), strong ions

**Decisions (lead, 2026-09-02).**

1. **SAO uses the hydrogenotrophic pH limits** (`pH_UL_h2` / `pH_LL_h2`), not the
   acidogen ones: SAO only proceeds coupled to hydrogenotrophic methanogenesis, so the
   pair is limited by the methanogen's window. Tested.
2. **Calcite stays without a surface term and without dissolution**, and this is
   documented rather than modelled: the rate is zero for SI < 1, and the model now
   reports `calcite_SI` and a flag `calcite_undersaturated` (1 when SI < 1 while
   X_caco3 > 0, i.e. wherever dissolution would occur) so that runs entering that
   regime are visible in the derived outputs. X_caco3 leaves with the liquid (no solids
   retention). Tested.
3. **K_sp of calcite is temperature-dependent** through Plummer & Busenberg (1982,
   *Geochim. Cosmochim. Acta* 46, 1011–1040):
   log₁₀ K_sp = −171.9065 − 0.077993 T + 2839.319/T + 71.595 log₁₀ T, evaluated at
   T_op (pK 8.480 at 25 °C, 8.543 at 35 °C, 8.709 at 55 °C). It is a cited physical
   relation in code, like the Davies A(T), and no longer a config parameter. pK_a2 is
   still the 25 °C value (10.33); Plummer & Busenberg give K₂(T) as well, and applying
   it is a one-line follow-up if the reviewer wants SI fully consistent.
4. **Strong-ion convention.** `S_cat` and `S_an` are ADM1's lumped monovalent strong
   cations and anions (kmol charge m⁻³) and enter the ionic strength with |z| = 1, as
   Na⁺/K⁺ and Cl⁻. Divalent strong ions (Mg²⁺, SO₄²⁻) are not represented; Ca²⁺ from
   the calcite extension is the only divalent ion in I. A feed rich in divalent ions
   understates I by up to a factor of two per divalent equivalent. Documented in the
   configuration.

**Alternatives.** Model dissolution as the reverse of the SI law (rejected for Phase 1:
adds a rate constant no scenario needs; the flag makes the omission visible); keep
K_sp as a 25 °C config constant (rejected: a 70 % error in K_sp at 55 °C for Plant A's
thermophilic sibling would be a silent unit-like choice).

---

## 2026-09-02 — Plant configurations A/B/C — proposed (superseded the same day by the lead's answers, next entry)

**Proposal.** A plant is a *declared* configuration (`configs/plants/plant_<id>.yaml`,
schema `sim/plants/schema.py`) that a workflow may read — geometry, set points, feed
catalogue, anchoring — plus *distributions* for what the operator does not know; the
realisation of those (the hidden active-volume error) is sampled per run from an
explicit seed (`sim.plants.sample_hidden_geometry`) and is hidden truth. Every
dataset-anchored number carries its source and is re-derived from the committed
Muscatine daily file by `tests/test_plants.py`, so the configs cannot drift from the
data they claim to summarise.

| | Plant A | Plant B | Plant C |
|---|---|---|---|
| Domain | slurry + grass silage, 41 °C | sludge + HSW + FOG co-digestion, 35.3 °C, load swings | sludge streams only, 35.3 °C, steady |
| Anchoring | statistics (Tisocco 2024/2026) | dataset (Muscatine) | dataset (Muscatine) |
| Modelled unit | AFBI heated primary, 650 m³ | one of two 1,836 m³ digesters, half the plant feed | the same digester, sludge feeds only |
| Feed (median, p10–p90) | 16.5 (13–20) m³ d⁻¹ from the paper's ranges | 94 (49–145) m³ d⁻¹ | 48 (31–69) m³ d⁻¹ |
| HRT | 28 d as published (see question 2) | 19.5 (12.6–37.6) d; plant SRT 22 (16–35) d | 38 (27–60) d |
| Hidden active volume | ±5–15 %, sign random | same | same |
| Mixing | ideal CSTR | ideal CSTR | ideal CSTR |
| Truth extensions | all four | all four | all four |
| Scenarios | Levels 2–5 at Tier A **plus the SAO structural scenarios**, reported separately | full factorial; precipitation and ionic-strength structural scenarios | full factorial; same |

**Decided by earlier entries and applied here.** Plants B and C dataset-anchored,
Plant A statistics-anchored and outside the factorial (2026-09-02); the SAO Level-6
scenario on Plant A (2026-09-02).

**Open design questions, in the order they block work.**

1. **SAO establishment at Plant A.** At the published 28-d HRT and 41 °C the truth
   model with the current SAO kinetics (μ_max 0.08 d⁻¹, decay 0.02 d⁻¹,
   `K_I_nh3_sao` 0.05) does not establish SAO: over 400 d a 0.05 kg COD m⁻³ seed
   grows to 0.06–0.11 and removes under 5 % of the acetate at feed TAN of 1.4–2.8
   g N L⁻¹ (`scripts/plant_a_sao_probe.py`, ADM1 STR feed). At 35 d it grows 4–6×; at
   45 d it removes 40–80 % of the acetate. Options: (a) `k_m_sao` at the literature's
   fast end (generation 3–5 d, μ_max 0.14–0.23 d⁻¹, Westerholm et al. 2019), (b) run
   the SAO scenario at the long end of Plant A's HRT envelope, (c) accept a slow,
   partial takeover as the scenario's signature. Recommendation: (a) with (b) as the
   check, because the 2019 growth data are the better-documented number and the SAO
   scenario must produce a persistent structured residual within a 180-d scenario.
2. **Plant A hydraulics.** The paper's numbers disagree: 650 m³ at 13–20 m³ d⁻¹ gives
   32–50 d, not the stated 28 d. The config carries both with a wide consistency
   tolerance; the simulator must honour one.
3. **Plant B's character.** Proposal §6.1 calls B a "food-waste digester, high
   nitrogen". The data B is anchored to are municipal sludge with industrial organic
   waste and FOG at low ammonia. The config describes what the data show and drops the
   high-nitrogen claim; the proposal text needs the lead's edit, and the high-ammonia
   domain lives on Plant A.
4. **Plant C's definition.** Proposed as the same digester with only its sludge streams
   (HRT 38 d), which keeps every number traceable but is longer-loaded than typical
   municipal practice (15–25 d). Alternative: an independent sewage-sludge plant with
   assumed geometry, which would not be dataset-anchored.
5. **Headspace volumes** are assumed at 10 % of the liquid volume for all three plants
   (not reported by any source).
6. **Mixing.** Ideal CSTR everywhere, the dead volume carried by the hidden
   active-volume error; a tanks-in-series RTD is in the schema but unused until a
   scenario needs imperfect mixing.
7. **Plant A's TAN/pH/VFA envelope** is not yet transcribed from the Tisocco tables
   (`configs/plant_a_statistics.yaml` carries nulls with `todo` markers, none filled
   from memory).

**What is deliberately not here.** Feed COD fractionation, assay statistics, seasonal
drift and delivery irregularity (influent generator, §6.1); sensor models (observation
model); the run layer that writes the sampled hidden geometry to `runs/<id>/truth/`.

**Alternatives.** One shared plant schema with per-plant overrides (rejected: each
plant's provenance is different and should be readable on its own); put the hidden
error realisation in the config (rejected: CLAUDE.md rule 1).

---

## 2026-09-02 — Plant configurations A/B/C — **frozen** (the lead's answers to the seven questions)

1. **SAO kinetics and Plant A's HRT.** `k_m_sao` is raised from 2.0 to **4.0 kg COD
   kg COD⁻¹ d⁻¹** (μ_max = Y·k_m = 0.16 d⁻¹, doubling 4.3 d), the fast end of the 3–20 d
   generation times measured for syntrophic acetate-oxidising co-cultures (Westerholm
   et al. 2019, *Environ. Sci. Technol.* 53, doi:10.1021/acs.est.9b00288). Plant A's
   HRT is set at **35–45 d (median 40)**, inside the 32–50 d that the published volumes
   imply (Tisocco et al. 2024, doi:10.1007/s11783-024-1810-9: 650 m³ at 13–20 m³ d⁻¹).
   Verified (`tests/test_plants.py::test_sao_establishes_at_plant_a`, with the feed
   inorganic nitrogen at the transcribed digestate-TAN midpoint of 3.3 kg N m⁻³, see
   the next entry): at Plant A's declared geometry and 40-d HRT the reactor sits at
   pH 7.48 and 235 mg L⁻¹ free ammonia, a 0.05 kg COD m⁻³ SAO seed grows 9.3× to
   0.465 kg COD m⁻³ within 180 d and takes the acetate the inhibited acetoclasts leave
   from 18.8 to 0.96 kg COD m⁻³ (the first draft measured 15.5 → 0.6 at a provisional
   2.8 g N L⁻¹); at the BSM2 20-d HRT SAO still washes out (X_sao 0.05 → 0.0077 in
   60 d, `tests/test_adm1_extensions.py`). The 60-d takeover test of the earlier draft
   is kept as is.
2. **Plant A hydraulics.** The Tisocco volumes are kept (650 m³); the feed rate is
   derived from the chosen HRT (16.25 m³ d⁻¹, 14.4–18.6), which is consistent with the
   published 11–18 m³ d⁻¹ slurry plus 2 t d⁻¹ silage; the published inconsistency (stated
   28 d vs 32–50 d from the volumes) is recorded in `configs/plant_a_statistics.yaml`.
3. **Plant B** is Muscatine-anchored co-digestion with load swings and makes no
   high-nitrogen claim. The ammonia scenarios — Level-5 "true ammonia-inhibition
   shift", Level-6 "omitted SAO pathway" and their Level-7 compound — run only on
   Plant A. Proposal copy updated to v0.3 (§6.1, §6.3, §7: the factorial is 16 scenarios
   × 3 tiers × 2 plants).
4. **Plant C** is the sludge-only version of Plant B: B and C share geometry, temperature
   and hidden-error distribution and form a **controlled pair** that differs only in the
   co-substrate streams (tested).
5. **Headspace volumes** use the BSM2 ratio V_gas/V_liq = 300/3400 = 0.0882 (A 57.4 m³,
   B/C 162 m³), marked as assumed in every config (tested).
6. **Mixing** is an ideal CSTR in the plant contract (the schema allows nothing else).
   Imperfect mixing is a fault-injection *truth variant* of the Level-6 "Imperfect
   mixing" scenario: recorded now, implemented with the fault-injection API.
7. **Plant A's ammonia envelope** was transcribed by the lead the same day (next
   entry); the SAO test reads it from `configs/plant_a_statistics.yaml`.

---

## 2026-09-02 — Plant A ammonia envelope transcribed (by the lead); hydraulics AFBI-anchored only

**Recorded.** From Tisocco et al. 2024 (doi:10.1007/s11783-024-1810-9), Section 3.2 and
Table 1, into `configs/plant_a_statistics.yaml`: digestate total ammonia 2.3–4.3 kg N m⁻³
(weekly samples), feed TAN and TS of the slurry and silage for data sets A and B, and the
acetoclastic free-ammonia inhibition constant of 1.0 kg m⁻³ the paper fitted for its
adapted community. Digestate pH is plotted only (Fig. 2) and is **not** transcribed, so
free ammonia stays null until it is; both are marked with the reason.

**Decisions.**

1. **Plant A hydraulics are AFBI-anchored only.** AU Foulum (Tisocco et al. 2026,
   doi:10.1016/j.ese.2026.100662) is thermophilic (53 °C, 1,200 m³, primary HRT 13–15 d)
   and its accessible text carries no TAN or pH values; it is cited only as the
   thermophilic envelope, never for Plant A's volumes, HRT or ammonia.
2. **The SAO-takeover test reads the envelope.** `tests/test_plants.py` sets the feed
   inorganic nitrogen to the midpoint of the transcribed range (3.3 kg N m⁻³ =
   0.2356 kmol N m⁻³, `sim.plants.plant_a_digestate_tan`) instead of the earlier
   provisional 2.8 g N L⁻¹. Using digestate TAN as the feed value is a proxy that errs
   towards stronger ammonia stress (protein degradation adds nitrogen in the reactor).
3. **The SAO constant is conservative.** Tisocco et al. 2024 fitted 1.0 kg N m⁻³
   (0.071 kmol N m⁻³) as the free-ammonia inhibition constant of the *acetoclastic*
   community at AFBI after adaptation. Our SAO–hydrogenotrophic constant `K_I_nh3_sao`
   is 0.05 kmol N m⁻³, i.e. the model inhibits the ammonia-tolerant pathway *more* than
   that paper's adapted acetoclasts. This supports the literature range of the entry
   "`K_I_nh3_sao` anchored" and places 0.05 on its conservative side; the BSM2
   acetoclastic constant of 0.0018 kmol N m⁻³ that the base model keeps is the
   *unadapted* value, which is what makes the acetoclastic pathway collapse under
   Plant A's ammonia in the truth model and gives the SAO scenario its signature.

**Addendum (salvage session, later the same day).** The lead re-sent the envelope with
PR #8's review. It is identical, field for field, to the block already in
`configs/plant_a_statistics.yaml` (checked by parsing both through `AmmoniaEnvelope`),
so the file is unchanged, pH and free ammonia stay null with their stated reasons, and
decisions 1 and 3 above are re-affirmed as the lead's. `test_sao_establishes_at_plant_a`
reads the TAN midpoint from the file and carries no envelope literal. The "pending"
item of the salvage session is closed.

---

## 2026-09-02 — Duplicate plant layer — salvage from PR #7 into the #6 contract

**What happened.** Two sessions built the plant layer in parallel. PR #6
(`claude/milestone-2-plant-configs`, merged at 5237ac7) went through the lead's seven
answers and is the design authority: ideal CSTR in the plant contract, imperfect mixing
as a Level-6 truth variant, Plant B as Muscatine co-digestion, ammonia scenarios on
Plant A, `k_m_sao` 4.0, the feed catalogue as identity and delivery pattern only with
fractionation deferred to the influent generator. PR #7 (`claude/milestone-2-plants`,
draft, never merged) carried a different schema (`PlantDeclared` / `PlantTruth`) with its
own plant YAMLs, a hidden-volume sampler, a 100-day plausibility table, and three pieces
of engineering the lead wanted kept.

**Decision (by the lead; executed by this session).** No design re-decision: every value
frozen in #6 stands. One PR salvages from #7, adapted to #6's schema, and #7 is closed.

*Kept, and where it went.*

1. **Seeded true per-feed COD fractionation** (`sim/plants/sampling.py` →
   `sim/influent/fractionation.py`). Dirichlet draw around the catalogue fractionation
   with the feed's declared concentration `κ` (`sd_i ≈ √(m_i(1−m_i)/(κ+1))`); catalogue
   zeros stay zero; one `numpy.random.default_rng(seed)` stream consumed in sorted
   feed-id order, so the draw for a feed does not depend on which other feeds are listed
   (tested). Returns a `TrueFractionations` object (hidden truth); writes nothing.
2. **Feed catalogue → 26-state ADM1 influent** (`sim/plants/feed.py` →
   `sim/influent/mapping.py`). Total COD = TS × VS/TS × COD/VS; the six-way split feeds
   `X_ch`/`X_pr`/`X_li` directly (no composite), inerts to `X_I`/`S_I`, VFA to `S_ac`;
   dissolved species flow-weighted; OLR and COD loading; TKN implied by the
   fractionation and the ADM1 N contents (`N_aa` on proteins, `N_I` on inerts) checked
   against the declared TKN. Recipes stay in kg wet/d because the frozen contract reports
   silage by fresh mass; `nominal_mass_rates` converts a `PlantConfig`'s feed medians.
   The catalogue values themselves are a **separate declared-data file**,
   `configs/influent/feed_fractionation.yaml`, keyed by the #6 feed ids (`hsw_liquid` →
   `high_strength_waste`, `twas` → `thickened_was`), every value `# DESIGN` and
   `status: provisional` (next entry).
3. **Two-zone mixing structure** (`sim/plants/reactor.py` → `sim/plants/mixing.py`,
   *parked*). Active zone `V(1−φ)`, stagnant zone `Vφ` exchanging at `k_ex V_stag` with
   full biochemistry and gas transfer into the shared headspace, bypass `β` of the
   influent to the effluent. Compiled on a `PlantGeometry` (the true active volume from
   `sim.plants.true_geometry`) instead of #7's `PlantDeclared`/`PlantTruth`. Reduces bit
   for bit to `sim.adm1.simulate` (no extensions) and to `simulate_extended` (all four)
   at `β = φ = 0`; verified against the analytical two-compartment tracer solution on
   `S_cat` and the fast-exchange well-mixed limit (which also checks the stagnant zone's
   gas reaches the headspace). #7's reasoning for this structure over tanks-in-series is
   kept as the record: tracer studies of full-scale digesters report non-effective volume
   (22 % in Capela et al. 2009; 75 % in Monteith & Stephenson 1978) and short-circuiting
   (up to 61 % of flow in the latter), and the Level-6 scenario needs a load-dependent
   residual; tanks-in-series moves the RTD towards plug flow, less dispersion than a
   CSTR. The module docstring states it is not part of the plant contract; `PlantConfig`
   carries no mixing parameters and the tests assert the YAMLs never will. #7's
   `mixing_prior` bands (bypass 1–10 %, stagnant 3–30 %, exchange 0.2–2 d⁻¹) are **not**
   carried: they belong to the fault-injection scenario definition, not to a plant.

*Dropped.* `PlantDeclared`/`PlantTruth` and #7's plant YAMLs (their content is #6's,
with different numbers for Plant B's feeds and C's geometry); the hidden-volume sampler
(#6 has `sample_hidden_geometry`); the 100-day plausibility table and its methane-yield
gate (needs #7's recipes and per-plant parameter overrides, neither in the contract);
`apply_parameter_overrides` and the `parameter_overrides` field (the per-plant `N_I`
override is recorded per feed as `inert_N_I`; decided the same day, see the inert-nitrogen entry); #7's
`plant_a_statistics.yaml` (T2026 Table 1 transcription; #6's file has a `todo` for it
and the values live in the catalogue descriptions); the `dilution_water` pseudo-feed;
tests that duplicate #6's (config loading, hidden-volume determinism and bounds). The
"never writes files" AST check is kept and now covers `sim/plants` and `sim/influent`.

**Alternatives.** Merge both branches (rejected: two schemas for one contract, and #7's
Plant B contradicts answer 3); drop #7 entirely (rejected: the fractionation sampler, the
influent mapping and the verified mixing structure are the next milestone's work and
were already tested); re-run #7's plausibility table on the #6 plants (rejected: it
depends on provisional fractionation values and on `N_I` overrides the lead has not
approved; it returns with the influent generator).

---

## 2026-09-02 — Feed fractionation values are provisional pending lead review

**Decision.** `configs/influent/feed_fractionation.yaml` carries PR #7's per-feed
composition (TS, VS/TS, COD/VS, six-way COD fractionation, Dirichlet concentration,
TAN, TKN, inorganic C, strong ions, calcium) for cattle slurry, grass silage, food waste,
high-strength waste, FOG, primary sludge and thickened WAS, with #7's citations and
"assumed" notes verbatim and nothing added or re-derived. Every entry is
`status: provisional` and every numeric leaf `# DESIGN`. The lead's answer 7 (#6)
deliberately deferred these numbers, so they are **not frozen**; the schema will accept
no other status until the lead reviews them, at which point the reviewed entries become
`frozen` by a decision here.

**What the lead is asked to review (summary; sources per value in the YAML).**

| Feed (kind) | Fractionation ch/pr/li/xi/si/vfa | κ | Basis |
|---|---|---|---|
| cattle_slurry (slurry) | 0.34/0.17/0.13/0.22/0.02/0.12 | 150 | Tisocco 2026 Table 1 (TS, VS, XC/XP/XL, NH₄-N, VFA, DQ_XC 69 %); inerts and solubles assumed |
| grass_silage (silage) | 0.327/0.148/0.075/0.25/0/0.20 | 100 | Tisocco 2026 Table 1; inert share from BMP over theoretical (Amon 2007, assumed 25 %); TAN **assumed** 10 % of crude-protein N because the table's 7.28 g/L cannot be per kg FM |
| food_waste (food_waste) | 0.36/0.16/0.25/0.17/0.02/0.04 | 40 | Zhang 2007, Fisgativa 2016, Bong 2018; no frozen plant uses it |
| high_strength_waste (hsw) | 0.20/0.10/0.55/0.08/0.02/0.05 | 30 | Muscatine COD 137.6 g/L and VS 6.16 % w/w measured; split assumed from COD/VS 2.23 |
| fog (fog) | 0.05/0.05/0.85/0.04/0.01/0 | 60 | all assumed (lipid-dominated); Muscatine delivery statistics only |
| primary_sludge (primary_sludge) | 0.15/0.25/0.15/0.40/0.02/0.03 | 200 | Muscatine VS 3.0 % w/w; split of the BSM2 influent's COD shares assumed |
| thickened_was (thickened_was) | 0.05/0.45/0.05/0.44/0.01/0 | 300 | Muscatine VS 3.09 % w/w; BSM2 split assumed, biomass COD/VS 1.42 |

**The inert-nitrogen question, carried as data rather than decided.** #7 found that the
BSM2 `N_I` (0.06 g N/g COD, derived for sludge inerts) over-counts the nitrogen of
lignocellulosic and food-waste inerts several-fold (grass silage: 11 g N/L implied
against 6.6 g N/L from crude protein and ammonia) and applied per-plant overrides
(A 0.001, B 0.0015 kmol N/kg COD) as a declared `PlantDeclared` field. The frozen
`PlantConfig` has no override field and this PR adds none. Each catalogue entry records
`inert_N_I`, the inert N under which its declared TKN is consistent with the
ADM1 N contents (tested: every entry consistent under its own value; the five
non-sludge entries inconsistent under BSM2's). *Decided the same day with the PR #8
review* (entry "Per-feed inert nitrogen in the truth model"): the truth model applies
the per-feed values, the fitted model keeps the ADM1 default, intentionally.

**Alternatives.** Leave the numbers out until the lead supplies them (rejected: the
mapping and the sampler need a catalogue to be tested against, and #7's sourced values
are better than placeholders); merge them into `configs/plants` (rejected: the frozen
contract keeps fractionation out of the plant files); mark them frozen because they
carry citations (rejected: most of the inert/soluble/ion values are explicitly assumed).

---

## 2026-09-02 — Per-feed inert nitrogen in the truth model; the fitted model keeps the ADM1 default (intentional mismatch)

**Decision (by the lead, with PR #8's review).** The truth model applies the per-feed
inert nitrogen content `inert_N_I` of `configs/influent/feed_fractionation.yaml`
(kmol N per kg COD of `X_I`/`S_I`: 0.001 for cattle slurry and grass silage, 0.0015 for
food waste, high-strength waste and FOG, the BSM2 0.06/14 = 0.00429 for primary sludge
and thickened WAS, all provisional with the rest of the catalogue). The fitted model
(standard ADM1) keeps the ADM1 default `N_I` for every plant. The gap is **deliberate**:
a small, real structural mismatch of exactly the kind the benchmark exists to expose
(proposal §6.1, "the fitted model is structurally wrong by design"). Nobody should
later "fix" it by aligning the two values; a scenario that wants them aligned says so.

**Reason.** ADM1's default is a sewage-sludge value (Batstone et al. 2002); the inerts
of lignocellulosic feeds and food waste carry much less nitrogen, and the truth model
should be as realistic as the data allow. With the default, the ADM1-implied TKN of
grass silage is 11 g N/L against the 6.6 g N/L its crude protein and ammonia give
(tested in `tests/test_influent.py`: every catalogue entry is consistent under its own
value, the five non-sludge entries inconsistent under the default). PR #7 had reached
the same numbers but applied them as a plant-level parameter override visible to
workflows; that field is not in the frozen contract and is not added.

**Implementation (influent-generator session, not this PR).** ADM1 carries one `N_I`
per reactor, so "per feed" means: the truth model's `N_I` is the COD-weighted mean of
the `inert_N_I` of the feeds actually fed (recomputed when the recipe changes, i.e. a
plant-level truth parameter derived from the catalogue, never a workflow-visible
config), and the TKN the influent generator reports as a "routine assay" is the one
implied by the per-feed values. The fitted model's parameter file stays the BSM2 set.
Which quantities a workflow may see (feed TKN yes; the truth `N_I` no) follows CLAUDE.md
rule 1 as for any other hidden truth.

**Alternatives.** Per-plant override visible to workflows (PR #7; rejected: makes the
modeller's prior carry the truth's value, removing the mismatch); a per-feed inert
component in the state vector (rejected for Phase 1: adds states for a bookkeeping
quantity); keep the ADM1 default in the truth too and loosen `tkn_tolerance` (rejected
by the lead: hides a real factor-of-several nitrogen error behind a tolerance).

---

## 2026-09-02 — Feed catalogue consistency: COD/VS derived, slurry inert share 0.40, silage TAN basis (the lead's answers)

**Context.** The salvage PR's composition read (PR #8 review comment) found that the
provisional catalogue declares `cod_per_vs` and the fractionation independently and that
they disagree for high-strength waste (−20 %), primary sludge (−15 %) and FOG (−12 %);
that the cattle-slurry inert share (0.24, from Tisocco's fitted DQ_XC 69 %) sits at the
degradable end of the BMP literature; and that the grass-silage TAN rested on an
untraced "7.28 g/L". The lead answered all three; they are recorded here and are the
first tasks of the influent-generator session together with the per-feed inert N
(previous entry). The catalogue stays `provisional` until that session applies them.

**Decisions (by the lead).**

1. **COD/VS is derived from the fractionation, never declared.** `cod_per_vs` becomes a
   computed quantity (the fractionation's classes at their COD equivalents: carbohydrate
   1.19, protein 1.42, lipid 2.90 kg COD/kg, VFA as acetate 1.07; inerts at the
   carbohydrate-like 1.19 unless the session records a better inert equivalent). The
   literature or measured COD/VS stays in the catalogue as a **check field** with a
   ±10 % tolerance **enforced by a test**. Consequences for the provisional entries:
   - **FOG**: fix the mass-share / COD-share mix-up (PR #7 computed 2.75 from a *mass*
     share of 0.85 lipid, while `f_li` 0.85 is a *COD* share, which gives 2.43); the
     lipid COD share rises (≈ 0.93) so the derived COD/VS lands near 2.7–2.9.
   - **High-strength waste** and **primary sludge**: adjust the splits so the derived
     COD/VS passes the check against the measured Muscatine 2.23 (HSW; lipid COD share
     ≈ 0.7–0.75) and the typical 1.60 (primary sludge; more lipid, less
     carbohydrate-like inert), and **cite the adjustment** beside the value.
2. **Cattle-slurry inert share: centre the hidden-truth Dirichlet at 0.40** (particulate
   plus soluble inerts), with a spread covering 0.30–0.50, on BMP evidence (cattle-slurry
   BMP ≈ 0.20–0.25 m³ CH₄ per kg VS against a theoretical ≈ 0.47 for this composition).
   Tisocco's DQ_XC of 0.69 is a *fitted* value and sits inside that range. Arithmetic
   for the session: keeping the measured VFA 0.12, protein 0.17 and lipid 0.13, the
   carbohydrate share becomes 0.16; a concentration κ ≈ 100 gives sd ≈ 0.05 on the 0.40
   share, i.e. 0.30–0.50 as ± 2 sd.
3. **Silage TAN basis.** Tisocco 2024 Table 1 is **g N per kg TS**: 25.6 (data set A)
   and 21.8 (data set B) for grass silage, as already transcribed in
   `configs/plant_a_statistics.yaml` (`feed_TAN_g_N_per_kg_TS`), with 65.3 / 57.8 for
   cattle slurry. The "7.28 g/L" that PR #7 attributed to the 2026 Table 1 and rejected
   is to be **traced or dropped**; the catalogue's silage TAN is to be derived from the
   2024 basis (25.6 g N/kg TS × 20.1 % TS = 5.1 g N/kg FM for set A; 21.8 × 25.2 % =
   5.5 for set B), replacing the assumed 0.6 g N/kg FM.

**Observation for the session (recorded, not decided).** On the 2024 basis the silage
values (25.6 / 21.8 g N per kg TS) exceed the crude-protein nitrogen the 2026 table's
XP implies (116.9 / 6.25 = 18.7 g N per kg TS), and the slurry values (65.3 / 57.8)
exceed its 19.8 by three-fold; multiplied by the 2024 TS they give 4.44 / 4.33 g N per kg
FM for slurry, which is what the 2024 ESM Table S2 lists as the slurry's `S_IN`
(4.35–5.95 kg N m⁻³) and what PR #7 declined to use as ammoniacal N. The column
therefore reads as total (Kjeldahl) N with the paper feeding it to ADM1 as `S_IN`,
rather than as ammoniacal N alone. The session must settle which it is before deriving
`tan` (ammoniacal, `S_IN`) and `tkn` from it; if it is total N, `tan` needs a TAN/TKN
ratio (cattle slurry ≈ 0.5–0.6; silage lower) recorded with its source, and the
`tkn` field becomes the transcribed number.

**Alternatives.** Keep `cod_per_vs` declared and loosen the fractionation (rejected: two
numbers for one quantity, one of them silently wrong); adopt a per-class inert
equivalent instead of adjusting the sludge splits (not chosen; may be recorded by the
session if the adjusted splits become implausible); keep the slurry inert share at the
fitted 0.24 (rejected: a fitted degradability is not a measured one, and the BMP
evidence is independent).

---

## 2026-09-02 — Truth `N_I` weighting: inert-COD-weighted mean of the fed feeds

**Decision.** `sim.influent.nitrogen.truth_inert_nitrogen` computes the truth model's
`N_I` as the mean of the fed feeds' `inert_N_I` weighted by each feed's **inert COD
load** (`m_k · COD_k · (f_xi + f_si)_k`), using the true fractionation when one is given.
Under this weighting the inert-nitrogen load of the blend equals the sum of the per-feed
loads exactly, which is what "per-feed inert N" means once ADM1 has only one `N_I`.
`truth_parameters` returns a copy of the BSM2 set with that one field changed; the file
and the loaded object are untouched (tested). The generator sets the run's `N_I` from
the horizon's mean true recipe, so a run has one value (a scenario that changes the
recipe mid-run inherits a small, known approximation; recorded here rather than adding a
time-varying parameter to the truth model). The module docstring states that the gap to
the fitted model is intentional and must not be "fixed".

**Alternatives.** Weight by total COD (rejected: over-weights degradable feeds whose
inerts are few); weight by wet mass (rejected: a dilute slurry would dominate a
concentrated silage); a per-feed inert component in the state vector (rejected earlier,
Phase 1).

---

## 2026-09-02 — Inert COD equivalent stays at the carbohydrate-like 1.19 kg COD/kg

**Decision.** The derived COD/VS (`CODFractionation.cod_per_vs = 1 / Σ f_i/e_i`) uses
1.19 kg COD/kg for both inert classes, as the lead's answer allowed unless a better
equivalent was found. With that equivalent the adjusted sludge splits (HSW lipid COD
share 0.75 → 2.15 against the measured 2.23; primary sludge lipid 0.35, inerts 0.33 →
1.56 against 1.60; FOG lipid 0.95 → 2.72 against 2.80) are physically plausible (mass
shares: HSW 56 % lipid; primary sludge 19 % lipid, 22 % protein, inside the typical
composition of untreated primary sludge; FOG 95 % lipid), so no per-class inert
equivalent was needed. The equivalents live in code
(`sim/influent/schema.py::COD_EQUIVALENTS_KG_COD_PER_KG`) with their derivation, and the
check is enforced twice: the schema rejects an entry whose literature value is more
than `cod_per_vs_tolerance` (10 %) from the derived one, and `tests/test_influent.py`
asserts every entry passes and that PR #7's FOG split fails.

**Alternatives.** A lignin-like 1.9 kg COD/kg for lignocellulosic inerts and a
biomass-like 1.42 for sludge-derived inerts (not adopted: it would let the sludge splits
keep less lipid, but the inert *mass* is not what is measured either, and one convention
for both inert classes keeps the derivation auditable; revisit if the lead's freeze
finds a split implausible); keep COD/VS declared (rejected by the lead).

**Cattle slurry arithmetic.** The lead's entry wrote "carbohydrate becomes 0.16" with
inerts 0.40; with VFA 0.12, protein 0.17 and lipid 0.13 kept, 0.16 sums to 0.98. The
inert share 0.40 is the substantive decision, so carbohydrate is 0.18 (particulate
inerts 0.38 + soluble 0.02); the slip is noted in the YAML beside the value.

---

## 2026-09-02 — Tisocco 2024 Table 1 "NH4-N [g/kg TS]" is read as total N; the 2026 "7.28 g/L" is dropped

**What the papers say (both read in full from this environment: Springer PDF and ESM;
Europe PMC full text of the 2026 paper).** The 2024 methods (§2.2.1) describe ammonium
N of the slurry by gas-sensing electrode, total N by Kjeldahl, and crude protein of the
slurry as (total N − inorganic N) × 6.25; silage XP, XL and "ammonium nitrogen" by NIRS.
Table 1 labels the row "NH4-N [g/kg TS]": silage 25.6 / 21.8, slurry 65.3 / 57.8.

**Why it is total N.** (1) For silage the row equals XP/6.25 exactly: 160/6.25 = 25.6
and 135/6.25 = 21.6, i.e. it is the crude-protein (total) N that NIRS reports. (2) The
ESM Table S2 feeds it as `S_IN` for data set A: silage 25.6 × 20.1 % = 5.15 ≈ 5.1,
slurry 65.3 × 6.8 % = 4.44 ≈ 4.35 kg N/m³ (set B does not reproduce either way).
(3) Read as ammoniacal N the slurry would carry 65 g NH4-N per kg TS, and the AFBI
digestate (2.3–4.3 kg N/m³) would hold less ammonia than its feed with no sink; read as
total N the feed TKN is 4.4 g N/kg FM, ordinary for dilute cattle slurry. (4) The Foulum
slurry's directly measured NH4-N (2026 Table 1, 1.08 g/L at 3.6 % TS = 30 g N/kg TS)
is 0.49 of the 2024 value per kg TS, the literature TAN/TKN ratio of cattle slurry.
The paper's label is therefore taken as a mislabel of a total-N column, and the paper's
own use of it as `S_IN` as a modelling choice of theirs, not repeated here.

**Consequence for the catalogue.** `tkn` of cattle slurry and grass silage is the 2024
basis (mean of the two data sets: 61.6 and 23.7 g N per kg TS) at the catalogue's own
TS (2026 Table 1: 3.6 % and 31.9 %), so that TS, VS, crude fractions and N share one
fresh-matter basis: slurry 2.22 g N/kg FM (0.158 kmol N/m³), silage 7.56 g N/kg FM
(0.540 kmol N/m³). `tan` is a cited ratio times `tkn`: cattle slurry 0.55 (TAN 50–60 %
of total N: Sommer & Husted 1995, *J. Agric. Sci.* 124:45; Webb et al. 2010, *Agric.
Ecosyst. Environ.* 137:39), cross-checked by the measured Foulum ratio 0.49; grass silage
0.10 (ammonia N below 10 % of total N in well-preserved silage: McDonald, Henderson &
Heron 1991, *The Biochemistry of Silage*). The implied TKN under each feed's own
`inert_N_I` is within 10 % of the declared value (tested). The lead's per-FM figures
(5.1 / 5.5 g N/kg FM on the 2024 TS) are recorded beside the values.

**The 7.28 g/L.** The 2026 Table 1 prints 7.28 g L⁻¹ NH4-N for grass silage with no
footnote (footnote *i* on the same column says the silage acids are "reported in the
source as g per kg TS ... reproduced here as reported"). It is not the 2024 values
converted at any of the three TS figures (5.1, 5.5 or 7.56 g/kg FM) nor XP/6.25 at the
2026 TS (5.97), and exceeds the silage's total N as g/L of fresh matter. It cannot be
traced and is **dropped**, as the lead instructed; the assumed 0.6 g N/kg FM it had
displaced is replaced by the derived 0.76.

**Flagged for the freeze (not decided here).** The catalogue's silage TS is the Foulum
31.9 % (2026), while AFBI's own silage was 20.1 / 25.2 % (2024); Plant A is AFBI-anchored
for hydraulics and ammonia. Nitrogen per kg TS is basis-free, so this affects only the
per-m³ values. Recorded in the YAML beside `ts`.

**Alternatives.** Read the column as ammoniacal N because the paper says so (rejected:
contradicted by the silage arithmetic, the digestate ammonia and the Foulum measurement);
use the Foulum measured NH4-N (1.08 g/L) directly as the slurry `tan` (not chosen: the
lead asked for a cited ratio on the 2024 basis; the measurement is the cross-check and
is 12 % below the ratio's value).

---

## 2026-09-02 — Influent generator: stochastic structure, random-stream order, what is assumed

**Decision.** `sim/influent/generator.py` implements proposal §6.1 as follows (details
and the exact stream order in the module docstring).

1. **Delivery days** per feed: `continuous`; `weekday` (listed weekdays, each skipped
   with a probability: Plant A silage Monday–Friday with no skips, Plant B FOG
   Monday–Friday with 5 % skips); `markov` (two-state chain with the anchor's
   stationary zero-day fraction and lag-1 persistence: Plant B HSW 0.10 / 0.84, whose
   mean no-delivery run of 6.9 d matches the daily file's 6.94).
2. **Amount** on delivery days: `nonzero_median × seasonal × exp(AR(1))`, the AR(1) in
   the log with the anchor's marginal sd and lag-1; seasonal factor `exp(A cos(2π(doy −
   peak)/365.25))` with `A` half the log ratio of the highest to the lowest monthly
   mean. Plant B/C statistics from the Muscatine daily file through
   `anchor/ingest_muscatine.py`, re-derived by `tests/test_generator.py`; Plant A's from
   the Tisocco ranges where published, assumed otherwise.
3. **Moisture**: per-delivery total solids `ts × seasonal × exp(AR(1))`, VS/TS fixed;
   the seasonal term is the "wetter season" of the Level-3 scenario (Plant A slurry:
   ±10 %, driest in late summer, assumed). The Muscatine VS-% spreads (log sd HSW 0.475,
   PS 0.32, TWAS 0.20) are attributed to the moisture AR(1) after removing an assumed
   0.03 assay cv; true-vs-assay attribution is not identifiable from the data and is
   recorded as a choice.
4. **Log errors**: unrecorded deliveries (an extra batch on a day, never logged; 1 %/d
   for trucked or loader-fed feeds, 0 for pumped metered feeds) and mis-logged masses
   (2–3 % of entries, lognormal factor sd 0.3). All assumed.
5. **Assays**: TS, VS, COD, TKN, TAN, alkalinity, pH of the sampled delivery with
   relative noise (pH absolute) and turnaround lag, on the feed's schedule (Plant A
   weekly per Tisocco §2.2.1; Muscatine weekday VS/COD per the daily file's
   measured-day pattern), reported with unit and basis. TKN is the per-feed value.
   Alkalinity is a bicarbonate proxy from `S_IC` and the feed's catalogue pH (a new
   provisional `ph` field). Assay cv, lags and the feed pH values are assumed.
6. **Influent series**: one sample per day, flow-weighted true mix, **sample-and-hold**
   (a piecewise-constant daily input is what a batch process produces; the hold
   treatment is exact for it and costs one restart per day). The truth `N_I` from the
   mean true recipe.
7. **Randomness**: one `default_rng(seed)` per run; the true-fractionation draw first
   (so it equals `sample_true_fractionations(seed)`), then per feed in sorted order a
   fixed block of draws (delivery uniforms always consumed whatever the model), then
   assay noise per feed and assay in sorted order. Tested: a later stage cannot change an
   earlier one.

**What is left out of this session.** Temperature seasonality ("seasonal drift in
composition and temperature") belongs with the plant heating model / observation model,
not the influent; feed identity per delivery is fixed by the plant's catalogue (no
mislabelled feed here: the Level-3 "feed mislabelled" scenario is a fault injection on
the mapping). The 100-day plausibility table of PR #7 is replaced by a 30-day Plant C
integration test on the generated influent (standard ADM1, pH 6.8–7.8, gas positive).

**Alternatives.** Hourly deliveries (rejected: the anchor is daily; nothing finer is
observable); linear interpolation of the daily series (rejected: a delivery is not a
ramp; the ring-test decision keeps both treatments available); a shared AR(1) across
feeds (rejected: no evidence of cross-feed correlation in the daily file beyond the
seasonal term, which is shared by construction through the day of year).

**Addendum (engineering review of PR #10, same day).**

1. **Assays sample logged deliveries only.** An assay on an unrecorded delivery would
   put hidden truth into the operator record (a record on a day whose log reads zero).
   The sampling mask is now `logged > 0`; the schedule is anchored to the first eligible
   day of the horizon (a weekly, weekdays-only schedule previously produced no samples
   at all when day 0 fell on a weekend). Alternative: keep the sample as an intended
   clue (rejected: the Level-3 "unrecorded delivery" scenario should be detectable from
   the mass balance, not from a stray assay).
2. **Solids vary, the liquor does not.** The per-delivery TS scales the particulate COD
   and its organic N; the dissolved species per m³ (TAN, inorganic C, strong ions,
   calcium, pH) stay at the catalogue values, so the reported TAN/TKN ratio moves with
   the moisture by construction (slurry 0.45–0.67 at the assumed TS spread). Recorded
   as the choice rather than scaling dissolved species with TS: dilution by rainwater
   dilutes the liquor, a drier clamp does not concentrate it, and no anchor measures
   both together. Revisit if a scenario needs feed TAN to track TS.
3. **Seasonal amplitudes are bounded by the monthly-mean statistic**, not equal to it
   (half the log ratio of the extreme monthly means over-states a true cycle by the
   sampling noise of twelve monthly means of a 0.4–0.8 log-sd series); the test accepts
   half that bound up to the bound plus 0.03. Moisture log sds are the assay column's
   log sd less the assumed 0.03 assay cv in quadrature (0.32 / 0.20 / 0.47).
4. **The horizon is not prefix-stable**: the stream blocks are `n_days` long, so seed and
   horizon together identify a run (documented; a per-day stream layout would make the
   generator O(feeds × days) slower for no scenario need).

---

## 2026-09-02 — FREEZE (by the lead): silage on the Tisocco 2024 basis; the inert COD equivalent is per feed

**Decisions (the lead's answers on PR #10; the catalogue values they touch are now
settled, the rest of the catalogue stays `provisional` until the lead says otherwise).**

1. **Silage basis follows Tisocco et al. 2024 throughout.** Total solids as a percentage
   of **fresh matter**, every composition figure **per kg TS**, and **VS = TS − ash**.
   Every silage field in `configs/influent/feed_fractionation.yaml` is labelled with that
   basis. The liquid-basis ("g/L") reading of the 2026 Foulum table is dropped for this
   feed, and with it the last use of the untraced 7.28 g/L.
2. **The inert COD equivalent is per feed, with a source.** `inert_cod_equivalent`
   (kg COD per kg of inert VS mass) is a catalogue field, not a global constant:
   **1.2** for lignocellulosic inerts (cattle slurry, grass silage) and **1.42** for
   sludge-derived inerts (the Muscatine feeds, at the ADM1 biomass composition C₅H₇O₂N,
   inside the lead's 1.4–1.5). **FOG and food waste take the sludge value** by the lead's
   instruction, documented beside each value as an assumption rather than a measurement.

**What changed in the catalogue.**

| Field | Before | After |
|---|---|---|
| `grass_silage.ts` | 0.319 (Foulum, % FM) | **0.2265** (AFBI 2024: mean of 20.1 / 25.2 % FM) |
| `grass_silage.vs_of_ts` | 0.877 (Foulum) | **0.815** (TS − ash: 1000 − 185 g XA per kg TS) |
| `grass_silage.fractionation` | 0.327 / 0.148 / 0.075 / 0.25 / 0 / 0.20 | **0.328 / 0.202 / 0.081 / 0.25 / 0 / 0.139** (2024 crude fractions per kg TS; acids at acetic 1.07, butyric 1.82, propionic 1.51, lactic 1.07 kg COD/kg) |
| `grass_silage.cod_per_vs_literature` | 1.277 | **1.274** (derived 1.275, +0.1 %) |
| `grass_silage.tkn` / `tan` | 0.540 / 0.054 | **0.383 / 0.038** (23.7 g N per kg TS × 226.5 g TS/kg FM = 5.37 g N/kg FM; TAN ratio 0.10 unchanged) |
| `inert_cod_equivalent` | (global 1.19) | **1.2** slurry, silage; **1.42** food waste, HSW, FOG, primary sludge, thickened WAS |
| `cattle_slurry.ts` / `vs_of_ts` | 0.036 / 0.751 (Foulum) | **0.0715 / 0.759** (AFBI 2024) — see the flag below |
| `cattle_slurry.tkn` / `tan` | 0.158 / 0.087 | **0.314 / 0.173** (same 61.6 g N per kg TS at the 2024 TS; = the ESM's slurry `S_IN` of 4.35–5.95 kg N/m³) |
| `cattle_slurry.cod_per_vs_literature` | 1.337 (2026 fractions) | **1.332** (2024 fractions; derived 1.314, −1.4 %) |

Derived COD/VS against its check after the freeze: slurry −1.8 %, silage +0.1 %, food
waste +0.1 %, HSW −2.2 %, FOG −2.1 %, primary sludge +4.8 %, thickened WAS +1.6 % — all
inside ±10 %. Declared TKN against the ADM1-implied one: −9.2 % to +12.2 %, all inside
each entry's `tkn_tolerance` of 0.15.

**FLAGGED FOR THE LEAD: the cattle-slurry basis moved too, and it was not in the
instruction.** Applying the freeze to silage alone put grass silage on AFBI 2024
(22.65 % TS) while cattle slurry stayed on Foulum 2026 (3.6 % TS), and Plant A's organic
loading then fell to **1.17 kg VS m⁻³ d⁻¹**, outside the published AFBI envelope of
1.4–2.1 that `tests/test_influent.py::test_plant_a_loading_lands_in_the_published_olr_range`
asserts. Putting both Plant A feeds on the 2024 basis restores **1.78**, inside it. The
freeze's stated principle is a basis rule for the AFBI plant, so it was applied to the
plant's other feed as well; the slurry's *fractionation* is untouched (it is the lead's
frozen one, and the two tables' crude fractions agree to a few per cent). Consequence to
note: the slurry's feed TKN and TAN roughly double (4.40 and 2.42 g N/L), which is what
the 2024 ESM lists as the slurry `S_IN`. If the lead prefers the slurry on the 2026
column, revert those four fields and the OLR test's envelope needs the lead's ruling
instead.

**Alternatives.** Keep the slurry on the 2026 column and accept an OLR outside the
published range (rejected: the catalogue would no longer reproduce the plant it is
anchored to, and the OLR test is one of the few anchored checks Plant A has); loosen the
OLR test (rejected: it would hide the inconsistency the basis change exposed); use a
lignin-like 1.9 kg COD/kg for lignocellulosic inerts (superseded: the lead fixed ~1.2).

---

## 2026-09-02 — Observation model: channels, sensor specs, tier masks, conditional missingness

**Decision.** `sim/observation/` implements proposal §6.1's observation model and §6.4's
tiers, with `configs/observation/sensors.yaml` as the declared data.

1. **Channels are hidden truth, records are not.** A *channel* is an observable quantity
   computed from the truth trajectory (pH, gas flow in both conventions, CH₄/CO₂/H₂
   fractions on a dry basis, partial and total alkalinity, VFA total and speciated, TAN,
   free ammonia, COD, digestate VS and TS, and the FOS/TAC stress index), each with its
   unit and convention. `observe()` turns channels into an `ObservationRecord` through a
   tier mask; the condition flags that drove missingness stay with the truth.
2. **Solids without new states.** Volatile solids come from the COD states divided by the
   COD equivalent of their class, with the two inert states using the influent's own
   inert equivalent (the inert-COD-weighted mean, the same construction as the truth
   `N_I`). Ash is not an ADM1 state, so total solids add a **conserved-tracer** balance
   integrated analytically alongside the run. The frozen ADM1 core is untouched.
3. **Sensor model.** Schedule, then fouling (a ramped gain/offset episode), bounded
   random-walk drift with recalibration resets, noise, saturation clipping, flatline
   (the sensor repeats its last value), conditional missingness, and turnaround lag.
   Every stage is declared per sensor and every quantity carries its unit and convention.
4. **Tiers are nested masks.** §6.4 says tiers are masks on identical truth, so the
   schema *enforces* that B contains A and C contains B, for both sensors and feed
   assays. Tier A is the three online instruments plus the operator's feed log and the
   generator's weekly feed TS/VS; B adds CH₄, alkalinity, VFA, TAN and COD; C adds VFA
   speciation, off-gas H₂ and digestate solids.
5. **Conditional missingness — the rule.** A scheduled sample is lost with probability
   `base_rate`, multiplied while a condition flag is raised. Two flags: **overload**
   (FOS/TAC above 0.40) and **foaming** (FOS/TAC above 0.30 *and* gas above 1.35× its
   trailing 14-day median). Multipliers are 1.5–2 for the lab assays and 3–6 for the
   online instruments a foaming digester actually takes out. Because the flags are
   functions of the state, gaps coincide with the transients that identify the process,
   which is what makes naive interpolation destructive rather than merely lossy.
6. **One seeded stream** per run, consumed per sensor in sorted name order with a fixed
   block per sensor drawn whether or not the sensor declares that effect, so a change to
   one sensor cannot move another (tested).

**Anchoring.** Two values are re-derived from the Muscatine 1-minute SCADA file by
`tests/test_observation.py` through `anchor.ingest_muscatine.scada_noise_statistics`:
digester-temperature noise (0.052 °F = **0.029 K**, robust first-difference estimate) and
biogas-flow noise (2.35 cfm on 112.8 = **2.1 %** relative), plus both flatline
occupancies (0.08 % and 0.01 % of the record). The overload threshold is the 92nd
percentile of the plant's own FOS/TAC column, which our channel reproduces from its VFA
and alkalinity to r = 0.99. **Everything else is ASSUMED and marked**, including every
missingness rate: the provider pre-cleaned the SCADA file, so both channels are 100 %
finite and no dropout statistics exist to fit. **Flagged for the lead.**

**Not modelled, deliberately.** Off-gas H₂S (§6.4 Tier C): ADM1 has no sulfur, so there
is no truth to observe and the channel is declared absent rather than faked. Reactor
temperature varies only as sensor noise, because the truth model integrates at a fixed
set point — the plant's `day_sd_K` belongs to a heating model that is not built.

**Alternatives.** Sample the channels at the truth model's own output times (rejected:
the schedule is part of the tier); model missingness as a Markov chain over instrument
health (not chosen for Phase 1: no data to fit the transitions, and the flag-multiplier
form is the one §6.1 describes); put the FOS/TAC stress index in the record (rejected: it
is a function of the truth, and a workflow can compute its own from the VFA and
alkalinity it is given).

---

## 2026-09-02 — Fault injection: magnitude semantics per fault type, and a layer per fault

**Decision.** `sim/faults/` is the fault-injection API of §6.1. The scenario schema
leaves the meaning of `Fault.magnitude` to the simulator; `sim/faults/schema.py` is that
mapping — one entry per `FaultType` giving the **unit**, the admissible **range**, the
**target** and the **layer**, and `benchmark_card_rows()` renders the benchmark card's
table from the same table, so the card cannot drift from the code.

**Six layers, each applying only its own faults.** `influent` (the generator),
`parameter` (a truth constant that changes at the onset day, so the run is integrated in
segments), `state` (the initial vector), `structure` (an extension the fitted model must
lack, or the two-zone reactor), `observation` (the record only), `workflow` (the tool
registry and the operator's notes, applied by the run harness). The layer of a fault is
also what its truth label means in §6.3, which is why the routing is declared rather than
inferred.

**The fault layer has its own random stream.** Only the mislabelled-feed redraw needs
randomness, and it draws from `default_rng(fault_seed)` — separate from the generator's
and the observation model's. A faulted run therefore differs from its clean twin **only**
by the fault: same deliveries, same mis-logs, same noise, same gaps (tested on both
layers). Without this the paired comparison a scenario rests on would be confounded by a
reshuffled stream.

**Magnitude choices worth recording.** `feed_mislabelled` is a Dirichlet concentration
(smaller = further from the catalogue), which reuses the generator's own spread
machinery; `unrecorded_delivery` is a multiple of the feed's median delivery;
`moisture_drift` is the relative change in total solids across the window;
`imperfect_mixing` is the stagnant volume fraction, with the bypass fixed at a fifth of
it and the exchange at 1 d⁻¹ (the mid-point of PR #7's 0.2–2 d⁻¹ band), so one number
sizes the whole non-ideality; `ch4_analyser_flatline` and the two omission faults ignore
their magnitude, which the table says explicitly.

**The Level-6 mixing variant, wired in and measured.** `truth_mixing()` compiles
`sim/plants/mixing.py` (parked since the salvage session) as the truth reactor. At
magnitude 0 it reproduces the extended model bit for bit. At a stagnant fraction of 0.30
the gas deficit against the CSTR is 24.7, 41.2 and 57.9 m³ d⁻¹ at 0.6×, 1.0× and 1.4× the
declared feed — **proportional to the load** to within a few per cent, while the relative
deficit stays near 6 %. That load-proportional signature is what separates a hydraulic
fault from a kinetic one, which is what the Level-6 row asks a workflow to notice.

**Addendum (self-review of PR #11, same day).** Six findings, all fixed on the branch:
(1) the observation model drew **one** normal for both the relative and the absolute noise
term, so the one sensor declaring both (the H₂ cell) had perfectly correlated components
and a total sd of 2.80 ppm where the independent draws give 2.06 — now two blocks, and the
documented stream order says so; (2) `ash_trajectory` interpolated the influent flow even
for a sample-and-hold series — latent only (the error is exactly zero when the output
times are the influent's own, which is every current call, and 3 % on a four-times finer
grid), now the declared convention is honoured; (3) the two constants that shape the
imperfect-mixing structure beyond its magnitude were hard-coded in `sim/faults/plan.py`
against the repo's convention that design values are reviewable data — moved to
`configs/faults/injection.yaml` with sources; (4) `build_plan` picked the influent fault's
target as the *last* of the feed ids it was handed, which silently depends on the caller's
ordering — a `target_feed` argument now names it, and the test shows the two orderings
disagree; (5) a dead `channel_unit` helper removed; (6) `channels_from_two_zone` typed
against `TwoZoneResult` instead of `object`. The rule-1 hygiene check now covers
`sim/faults` and `sim/observation` as well as `sim/influent` and `sim/plants`.

*Test sizing, not a code defect.* The conditional-missingness test compared a ratio of two
small counts (109 and 179 losses) against a 35 % tolerance and flaked once the extra noise
draw shifted the realisation. Pooling forty seeds gives 2.055 ± 0.088 (gas flow) and
1.981 ± 0.061 (pH) against an expected 2.0, so the estimator is unbiased; the test now
pools twelve seeds over 6,000 days, which is what makes its 20 % bound meaningful.

**Alternatives.** Apply every fault inside one `run()` function (rejected: the layers
have different owners and different test surfaces, and a fault that silently touched two
layers would make its truth label ambiguous); let the magnitude be a typed union per
fault (rejected: the scenario schema is frozen and a float plus a declared unit is
auditable); size imperfect mixing with three independent numbers (rejected: a scenario
row carries one magnitude, and the fixed ratios are recorded here).

---

## 2026-09-02 — FREEZE (by the lead): observation defaults, and missingness as a tier policy

**Decision.** The lead's answers to the flags raised on PR #11. They supersede the
provisional numbers in "Observation model: channels, sensor specs, tier masks, conditional
missingness" (same day) wherever the two differ. `configs/observation/sensors.yaml` goes
to **version 2**.

### 1. Missingness is declared by tier and by instrument kind, not per sensor

The lead gave the base rate *per tier* and the multipliers *per kind of instrument*, which
is a different shape from the per-sensor block the branch had. The schema follows the
answer rather than paraphrasing it: `MissingnessPolicy` carries

| | A | B | C |
|---|---|---|---|
| base rate | 0.08 | 0.04 | 0.02 |

with multipliers 4× (overload) and 3× (foaming) for online instruments and 1.5× for lab
assays, and `SensorSpec` no longer carries a missingness block at all.

**The reasoning behind the shape, recorded because it now constrains the code.** How often
a scheduled sample is simply lost is a property of the *plant's monitoring capability* —
the constrained Tier-A plant loses most — while how much worse it gets under stress is a
property of the *instrument* — a probe in a foaming digester fails far more than a grab
sample sent to a laboratory. Two other values are tier properties by the same argument and
moved with it: **laboratory turnaround** (7/3/1 d at A/B/C) and the **recalibration
cadence** (quarterly at A, monthly at B and C). `SensorSpec` therefore lost `missingness`
and `lag_d`, `DriftModel.recalibration_interval_d` became the boolean `recalibrated`, and
`TierSpec` gained `lab_turnaround_d` and `recalibration_interval_d`. Tiers remain **masks
on identical truth** (§6.4): the truth is the same, only the quality of the window differs.

**Interpretations made where the answer was silent, each flagged here rather than buried:**

- The lead gave **one** lab figure ("1.5× lab assays"). It is applied to **both** flags,
  not to overload alone. The earlier draft gave lab assays an overload multiplier and no
  foaming one; a foaming digester makes grab sampling harder too, so the symmetric reading
  is the conservative one.
- The recalibration cadence applies to every sensor that declares `recalibrated: true` —
  the pH probe, the CH₄ analyser and the H₂ cell. So the CH₄ analyser is now recalibrated
  monthly at Tiers B and C and quarterly at Tier A, which the lead did not say explicitly
  but follows from making the cadence a tier property.
- The digester thermocouple and the gas meter declare `recalibrated: false`: neither is
  routinely recalibrated in the field, and the gas meter's error is a *scale* error
  injected as the Level-2 `gas_meter_scale` fault rather than a zero drift.

### 2. Sensor defaults, and the two conversions they needed

pH noise 0.02 (absolute); CH₄ ±1 % **absolute**, i.e. one percentage point of methane
content, not 1 % of the reading (`sd_abs: 0.01`, `cv: 0`); laboratory cv 3 % TS/VS, 5 %
COD, 8 % VFA, 5 % alkalinity. All marked `ASSUMED (lead's default)`.

Two figures were given per month and the model is a random walk, whose sd accumulates as
`s√t`, so `s = (per month) / √30 d`:

- **pH drift 0.05–0.1 pH/month** → `sd_per_sqrt_d` 0.0091–0.0183; the **midpoint 0.0137**
  (0.075 pH/month) is used, and the range is recorded in the file.
- **CH₄ drift 0.5 %/month absolute** → `sd_per_sqrt_d` **0.0009** fraction/√d.

Two sensors are **not** in the lead's list and keep the branch's assumptions, flagged:
**TAN** at cv 0.05 (a gas-sensing electrode, kept at the alkalinity/COD level) and the
**H₂ cell** at cv 0.15 with a 1.0 ppm floor. The 8 % VFA figure is applied to all four
speciated assays as well as to total VFA; valerate sits near the quantification limit, so
8 % is probably optimistic there and the file says so.

### 3. Feed bases, FOG and the overload threshold — approved as proposed

- Plant A's **cattle slurry moved onto the same Tisocco 2024 basis as the silage**
  (approved). This went beyond the literal wording of the #10 freeze, which named silage
  only, and was flagged as such: leaving slurry on the old basis dropped Plant A's OLR to
  1.17 kg VS m⁻³ d⁻¹, outside the published 1.4–2.1 band, and moving it restores 1.78.
- **FOG at 2.0 % TS** (approved), the anchor-derived value that replaced the assumed 10 %.
  The error and its detection are recorded in the **benchmark card**, `docs/benchmark_card.md`
  §5.1, at the lead's instruction: it is the clearest example the project has of the anchor
  catching a plausible design value that was wrong.
- **FOS/TAC overload threshold 0.40** (approved), the ~92nd percentile of the plant's own
  column.

### 4. Consequences in the tests

`tests/test_observation.py` now checks the tier properties as *tier* properties: the base
rates 8/4/2 %, the turnarounds 7/3/1 d and the cadences 90/30/30 d as declared; and,
observed, that on identical truth and the tiers' shared sensors Tier A loses ~4× as many
samples as Tier C, that the laboratory lag on a weekly assay is the tier's, and that the
pH probe's drift is reset on the tier's cadence — with only the cadence varied, so the
same stream and the same draws produce both walks, and the ratio of their rms offsets is
the √3 the reset interval predicts.

The conditional-missingness ratio is now **4** rather than the 2 the earlier entry's
test-sizing note quotes, because the online overload multiplier changed. Over forty seeds
the estimator gives 3.96 ± 0.07 (pH), 4.12 ± 0.07 (gas flow) and 3.92 ± 0.06 (CH₄), so it
remains unbiased; pooled over the twelve seeds the test uses, the standard error is ~0.12
and the 20 % tolerance is a ~6 sd bound.

**Alternatives.** Keep the per-sensor missingness block and set every sensor's base rate
from the tier at load time (rejected: the same number would then be written fifteen times
and could drift); make the multipliers tier-dependent too (rejected: the lead gave one
set, and an instrument's failure mode under foaming is not a function of how well the
plant is instrumented); keep the recalibration interval on the sensor and let the tier
override it (rejected: two places to look for one number).

---

## 2026-09-02 — Valerate assay carries 15 % plus a 0.05 g/L floor (the lead, on PR #11)

**Decision.** Answering the flag that 8 % is optimistic for valerate: `vfa_va` noise
becomes `cv: 0.15` with `sd_abs: 0.05` kg m⁻³ as valeric acid (0.05 g/L). The other three
speciated acids stay at 8 %. Valerate is the scarcest of the four and sits at the
quantification limit of the GC method, so it carries roughly twice the relative error of
the others *and* an absolute floor.

**Where the floor bites.** The two terms are independent draws (the total sd is
`√((v·0.15)² + 0.05²)`), so the floor dominates below about 0.33 kg m⁻³ — which is most of
the operating range for valerate. At a truth of 0.05 kg m⁻³ the relative term contributes
0.0075 and the floor 0.05.

**Open design item, flagged rather than decided.** With a floor of the same size as the
quantity, **17 % of reported valerate values are negative** (measured: 565 samples over
4,000 days, mean 0.0494, sd 0.0497, minimum −0.102). Three options, none of them free:

1. **Leave it** (what the branch does). A laboratory reporting raw instrument values below
   its limit of quantification does produce negatives, and a workflow that treats a
   negative concentration as a measurement rather than a signal has made a real mistake
   that the benchmark should be able to catch.
2. **Clip at zero.** Physical, but it biases the mean upward by ~4 % at these levels, and
   the bias is largest exactly where the acid matters least.
3. **Censor at the limit of quantification** — report `< LOQ` rather than a number. This
   is what a laboratory actually does, but it changes the record's *type* (a censored
   observation is not a float), so it is a schema change and a decision for the lead.

The branch takes option 1 unchanged and records the number here so the choice is visible.

**Test.** `test_relative_and_absolute_noise_are_independent_draws` is now parametrised over
the two sensors that declare both terms. The H₂ cell is the one that *discriminates*
between the independent and the correlated form (its terms are comparable, so the
correlated sum is 36 % larger); valerate's floor dominates, so the two forms differ by only
12 % there and the test checks the magnitude alone — but a floor applied as a relative term
or silently dropped still fails it.

---

## 2026-09-02 — Two-zone channels: a grab sample carries its own speciation

**Decision.** `channels_from_two_zone` took the *concentrations* from the effluent and the
*speciation* from the active zone, so under a bypass `alkalinity_total` (bicarbonate + VFA
anions) described the reactor while `vfa_total` described the sample, and `fos_tac` was a
ratio across two different liquids. `simulate_two_zone` now also returns
`effluent_derived` — `derived_extended` on the effluent composition with the shared
headspace's gas states — and each channel comes from where its instrument actually is:

| Where | Channels |
|---|---|
| the shared **headspace** | every gas channel (both gas-flow conventions, CH₄/CO₂/H₂) |
| the **probe in the reactor** | pH, free ammonia — the electrode hangs in the active zone, and free ammonia is the inhibition the biomass experiences |
| the **grab sample** (the effluent) | alkalinity partial and total, VFA total and speciated, COD, TAN, VS/TS, FOS/TAC |

`channel_series` now *raises* if given an `effluent` without an `effluent_derived`, so the
inconsistency cannot come back by a caller forgetting an argument.

**Why it mattered.** Measured at Plant C, 60 d, stagnant fraction 0.30 (bypass 0.06):
the sampled alkalinity is 4.1 % below the reactor's, the sampled VFA 54 % above it, and
FOS/TAC 61 % above the reactor's rather than the 54 % the hybrid gave. FOS/TAC is also
what raises the overload and foaming flags behind the missingness model, so a Level-6
mixing run was getting its stress flags from a quantity that was neither the sample nor
the reactor. At bypass 0 the two are bit-identical, which the test asserts.

**How it survived until now.** `channels_from_two_zone` was exported and had **no test**.
It has one now (`test_two_zone_channels_come_from_where_the_instrument_is`), covering the
degenerate case, the three sources under a bypass, and the raise.

**Also fixed in the same pass.** `ash_trajectory` documented that the flow "follows the
influent's declared `interpolation`" but interpolated it linearly regardless; only the
feed-ash series honoured the hold. Latent — the error is exactly zero whenever the output
times are the influent's own, which is every current call — but the docstring was a claim
the code did not keep. The flow now reads `influent.interpolation` like the feed ash does.

---

## 2026-09-02 — Independent review of PR #11: the VFA channels were 1000x too small

**Decision.** An independent review pass (fresh context, told to verify rather than trust
the PR's claims) found nine real defects. All are fixed on the branch. The one that
mattered is recorded here in full because it silently disabled the property this whole
component exists to deliver.

### The defect

`channel_series` computed every VFA channel as `kmol/m3 * kg/kmol / 1000`. The division
has no dimensional justification: `S_ac` is kg COD/m3, `VFA_COD_PER_KMOL["S_ac"]` is
64 kg COD/kmol, so the quotient is kmol/m3, and multiplying by `M_ACETIC` (60.05 kg/kmol)
already gives kg/m3. **1 kg COD/m3 of acetate is 0.93828 kg/m3 as acetic acid**, and the
code returned 0.00093828. The alkalinity term two lines below carries no such factor,
which is what makes the inconsistency visible on inspection.

### Why it was not merely cosmetic

FOS/TAC is total VFA over total alkalinity, so it was 1000x too small too, and the
condition flags that drive **conditional missingness** are thresholded on it:

| | as coded | corrected | anchor (Muscatine Dig1) |
|---|---|---|---|
| alkalinity_total | 2.556 | 2.556 | median 5.04 kg CaCO3/m3 |
| vfa_total | 5.65e-05 | 0.0565 | median 1.18 kg/m3 |
| fos_tac | 2.21e-05 | 0.0221 | median 0.23 |

At that scale `fos_tac` could never approach the 0.40 overload or 0.30 foaming thresholds
— a digester souring to 10 kg COD/m3 of acetate reached 0.003 — so `condition_flags`
returned all-`False` on every real run, the missingness model always used its base rate,
the §6.1 property that "instruments fail *during* the transients" never fired, and the
Level-4 `informative_missingness` fault was a no-op. None of it raised an error.

### Why the tests did not catch it

The test that claimed to check "the channel arithmetic against hand calculations"
re-implemented the formula: `assert vfa_ac == approx(ac_kmol * M_ACETIC / 1000.0)` is
`implementation == implementation` and passes under **any** global scale error, and
`assert fos_tac == approx(vfa_total / alkalinity_total)` restates the implementation line
verbatim and cannot fail at all. The other tests fed `fos_tac` in directly as a synthetic
array, so they never exercised the real channel. The hand calculations are now **literals**
(0.93828 kg/m3 per kg COD/m3), and a new test feeds the anchor's own VFA and alkalinity
columns through the formula and recovers the anchor's own FOS/TAC column, then shows the
0.40 threshold sits at the ~92nd percentile of the distribution the plant really visits.

### The realism gap this exposed, FLAGGED for the lead

With the units right, a **healthy simulated** digester sits at FOS/TAC 0.01–0.07 against
the plant's median of 0.23; even at 2.5x the declared feed, Plant B reaches only 0.15. A
converged ADM1 steady state carries far less residual VFA than a real plant, and a
titrimetric FOS over-reads true VFA. The threshold is still reachable (VFA 1.0 kg/m3 at
the anchor's median alkalinity crosses it, and the anchor exceeds that VFA on a third of
its days), but **the overload flag will fire on materially fewer simulated days than the
"~8 % of days" the anchor's own column implies.** Recorded in the config beside the
threshold. If the lead wants the simulated distribution to match the plant's, that is a
change to the feed catalogue or the kinetics, not to the threshold.

### The other eight, all fixed

1. **Sub-interval episode durations inflated the anchored flatline rates.** The mask lasts
   `max(1, round(duration/dt))` samples, so a declared 0.4 d episode on a daily sensor
   really lasted 1 d and the realised occupancy was 2.5x the anchor (5x for the 0.2 d gas
   meter). Durations are now declared in whole samples, the hazards carry the anchored
   occupancy directly, `SensorSpec` **rejects** a duration below the sampling interval, and
   the test measures the *realised* mask instead of the declared product.
2. **`scada_noise_statistics` marked one sample too many per flatline run** (`in_run[i-run
   : i+2]` spans `run+2` values where the identical values are `run+1`) **and dropped a run
   beginning at index 0** entirely (negative slice start). Re-measured: temperature
   0.0765 % (was quoted 0.08 %), gas 0.0144 % (was quoted 0.01 %). The config now carries
   the corrected figures. Also, a literal `NaN` parsed fine and was dropped without being
   counted, so `missing_fraction` could read 0 for a file full of them.
3. **`random_gaps` was not MCAR.** It scaled the base rate, which scales the stressed rate
   by the same factor, so every added gap was `overload_multiplier` times more likely under
   stress — exactly as informative as the originals, and indistinguishable from the
   Level-4 fault that exists to be the informative one. It is now an additive unconditional
   term, and a test measures the added gaps in and out of the stress window.
4. **`ph_electrode_drift` never produced its "drift-then-step" signature.** The injected
   ramp was applied after the intrinsic drift's recalibration reset and never reset itself,
   so a -0.01 pH/d fault ran monotonically to -1.7 pH over 200 d. A calibration fault is
   removed by a calibration: the ramp now resets on the tier's cadence, and the test
   asserts the sawtooth, its bound, and that an un-recalibrated sensor keeps the old
   behaviour.
5. **`cod_total` and `vs` silently excluded every extension state**, because those sit
   after the gas states and the liquid slice stops at 26. Negligible at a healthy steady
   state (X_sao ~ 1e-7) and material in the Level-5/6 ammonia scenarios, where growing SAO
   biomass *is* the signal. Extension components are now classified in three tables
   (COD-bearing, inorganic solid, neither) and a test asserts every component the
   extensions config declares appears in exactly one, so a new one cannot be forgotten.
   Precipitated calcite now counts towards TS and not VS, at 100.09 kg/kmol.
6. **A `saturated` flag could contradict its own reading.** A flatlined sample reports the
   previous value but kept its own pre-hold saturation flag, so the record could tell a
   workflow the instrument hit its range while showing a number inside it (16 occurrences
   over 40 seeds on a stepping truth). The flag is now held with the value.
7. **"The card and the code cannot drift apart" was not true.** `benchmark_card_rows()` was
   rendered nowhere and the card had no fault table. The card now carries the generated
   block between markers and a test compares it verbatim — it caught its first drift within
   the hour, when the two fault descriptions above changed.
8. **Smaller:** `sample_times` dropped the final sample when `horizon/interval` fell just
   below an integer in binary floating point; `observe` silently fabricated constant
   readings for a horizon beyond the run's last channel time (now raises); `faults or
   Default()` discarded an empty-but-seeded directive object because both classes define
   `__bool__` (now `is None`).

### Recorded, not fixed

`hazard_per_d` is typed as a fraction (`le=1`) though a hazard rate is not bounded by 1;
repeated observation faults on one sensor overwrite rather than compound, while the three
global scales multiply; `tool_failure` cannot name a tool other than the default;
`UnrecordedDelivery` truncates a fractional onset day; `condition_flags` is O(n^2) and is
most of the suite's runtime; a `flatlined` flag on the first sample is reported but nothing
is held. None changes a result today; all are listed here so the next session can pick them
up deliberately.

**Process note.** This was a fresh-context review of a branch this session largely wrote,
which is better than a self-review and still not an outside one. The reviewer was told to
verify arithmetic independently and to try to construct broken implementations that pass
each test; the three findings that mattered most came from exactly that instruction.

---

## 2026-09-03 — Duplicate observation model and fault injection: PR #11 canonical, PR #12 closed, three items salvaged

**What happened.** The observation model and the fault-injection API were built twice in
parallel: PR #11 (`claude/milestone-2-observation-fault-injection`, merged at b469317) and
PR #12 (`claude/milestone-2-observation-faults`, `sim/observe/` + `sim/faults/`, CI green,
closed unmerged). The second session branched from `main` at 2204dcf after confirming that
its stated predecessor (PR #10) had merged, and did not list the *other* open PRs. This is
the third collision of the same kind after "Duplicate ADM1 core" (#2 vs #4) and "Duplicate
plant layer" (#6 vs #7).

**Decision (by the lead).** PR #11 is canonical: it is merged and its configuration already
carries the lead's answers. PR #12 is closed. No design is re-decided. Three things it had
that `main` did not are salvaged into a small follow-on PR, adapted to #11's contract:

1. **The anchored sensor values are re-derivable on a fresh clone.**
   `tests/test_observation.py::test_anchored_sensor_values_are_rederived_from_the_scada_file`
   skips unless the git-ignored 88.8 MB `SCADA-raw.csv` is present — an anchor that only
   holds for whoever fetched it. `anchor/derived/muscatine-scada-window.csv.gz` (days
   240-300, three columns, biogas rounded to 1e-3 cfm, 629 KB, ODC-By with attribution and
   the parent's SHA-256) plus `anchor/derived/muscatine-scada-sensor-statistics.json` make
   the anchored **noise** re-derivable offline, and the config checkable against a
   committed derivation always. `scripts/muscatine_scada_observation.py` writes both.
2. **The Tier C online missing rate is measured, not assumed.**
3. **The temperature saturation range is the data dictionary's, and its floor is reached.**

**On (1), the window was chosen by measurement.** Candidate 60/90/120-day windows were
scored against the full year on the two anchored statistics using the tolerances the
existing test already applies. Days 240-300 reproduce the temperature noise *exactly*
(0.052418 degF -> 0.02912 K) and the gas cv to 0.0013 (0.0221 against 0.0208, tolerance
0.003). **What the window cannot carry is stated rather than smoothed over:** the flatline
occupancies are rare-event statistics — this window contains no stuck run of ten minutes
or more, and no 60-day window reproduces 0.00077 within 25 % — and the dropout rate is
unrepresentative over 60 days (18 of the record's 19 gaps fall in the first 90). Both stay
full-record figures in the JSON, checked against the parent when it is present.

**On (2), what "the anchor carries no dropouts" got wrong.** `sensors.yaml` and
`MissingnessPolicy` said missingness could not be anchored because the SCADA file is
pre-cleaned and "100 % finite". That is true of the file's *cells* and false of its *rows*:
`anchor.ingest_muscatine.scada_row_gap_statistics` finds **19 gaps in 347.8 d, 0.0966 % of
minutes missing, median 2 min, p90 9.8 min, longest 421 min**. The lead's ruling: that
measures **Tier C online and nothing else** — it is what a SCADA-equipped plant's online
instruments lose. Tier A and B (8 % and 4 %, manual logging) and every laboratory rate stay
assumed, and the tier structure stays. Implemented as a narrow
`MissingnessPolicy.base_rate_overrides[tier][kind]` consulted by `model_for`, so
`base_rate_by_tier` remains the contract and the exception is visible; a test asserts that
`("C", "online")` is the *only* cell that departs from its tier rate.

Two caveats are recorded beside the value: the providers deleted 485 rows they assumed
were power surges, so 0.097 % is the *published* record's dropout and a lower bound on the
plant's; and these sensors report a daily mean of the 1-minute record, which survives a
partial-day gap, so as a per-sample loss rate it is conservative in the same direction.

**On (3).** The range was assumed at 273.15-353.15 K while the file's data dictionary gives
85-150 degF for `D1/D2_TEMPERATURE`. The record sits **at** the 85 degF floor on 0.066 % of
its minutes, so the dictionary range is an observed limit, not a hypothetical one; the
config now carries 302.594-338.706 K.

**Consequences for #11's tests.** Two assertions changed with the contract, not around it:
the tier-property test now asserts exactly one measured exception rather than none, and the
observed-ordering test asserts the online A/C ratio is now more than 20x (it was 4x) while
the *laboratory* B/C ratio still carries the assumed 4 %/2 % structure. The
"without missingness" helper also clears the override, or Tier C online would keep losing
0.1 % of its samples in tests that ask for none.

**Alternatives.** Resolve #12's conflict and keep both (rejected: two observation packages
and two fault schemas); re-open the design questions #11 settled (rejected: the lead had
already answered them there); apply the measured dropout to every tier (rejected by the
lead: it is a SCADA-equipped plant's online figure and says nothing about manual logging
at a constrained plant).

---

## 2026-09-03 — The daily routine no longer launches component sessions

**Decision (by the lead).** The routine's launch authority is removed. It reviews,
subscribes, reports and salvages; it launches nothing. A component session starts only when
the lead sends `launch: <component>` to the coordinating session, after the previous
component's PR has merged. Every "reply to paste" goes to the coordinator, and the
coordinator relays a child session's questions. Recorded in `CLAUDE.md` under "Who starts a
component session", which is now the first section of the file.

**Reason.** Three of the first six components were built twice (#2/#4, #6/#7, #11/#12).
Each collision had the same shape: the routine launched a component because its plan said
so, while a session was already building it because a decision had reached that session
directly. The mitigation added after the first collision — "check the open PRs" in
`CLAUDE.md` — did not stop the third, because by the time anyone looks the duplicate work
has usually started. Removing the authority removes the failure mode at a cost of one
message per component.

**Alternatives.** A stronger check in the session brief (rejected: it is the same
mitigation that already failed twice); a lock file or a registry of in-flight components
(rejected: more machinery than a one-line message, and it would still depend on every
launcher consulting it).

---

## 2026-09-03 — The measured dropout is a plant-level process, not a per-sensor rate

**Decision (by the lead), on the coordinator's finding.** PR #13 carried the Muscatine
row-dropout measurement into `MissingnessPolicy.base_rate_overrides[C][online]`, i.e. as
an independent per-sensor rate. That imports the *number* and discards the *structure*.
A plant-level historian dropout process is added instead, shared across all online sensors
at a tier; **per-sensor independent missingness is unchanged**, and the two compose.

### What the anchor actually shows, and why the shape matters

The SCADA file is 100 % finite in its **cells** — which is why missingness was first
recorded as unanchorable — but whole **rows** are absent. Measured independently by the
coordinator before the ruling, and again here:

| | |
|---|---|
| gaps | **19** over 347.8 d |
| minutes missing | **484** = **0.0966 %** of the record |
| lengths | median 2 min, p90 9.8 min, longest **421 min**; all 19: 1,1,1,1,1,2,2,2,2,2,3,3,4,4,5,7,9,13,421 |
| blank cells in either channel | **0** — every dropout is a whole row |

Because whole rows go, both online channels lose **exactly the same minutes**. As an
independent per-sensor rate `p`, two online sensors lose the same sample with probability
`p² = 9.3e-7`; in the record it is `1`. Six orders of magnitude, in exactly the structure
§6.1 exists to test — a workflow that sees every online channel drop out together learns
something quite different from one seeing scattered independent gaps.

### The design

`HistorianDropout` (`sim/observation/schema.py`), declared in `configs/observation/sensors.yaml`:

- **`rate_by_tier`** — C **0.000966** (MEASURED, `measured_tiers: [C]`); A **0.010** and
  B **0.005** (ASSUMED). Tiers A and B have no historian: their online readings are logged
  by hand, so the shared failure is "nobody wrote the readings down that day" — coarser and
  rarer than a per-instrument fault, hence well below the 8 %/4 % per-sensor rates.
  **FLAGGED: nothing anchors the A and B figures.**
- **`gap_lengths_min`** — the record's own 19 outages. Carried rather than collapsed to a
  mean because it decides how many samples one outage costs: every observed outage is under
  a day, so on the daily schedule an outage costs exactly the sample it lands on and the
  realised loss fraction equals the declared rate. On an hourly schedule the 421-minute
  outage would cost seven samples, and `spans_multiple_samples()` says so.
- **Laboratory assays are untouched** — a grab sample does not pass through the historian.
- **Additive, not a replacement.** An instrument can fail while the historian is up, and
  the historian can fall over while every instrument is healthy. Online loss at a tier is
  `1 − (1−per_sensor)(1−shared)`: **8.92 % / 4.48 % / 2.10 %** at A/B/C against the frozen
  per-sensor 8 / 4 / 2 %. **FLAGGED: this moves the frozen totals, by design.**

**Its own random stream** (rule 4), derived from the run seed by `HISTORIAN_STREAM_OFFSET`
(re-keyed under ruling 7, 2026-09-14, to `SeedSequence([seed, HISTORIAN_STREAM_KEY,
block])`, one stream per block, like a sensor's)
and drawn once per run before any sensor, on the tier's finest online schedule. Deriving it
by an offset rather than by splitting the run seed leaves every sensor's own draws
bit-identical to what they were before the historian existed — an archived run is not
silently re-rolled by adding a component.

### Consequences

`base_rate_overrides` is removed: with the measurement in its proper home there is no
exception to the tier structure, and `model_for` is a plain lookup again. Four of #13's
tests move back with it — the tier-property test asserts no cell departs from its tier
rate, and the observed A/C ordering is the composition `4.25`, not the bare `4.0` and not
`>20`. Two new tests carry the property that motivated all this: with only the shared
process active, `temperature.missing` and `gas_flow.missing` are asserted **array-equal**
(the same days, not merely the same rate), the laboratory assay loses nothing, and the
joint loss rate is >100× what independence would give.

**Alternatives.** Keep the override as well as the process (rejected: double-counts, and
preserves the misattribution); model the outage as a per-sensor rate with a correlation
parameter (rejected: one shared series is the physical object, and a correlation
coefficient would be a free parameter nothing anchors); give Tiers A and B no shared
process at all (rejected: manual logging fails in exactly this correlated way, and
declaring the rate zero would assert something stronger than "unmeasured").

**Addendum, same day — the composite totals are ACCEPTED as the effective online loss.**
The lead's answer on the two items flagged with the ruling: the Tier A and B shared rates
(0.010 and 0.005) **stay as assumed**, and the composite totals are **accepted and recorded
as the effective online loss, with no renormalisation**:

| Tier | per-sensor (frozen) | shared | **effective online loss** |
|---|---|---|---|
| A | 0.08 | 0.010 | **8.92 %** |
| B | 0.04 | 0.005 | **4.48 %** |
| C | 0.02 | 0.000966 | **2.09 %** |

The per-sensor rates are unchanged at the frozen 8/4/2 %. The totals are higher because a
second, real failure mode was added — not because a rate was re-tuned — and renormalising
them back to 8/4/2 % would make the historian free, which is the opposite of modelling it.
Laboratory assays never pass through the historian, so their loss remains exactly the
per-sensor tier rate. Recorded in `configs/observation/sensors.yaml` beside the process and
pinned by `test_the_effective_online_loss_is_the_recorded_composite`, which asserts both
the declared inputs and the loss a 6,000-day run actually shows.

---

## 2026-09-03 — The run harness: `runs/<id>/`, the redacted manifest, and where the code lives

**Decision.** `sim/run/` builds a run and writes it; `state/` reads one back for a
workflow. The split is the rule-1 boundary made structural rather than procedural.

| Module | Owns |
|---|---|
| `sim/run/layout.py` | the directory contract (`truth/`, `observations/`, `manifest.json`, `calls.jsonl`) and the opaque run id |
| `sim/run/seeds.py` | one seed per stochastic component, in a fixed documented order |
| `sim/run/manifest.py` | the complete manifest **and** the projection a workflow sees |
| `sim/run/notes.py` | the operator's log, including the Level-8 adversarial note |
| `sim/run/artifacts.py` | two writers: one for truth, one for observations |
| `sim/run/harness.py` | `generate_run`, wiring generator → truth model → channels → tier mask |
| `sim/run/matrix.py` | the §7 generation matrix and its CLI |
| `state/provenance.py` | the append-only `calls.jsonl` (CLAUDE.md rule 3) |
| `state/run_view.py` | the workflow-facing loader |

`sim/run/__init__.py` deliberately does **not** import the harness, so that
`state.run_view` can import `PublicManifest` without dragging in the module that knows how
to write hidden truth.

**The manifest is redacted, not truncated.** The task specification for this session asked
for a manifest carrying "scenario id, plant, tier, seeds, config versions, git SHA, and the
declared fault layers", and for `workflows/` to be able to read it. Those two cannot both
hold literally: the scenario id names the row of the ladder, the fault layers *are* the
uncertainty class §6.7 B scores, and the seeds would let a workflow re-run the generator
and read the answer off its own copy. Proposal §10 anticipates precisely this ("agents leak
information via prompts (e.g. scenario names) ... scenario IDs randomised; agents never see
YAML").

So `runs/<id>/manifest.json` is written **complete**, as asked, and `state.run_view` returns
`PublicManifest` — run id, plant, tier, horizon, seasonal phase, config versions, git SHA,
harness version. The projection is built by naming the public fields rather than by deleting
the secret ones, so a field added to the manifest is invisible to a workflow by default
instead of leaking until someone remembers the deny-list; `REDACTED_FIELDS` lists the rest
and a test asserts the two partitions cover the manifest exactly.

**The run id is opaque.** `run_<12 hex>`, a hash of (scenario, plant, tier, seed, replicate).
A directory called `S2-03-PB-TA` would reintroduce the §10 leak the moment a path appeared
in a prompt. It is still deterministic, so regenerating a cell overwrites its own directory;
`runs/index.jsonl`, at the root of the store rather than inside any run, maps ids back to
cells for the evaluator.

**The loader cannot name hidden truth.** `state.run_view.RunView` is rooted at
`runs/<id>/observations/` and resolves every caller-supplied path against that root,
requiring the result to stay inside it. `"../truth/faults.json"`, an absolute path and a
symlink out of the tree all fail identically with `TruthAccessError`; `RunView.files` lists
only what is inside. `tests/test_truth_isolation.py` drives all of that on a real generated
run and first asserts that the truth *is* on disk, so the refusals cannot pass by there
being nothing to find.

**Alternatives.** Put the loader in `tools/` (rejected: the registry is a later milestone
and its design should not be pre-empted by a file loader). Write two manifests, a public one
beside a private one (rejected: two files that must agree is a drift risk, and the
projection is one function). Keep the run id readable and rely on the driver to rename
(rejected: a leak that depends on a future component doing something is a leak).

---

## 2026-09-03 — The published R&J 2006 steady state moves into `configs/`

**Decision.** `configs/adm1/initial_state_rj2006.yaml` carries the Rosen & Jeppsson (2006)
Table-5 steady state, and `sim.adm1.load_initial_state()` reads it.

The only copy was in `scripts/adm1_candidates/common.py`, which is disposable probe code
(decision 2026-09-02, "Disposable code lives in `scripts/`"), so `sim/` may not import it.
The numbers are unchanged and `tests/test_run_harness.py` asserts the file and the probe
module agree state for state, so the transcription cannot drift. It is not a design value
and it is not the initial state of any scenario: only the burn-in starts there.

---

## 2026-09-03 — A scenario starts on a running digester: the burn-in

**Decision.** The harness integrates the plant's own median recipe for 200 d from the
published steady state and starts the scenario from the state that reaches
(`configs/runs/harness.yaml`). Starting a scenario at a textbook steady state would make the
first weeks of every run a start-up transient no fault caused, and the Level-4
mis-initialised-biomass row would be indistinguishable from it; the Level-4 multiplier is
applied to the burn-in state, which is what makes it a mis-initialisation of *this* digester.

`X_sao` is seeded at 0.01 kg COD/m3, because syntrophic-oxidiser growth is proportional to
the biomass present and a run started at exactly zero stays there for ever — which would
make the SAO extension silently inert in the very scenarios it exists for. Measured: it
washes out on Plants B and C (to ~1e-7 and ~1e-5) and establishes on Plant A, so the seed
does not decide the outcome, it only makes the outcome possible.

---

## 2026-09-03 — Burn-in length, and Plant A's SAO succession — FLAGGED for the lead

**Measured.** 200 d is a converged steady state on Plants B and C: a further 100 d moves no
state above 1e-3 kg COD/m3 by more than 0.02 %, pH by <0.0005 and the gas rate by <0.001 %.

**On Plant A it is not, and lengthening it would break three scenarios.** Plant A's free
ammonia (185–190 mg NH3-N/L) is inside the pathway-shift window, so the plant undergoes a
slow succession from acetoclastic methanogenesis to syntrophic acetate oxidation. It
completes only at ~800 d, and at that point the acetoclastic methanogens have washed out
entirely:

| burn-in | X_ac | X_sao | effect of doubling `K_I_nh3` for 120 d |
|---|---|---|---|
| 200 d | 0.53 | 0.54 | gas +2.2 %, acetate −19 % |
| 400 d | 0.027 | 0.95 | gas +0.2 %, acetate −1.5 % |
| 800 d | 4.6e-5 | 0.97 | gas +0.002 %, acetate unchanged |

All three ammonia scenarios (S5-01, S6-01, S7-02) would be **inert** from a converged Plant
A state: there is no acetoclastic population left for a change in its inhibition constant to
act on. 200 d leaves the mixed community those rows are about, so the harness burns in to a
deliberately mid-succession state on Plant A and says so.

**This needs the lead's decision.** Three readings, none of which this session took:

1. The SAO uptake rate is too fast. `k_m_sao` was raised to the literature fast end
   (`mu_max` 0.16 d⁻¹) by the lead's own answer of 2026-09-02 precisely so SAO would
   establish inside a 180-d scenario. It now establishes so well that it excludes the
   acetoclasts entirely.
2. Plant A's ammonia envelope is too high for a co-existence regime.
3. Plant A is *defined* as a digester in transition, and the ammonia rows are scored on a
   plant that is not at steady state. This is what is implemented, with the succession
   recorded rather than hidden.

`tests/test_run_harness.py::test_plant_a_is_mid_succession_at_the_burn_in_length_and_that_is_the_point`
fails if someone "fixes" the convergence by lengthening the burn-in.

---

## 2026-09-03 — Plant B sours on 5 of 12 seeds — BLOCKING finding, FLAGGED for the lead

**Measured.** Under the frozen feed catalogue, plant configuration and influent generator,
a clean Level-0 run on **Plant B** acidifies within 180 d on **5 of 12** base seeds: median
pH 4.6–5.0 with 0.0–0.36 methane, against 6.9–7.1 and 0.65–0.70 on the seeds that survive.
Plants A and C are 12 of 12 sound.

**It is not the harness.** It reproduces with the declared geometry (no hidden volume
error), the published initial state (no burn-in), no extension influent and no faults: five
of twelve small integer seeds crash the same way. It is not driven by the mean load either —
seed 1002 is sound at OLR 2.66 kg VS m⁻³ d⁻¹ and seed 1006 sours at 1.77 — but by *runs of
consecutive high-load days*.

**Why the existing tests did not catch it.**
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings` tests exactly one
seed (11), which is one of the seven that survive. A single-seed plausibility check on a
stochastic generator cannot see a 40 % failure rate.

**The most likely cause, for the lead.** `configs/plants/plant_B.yaml` describes the
high-strength waste as "trucked deliveries **blended in a 65,000-gal tank**", and the FOG
likewise as trucked. The influent generator feeds truck arrivals straight to the digester on
the day they arrive; the real plant damps them through a buffer with roughly six days of
hold-up (246 m³ against ~42 m³/d of HSW, plant total). The physical feature is documented in
the frozen plant config and not implemented in the frozen generator, and its absence is
exactly what would turn a run of arrivals into an acid pulse.

**Not fixed here.** Adding a buffer tank changes the frozen influent generator and would
move every generated cell and every anchored delivery statistic; that is the lead's call.
This session instead:

* labels every generated run sound or soured (`sim.run.harness.assess_health`), writes the
  verdict to `runs/<id>/truth/geometry.json`, and reports the counts per cell in the
  generation report;
* measures and reports the rate in `docs/g1_anchor_report.md`;
* pins it in `tests/test_g1_anchor.py::test_plant_b_sours_on_a_material_fraction_of_seeds`,
  which fails **if the rate goes to zero as well as if it gets worse**, so a fix must come
  with an update to the record.

**Consequence for gate G1.** The gate's literal criterion — every scenario generates, truth
logged separately, influent statistics inside the declared tolerance — is met. The digester
those scenarios are staged on is not yet reliable on Plant B, and the benchmark is not usable
for the factorial until it is.

---

## 2026-09-03 — Level-8 scenarios carry an underlying fault

**Decision.** S8-01 (tool failure) and S8-02 (adversarial log note) each inject the
Appendix-B gas-meter scale error alongside their workflow-layer fault, and carry the truth
label `sensor`.

The §6.3 table gives Level 8 no truth label ("—"), but the frozen scenario schema requires
at least one and forbids `none` above Level 1. Rather than weaken the schema, the constraint
was taken as a design hint, and it is a good one: "did the workflow fall back correctly?"
needs something to fall back *to*, and "the note asserts a false cause" needs a true cause to
be false about. Both rows are therefore scored on two axes — the sensor attribution, and the
handling of the failed tool or the false note.

**Alternative.** Relax the schema so `none` is admissible at Level 8 (rejected: it is frozen,
and a Level-8 row with no diagnostic task is a weaker scenario, not a purer one).

---

## 2026-09-03 — Every run carries operator notes

**Decision.** `configs/faults/log_notes.yaml` holds a catalogue of true, mundane operator
notes, and `sim/run/notes.py` places a few of them (Poisson, ~6 per 100 d) in **every** run
at seeded random days. The Level-8 adversarial note is one more entry, authored by a
"process_engineer" rather than an "operator".

If a notes file existed only in the adversarial run, its presence would be the answer and
the scenario would test nothing. The benign notes are written to be true of the run and
useless for diagnosis — maintenance, staffing, weather — so a workflow that reads them
learns nothing the record does not already show.

The note texts are DESIGN values with no anchor: no open dataset of operator log notes
exists. The adversarial note is written to be a plausible *misdiagnosis* of the fault
actually injected, pointing at the hydrolysis constants, so following it produces exactly
the false kinetic drift of §6.7 B.

---

## 2026-09-03 — Per-tier answer keys do not exist — FLAGGED for the lead

**The gap.** The frozen scenario schema carries one `correct_conclusion` per scenario. The
matrix runs most scenarios at all three tiers, and at least one row's fault is **invisible**
at the lowest tier: S2-02 flatlines the methane analyser, which is a Tier-B instrument, so at
Tier A there is nothing to observe and the run is indistinguishable from Level 0. Its answer
key names `ch4_fraction`, which is the Tier-B/C answer and is wrong at Tier A, where the
defensible conclusion is that no fault is detectable.

**Not fixed here** (the schema is frozen). Each affected scenario says so in its `notes`.
Three ways out, for the lead: make `correct_conclusion` a mapping keyed by tier; exclude a
scenario from the tiers where its fault is unobservable; or keep one key and score Tier-A
runs of such rows on correct abstention instead of attribution — which is arguably the most
interesting of the three, since "the instrument that would have shown you is not installed"
is a real situation on a constrained plant.

---

## 2026-09-03 — Scenario magnitudes, seeds and budgets

**Magnitudes.** Every value is inside the admissible range `sim/faults/schema.py` declares,
and the reason for each is in the scenario file's own header comment rather than here. The
ones that are judgement calls: `sensor_noise` and `random_gaps` at 2.0 (a doubling, the
smallest unambiguous departure from the declared instrumentation); `ph_electrode_drift` at
−0.01 pH/d (~4× the healthy electrode's own 0.0025 pH/d, giving a 0.30 pH sawtooth at the
monthly recalibration cadence and 0.90 at the quarterly one); `feed_mislabelled` at a
Dirichlet concentration of 5.0 (3–8× wider than the feeds' own 30–300, so a batch genuinely
unlike its label); `unrecorded_delivery` at 3 medians (one median is indistinguishable from
the generator's own background of unlogged trucks); `moisture_drift` at −30 % (a season, well
outside the generator's own few-per-cent day-to-day TS process); `biomass_misinitialised` at
0.25 (0.8 recovers inside a fortnight and is indistinguishable from Level 0; below ~0.1 the
run becomes a souring scenario rather than a state-estimation one); `informative_missingness`
at 3.0; `ammonia_inhibition_shift` at ×2.0 *upwards*, the ladder's own "after acclimation";
`hydrolysis_regime_change` at ×0.6, a coarser feed; `imperfect_mixing` at a stagnant fraction
of 0.30, the value whose load-proportional gas deficit was already measured on 2026-09-02;
`tool_failure` at probability 1.0, because the property under test is the response to a
failure and not its frequency.

**Seeds.** `1000 + 10 × level + index`, so S2-03's seed is 1023. Unique, explicit and
readable; nothing depends on the arithmetic.

**Budgets — a proposal, flagged.** The proposal fixes only the Appendix-B example
(4,000 simulator evaluations / 90 min / 2 assay units). The library uses three bands:
Levels 0–2 at the Appendix-B figures, Levels 3–5 at 6,000/120/4 and Levels 6–8 at
8,000/150/6, on the grounds that a compound or structural row needs more evidence-gathering
before it can conclude. §7 requires the budget to be identical across workflows *within* a
cell, which this respects. If the lead prefers one envelope for the whole ladder, that is a
one-line change per file.

---

## 2026-09-03 — Plant A's ammonia scenarios run at all three tiers

**Decision.** §7 pins Tier A for Plant A's "Level 2–5 scenarios" and is silent on the tier of
the three ammonia rows. They run at all three tiers.

An ammonia-inhibition shift and an omitted oxidative pathway are diagnosed through TAN, total
and speciated VFA and off-gas hydrogen; Tier A carries none of them. Confining those rows to
Tier A would leave the only plant that can host them unable to answer them. The Level-2 to
Level-5 subset stays at Tier A as §7 says. This adds 6 cells (S5-01 at B and C, S6-01 and
S7-02 at B and C) and Plant A still contributes no rows to the factorial.

---

## 2026-09-03 — Gate G1's tolerances are declared before the comparison

**Decision.** `anchor/compare_generated.py` holds `TOLERANCES` as a frozen table with a
rationale per row, written before anything was measured, and `tests/test_g1_anchor.py`
recomputes `docs/g1_anchor_report.md` and compares it verbatim.

Most bounds are **inherited** rather than invented: the per-stream delivery bounds are the
ones `tests/test_generator.py` already applies (rel 0.15, rel 0.30, abs 0.04) and the biogas
band is the one `tests/test_plausibility.py` applies (0.6–1.5). A test reads those literals
out of the test files, so widening one "for consistency" fails.

**One procedural change is recorded rather than hidden.** The output statistics were first
measured on a single Level-0 run at the scenario's own seed. That seed turned out to be one
of the Plant B seeds that sours, so every output row failed for the wrong reason. The
measurement was widened to a declared twelve-seed panel with each run labelled sound or
soured, and the comparison is made across the sound runs with the soured fraction reported
beside it. **The tolerances were not touched when this changed.**

**Three rows fail and are asserted to fail.** `vfa_median` (0.054 against 1.178 kg m⁻³,
ratio 0.05), `alkalinity_median` (2.78 against 5.04 kg CaCO₃ m⁻³, −45 %) and
`fos_tac_median` (0.021 against 0.232, ratio 0.09) are one finding from three sides: a
converged ADM1 carries far less residual VFA than a real digester, and less alkalinity with
it. It is the realism gap the PR-#11 review recorded (it predicted 0.01–0.07 for FOS/TAC;
the panel gives 0.017–0.027). The test pins the failure *and its size* in both directions,
so closing the gap fails a test and forces the record to be updated, rather than letting a
quiet tuning pass unnoticed.

**And one consequence that is worse than a failed row.** The overload flag fires when
FOS/TAC exceeds 0.40, and across the panel it is **bimodal**: five of the seven sound runs
never raise it, the other two raise it on 8.6 % and 9.3 % of days (about the plant's own
~8 %), and every soured run raises it on 63–100 %. So conditional missingness — the §6.1
property that instruments fail during the transients that identify the process — has
nothing to act on in most healthy Plant B runs, and the Level-4 `informative_missingness`
row (S4-02) is a near-duplicate of Level 1 there. `docs/g1_anchor_report.md` §6 lists the
five things that would close the underlying gap and which two of them actually change the
answer.

---

## 2026-09-03 — RULING 1 (the lead): Plant B's blend tank is part of the plant contract

**Decision.** `configs/plants/plant_B.yaml` declares an `equalisation` block — a well-mixed
buffer of 123.02 m³ (65,000 gal for the plant, halved for the modelled unit) holding the
high-strength waste — and `sim/plants/equalisation.py` implements it. The influent
generator is **untouched**, as ruled: the buffer is what absorbs the swings.

**Reason.** The plant's own description had always said the HSW is "trucked deliveries
blended in a 65,000-gal tank" and the simulator had never implemented it, so arrivals
reached the biomass as acid pulses. It is **declared, not hidden**: a workflow is told the
tank exists, its size and which feeds pass through it, exactly as it is told the digester's
volume. What stays hidden is the composition of what was delivered into it.

**The model.** One continuously stirred tank: `dV/dt = q_in − V/τ` and the same for each
component mass, integrated exactly over a day with the arrivals held. Drawing in proportion
to level is what a level-controlled pump does and makes the tank unconditionally stable —
it cannot run dry or overflow and passes exactly what it receives in steady state. The
outflow is computed *from* the balance rather than alongside it, so mass closes to machine
precision, and at zero volume it reduces to a pass-through exactly (tested).

**The buffered share is taken as a residual** — the whole influent minus the direct feeds'
own flow and load — so the tank never has to know the composition of what is in it,
including a mislabelled batch's redrawn fractionation. The direct feeds are reconstructed
from the catalogue, so a fault that altered *their* composition would break that; the code
refuses rather than silently mis-reconstructing.

**FOG is not buffered.** It is trucked too, but the plant description names a tank only for
the HSW, and this is the reading closest to the evidence. Widening it is a one-line change.

**Measured, and it matters for the diagnosis.** On the twelve-seed panel, with the other
correction held back:

| | no tank | with tank |
|---|---|---|
| original strong cations | 7/12 sound, min pH 4.50 | 12/12, min pH 6.53 |
| calibrated strong cations | 12/12, min pH 7.06 | 12/12, min pH 7.13 |

**Either change alone is sufficient**; both together give the most margin. Stated plainly,
as the coordinator asked: **the calibrated feed with no tank at all is already 12 of 12
sound**, so the alkalinity calibration removes the souring on its own — and so does the tank
on its own, on the uncalibrated feed. Neither is credited with the other's work. The tank is
a plant-contract correction justified by the plant's own description that also happens to be
sufficient; the calibration is an anchor-driven correction that also happens to be
sufficient. On the twenty-four-seed panel with both: **24 of 24 sound**, pH 7.24–7.40,
methane 0.70–0.73, met with margin rather than scraped. The sound/soured labelling stays as
instrumentation, as ruled.

**Alternatives.** Buffer FOG as well (not chosen: the anchor names a tank only for HSW);
model the tank as a fixed-outflow surge vessel (rejected: it can run dry or overflow, and
needs a control law the plant description does not give); re-tune the generator (forbidden
by the ruling, and wrong — the arrivals are anchored data).

---

## 2026-09-03 — RULING 2 (the lead): Plant A declares an adapted inhibition constant

**Decision.** `PlantConfig` gains an `adaptation` block; Plant A declares
`K_I_nh3 = 0.02 kmol N/m³` against the ADM1 default 0.0018; Plants B and C declare nothing
and keep the default. The 200-d burn-in workaround and its guard test are **gone**; the
burn-in is now 400 d and converges on all three plants.

**Reason.** ADM1's default is a sewage-sludge community's. A digester that has run for
years at a digestate TAN above 3 kg N/m³ does not have that community, and modelling the
acclimation as a **plant property** is what lets Plant A hold a stable steady state instead
of being caught mid-washout.

**Why the bottom of the ruled range and not its midpoint.** Measured: the
`ammonia_inhibition_shift` magnitude range is 0.1–10 (frozen), the acetoclastic/syntrophic
exchange point is at K_I ≈ 0.003, and 0.02 × 0.1 = 0.002 clears it while 0.035 × 0.1 =
0.0035 does not. From the midpoint, the largest admissible loss of adaptation produces no
pathway shift at all. 0.02 is the only part of the ruled range from which the frozen
magnitude range can express a full de-adaptation.

### What could not be delivered, and why — FLAGGED

**Coexistence is impossible, and it is not a parameter problem.** The ruling asked for a
steady state with both acetoclasts and SAO present. They compete for one substrate, so one
always excludes the other; measured, below K_I ≈ 0.003 SAO wins outright and above it the
acetoclasts do, at both a constant and the stochastic feed. There is **no** adapted K_I in
0.02–0.05 at which both are present.

**The ruling's fallback has the wrong sign.** Reducing `k_m_sao` towards 3.0 makes SAO
weaker, which moves the exchange point *down* and makes coexistence harder, not easier.
Measured at k_m_sao 3.0: at K_I 0.003 the acetoclasts already win outright, where at 4.0
both were still present. `k_m_sao` has therefore **not** been changed.

**So the rows are staged as transitions, which is the ruling's other half and does work.**
S5-01 and S7-02 now apply a ×0.1 loss of adaptation at day 120. Measured through the full
harness: S5-01 takes acetate from 0.045 to 4.30 kg m⁻³ with X_ac 1.09 → 0.84 and X_sao
7.5e-5 → 0.15; S7-02 gives a residual that *grows* as the truth reroutes its acetate
through a pathway the fitted model does not have. Both are strong, correctly-signed rows.

**S6-01 is inert and needs a decision.** It is the pure structural omission with no
transition by construction, so at an acetoclastic baseline the truth's SAO carries no flux
and omitting it produces no residual. Three ways out are written into the scenario file:
(a) set Plant A's adapted K_I to ~0.003, the exchange point — outside the ruled range and
structurally fragile, being the knife edge of a competitive exclusion; (b) give the row the
same transition and accept a `structural + parameter` label, at which point it duplicates
S7-02; (c) rescore it as an **abstention** row — the fitted model omits a pathway carrying
no flux, so the correct conclusion is that no structural residual is detectable. This
session recommends (a) or (c) and has changed nothing pending the answer.

**Baseline TAN is 3.1–3.7 kg N/m³**, above the 2.3–2.8 the ruling named but inside
Tisocco et al. 2024's published 2.3–4.3. Nothing was adjusted to move it.

---

## 2026-09-03 — One change beyond the rulings: the feed re-seeds syntrophic oxidisers — FLAGGED

**Decision.** `configs/runs/harness.yaml` adds `influent_extension_states: {X_sao: 1e-4}`,
a trace of syntrophic oxidisers in the feed.

**Reason, and it is the ruling's own goal that requires it.** ADM1 has no immigration term:
a population that reaches zero can never return, however favourable conditions become. With
Plant A adapted, its oxidisers wash out to ~1e-8 during the burn-in, and a loss of
adaptation then produces **no pathway shift at all** — measured, acetate simply accumulates
to 1.4 kg m⁻³ while nothing grows to consume it, and the Level-6/7 structural rows stay
inert. With the term, the same transition takes X_sao from 7e-5 to 0.60 kg COD m⁻³ and the
acetoclasts from 1.2 to 0.46 in 240 d.

It is physically the right correction rather than a fudge: syntrophic acetate oxidisers are
continuously re-introduced with the substrate and in a real digester are never absent, only
rare. At 1e-4 kg COD m⁻³ it is ~1e-5 of the smallest ADM1 biomass state — far too small to
matter anywhere it is not selected for, which the measurements confirm.

**It is not a kinetic change** and so does not trespass on ruling 3, but it is a truth-model
addition beyond the letter of ruling 2 and is flagged here, in the config beside the value,
and in the PR.

---

**Correction, 2026-09-10 (F2 check; no ruling needed, a factual correction).** The figure
above — "the same transition takes X_sao from 7e-5 to 0.60 kg COD m⁻³ and the acetoclasts
from 1.2 to 0.46 in 240 d" — is **not reproducible**. Run through the harness at S7-02's and
S5-01's own seeds in worktrees of `42bbe8e` (the commit that recorded it, with the reseeding
term in place), `9db569b`, `4a022e8`, `56aeceb`, `fd76983`, `39d0e14` and the current tree,
each with its own package on the path, the transition ends at 240 d with X_sao 0.154 and
X_ac 0.839 (S5-01) and X_sao 0.090, X_ac 1.129 (S7-02) on every tree through 2026-09-09,
and X_sao 0.092 / X_ac 0.934 and X_sao 0.039 / X_ac 1.171 on the current feed. The recorded
number cannot be traced to a committed state; a different seed, burn-in or constant at the
time is the likely explanation. What the reseeding term does buy is real and stands: SAO
*grows in* behind the inhibited acetoclasts (from 7e-5 to 0.04–0.15 rather than staying at
zero), reaching 9.0 % (S5-01) and 3.2 % (S7-02) of the acetate-consuming biomass by day 240
on the current feed — 1.2 % / 0.4 % at 200 d, 3.6 % / 1.0 % at 220 d — while acetate rises
30–100× after the onset and stays there. The scenario headers, the harness config note and
the truth-side Plant A record carry the measured numbers as of this date. What the S7-02
structural half is worth at a few per cent of the flux is with the lead
(`docs/f2_horizon_report.md`, §6 and §9).

## 2026-09-03 — RULING 3 (the lead): feed strong cations calibrated to the anchor's alkalinity

**Decision.** The Muscatine feeds' `s_cat` is calibrated to the anchor's own digester
alkalinity: primary sludge and thickened WAS 0.04 → 0.05, high-strength waste 0.03 → 0.225
kmol m⁻³, FOG unchanged. `s_an` and **inert-N are untouched**. No kinetic parameter moved.

**Reason and result.** The anchor measures alkalinity in the digester (median 5.04 kg
CaCO₃ m⁻³) and the simulator produced 2.78 — an under-buffered digester, which is exactly
one that acidifies under a load pulse. After calibration: alkalinity **5.12** and pH
**7.29** against the plant's **7.27**. Both anchored quantities land together, which is the
sign of a physically coherent calibration rather than a fitted offset. The
`alkalinity_median` row now passes its declared tolerance.

**What the anchor does and does not fix.** It constrains the **flow-weighted** cation excess
of the blend, not its split between streams; the split is an assumption, stated as such:
nothing on FOG, a modest rise on the sludges (~1,500 mg L⁻¹ as CaCO₃ in the liquor, the
upper end for thickened municipal sludge with recycle), and the remainder on the industrial
stream, on the grounds that clean-in-place caustic is the usual source of alkalinity in food
and beverage waste and that this stream carries 137 kg COD m⁻³.

**Inert-N was available and not used**: `s_cat` alone reaches the anchor, and inert-N
carries the deliberate truth/fitted mismatch of 2026-09-02 that the benchmark exists to
expose.

**Consequence, reported not hidden.** FOS/TAC falls from 0.021 to 0.013 against the
anchor's 0.232, because the denominator is now right and the whole discrepancy sits in the
numerator where it belongs. The coordinator's sweep predicted exactly this and instructed
that it be noted rather than compensated for; it is. The overload flag now fires on no day
at all in most sound runs and on 3.3 % in the worst, so the Level-4 `informative_missingness`
row is close to a duplicate of Level 1. **The 0.40 threshold has not moved.**

**Addendum (same day): the gap list exists and rules out kinetics.** `docs/vfa_gap.md`
(branch `claude/vfa-gap-list`) measured that **no value of `k_m_ac` closes the VFA gap** —
×0.40 gives VFA 0.183 kg m⁻³ at pH 6.95, ×0.35 gives 10.08 at pH 4.60, the model is
**bistable**, and the anchor's 1.18 lies *between* the branches; `k_hyd` at ×2 and ×4
changes residual VFA not at all. The gap is a measurement-convention question and is with
the lead. An earlier draft of `docs/g1_anchor_report.md` §6 proposed a lower `k_m_ac` or a
higher `K_S_ac` as "the most direct lever"; that was speculation, it is now measured to be
wrong, and it has been **withdrawn** from the report. No kinetic parameter was touched at
any point, and the declared VFA tolerance stays at 0.25–4.0 and is left to fail.

**On the split, flagged for the coordinator to check.** The coordinator's sweep varied
`S_cat` uniformly and found +0.05 kmol m⁻³ hits the anchor. This implementation applies the
same **+0.05 flow-weighted** with an uneven split (nothing on FOG, a little on the sludges,
most on the industrial stream). Plant B is identical either way, since only the
flow-weighted total reaches its digester; **Plant C is not**, because it is fed the sludges
alone — uniform gives it alkalinity 7.77, this split 5.85, the more defensible figure for a
sludge-only municipal digester. Plant C has no output anchor, so this is a judgement.

---

## 2026-09-03 — The gate-G1 panel runs behind a `g1` marker

**Decision.** `tests/test_g1_anchor.py` is marked `g1` and `pyproject.toml` deselects it by
default (`-m 'not g1'`). CI runs it **nightly** (03:17 UTC) and on any pull request that
touches `sim/`, `configs/`, `scenarios/` or the comparison module itself; the rest of the
suite runs on every push and pull request as before.

**Reason.** The panel is twenty-four 180-day Level-0 runs plus a two-year generator draw,
about six minutes, and it only tells you something when the simulator has changed. The
paths filter is deliberately wider than `sim/` alone, because a config or scenario change
moves these numbers just as surely as a code change does.

**Alternatives.** Keep it in the default suite (rejected: it trebles the time of an
unrelated documentation PR); run it only nightly (rejected: a PR that breaks it would not
be caught until the next morning, and the author would have moved on).

---

## 2026-09-03 — The five interpretations of the first G1 pass are approved (the lead)

Recorded so the approval is on the record with the things it approves: the redacted
manifest; the opaque run id; Level-8 rows carrying an underlying fault; Plant A's ammonia
rows running at all three tiers; and the per-level budget bands. All five stand as
implemented and described in their own entries above.

---

## 2026-09-04 — RULING H1 (the lead): hidden truth becomes structurally unreachable

**What was broken.** The G1 review demonstrated two live bypasses of `state/run_view.py` on
a real generated run, neither of which writes the string `truth`, so the AST checker of
`tests/test_truth_isolation.py` was blind to both:

1. `view.root` was a public dataclass field, so `view.root / "truth" / "parameters.json"`
   read the true parameters outright — no traversal, no forbidden literal.
2. `view.path(".")` was accepted, because the containment guard read
   `resolved != base and base not in resolved.parents` and `"."` resolves *to* `base`. It
   returned the observations directory, whose `.parent` is the run root.

**Decision (by the lead). Structural, not a patch.** Hidden truth moves to a **separate
top-level tree**, `truth_store/<run_id>/`, a sibling of `runs/`. `runs/<run_id>/` contains
the observations, the **redacted** manifest and `calls.jsonl`, and nothing else. A workflow
rooted there has nothing to escape *to*: the worst a containment bug can hand it is its own
run directory. Two consequences follow from the same reasoning and are applied:

* **The complete manifest is hidden truth** and moves with it. It names the scenario, every
  seed and the declared fault layers, so it is written to `truth_store/<id>/manifest.json`
  and `runs/<id>/manifest.json` carries only `PublicManifest`. The redaction now happens at
  **write** time; the file a workflow can open never carried the answer.
* **`index.jsonl` moves too**, from `runs/index.jsonl` to `truth_store/index.jsonl`. It maps
  every opaque run id back to its scenario, which is the answer key, and it sat one level
  above a directory a workflow is handed.

**Defence in depth, all of it, because this module must not depend on the layout.** The run
root is private (`_root`); every accessor returns **file contents**, never a `Path`, since a
path is a capability and handing one out re-creates the field the ruling removed; the
resolver rejects `""`, `"."`, `"./"`, whitespace, absolute paths, traversal and symlinks out
of the tree. `RunView.path` no longer exists.

**The AST checker stays** as the second layer — it covers code that is never executed, which
no runtime sandbox can — widened to `truth_store`.

**The test.** An adversarial bypass suite drives every route: the attribute route (it walks
every public attribute and no-argument method of the view and asserts none yields a `Path`),
`"."`, `""`, `".."`, absolute paths, a directory symlink and a file symlink, plus a layout
test asserting the truth tree is not under the run directory. It carries a **negative
control** — a legitimate read of `sensors.json` and `feed_log.csv` that must still succeed —
because a sandbox that refuses everything passes every refusal test ever written.

**One rule and its corollary, recorded because it bit immediately.** The truth store is the
run store's sibling (`truth_store_for(runs_root) = runs_root.parent / "truth_store"`), which
means **a parent directory holds one run store**: two stores sharing a parent share a truth
store, and two runs of the same cell would overwrite each other's truth. Each test now gives
its store its own parent (`<tmp>/runs`). `RunPaths.for_run` takes an explicit `truth_store`
for anything that needs to break the rule.

**Residual, flagged, not changed.** `runs/<id>/calls.jsonl` stays where CLAUDE.md rule 3
puts it. It carries argument *fingerprints* and no values, so it leaks nothing directly, but
the harness's own entries include one `sim.simulate_truth_segment` record per integration
segment, and the number of segments is one bit about whether a parameter fault has an onset.
`RunView` cannot reach it. Moving the harness's own calls to the truth store would trespass
on rule 3's wording, so it is reported rather than done.

**Alternatives.** Patch the guard again and keep truth under the run (rejected by the lead:
this is the third containment fix, and each one left the secret one directory away); keep
returning `Path` from a private resolver only (rejected: `feed_log()` and `feed_assays()`
would still have to hand one to a reader, so the readers take a stream instead); make the
run root a name-mangled attribute rather than a single underscore (rejected: mangling is
obfuscation, not a boundary — the boundary is that nothing returns a path).

---

## 2026-09-04 — RULING H3 (the lead): each sensor's stream is derived from its own identity

**What was broken.** `observe()` consumed one serial `numpy.random.default_rng(seed)` over
`sorted(tier.sensors)`. Tiers carry different sensor sets, so a shared instrument's position
in that queue changed with the tier and it got a different realisation. Measured at one
observation seed: tier A's `gas_flow` began 3212.4, nan, 5413.4 and tier C's 3065.9, 5927.2,
5515.3 — the same instrument on the same digester, with tier A losing a sample tier C kept.
`sim/run/seeds.py` documents the opposite ("the same observation stream, so that every
difference between two tiers' records comes from the tier's own policy"), and §6.4's tier
comparison was confounded by it.

**Decision.** Each sensor's stream is
`numpy.random.default_rng(SeedSequence([observation_seed, sensor_stream_key(name)]))`, where
`sensor_stream_key` is the first 8 bytes of SHA-256 of the domain-separated sensor name.
Python's `hash()` is salted per process and would break CLAUDE.md rule 4. A sensor's draws
now depend on its own identity and on nothing else: not on which other sensors the tier
carries, not on whether a subset was requested. **The historian stream stays plant-level**,
shared across a tier's online sensors, as ruled — that is what it models.

**The test generates the tiers separately.** The old test compared one shared object with
itself, which is why it passed. `test_a_sensor_reads_the_same_whichever_tier_carries_it`
makes three `observe` calls, holds the declared tier policies equal so that only the sensor
*set* differs, asserts the shared sensors array-equal in value **and** in missingness, and
carries a **different-seed control** that must differ — otherwise a model that had stopped
drawing anything would satisfy the equality. It also asserts the sets differ in the way that
broke the old scheme (tier C carries sensors sorting *before* a shared one).

**Two further checks.** `sensor_stream_key` is pinned to golden values, since changing the
derivation changes every archived run's observations. And the historian's grid — the finest
online sampling interval — is asserted equal at every tier, so no second confound sits behind
the one just removed (it is 1 d everywhere today; only `rate_by_tier` differs, which is
declared policy).

**Three existing tests asserted a realisation rather than a property, and are re-expressed
rather than relaxed.** The drift-reset check was "smaller than the sample before it, or below
0.02" at four boundaries of one draw — a boundary step of 0.032 after a quiet 0.0009 is a
correct reset and failed it; it is now a ratio of magnitudes over every boundary and eight
seeds (~0.18 when reset, ~1.0 when not, bound 0.4). The flatline hold ran one seed on a
process whose occupancy is the anchor's 0.00077, so whether an episode occurred at all was a
coin toss; it is pooled over twelve seeds. The conditional-missingness check compared the
calm-window rate against the *per-sensor* 0.04 when an online sensor also passes through the
historian and actually loses 0.0448 — it passed only because 12 % sat inside a 15 %
tolerance; both expectations are now derived from the config as composites.

**No generated number moved.** The observation stream changes how a *sensor* is realised, not
what the digester does, and the G1 report's block is byte-identical apart from the M1
relabelling.

**Alternatives.** Derive the stream from `(seed, tier, name)` (rejected: that is the confound,
written down); keep the serial stream and reorder it to a fixed global sensor list (rejected:
a sensor's draws would still move when a sensor is added to the catalogue, and the property
wanted is independence, not a longer-lived accident).

---

## 2026-09-04 — RULING H2 (the lead): the blend tank's guard starts guarding

**What was broken.** `tests/test_equalisation.py::test_the_tank_conserves_mass_to_machine_precision`
asserted, per component, `sum(a) - sum(b) == sum(a - b)`. That is an identity of addition: it
holds for **any** `load_out` whatsoever — a pass-through, zeros, a scrambled series. The tank
sits between the frozen influent generator and the truth model on every Plant B cell, and the
one guard on its component balance could not see it stop working.

**Decision.** Replaced with a per-component comparison against the **closed-form solution** of
`dV/dt = q − V/τ`, written out from the ODE rather than from the implementation — which
computes the outflow as the balance `in − (level change)`, so the two agree only if the
balance it keeps is the balance the equation describes. Three hold-ups (0.5, 4, 12 d), three
components. The mass-balance test's per-component half is likewise reconstructed from the
analytical relaxation instead of from the returned series.

**The implementation is correct and is unchanged.** An independent Radau integration of the
same ODE (`scipy.solve_ivp`, rtol 1e-12) agrees to 1.2e-13 on the flow and 2.5e-13 on the
loads. This is a guard that starts guarding, not a bug fix.

**Confirmed by mutation, as the ruling asked.** `load_out[t] = load_in[t]` now fails four
tests — the three parametrised cases and the mass balance — and failed none before. A
negative-control test asserts the same thing from inside the suite (the pass-through is off by
more than 4 % of the mean load at a 4-day hold-up), so the comparison cannot quietly lose its
teeth again.

---

## 2026-09-04 — RULING M1 (the lead): the alkalinity row is a calibration, not a match

**Decision.** `Tolerance` gains a `calibrated` flag; `alkalinity_median` sets it. The row is
rendered **"calibrated to anchor"** rather than "pass", it is **excluded from the
anchor-match count** (`anchor.compare_generated.match_count`, and the generated block now
states that count explicitly), and its rationale is corrected. The old rationale — "alkalinity
follows the feed's inorganic carbon and cation load, which the catalogue carries as design
values (`s_ic`, `S_cat`) rather than fits" — was written before ruling 3 of 2026-09-03 fitted
the Muscatine feeds' `S_cat` to this very column, and became false at that moment.

The row is kept and reported rather than dropped: a large residual would still be a finding,
because the fit could have failed or could drift under a later change. What it cannot be is
evidence. `tests/test_g1_anchor.py::test_a_row_calibrated_to_the_anchor_is_never_counted_as_a_match`
asserts the label, the exclusion, and that the superseded rationale cannot come back.

**The pH corroboration claim is withdrawn.** The report read alkalinity 5.12 and pH 7.29
landing together against the plant's 5.04 and 7.27 as "the sign that the calibration is
physically coherent rather than a fitted offset". In a bicarbonate-buffered digester pH is a
function of alkalinity and pCO₂: fixing the alkalinity to a measured value and then observing
that the pH comes out right is one measurement reported as two.

**Recorded as a finding: one stream supplies almost all of the digester's buffering.**
Measured three ways on Plant B (base seed 1000, 180 d, settled from d 30):

| Basis | High-strength waste | The two sludges | FOG |
|---|---:|---:|---:|
| share of the blend's net strong-cation excess (flow-weighted) | 78 % | 22 % | 0 % |
| share of the `S_cat` increment the calibration added | 91 % | 9 % | 0 % |
| share of the digester alkalinity the calibration added (5.63 with, 3.65 without) | 86 % | 15 % | 0 % |

**The ruling states this share as ~95 %; none of the three bases reproduces that**, the
closest being the `S_cat` increment at 91 %. The measurement method is written out in
`docs/g1_anchor_report.md` §3.2 so the basis can be settled rather than argued. Reported, not
resolved here. Two consequences are for the lead: Plant C is fed the sludges alone, so it
inherits only the 15 % share and its alkalinity has no anchor behind it at all; and a Level-3
fault that alters the high-strength waste moves the digester's whole buffer capacity.

> **Settled 2026-09-09** — see "RULING: the HSW buffering share is reported on the
> `S_cat`-increment basis" below. The share is **91 % on the `S_cat`-increment basis**, and
> the basis is stated wherever the number appears. The ~95 % is superseded.

---

## 2026-09-04 — RULING M7 (the lead): the gap list is merged, and the branch is caught up

**Decision.** `origin/claude/vfa-gap-list` is merged into `claude/g1-scenario-generation`, so
the citation of `docs/vfa_gap.md` in `docs/g1_anchor_report.md` §6 and in
`anchor/compare_generated.py`'s `vfa_median` rationale resolves in the same tree that makes it.

The branch was `main` plus that one document, so the merge also brings this branch up to
`main`: PR #13's offline SCADA anchor and PR #14's plant-level historian dropout arrive with
it (five tests, 300 → 305 before this session's own work). The only conflicts were the two
append-only documents, `docs/decisions.md` and `docs/milestones.md`, resolved by keeping both
sides in chronological order.

---

## 2026-09-04 — Four defects found by the review and not ruled on (M5, M6, L7, L2)

Pure test and correctness work, fixed as marked in the remediation brief.

**M5 — nothing pinned the seed derivation or the run ids.** Every existing test asserted the
derivation was *self-consistent*: same input same output, different input different output.
All of that stays true if `STREAM_ORDER` is reversed or `_ID_SALT` is edited — and then every
archived run's geometry seed is silently some other stream's, and every run directory is
somewhere else. `test_the_seed_derivation_and_the_run_id_are_pinned` pins the stream order,
the golden seed tuple for two cells, and three run ids including
`run_id("S2-03", "B", "A", 1023) == "run_8bfeca8497d4"`.

**M6 — no end-to-end determinism regression.** Two tests. The first generates one cell twice
from scratch and asserts the truth trajectory, the channels, the hidden geometry, the
observations and the four written observation files are bit-identical, and that the two
manifests differ only in `created_utc` and `git_sha`. The second runs the same cell in a
**subprocess under two different `PYTHONHASHSEED` values** and compares the fingerprints with
the in-process one: `hash()` is salted per process, so anything that derived a stream, an
ordering or a key from it would be invisible to an in-process check. Verified by mutation —
making `sensor_stream_key` use `hash(name)` fails the subprocess test and nothing else.

**L7 — `write_index_entry` appended a duplicate line when a cell was regenerated.** A run id
is a hash of its cell, so regenerating a cell overwrites its own directories; the index alone
accumulated, and an evaluator counting its lines would over-count every regenerated cell. It
now keeps one line per run id, replaced in place.

**L2 — stale numbers.** `docs/g1_anchor_report.md` §7 said the output panel was base seeds
1000–1011 when it is 1000–1023 (24 runs); `docs/milestones.md` carried the first-pass biogas
ratio 1.37 where the post-ruling figure is 1.41, and a test count that the session's own later
work had moved. Corrected, with the correction marked in place rather than silently applied.

---

## 2026-09-04 — Three review findings referred to the lead, unchanged (M2, M3, M4)

Reported here so they are on the record with the rulings they were found alongside. **Nothing
in the code or the configuration was changed for any of them.**

> **RULED 2026-09-09** — see "RULING ON M2 (the lead): an AMENDMENT TO RULING 3" at the end
> of this file. Fixed: the assay is now computed from the full charge balance on every
> stream, and the HSW's inorganic carbon is paired to its cations. M3 and M4 stay referred.

**M2 — the feed's visible alkalinity assay and its `s_cat` charge disagree by ~490× on the
high-strength waste.** Independently re-measured here and confirmed: the assay a workflow can
read is the *bicarbonate* alkalinity of `s_ic` at the feed's pH, 0.0214 kg CaCO₃ m⁻³, while
the net strong-cation charge the simulator feeds the digester is 10.26 kg CaCO₃ m⁻³ — a factor
of **480**. The other streams are consistent (thickened WAS 1.0×, primary sludge 2.4×), so
this is specifically the stream ruling 3 of 2026-09-03 raised from 0.03 to 0.225 kmol m⁻³. The
assay and the charge describe the same stream to a workflow and to the simulator respectively,
and after that calibration they no longer correspond.

**M3 — `observations/sensors.json` carries the injected flatline window in `flatlined`.**
Confirmed on a generated S2-02 cell: the record a workflow reads flags the methane analyser as
`flatlined` on exactly the six samples the injected fault produced, and on nothing else. The
flag is meant to be an instrument's own self-report, and here it is also the answer key for
that row.

**M4 — the adversarial note's `author="process_engineer"` is a perfect tell for the Level-8
row.** Confirmed on a generated S8-02 cell: the notes file carries one `operator` entry and
one `process_engineer` entry, and the `process_engineer` one is the false note. Every benign
note in the catalogue is an operator's, so the field alone identifies the adversarial note
without reading it.

All three are design questions about what the visible record may contain, which is the lead's
to answer.

---

## 2026-09-09 — RULING 1 (the lead): Plant A declares two baselines; S6-01 bites, S6-04 abstains

**Decision.** Plant A's contract declares **two named baselines** and every scenario staged
on Plant A names the one its answer key assumes:

| baseline | `K_I_nh3` | X_ac | X_sao | acetate | pH | CH4 | rows |
|---|---|---:|---:|---:|---:|---:|---|
| `adapted` | 0.02 kmol N/m³ | 1.129 | 6.9e-05 | 0.038 kg/m³ | 7.80 | 0.688 | S5-01, S7-02, S6-04 |
| `unadapted` | ADM1 default (0.0018) | 9.9e-05 | 0.910 | 0.240 kg/m³ | 7.79 | 0.692 | S6-01 |

*(Superseded, 2026-09-10: these are the 2026-09-09 measurements. The table was re-measured
on the current feed the next day — adapted X_ac 1.065, unadapted X_sao 0.853 / X_ac 0.0019,
see "Close-out" below — and under the lead's ruling B5 it lives in the truth-side plant
record `sim/plants/truth/plant_A.yaml`, not in the visible contract. It is left here as the
record of what was decided on the day.)*

Measured through the full harness at the 400-d burn-in, 180 d, seed 1000. **Both are sound
digesters; they are two different ones.** A second row, **S6-04**, is added: the same SAO
omission on the `adapted` baseline, scored on **abstention**.

**Reason.** S6-01 was inert. Acetoclasts and syntrophic oxidisers compete for one substrate,
so one always excludes the other; at Plant A's adapted constant the acetoclasts win, the
truth model's SAO pathway carries no flux, and denying it to the fitted model produced no
residual at all. The fix is a **plant property**, not a scenario edit: at the ADM1 default
the acetoclasts wash out and syntrophic oxidation carries the entire acetate flux, so the
omission becomes unmissable. Acetate is 6× higher on the unadapted baseline at the same gas
rate, which is what makes the row diagnosable rather than merely different.

**The pair is the point, and it is why option (c) was kept as its own row rather than as a
replacement.** A benchmark that only ever asks "find the structural fault" rewards a
workflow that always answers "structural", and §6.7 B cannot then separate a diagnosis from
a reflex. S6-01 and S6-04 inject the *same* fault on the *same* plant and differ in one
declared property; their answer keys are opposite (`recommend_structural_review` true and
false). `tests/test_scenarios_library.py` pins both the pairing and the single declared
exception to "every structural row asks for a structural review".

**Declared, not implicit.** The baselines are in the plant contract with their measured
digestate-TAN bands, so a workflow is told the plant has two possible communities, in the
same way it is told the digester's volume. `PlantConfig.adaptation` is now *derived* from
the default baseline rather than declared separately — two places to say which constant a
community carries would be two places to disagree.

**Which baseline a run is on is REDACTED.** Only S6-01 uses `unadapted`, so a visible
`baseline` field would name the scenario outright — the §10 leak the opaque run id exists to
prevent. It is in the complete manifest and not in the projection. Which state the digester
is in is legible from the run's own record (acetate an order of magnitude apart at the same
gas rate) and working that out is the diagnostic task. If a later matrix runs several
scenarios per baseline the argument weakens and this can be revisited.

**The X_sao = 1e-4 feed trace is APPROVED** as a realism choice and is recorded as approved
rather than flagged (it was flagged on 2026-09-03). ADM1 has no immigration term, so a
population at exactly zero can never return however favourable conditions become.

**Matrix.** S6-04 runs on Plant A at all three tiers, as the other ammonia rows do: 114 →
**117 cells**, Plant A 18 → 21. `scenarios/README.md` and the library tests updated.

### Two departures from the ruling as written, both flagged

1. **The row is filed as `S6-04`, not `S6-01b`.** The frozen scenario id pattern is
   `^S\d+-\d{2}$` — `S<level>-<index>`, two digits, no letter suffix — so `S6-01b` is not a
   loadable id, and the id feeds the opaque run-id hash. Relaxing the pattern to
   `^S\d+-\d{2}[a-z]?$` is a one-line change plus a rename if the lead wants the literal id;
   not done unilaterally. The pairing is stated in the scenario file, the README and here.
2. **The unadapted baseline's digestate TAN is 3.5–3.7, not the ruled 3.7–4.3.** Measured:
   median 3.605 (p10 3.505, p90 3.689), *slightly lower* than the adapted baseline's 3.695.
   The unadapted constant does not raise TAN — the pathway change adds no nitrogen — and
   reaching 3.7–4.3 would require moving Plant A's frozen feed nitrogen. Not done. The
   causal mechanism the ruling needs (an SAO-dominated steady state) is delivered in full by
   the unadapted constant alone, and both bands sit inside Tisocco et al. 2024's published
   2.3–4.3.

   > **Settled 2026-09-09** — the measured 3.5–3.7 is **accepted** and the 3.7–4.3 is
   > **withdrawn**; see the close-out entry below. This is no longer a departure.

**Alternatives.** Set the adapted `K_I` to the ~0.003 exchange point so both pathways are
live (rejected: outside the ruled range and structurally fragile — it is the knife edge of a
competitive exclusion); give S6-01 the same transition as S7-02 (rejected: it would
duplicate S7-02 and change the row's label to `structural + parameter`); replace S6-01 with
the abstention row (rejected by the ruling: the pair is worth more than either row).

---

## 2026-09-09 — RULING 2 (the lead): Plant A's baseline TAN of 3.1–3.7 is accepted

**Decision.** The measured baseline digestate TAN of **3.1–3.7 kg N/m³ is ACCEPTED**. The
lead's earlier 2.3–2.8 is **WITHDRAWN**. `K_I_nh3 = 0.02` stands, on the reasoning already
recorded: the frozen `ammonia_inhibition_shift` range is 0.1–10, and 0.02 × 0.1 = 0.002
clears the ~0.003 exchange point while the midpoint of the ruled range does not, so 0.02 is
the only part of that range from which the frozen magnitude range can express a full
de-adaptation.

**Nothing changes in code.** This entry exists so the ruling and the plant stop disagreeing:
a withdrawn number that is not recorded as withdrawn is a trap for the next session, which
would find the config outside a range the log still asserts and "fix" the config.

---

## 2026-09-09 — RULING 3 (the lead): the titrimetric VFA convention is approved in principle and NOT implemented

**Decision.** A declared, `ASSUMED` **Nordmann-type titrimetric transfer function including
bicarbonate carry-over** on the `vfa_total` **sensor**, with `fos_tac` computed from the
titrimetric reading as it is at the plant, is **approved in principle**. True VFA stays the
hidden channel. The benchmark card carries a statement on the two conventions.

**It is NOT implemented and `sim/observation/channels.py` is unchanged.** The lead has asked
the coordinator to bring the transfer function's **form and band with measurements** before
it is built. Implementing a guessed transfer function now and correcting it later would
silently move every generated FOS/TAC twice.

**What is in force meanwhile, stated plainly** because every FOS/TAC number in this
repository depends on it: `fos_tac` is a **true-VFA ratio** measured against a threshold
**percentile-matched to a titrimetric column**. The two are different assays (benchmark card
§5.3), a titrimetric FOS over-reads true VFA by 2–5× at low true VFA, and the consequence is
that the overload flag fires on almost no day of a healthy simulated run. Recorded, not
resolved.

---

## 2026-09-09 — RULING 4 (the lead): the gap is a finding; the 0.40 threshold is percentile-matched

**Decision.** Options (a) and (b) of `docs/vfa_gap.md` both, with (a) deferred by ruling 3.
**No kinetic parameter moves** — `k_m_ac`, `k_hyd` and everything else stay frozen.

**The bistability is recorded for the paper as a finding, not a defect.** Residual VFA jumps
from 0.183 to 10.08 kg m⁻³ and the digester sours from pH 6.95 to 4.60 between `k_m_ac` ×0.40
and ×0.35, so the anchor's 1.18 lies in the *gap between the two branches* and no
single-parameter move reaches it; `k_hyd` at ×2 and ×4 moves residual VFA not at all. It
stays in `docs/vfa_gap.md` and is referenced from the G1 report and the benchmark card as a
property of the model.

**The 0.40 overload threshold stands and is now demonstrably percentile-matched.** The
lead's rule was "0.40 if the anchor's 92nd percentile lands near it under the titrimetric
convention, else the simulated titrimetric 92nd percentile". The anchor's FOS/TAC column *is*
titrimetric, so no conversion is needed on the anchor side. **Re-measured independently here**
on `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`, n = 861 per digester:

| | p50 | p90 | **p92** | p95 | max | days > 0.40 |
|---|---:|---:|---:|---:|---:|---:|
| Digester 1 | 0.232 | 0.371 | **0.402** | 0.439 | 0.930 | 8.25 % |
| Digester 2 | 0.231 | 0.390 | **0.408** | 0.453 | 0.636 | 9.18 % |

The 92nd percentile is 0.40 **within 0.01 on both digesters**, and the 92nd is the *closest*
percentile to 0.40 of any between the 50th and the 99th —
`tests/test_observation.py::test_the_overload_threshold_is_the_anchors_own_92nd_percentile`
pins that, where the previous guard only required 5–15 % of days above the threshold, a band
0.35 and 0.45 would also have passed. The benchmark card now says "the anchor's 92nd
percentile of titrimetric FOS/TAC" rather than quoting a design value.

**Two of the relayed numbers did not reproduce, and the difference is recorded rather than
adopted.** The relay gave Digester 2's max as 0.80 (measured: 0.636) and the exceedance
fractions as 7.78 % / 8.59 % (measured: 8.25 % / 9.18 %), on the same n = 861. The
percentiles that the ruling turns on agree to the third decimal, so the ruling is unaffected;
the discrepancy is reported to the coordinator rather than silently resolved either way.

**The overload firing rate on SOUND runs is now reported per-run and pooled** in the G1
report's generated block, under whichever convention is in force when the panel is
generated, as the ruling requires.

---

## 2026-09-09 — RULING A (the lead): the titrimetric FOS transfer function, κ = 1.0, frozen

**Decision.** The `vfa_total` **sensor** reports what a two-point Nordmann/Kapp titration
would report, and `fos_tac` is computed from that reading as it is at the plant. **True VFA
stays the hidden channel and no sensor sees it.**

```
FOS [kg/m3 as acetic] = (M_HAc / f_ac) * [ S_IC*(a_HCO3(5.0) - a_HCO3(4.4))
                                         + sum_i VFA_i*(a_i(5.0) - a_i(4.4))
                                         + ([H+]_4.4 - [H+]_5.0) ]
f_ac = a_HAc(5.0) - a_HAc(4.4)
```

**There is no fitted parameter.** κ is frozen at 1.0 and every equilibrium constant is the
truth model's own, through `sim.adm1.physchem.temperature_corrected` — no new constants were
introduced. **Re-derived independently here** at Plant B's 308.48 K, and every value matches
the relayed measurement exactly: pK_a(acetate) **4.760**, pK_a(CO₂) **6.305**, carry-over
fraction **0.0349** of S_IC, f_ac **0.3309** so the implicit scale-up is **3.022** — the
Nordmann formula's own ×3.02, *derived* rather than asserted.

**Measured result**, also reproducing the relay: median titrimetric FOS **0.775** kg m⁻³
against the anchor's 1.178 (the true-VFA channel gives 0.067), FOS/TAC median **0.150**
against 0.233. The gap falls from **17.5× to 1.52×** with nothing fitted. **90 %** of the
reading is bicarbonate carry-over.

**Consequence, and it is a big one: `vfa_median` and `fos_tac_median` now PASS.** The report
went from 20 of 22 independent rows inside their declared tolerance to **22 of 22**. This is
not a bound being widened — neither bound has ever been touched — and it is not the model
changing. It is the row finally comparing **like with like**: it previously measured a
chromatographic VFA against a titration. `tests/test_g1_anchor.py` used to pin those two
rows as *failing*, and their size in both directions, so that closing the gap would fail a
test and force the record to be updated. That is exactly what happened; the test now pins
the **residual 1.52× gap** in both directions instead.

**Kept alongside.** `fos_tac_true_vfa` and `vfa_true_median` are reported beside the
titrimetric ones, so the distance between the two conventions stays measurable rather than
disappearing the moment the transfer function landed.

**Alternatives.** Fit κ to the anchor (rejected by the ruling and by this session: a fitted
κ would make the row a calibration, like `alkalinity_median`, and it is not needed — pure
chemistry gets within 1.5×); apply the transfer function to the channel rather than the
sensor (rejected: the channel is hidden truth and must stay the true quantity).

---

## 2026-09-09 — RULING B (the lead): conditional missingness triggers on the hidden state

**Decision.** The overload flag that drives conditional missingness fires on **true VFA above
2.00× its own 30-day trailing median**, the window **excluding the current day**. It used to
fire on "the reported FOS/TAC exceeds 0.40".

**Reason, and it is two separate ones.** Conditional missingness (§6.1) is a property of the
**plant**: instruments fail during the transients that identify the process, whether or not
anyone has taken a reading. And the reading it used to fire on is 86–90 % bicarbonate
carry-over, which tracks slowly-varying alkalinity and therefore **masks** the VFA dynamics
the flag exists to detect.

**Excluding the current day is not a detail.** With it included, a sustained excursion enters
the median it is compared against and can mask itself; `tests/test_observation.py` measures
a case where inclusion would raise the reference from 1.0 to 5.5 and hide a tenfold
excursion outright.

**The measured candidates** (24 sound Plant B runs, 3,624 settled digester-days), relayed by
the coordinator and reproduced here for Plant B:

| signal | median | p92 | at the cut-off |
|---|---:|---:|---|
| **VFA / 30-d trailing median** | 1.002 | 1.989 | **> 2.00× → 7.92 % — ADOPTED** |
| gas / 30-d trailing median | 1.001 | 1.780 | > 1.35× → 21.80 % |
| OLR / mean (design proxy) | 0.834 | 1.860 | > design → 37.20 % |
| any of the three (OR) | | | → 47.27 % |

7.92 % against the anchor's own 7.78 % exceedance, **with nothing tuned**. The other two are
**not** OR-ed in. Their equivalent 7.8 % cut-offs — gas > 1.796× trailing, OLR > 1.871× mean
— are recorded and not used.

**This gives S4-02 back.** On the old trigger the flag fired on no day at all in 23 of 24
sound runs, so the Level-4 `informative_missingness` row was a near-duplicate of Level 1. It
now fires in **every** sound run on B and C.

**Cross-plant rates, measured here on 24 seeds per row.** The cut-off is 2.00× everywhere;
differences are recorded, not tuned away. **Four rows, because Plant A is two digesters**
(ruling 1) and its baselines must not be averaged into one number.

| Plant | baseline | sound | trigger, pooled | per-run range | runs that fire | VFA ratio p92 |
|---|---|---|---:|---|---:|---:|
| B | — | 24/24 | **7.92 %** | 2.65–15.89 % | 24/24 | 1.989 |
| C | — | 24/24 | **9.96 %** | 6.62–16.56 % | 24/24 | 2.147 |
| A | `unadapted` | 24/24 | **2.54 %** | 0.66–5.96 % | 24/24 | 1.635 |
| A | `adapted` | 24/24 | **0.52 %** | 0.00–1.99 % | **11/24** | 1.435 |
| *anchor* | | | *7.78 %* | | | |

The A-`adapted` figure reproduces the coordinator's independent measurement of 0.52 % exactly.

**Two effects, and the four-row table separates them.** The **feed pattern** is the larger:
B and C take trucked batches of high-strength waste and FOG, Plant A is fed steadily, and
even Plant A's spikier baseline sits 3–4× below B and C. But **the pathway matters too, and
that is new**: within Plant A, on the *same* feed pattern, the SAO-dominated `unadapted`
baseline fires at 2.54 % against `adapted`'s 0.52 % — nearly five times as often, and in
every run rather than 11 of 24. Routing the acetate flux through syntrophic oxidation, which
turns over more slowly, makes residual VFA genuinely more mobile. Neither explanation alone
accounts for the spread. **Accepted by the lead as the physical answer**, not a defect and
not to be tuned.

**The consequence, stated precisely.** Conditional missingness is close to inert on Plant A's
adapted baseline. It does **not** weaken the §7 factorial: the factorial is Plants B and C
only and Plant A contributes no factorial cells, so `S4-02`'s **6 factorial cells (B and C,
three tiers each)** all sit where the trigger fires in every sound run. Plant A additionally
runs S4-02 as **one Tier-A cell** in its separately-reported subset, and that cell is thin.
*(An earlier draft of this entry said "Plant A hosts S4-02" without that distinction, which
overstated the exposure; corrected here.)*

**`foaming` is unchanged** and still reads FOS/TAC — now the titrimetric one, which is the
same convention as its anchored threshold, so that pairing became more consistent rather than
less. Not part of the ruling; noted so the change is visible.

---

## 2026-09-09 — RULING C (the lead): the operator threshold and the trigger are separate

**Decision.** Titrimetric FOS/TAC > 0.40 remains the **operator-visible** overload threshold,
percentile-matched to the anchor, reported on the benchmark card as such. **It no longer
drives conditional missingness.** The two are kept apart in the code
(`ConditionThresholds.fos_tac_overload` versus `vfa_surge_ratio`/`vfa_median_window_d`), in
the config, and in the report, which now carries **both rates in one table** so they cannot
be confused: trigger 7.92 %, operator-visible 0.17 %, on the same 24 sound runs.

The operator threshold fires rarely because the simulated titrimetric distribution still sits
~1.5× below the plant's (ruling A). **The threshold is not moved to compensate.**

---

## 2026-09-09 — RULING D (the lead): the "variance deficit" was a wrong diagnosis; the convention masks the dynamics

**Correction of the record.** An earlier report of a **variance deficit in the model** was
wrong and is **not** recorded as a model finding.

**Measured.** True VFA's day-to-day spread is p92/median **2.06** pooled (2.27 on the single
run re-measured here), against the anchor's FOS/TAC spread of **1.74** — the model's VFA
dynamics are if anything *more* variable than the plant's, not less. What is flat is the
**titrimetric FOS/TAC**, p92/median **1.087** (1.14 re-measured), and it is flat **because**
86–90 % of the reading is bicarbonate carry-over tracking slowly-varying alkalinity.

**The finding for the paper is therefore:**

> **The titrimetric convention masks the VFA dynamics it is meant to report.**

A measurement-model property, not a model deficiency. It is also the independent
justification for ruling B: a flag meant to fire on process transients must not read a
quantity that averages them out. `tests/test_g1_anchor.py` pins it — the titrimetric reading
is several times the true VFA on every sound run, and its spread across the panel is smaller
than the true-VFA ratio's.

---

## 2026-09-09 — RULING E (the lead): the run root moves into a closure

**Decision.** `state.run_view.open_run` captures the run root in **closures** and the
`RunView` holds three callables. There is **no instance attribute at all** — not `root`, not
`_root`, not `_base` — so the attribute route the review used does not merely become private,
it stops existing. `tests/test_truth_isolation.py` asserts that nothing stored on the object
is a `Path` or a string, and that the run directory does not appear as a value anywhere on
it.

**Stated rather than glossed:** a closure cell is still reachable through `__closure__` by a
caller determined enough. This removes the *accident*, not the adversary. The layer that
actually protects hidden truth is that it is **not under the run directory at all**
(ruling H1 of 2026-09-04), and the module docstring says so.

**The listing and the resolver now agree.** `view.files` used to list a planted symlink that
`read_text` would then refuse, so the view advertised something it would not hand over. The
listing now filters through the resolver. Tested with a planted symlink, plus the negative
control that every listed file really is readable and the listing is not empty.

**The coordinator's own adversarial pass on `f8bfc14` found every path route already
blocked** — empty, `"."`, `"./"`, `".."`, `"../../"`, `"../manifest.json"`, traversal to
`truth_store`, absolute paths, a planted file symlink and a planted directory symlink, all
`TruthAccessError` — with both negative controls good. The AST checker is retained.

---

## 2026-09-09 — Open item: Plants B and C need a declared design organic loading rate

**Recorded as a follow-up, not done here** (the lead, 2026-09-09). `configs/plants/plant_B.yaml`
declares **no design OLR**, so "loading above design" has no referent in the plant contract;
the coordinator's trigger sweep had to use the run's own mean as a proxy.

**A declared design loading is to be added to Plants B and C from Muscatine's design or
permit figures the next time a session touches the plant configs.** It is not part of PR #15
and no design OLR is to be invented in the meantime. The conditional-missingness trigger does
**not** use OLR (ruling B adopted the VFA signal alone), so nothing depends on this today.

---

## 2026-09-09 — The missingness trigger is not frozen until its cross-plant rates are on the record

**Status.** The 2.00× cut-off is implemented and the three-plant firing rates are measured and
recorded (see ruling B above): B 7.92 %, C 9.96 %, A 0.55 %. The lead's condition for freezing
the trigger was that these be recorded beside Plant B's, with **differences between plants
expected and recorded rather than tuned away** — no per-plant cut-off and no adjustment to
equalise them. That condition is now met by this session's own measurements; the coordinator
is measuring the same quantity independently and the two sets should be compared before the
trigger is called frozen.


---

## 2026-09-09 — The lead confirms `S6-04`'s name; the scenario id pattern stays frozen

**Decision (by the lead).** The row the ruling named `S6-01b` **keeps the id `S6-04`**, and
the scenario id pattern `^S\d+-\d{2}$` **stays frozen**. It is not relaxed to admit a letter
suffix and the row is not renamed.

**Reason.** `S6-01b` is not a loadable id under the frozen pattern, and the id feeds the
opaque run-id hash (`sim.run.layout.run_id`), so renaming it would move every one of that
row's run directories. Flagging it rather than relaxing the pattern was the right call; this
entry closes the question so the next reader finds a settled answer rather than an open flag.
The pairing with S6-01 — the same fault on the two declared baselines, with opposite answer
keys — is what the ruling is about, and it is carried by the scenario file's header, by
`scenarios/README.md` and by the decisions log rather than by the filename.

---

## 2026-09-09 — What closing the remaining 1.52× FOS/TAC residual would take

**Recorded because a report that stops at "most of it was a convention" has not finished.**
The titrimetric transfer function took the gap from 17.5× to 1.52× with nothing fitted; this
is what the residual is and what closing it would cost. Written into
`docs/g1_anchor_report.md` §6.1.

**What the residual is.** A titrimetric FOS counts every species titratable between pH 5.0
and 4.4. The transfer function accounts for the two the truth model carries — bicarbonate and
the four VFA — and for free protons. It cannot account for what **ADM1 does not have**:
lactate, phenols, humic and fulvic acids. A ~1.5× residual in a reading that is 90 %
bicarbonate carry-over is a plausible size for exactly that, and it points at the truth
model's *component list*, not at any of its parameters.

**Two ways to close it, neither taken.**

1. **Fit κ.** Rejected on structural grounds rather than taste: a fitted κ makes
   `fos_tac_median` a row calibrated to the very anchor column it is compared against, which
   ruling M1 of 2026-09-04 then labels *calibrated to anchor* and **excludes from the
   anchor-match count**. The benchmark would trade a real 1.52× residual for a row that
   agrees by construction and counts for nothing. κ stays frozen at 1.0.
2. **Carry the missing species.** A truth-model extension for lactate and the other
   titratable non-VFA acids would close it through the process. That is a new component set,
   its own kinetics and its own identifiability work — the size of the SAO or precipitation
   extensions — and it would change what Level-6 structural scenarios mean. **Phase 2 at the
   earliest.**

**How this was found, and it matters for the tests.**
`tests/test_g1_anchor.py::test_the_report_says_what_closing_the_gap_would_take` required the
word "closing" among four phrases. The report was rewritten around the convention correction,
the section on closing the *remainder* went with it, and the guard failed. **The report was
fixed, not the test**: §6.1 is that section. The four original phrases are kept and joined by
seven more, each paired with the reason it is required — a single keyword can be satisfied by
the keyword alone, which is how the section came to be missing while three of the four still
matched.
---

## 2026-09-09 — CLOSE-OUT RULING (the lead): the unadapted baseline's TAN of 3.5–3.7 is accepted

**Decision.** The measured digestate TAN of the `unadapted` baseline, **3.5–3.7 kg N/m³, is
ACCEPTED as measured**. The lead's earlier **3.7–4.3 is WITHDRAWN**. This is the same
disposition as ruling 2 of 2026-09-09 for the adapted baseline (3.1–3.7 accepted, 2.3–2.8
withdrawn), and for the same reason.

**Nothing changes in code.** `configs/plants/plant_A.yaml` already carries the measured band
(median 3.605, p10 3.505, p90 3.689); what changes is that the `source:` note no longer reads
`FLAGGED ... with the coordinator` but records the ruling. The entry exists so the ruling and
the plant contract stop disagreeing — **a withdrawn number that is not recorded as withdrawn
is a trap for the next session**, which would find the config outside a range this log still
asserted and "fix" the config, moving Plant A's frozen feed nitrogen to chase a number no one
is asking for any more.

**Why the band could not have been reached.** The unadapted variant is the ADM1/BSM2 default
`K_I_nh3`. It changes which community carries the acetate flux; it adds no nitrogen. The
measured TAN is *slightly lower* than the adapted baseline's 3.695, not higher. Reaching
3.7–4.3 would have required moving the feed nitrogen, which is frozen. Both bands sit inside
Tisocco et al. 2024's published 2.3–4.3, so the plant remains evidenced.

**Alternatives.** Raise the feed nitrogen to land the band (rejected: changes a frozen design
value to satisfy a number, and would move the adapted baseline too); carry the discrepancy as
a permanent flag (rejected by this ruling: a flag no one intends to act on is noise).

---

## 2026-09-09 — RULING (the lead): the HSW buffering share is reported on the `S_cat`-increment basis

**Decision.** The high-strength waste's share of Plant B's buffering is reported as **91 % on
the `S_cat`-increment basis, with the basis stated in the sentence that carries the number**.
Not on the absolute-charge basis, and **never as a bare percentage**. The lead's earlier
~95 % is superseded.

**Why the basis is the ruling.** Three defensible bases were measured and they genuinely
disagree — 78 % of the blend's net strong-cation excess, 91 % of the `S_cat` increment the
calibration added, 86 % of the digester alkalinity that increment produced. They answer three
different questions ("how much of the charge is this stream's", "how much of what we *changed*
was this stream's", "how much of the resulting buffer"), and a percentage quoted without its
basis cannot be checked, reproduced, or argued with. The ruled basis is the one that describes
what the calibration did, which is the claim the finding is actually making.

**Applied in** `docs/g1_anchor_report.md` §3.2: the headline sentence now names the basis, the
ruled row of the three-basis table is marked as the ruled basis, and the Plant C consequence is
restated on the same basis (9 % of the increment, 15 % of the alkalinity). The three-basis
table stays: it is the measurement record, and it is what makes the ruled number checkable.

**Alternatives.** Report the absolute-charge 78 % (rejected by the ruling); report all three
every time (rejected: the finding needs one number to be a finding); drop the other two
(rejected: without them the 91 % cannot be reproduced or challenged).

---

## 2026-09-09 — FINDING (ruled to be recorded as one): the methanogenic pathway drives VFA excursions, not only the feed pattern

**Recorded on the lead's instruction** that this is a result about the model rather than a row
in a panel table, and that a benchmark exists to surface exactly this kind of thing. Written
up in `docs/g1_anchor_report.md` §5.4.

**The controlled comparison.** Plant A's two baselines share geometry, feed streams, delivery
schedule, seeds and the 2.00× cut-off. They differ in one declared property — `K_I_nh3`, and
so which community carries the acetate flux. 24 clean Level-0 seeds each:

| | `unadapted` (SAO) | `adapted` (acetoclastic) |
|---|---:|---:|
| hidden-state trigger, pooled days | **2.54 %** | **0.52 %** |
| per-run range | 0.66 – 5.96 % | 0.00 – 1.99 % |
| runs in which it fires at all | 24 / 24 | 11 / 24 |
| VFA ratio, 92nd percentile | 1.635 | 1.435 |

**4.9× on the pooled rate, and it fires in every run rather than 11 of 24.**

**What it says.** The trigger is a *relative* excursion measure — true VFA against its own
30-day trailing median — so this is not the SAO baseline sitting at a higher VFA level. The
same load fluctuations move the residual acetate pool further, relative to where it has been,
when that pool drains through syntrophic oxidation: SAO is the slower route, the perturbation
takes longer to relax, and a trailing median that absorbed it on the acetoclastic baseline no
longer does. Cross-plant, the feed pattern is the larger effect (B and C take trucked batches
and sit 3–4× above both Plant A rows), but **neither explanation alone accounts for the
spread**, and only this within-plant pair isolates the pathway.

**Why it exists to be found at all.** It came in as an apparent defect — Plant A fires far
below the anchor — and the obvious repair is a per-plant cut-off. The lead's ruling forbids
that: *differences between plants are expected and are to be recorded, not tuned away*. A
per-plant cut-off would have set both Plant A rows to ~8 % by construction and destroyed the
comparison. The ruling is what made the finding possible, and that is worth recording next to
the finding.

**Consequences.** A workflow that reads VFA variability as evidence about the *feed* will
misread this plant, and the correct inference is available in the record because both
baselines run the same feed. For Level 6 it means the S6-01 / S6-04 pair differs in the
observable record and not only in the answer key, so the abstention row is not asking a
workflow to separate two identical datasets.

---

## 2026-09-09 — RULING (the lead): the matrix is regenerated at the final branch head, last

**Decision.** The §7 matrix is regenerated as the **last action before the merge**, so every
`manifest.json` carries the `git_sha` of the code that actually produced it. **Not** earlier
followed by further commits — that is precisely what the ruling rules out, and it is what
happened twice on this branch before (the first two regenerations produced `-dirty` SHAs, and
a later one was overtaken by two more commits).

**The nuance, stated in the report rather than left to be discovered.** The manifests carry
the final **branch-head** SHA, not the merge-commit SHA. The merge commit does not exist until
after the merge, and regenerating after the merge would mean regenerating on `main` — a
different tree from the one the branch was reviewed on. `docs/g1_anchor_report.md` §7 says so
explicitly, including what a later session should do to reproduce a cell (check out that SHA
directly) and the one condition under which the record goes stale (`main` moving under `sim/`,
`configs/` or `scenarios/` between the regeneration and the merge).

**Alternatives.** Regenerate on `main` after the merge (rejected: it is no longer the reviewed
tree, and it puts a generation step after the gate); record the merge SHA by hand in the
manifests (rejected: a manifest field that is not what the generator observed is a lie in the
provenance record, which is the one place that cannot afford one); leave the earlier
regeneration in place (rejected by the ruling).

---

## 2026-09-09 — M2, M3 and M4 stay referred: change nothing

**Decision (coordinator, relaying the lead's instruction).** The three findings referred on
2026-09-04 and 2026-09-09 stay on the record **exactly as they are** while the lead reads
them. **No code, config or scenario change for any of them in this branch.**

1. **M2** — the factor of 480 between the HSW's visible bicarbonate-alkalinity assay
   (0.0214 kg CaCO₃/m³) and the net strong-cation charge the simulator feeds (10.26). The
   decisions entry has been sent to the lead verbatim; they rule after reading it.
2. **M3** — `observations/sensors.json` flags the methane analyser `flatlined` on exactly the
   samples the Level-2 fault injected, so the flag labels the row.
3. **M4** — the adversarial Level-8 note is the only entry authored by a `process_engineer`,
   so the author field alone identifies it without reading it.

**Why this is recorded as a decision rather than left implicit.** M3 and M4 are both one-line
fixes with an obvious shape, which is exactly why a later session would fix them on sight. Two
of them change what a scenario tests — M3 is the difference between a Level-2 row that must be
diagnosed and one that is labelled in its own metadata — so the fix is a design decision, not a
tidy-up, and it belongs to the lead.

---

## 2026-09-09 — RULING ON M2 (the lead): an AMENDMENT TO RULING 3 of 2026-09-03

> **M2 was NOT closed by this entry** — an independent review of this fix (2026-09-09)
> found three defects in it, B1–B3 below. **All three are now fixed**: B3 in the addendum to
> this entry, B2 by the liquor ruling of 2026-09-10, and B1 by the calcium ruling of
> 2026-09-10 after a first attempt against the uncorrected calcium breached three things.
> **M2 is closed as of the calcium entry**; the text below is the history.
>
> * **B1 — the charge side omits the fed calcium.** `feed_cation_charge` leaves out
>   `2 × S_ca`, which `sim/adm1/physchem_ext.py::_residual` carries, `configs/adm1/extensions.yaml`
>   declares with charge 2, all three plants enable, and `sim/run/harness.py` feeds. Counted
>   properly, **four of seven streams breach 1.5×**: primary sludge 2.94, thickened WAS
>   2.71, cattle slurry 1.83, grass silage 1.69. **M2 is reduced from 503× to about 2.9×,
>   not closed**, and the residual was hidden because the guard was written against a charge
>   definition that leaves out a cation the digester is fed.
> * **B2 — the invariant holds at catalogue TS only.** The assay's acetate term scales with
>   a delivery's solids; the charge side does not scale at all, and the guard is called at
>   catalogue TS, so it never sees the quantity a workflow actually reads. On real assay
>   records the HSW's reported alkalinity ranges 6.1–38.0 against a fed charge of 10.75;
>   primary sludge is outside 1.5× on 45 % of records, cattle slurry on 27 %. **The identity
>   stated flatly below is true of the catalogue row and false of the generated stream.**
> * **B3 — the guard was vacuous. Fixed.** See the addendum.
>
> Everything else in this entry was independently recomputed by the review and confirmed.


**Read this with the ruling-3 entry of 2026-09-03 ("The feed's strong cations are calibrated
to the anchor's alkalinity"), which it amends.** Ruling 3 raised the high-strength waste's
`S_cat` from 0.03 to 0.225 kmol m⁻³ to reach the anchor's digester alkalinity. M2 (review
finding of 2026-09-04) was that this pulled the stream's two descriptions apart: the routine
alkalinity assay a **workflow** reads was the bicarbonate alkalinity of `S_IC` alone, which
the calibration never touched, so the visible number said **0.0214 kg CaCO₃ m⁻³** while the
**simulator** was fed **10.75** of cation charge — a factor of **503** on the one stream the
plant's entire buffer capacity rests on. This is an **approved change to a frozen config.**

### Part 1 — the assay is computed from the full charge balance, on every stream

**Decision.** The workflow-visible feed alkalinity assay is total alkalinity at the stream's
own pH, from the full charge balance — strong ions and weak-acid species — for every stream
in the catalogue, not the bicarbonate alkalinity of `s_ic` alone.

Two paired functions in `sim/influent/generator.py`:

* `total_alkalinity(spec, fractionation, physchem, ts)` — what a titration to the CO₂ end
  point measures: `50 × ([HCO₃⁻] + [Ac⁻] + [OH⁻] − [H⁺])`, the **same convention as the
  effluent channel** `alkalinity_total`, so the feed and the digester are described in one
  unit. Acetate is the only organic term because ADM1 feeds only one free acid (`S_ac`), and
  it scales with the delivery's solids as its COD does.
* `feed_cation_charge(spec, physchem)` — what ADM1's charge balance must balance:
  `50 × (S_cat − S_an + [NH₄⁺])`. Ammonium is in it because it is a cation in that balance
  and a titration to the CO₂ end point leaves it protonated.

**Electroneutrality makes the two equal exactly when a stream's declared pH is consistent
with its declared composition.** That is the invariant, and it is what the new test asserts.

**The test** (`tests/test_generator.py::test_every_feed_assay_describes_the_charge_the_simulator_is_fed`)
covers **every catalogue stream** within 1.5×, names the stream and both numbers on failure,
and was **checked against the pre-fix catalogue first**: it fails there on two streams,
`high_strength_waste` at 4.00× and `food_waste` at 0.33× — and at **503×** against the
pre-ruling *assay*. Every stream, not just the HSW, because the failure was not a mistyped
number; it was that two descriptions of one stream were free to drift apart with nothing
comparing them, and a guard watching only the stream that had already broken would let the
next calibration break a different one.

**What the guard catches, measured, and what it does not.** Perturbing `s_cat` by ±50 % on
the **six** streams a plant feeds gives 12 mutants: **10 fail, 1 is skipped by the floor**
(FOG, which carries no liquor) **and 1 survives** — cattle slurry at half its cations moves
1.39× to 1.11×, *towards* the centre of the band. Perturbing `s_ic` or the declared pH is
caught where a stream sits near the edge of the band and **not** where it has slack inside
it: 1.5× is a band, not an equality.

> **CORRECTED 2026-09-09.** This entry first said "10 mutations out of 10" on "five"
> streams. Both were wrong: it is 9 of 10 on the five non-FOG streams, and FOG is a Plant B
> feed so there are six. The review of 2026-09-09 caught it. A claim stated as a
> measurement has to be reproducible, and that one was not — which is the same failure the
> claim itself was warning about.

**`food_waste` was fixed too**, since the ruling is on every stream: at 0.05 kmol m⁻³ of
cations it carried 0.152 kmol m⁻³ of acetate **anion** at its cited pH 5.1 with nothing to
balance it — the same defect as the HSW's with the sign reversed. `s_cat` → 0.152 (3.5 g
Na+K per litre, mid-range for food waste, and the only assumed field in that pair; the pH is
Fisgativa et al. 2016's measurement and is kept). **No plant feeds this stream**, so nothing
generated moves.

### Part 2 — the HSW stream had to be a physically possible waste

**The ruling was conditional on the implied pH, so it was computed first.** At the declared
composition the stream's own charge balance closes only at **pH 13.04**: 0.205 kmol m⁻³ of
net strong-cation charge against 0.01 kmol C m⁻³ of inorganic carbon leaves nothing but
hydroxide to balance it. That is a caustic solution, not a food or beverage waste, so the
condition was met and the redistribution was made. Ruling 3's caustic is spent neutralising
the stream's own acidity and arrives as sodium **bi**carbonate:

| | before | after |
|---|---:|---:|
| `S_cat` | 0.225 kmol m⁻³ | **0.225 — unchanged** |
| `S_IC` | 0.01 kmol C m⁻³ | **0.1607** |
| declared pH | 5.0 | **7.0** |
| implied pH | 13.04 | **7.00** |
| visible assay | 0.0214 kg CaCO₃ m⁻³ | **10.75** |
| fed cation charge | 10.75 kg CaCO₃ m⁻³ | **10.75 — unchanged** |

`S_IC` is **not fitted**: it is the inorganic carbon that closes the charge balance at the
declared pH. **`S_cat` did not move**, so the strong-ion difference reaching the digester is
exactly ruling 3's calibration; the counter-ion is now bicarbonate rather than nothing.

**Reconfirmed where ruling 3 put the digester**, on the same 24-seed panel: alkalinity
**5.125** kg CaCO₃ m⁻³ (target ~5.0; was 5.12), median pH **7.262** (target ~7.3; was
7.293), **24 of 24 sound**. Alkalinity barely moves because the strong-ion difference sets
it and that was held fixed; the extra inorganic carbon leaves as CO₂.

### What moved, measured, with nothing tuned to compensate

Only Plant B — Plant A is fed slurry and silage, Plant C the two sludges, and `food_waste`
is fed by no plant.

| | before | after | bound |
|---|---:|---:|---|
| `biogas_mean` ratio | 1.41 | **1.45** | 0.6–1.5 — **the least margin in the report** |
| `ch4_fraction_median` | 0.722 | **0.700** | no anchor row |
| `digester_pH_median` | 7.293 | **7.262** | ± 0.4 pH |
| `alkalinity_median` | 5.12 | **5.125** | ± 35 %, calibrated |
| `vfa_median` | 0.7753 | **0.7778** | ratio 0.25–4 |
| `fos_tac_median` | 0.1495 | **0.1501** | ratio 0.5–2 |
| residual VFA gap | 1.52× | **1.51×** | pinned 1.25–1.85 |
| missingness trigger, pooled | 7.92 % | **7.70 %** | anchor's own 7.78 % |
| operator overload, pooled | 0.17 % | **0.19 %** | 1 of 24 runs either way |

**All 23 rows stayed inside their declared bounds; no tolerance was touched.** The extra gas
is CO₂ and not methane — total gas up, methane fraction down 2.2 points — which is the
expected consequence of putting the missing inorganic carbon in. **`biogas_mean` at 1.45
against 1.5 is flagged to the lead**: it is inside, but it is the least margin anywhere in
this report and the next thing that raises gas will breach it.

**The trigger table in `configs/observation/sensors.yaml` is left as measured** and labelled
pre-M2. All four candidate rows came from one panel at one code version; re-measuring only
the adopted row would leave four numbers from two simulators. The adopted trigger's post-M2
rate (7.70 %) is stated beside it. The three rejected candidates lost by factors of 3 to 6,
which a 0.2-point shift does not touch.

**Alternatives.** Report the assay as the strong-ion difference itself (rejected: the test
would then be an identity and could not fail — the failure mode this whole remediation is
about); lower `S_cat` instead of raising `S_IC` (rejected: that unpicks ruling 3's
calibration and the digester would no longer land at the anchor's alkalinity); leave the
assay alone and document the discrepancy (rejected by the ruling, and it would leave a
workflow reading a number 503× away from the buffering the digester actually has).

**Still with the lead: M3 and M4**, unchanged.

---

## 2026-09-09 — ADDENDUM to the M2 ruling: B3 fixed, B1 and B2 open

**Read with the M2 entry above, which this corrects.** An independent fresh-context review
of the M2 fix found three defects. This addendum records the one that is fixed and pins the
two that are not, so that nothing in this log reads as settled while they are open.

### B3 — the ratio guard was vacuous. FIXED.

**The defect, demonstrated rather than argued.** Two mutants were built and run against the
whole suite:

* `total_alkalinity` and `feed_cation_charge` both returning `0.0` — **337 passed**. Every
  stream falls under `ASSAY_VS_CHARGE_FLOOR = 0.10` and is skipped.
* `total_alkalinity` returning `feed_cation_charge(...)` — **337 passed**. That is exactly
  the strong-ion-difference definition the M2 entry's *Alternatives* rejects on the grounds
  that a test of it "could not fail"; as written, the test could not tell whether precisely
  that had been implemented.

Nothing anywhere pinned the absolute value of the feed alkalinity assay, so nothing could
distinguish a correct implementation from a constant.

**The fix.** `tests/test_generator.py::test_the_feed_alkalinity_assay_is_pinned_and_the_two_quantities_are_independent`
asserts three properties, each killing one class of mutant:

1. **Committed absolute values** for both quantities on every stream
   (`COMMITTED_FEED_ALKALINITY`), which are the numbers `docs/g1_anchor_report.md` §3.3
   quotes — so the report and the code cannot drift apart. Kills zero, a constant, and a
   silent formula change.
2. **The two read different fields**: `s_ic` moves the assay and not the charge, `s_cat`
   moves the charge and not the assay. Kills the copy mutant — if the assay *were* the
   strong-ion difference, `s_cat` would move both.
3. **One stream reproduced from the ADM1 constants** without calling the implementation,
   with an assertion that those literals still match `physchem`. Kills a wrong equilibrium
   constant or a dropped term.

Both mutants were rebuilt after the fix and **both now fail**. The ratio guard's docstring
now says plainly that it is not sufficient alone and names this test as part of it.

### B1 — the fed calcium is missing from the charge. Was OPEN; closed 2026-09-10 (calcium ruling).

Independently reproduced here. `sim/adm1/physchem_ext.py::_residual` carries `+ 2.0 * tot.ca`;
`configs/adm1/extensions.yaml` declares `S_ca` with `charge: 2`; **all three plants enable
the `precipitation` extension**; `sim/run/harness.py` feeds `S_ca`. `feed_cation_charge`
computes `50 × (S_cat − S_an + [NH₄⁺])` and omits it, so the guard's "what the simulator is
handed" is not what the simulator is handed.

| stream | ratio as shipped | ratio with `+ 2 × S_ca` |
|---|---:|---:|
| `primary_sludge` | 1.47 | **2.94** |
| `thickened_was` | 1.35 | **2.71** |
| `cattle_slurry` | 1.39 | **1.83** |
| `grass_silage` | 1.16 | **1.69** |
| `high_strength_waste` | 1.00 | 1.09 |
| `food_waste` | 1.00 | 1.20 |

**So M2 is reduced from 503× to about 2.9×, not closed.** Nothing has been changed: the
correct definition breaches the band on four streams, and closing those would mean either
redistributing the sludge streams' composition or revisiting their declared pH — a further
change to a frozen config, which is the lead's to approve. Recorded here so the next session
cannot read the M2 entry as finished.

### B2 — the invariant holds at catalogue TS, not for the reported assay. Was OPEN; closed 2026-09-10 (liquor ruling).

`total_alkalinity`'s acetate term scales with a delivery's solids (its COD does); the charge
side does not scale at all, because the dissolved liquor stays at the catalogue value by the
generator's own moisture convention. The guard is called at catalogue TS, so it never sees
the quantity a workflow reads. Measured on real `AssayRecord`s (4 seeds × 400 d, Plants A
and B): the high-strength waste's reported alkalinity ranges **6.1 to 38.0** kg CaCO₃/m³
against a fed charge of 10.75; `primary_sludge` is outside 1.5× on **45 %** of records,
`cattle_slurry` on **27 %**.

This is a real inconsistency in the generator, not only in the claim: as a delivery gets
drier, more free acetate anion is fed with no more cations to balance it. The M2 entry, the
report and the commit message all state the identity flatly, and it is true of the catalogue
row and false of the generated stream. Nothing has been changed — a fix moves the influent
again — and it is with the lead.

### Also corrected

The M2 entry's mutation claim was wrong twice over and is fixed in place: **10 of 12 on six
fed streams** (10 fail, FOG is skipped by the floor, cattle slurry at half its cations
survives by moving towards the centre of the band), not "10 of 10 on five". `primary_sludge`
at 1.470 against the 1.5 limit — 2 % of margin — is now named in the report as a row to
watch, beside `biogas_mean` at 1.45.

---

## 2026-09-10 — RULING (the lead): dissolved species scale with the liquor, not the solids

**An APPROVED CHANGE TO A FROZEN COMPONENT**, and a further amendment in the ruling-3 /
M2 thread. It fixes review finding **B2** of 2026-09-09 at the root.

### The defect

The catalogue declares `s_cat`, `s_an`, `tan`, `s_ic` and `s_ca` **per m³ of wet feed**, at
the catalogue entry's own total solids. `feed_concentrations` carried those numbers through
unchanged whatever a delivery's moisture was, while the free acetate came from the VFA share
of the COD — and COD scales with solids. So on a delivery drier than the catalogue entry the
stream was handed *more* acetate anion and *the same* cations.

The consequence is not cosmetic: **every stream was electroneutral only at catalogue TS**,
and its implied pH drifted with every delivery. Measured on real `AssayRecord`s before the
fix, the reported alkalinity against the fed charge: high-strength waste **15.2 %** of
records outside 1.5× (worst 3.24×, assay spanning 6.12–38.03 against a charge of 11.75),
primary sludge **45.1 %**, cattle slurry **27.2 %**.

### The physics, and the fix

Those species are not properties of the wet feed. They are **solutes carried in its liquor**.
A delivery that arrives drier is the same solute load in less water per m³ of stream, so the
concentration per m³ moves with the liquor:

```
liquor_fraction(spec, ts) = (1 - ts) / (1 - ts_catalogue)
```

`sim/influent/mapping.py` now applies it to `S_IN`, `S_IC`, `S_cat`, `S_an` **and the free
acetate**, while the particulate classes keep following the solids as their COD does.
`total_alkalinity` and `feed_cation_charge` carry the same factor, so both sides of the
balance scale together and the ratio is **exactly** invariant to solids rather than
approximately so.

**`S_I` deliberately stays with the COD, and is flagged rather than moved.** It is a soluble
lump, so the same argument reaches it; but it carries no charge, so moving it would re-open
the `cod_per_vs` derivation and the COD assay without fixing anything this ruling is about.
For the lead, in a later session.

### Measured, before and after

Analytically over ±3 σ of each stream's `ts_log_sigma` — wider than the ±2 σ the ruling asked
for, because an exact invariance does not need a margin — every fed stream's ratio is
constant to four decimal places. Empirically on real `AssayRecord`s (3 plants × 8 seeds ×
400 d):

| stream | % outside 1.5×, before | after | worst, after |
|---|---:|---:|---:|
| `cattle_slurry` | 27.2 % | **0.00 %** | 1.31 |
| `primary_sludge` | 45.1 % | **0.00 %** | 1.43 |
| `thickened_was` | 2.8 % | **0.00 %** | 1.23 |
| `high_strength_waste` | 15.2 % | **9.26 %** | 1.82 |

### The remaining tail is a FINDING, and the band was not widened

The high-strength waste's residual **is not the solids**. Decomposed on the same records:

| high-strength waste | % outside 1.5× | worst |
|---|---:|---:|
| as reported (assay noise + true fractionation) | 9.26 % | 1.82 |
| no noise, **true** fractionation | 11.91 % | 1.53 |
| no noise, **catalogue** fractionation | **0.00 %** | **1.09** |

With the declared fractionation the ratio is 1.093 at *every* delivery. The whole tail is the
per-run **Dirichlet draw of the true fractionation**: this stream's composition is not
measured at Muscatine, so its `fractionation_concentration` is 30, which gives the declared
0.04 VFA share a standard deviation of about 0.035 — the share can plausibly double or vanish.
The assay reports the true composition; the charge is computed from the declared one; the gap
between them **is the hidden-truth mismatch the benchmark exists to contain.** Closing it
would mean deleting the thing being measured.

Note also that the tail is *smaller* with assay noise (9.26 %) than without it (11.91 %): the
noise is multiplicative and symmetric in the ratio, so it moves as many records back inside
the band as out. Nobody should read the noise as the cause.

### The guard

`tests/test_generator.py::test_the_charge_consistency_survives_the_whole_range_of_deliveries`
asserts the band at ±3 σ **and** that the ratio is constant to 1e-3 across that range.
Mutation-checked, with the mutants built and run:

| mutant | caught |
|---|---|
| the acetate back on the solids (the shipped defect) | **yes** |
| `liquor_fraction` inverted | **yes** |
| `liquor_fraction` always 1.0 — no scaling at all | **yes, but only by the second half** |

The third is the one worth recording: an invariance test **cannot** distinguish the correct
scaling from *no* scaling, because both leave the ratio constant. That is why the test also
asserts the physics directly — a drier delivery carries less of every solute per m³ and more
of every particulate class. Written down because a guard described as tighter than it is
would be worse than the one it replaces.

**Alternatives.** Widen the band to swallow the tail (rejected by the ruling, and it would
hide the fractionation spread that is the actual content); scale the dissolved species by the
solids too (rejected: it is the wrong physics and would double the drift); leave the
catalogue-TS invariant and document the drift (rejected: the assay a workflow reads is the
one that has to be right).

---

## 2026-09-10 — RULING (the lead): grass silage at pH 4.28 is ACCEPTED

**Decision.** `grass_silage`'s declared pH of **4.28 is accepted**, not treated as an outlier
or a workaround. Grass silage is a **fermented, lactic-acid-preserved feed**; a pH in the low
fours is what it physically is, not an artefact of a charge balance.

**Why it came up.** It was the one stream of the four B1 breached that could **not** be fixed
by pairing `s_ic` to its cations. At pH 4 bicarbonate sits four pK units below `pK_a1`, so no
amount of inorganic carbon balances anything — silage juice cannot hold bicarbonate; it would
evolve CO₂. Its own charge balance closes at 4.28, so the **declared pH** moved and the
composition did not. 4.28 is inside McDonald, Henderson & Heron 1991's cited 3.8–4.3 for
well-preserved grass silage, which the catalogue already cites for this field.

**Nothing the simulator is fed changes.** The declared feed pH is read only by the two visible
assays (`ph` and `alkalinity`), never by the truth model, so this moves the operator's record
and not the digester.

---

## 2026-09-10 — RULING (the lead): `s_ca` is dissolved calcium and is DERIVED, not cited

**A further amendment in the ruling-3 / M2 / B1 thread, replacing the "cited sludge-liquor
value" instruction of earlier the same day.** An approved change to a frozen config on every
catalogue stream, and the change that let B1 land.

### The unit check, done before anything was edited

Ca is 40.08 g/mol and 1 mol/L is 1 kmol/m³, so g Ca/L ÷ 40.08 = kmol/m³: 0.05–0.15 g/L is
**0.00125–0.00374 kmol/m³**. The catalogue carried 0.01–0.04 kmol/m³, i.e. **0.4–1.6 g Ca/L**
— flow-weighted 1.51 (A), 0.51 (B), 0.80 (C) g/L. The correction is a **reduction of 10–30×**,
confirmed independently against the coordinator's own conversion before it was applied.

### Why the old values were wrong

`s_ca` is declared in the schema as **dissolved** calcium. The values it held read like
**total** calcium: cattle slurry really does carry ~1.5 g Ca per litre, but almost all of it is
in the solids and in calcite and calcium-phosphate precipitate, not in solution. Dissolved
calcium is capped by calcite solubility at circumneutral pH. Only the dissolved quantity
belongs in a charge balance, and counting the total-sized number doubled the sludges'
cation charge — which is what pushed 0.17 kmol C/m³ of extra bicarbonate into Plants B and C
in the first B1 attempt and showed up as CO₂ in all three of its stop conditions.

### The derivation

For **primary sludge, thickened WAS and cattle slurry** (calcite-buffered streams), `s_ca`
and `s_ic` are solved **jointly** at the stream's declared pH:

1. electroneutrality — `total_alkalinity(s_ic) = feed_cation_charge(s_ca)`;
2. calcite saturation — `s_ca = SS × K_sp / (γ² × [CO₃²⁻](s_ic, pH))`.

`K_sp` is the truth model's own `pK_sp_calcite` (Plummer & Busenberg 1982; 8.480 at 25 °C —
the feed is taken cold, stated rather than tuned). `pK_a2` is the shared 10.33. **γ = 1 at
the feed is ASSUMED**; the truth model's ionic-strength correction would lower γ and raise the
saturated calcium somewhat. **SS = 2.5 is ASSUMED**, the middle of the ruled 2–3× bracket;
the bracket moves primary sludge's value 0.169–0.232 g/L, WAS 0.022–0.032, slurry
0.0015–0.0023. **Mechanism**: calcite precipitation in slurry is calcium-controlled because
carbonate is in excess — Hjorth, Christensen, Christensen & Sommer 2010, *Agron. Sustain.
Dev.* 30:153–180 (doi:10.1051/agro/2009010), as the lead directed. The citation was verified
to exist; the passage was not readable from this session (403), so the mechanism attribution
is the lead's and is recorded as such.

For the streams calcite does not govern the values are **declared assumptions, flagged**:
grass silage (pH 4.28) **0.2 g Ca/L** from the ruled 0.1–0.3; high-strength waste and FOG
**low**, 0.05 g/L and 0; `food_waste` treated as the HSW is (the ruling did not name it; no
plant feeds it).

| stream | pH | `s_ic` old → new | `s_ca` old → new, kmol/m³ (g Ca/L) | implied pH old → new | ratio |
|---|---:|---:|---:|---:|---:|
| `primary_sludge` | 6.0 | 0.04 → **0.1140** | 0.0200 → **0.00503** (0.80 → 0.20) | 12.16 → 6.00 | 1.000 |
| `thickened_was` | 6.8 | 0.04 → **0.0560** | 0.0200 → **0.00068** (0.80 → 0.03) | 12.48 → 6.80 | 1.000 |
| `cattle_slurry` | 7.5 | 0.05 → **0.1249** | 0.0400 → **0.00005** (1.60 → 0.002) | 10.05 → 7.50 | 1.000 |
| `grass_silage` | 4.28 | 0.0 | 0.0200 → **0.00499** (0.80 → 0.20) ASSUMED | 4.28 → 4.20 | 0.771 |
| `high_strength_waste` | 7.0 | 0.1607 → **0.1638** | 0.0100 → **0.00125** (0.40 → 0.05) ASSUMED | 7.00 | 1.000 |
| `food_waste` | 5.1 | 0.0 | 0.0150 → **0.00125** (0.60 → 0.05) ASSUMED | — | 1.018 |
| `fog` | 5.0 | 0.0 | 0.0 | — | floor |

`s_cat` did not move on any stream. The **plausibility check** — the sewage-liquor range
0.05–0.15 g/L — is met flow-weighted on Plant B (0.083 g/L) and Plant C (0.138); Plant A is
below it (0.026) because slurry at pH 7.5 is carbonate-rich and calcite pins its dissolved
calcium low, which is the mechanism working. Primary sludge alone sits just above the range
(0.20 g/L, 0.17 at SS = 2): at pH 6.0 carbonate is scarce, so calcite allows more calcium in
solution. Reported, not adjusted.

**Silage** keeps its accepted 4.28 (ruling 3 of 2026-09-10). With the assumed calcium its
balance would close at 4.20, and at 4.28 it now carries slightly more acetate anion than
cations — 0.771×, inside the band. Recorded rather than moved, because the ruling named the
pH.

### B1 redone against the corrected calcium — and both of the lead's tests passed

The lead set two tests of whether the correction was right: `biogas_mean` back inside its
declared band, and the B/C loaded-and-control pair restored. Neither was tuned towards.

| | before M2 | after the first B1 attempt | **after this ruling** | bound |
|---|---:|---:|---:|---|
| `biogas_mean` ratio | 1.45 | 1.532 ✗ | **1.489** | 0.6–1.5 — inside, 0.7 % of margin |
| `ch4_fraction_median` | 0.700 | 0.666 | **0.680** | — |
| `digester_pH_median` | 7.262 | 7.212 | **7.232** | ± 0.4; ruling 3's ~7.3 |
| `alkalinity_median` | 5.125 | 5.131 | **5.116** | calibrated; ruling 3's ~5.0 |
| `vfa_median` | 0.7778 | 0.7834 | **0.7804** | 0.25–4 |
| `fos_tac_median` | 0.1501 | 0.1511 | **0.1507** | 0.5–2 |
| Plant B sound | 24/24 | 24/24 | **24/24** | acceptance condition |
| B/C pair, pH C vs B | 7.336 > 7.269 | 7.196 < 7.216 ✗ | **7.252 > 7.238** | restored |

**All 23 anchored rows inside their declared bounds; no tolerance touched.** Per plant at
the declared median feed, before → after: A pH 7.681 → 7.656, CH₄ 0.658 → 0.612; B
7.269 → 7.238, 0.697 → 0.675; C 7.336 → 7.252, 0.687 → 0.619.

**B2 band on real `AssayRecord`s** (3 plants × 8 seeds × 400 d), share outside 1.5×, original
→ after the liquor fix → after this ruling: cattle slurry 27.2 → 0.00 → **0.00 %**; primary
sludge 45.1 → 0.00 → **0.31 %**; thickened WAS 2.8 → 0.00 → **0.00 %**; high-strength waste
15.2 → 9.26 → **0.88 %** (worst 1.65×). The HSW residual is the true-fractionation draw
(previous entry); the band was not widened.

**The four hidden-state trigger rows**, 24 seeds each, cut-off 2.00× everywhere:

| plant | baseline | pooled | per-run | fires in | previous |
|---|---|---:|---|---:|---:|
| B | — | **7.67 %** | 2.65–16.56 % | 24/24 | 7.70 % |
| C | — | **9.22 %** | 6.62–16.56 % | 24/24 | 9.96 % |
| A | `unadapted` | **1.49 %** | 0.00–3.97 % | 21/24 | 2.54 % |
| A | `adapted` | **0.28 %** | 0.00–1.32 % | 7/24 | 0.52 % |

Both Plant A rows fell — slurry's inorganic carbon more than doubled, so its buffer is
deeper and relative excursions rarer — and the pathway ratio between them **widened**, 4.9× →
**5.3×**. A finding about the pathway rather than the feed should survive a change to the
feed that moves both its numbers, and this one did. The VFA-ratio p92 column of the earlier
table was not re-measured and is left blank in the report rather than carried over.

**Not re-measured here, flagged**: Plant A's baseline tables in `configs/plants/plant_A.yaml`
(X_ac, X_sao, acetate, the TAN bands) were measured on the old slurry feed. Both baselines
ran 24/24 sound on this panel with pH 7.62–7.76, and nothing changed the feed nitrogen, so
the TAN bands are not expected to move; the population numbers may have. For a later
session before anything depends on them.

### Guards and tests

`COMMITTED_FEED_ALKALINITY` moved with every stream and its docstring says why.
`tests/test_influent.py::test_mixed_influent_is_flow_weighted_and_cod_consistent` carried a
pin on Plant C's flow-weighted `S_ca` at the old 0.02; it now derives the expectation from
the catalogue and asserts the ruled direction (below 0.02), so it stays a test of
flow-weighting rather than of a number. `pytest -q` 339 passed, `-m g1` 13 passed.

**Alternatives.** Cite a sludge-liquor number and apply it across the catalogue (rejected by
this ruling: three streams are not sludge, and a citation attached to a stream it does not
describe is a false attribution); lower `s_ca` only where the balance failed (rejected: the
field was wrong in kind everywhere, not in size on four streams); fit SS or γ to land biogas
further from its bound (rejected: the lead's tests are of the physics, and tuning towards
them would make them meaningless).

---

## 2026-09-10 — CLOSE-OUT (the lead): Plant A's baselines re-measured on the current feed; the rows to watch

**The lead accepted the pre-regeneration report and closed M2 at `c8c048f`.** Final close-out
steps, in the lead's order: re-measure Plant A's baseline tables, fast-forward the side branch
into PR #15's branch, record the rows to watch, regenerate the matrix at the final head as the
last action, then stop for the independent whole-branch review at that head.

### Plant A's two baseline tables, re-measured

The calcium ruling (cattle slurry's dissolved calcium 0.04 → 0.00005 kmol/m³, its paired
inorganic carbon 0.05 → 0.1249) and the liquid-fraction generator fix both changed what Plant
A is fed, so the tables in `configs/plants/plant_A.yaml` were stale. Re-measured the way they
were measured originally — the full harness, 400-d burn-in, 180-d horizon, seed 1000, medians
from day 30:

| baseline | | X_ac | X_sao | SAO share | acetate | pH | CH₄ | TAN p10 / median / p90 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `adapted` | was | 1.129 | 6.9e-05 | 0.000 | 0.038 | 7.80 | 0.688 | 3.588 / 3.695 / 3.788 |
| | **now** | **1.065** | **6.9e-05** | **0.000** | **0.037** | **7.73** | **0.629** | **3.640 / 3.703 / 3.771** |
| `unadapted` | was | 9.9e-05 | 0.910 | 1.000 | 0.240 | 7.79 | 0.692 | 3.505 / 3.605 / 3.689 |
| | **now** | **0.0019** | **0.853** | **0.998** | **0.240** | **7.72** | **0.628** | **3.556 / 3.614 / 3.677** |

**What moved and by how much.** TAN within 0.01 on both — nothing changed the feed nitrogen,
so the TAN bands the rulings of 2026-09-09 accepted (3.1–3.7 adapted, 3.5–3.7 unadapted) still
hold. pH down 0.07 and CH₄ down 6 points on both: the slurry's missing inorganic carbon now
arrives and leaves as CO₂, the same mechanism that moved Plants B and C. Biomass down about
6 % on both. The unadapted acetoclasts are 19× the old value (0.0019 against 9.9e-05) but
still 0.2 % of the acetate-consuming biomass — washed out, as declared.

**The lead's stop condition was not met**: the adapted baseline is still acetoclastic-dominated
and the unadapted one still SAO-dominated, so **`K_I_nh3` was not touched**. Both are sound
digesters. The yaml carries the new numbers with the old ones beside them.

### The rows to watch, as ruled

**Anchor side: `biogas_mean` at 1.489 against a declared band of 0.6–1.5, band UNCHANGED.**
Named in the G1 report as the row with the least margin. The extra gas is CO₂, not methane —
the inorganic carbon the catalogue was missing now leaves through the gas — so it is the
expected consequence of the correction rather than a new realism problem, and it is the first
row the next thing that raises gas will breach.

**Catalogue side: re-checked after the redistribution, and it is no longer `primary_sludge`.**
Every derived stream sits at 1.000×; `food_waste` at 1.018×; **`grass_silage` at 0.771×** is
now the closest to a band edge (1.5× either way), because the ruling kept its accepted pH of
4.28 while its assumed calcium fell and its balance would close at 4.20. Inside the band,
reported rather than moved. `primary_sludge`, which was 1.470× before B1, is exactly on the
balance.

### Sequence and what comes after

The side branch was a clean fast-forward (merge-base `fd76983`, checked); the re-measure
landed once, on the merged branch. Next: commit, push, CI green, **then regenerate the matrix
at that head as the last action**, report the head SHA, cell count, wall-clock, the index line
count, the four trigger rows and the operator-visible rate on the regenerated matrix — and
stop. Nothing is pushed after the regeneration unless the coordinator asks, so every
manifest's `git_sha` matches the head that is merged. The independent whole-branch review is
redone at that head (the earlier one covered `f8b27c4`, before any of the M2, B1, B2 or
calcium work), its verdict goes to the lead, and only then does the coordinator merge and tag.

---

## 2026-09-10 — The independent whole-branch review at `f8b27c4`: five blockers, two fixed, three with the lead

**The regeneration is HELD** (the coordinator, 2026-09-10). The review found five blockers in
code no later commit touched. Two of them change what a regeneration writes, so the matrix
cannot be regenerated until they are settled. Every finding below was verified at the source
in this session before anything was done about it; the two the coordinator marked *no ruling
needed* are fixed on `claude/g1-review-blockers` (branched at `0cf564a`) and not pushed to
PR #15; the three that need a ruling are untouched.

### Verified, awaiting the lead's ruling — nothing changed

**B1 — the run id is invertible (rule 1).** `sim/run/layout.py:101–123`: `run_id` is the
SHA-256 of `"ad-agentbench/g1|<scenario>|<plant>|<tier>|<seed>|<replicate>"`. The salt is a
repository literal, the scenario ids and seeds are committed, and plant and tier are in the
visible manifest, so the space is enumerable — the review brute-forced 1,440 hashes and
recovered `run_6ebcad561b75 → S6-01/unadapted` and `run_14c87b1772ec → S6-04/adapted`. Every
`REDACTED_FIELDS` entry and the answer key follow from the scenario id, so the opacity §10
relies on is not there. **Needs a ruling on the id scheme** (a per-store secret salt kept
outside the repository, or an id drawn from the run's seeded RNG and stored only
truth-side); it changes every run id, so it must land before regeneration.

**B3 — the foaming flag never fires.** `sim/observation/channels.py:694`:
`foaming = (fos_tac > 0.30) & (gas > ratio × trailing)`, on the **titrimetric** `fos_tac`
channel. That channel has a structural floor near 0.13 (the bicarbonate carry-over) and the
24-seed panel puts it at 0.138–0.184 in every sound run; the panel records
`foaming_day_fraction` 0 everywhere, and the foaming stress multiplier is dead in every cell.
The same class of defect as the 1000× VFA bug: a mechanism silently disabled. **Needs a
ruling** — the obvious shape is the hidden-state trigger the lead already chose for overload,
but the threshold is the lead's.

**B5 — the baseline redaction is defeated.** Redacting `baseline` from the manifest does not
hide it: `configs/plants/plant_A.yaml` publishes per-baseline acetate and TAN tables, the
committed scenarios publish baseline → `correct_conclusion`, and the Tier-C `vfa_ac` sensor
reads the **true** speciated acetate (`sensors.yaml:387–413`: only `vfa_total` went
titrimetric; `vfa_ac/pro/bu/va` did not). Through `open_run` alone, `vfa_ac` median 0.1341 on
S6-01 against 0.0253 on S6-04, 5.3×. **Needs a ruling on the visible-information contract.**

### Fixed, no ruling needed — on the side branch, mutation-checked

**B2 — `calls.jsonl` hashed the scenario id (rule 1 broken through rule 3), and it was
wider than the finding.** `runs/<id>/calls.jsonl` is workflow-visible and its `args_hash`
covered the real arguments of *every* harness call, not only the segments: `sim.generate_influent`
hashed the derived influent seed and the influent fault plan as a string; `sim.burn_in` the
realised mixing structure; `sim.channel_series` the scenario id; `sim.observe` the observation
seed and the observation fault plan; and each segment its scenario id, index and span, so
the *count* of segment records said whether a parameter fault existed. All over small public
spaces; `75fbaaa4b387afcc` inverted to `('S0-01', 0, 0.0, 180.0)` on a real run.

*The fix.* The record is kept twice (`sim/run/harness.py::RunLogs`). The **full** log lives in
`truth_store/<id>/calls.jsonl` with the real arguments and every segment — the evaluator's
copy, since rule 3 says evaluation reads logs only. The **visible** log in `runs/<id>/` is a
projection: the same calls in the same order with the same timings and outcomes, hashed over
nothing the visible manifest does not already state (plant, tier, horizon, the committed
burn-in length, the output length), and the segment integrations collapsed to **one**
`sim.simulate_truth` record whatever the segment count. Both logs start **fresh** on every
generation (`CallLog(..., fresh=True)`), which also closes the non-blocking finding that a
regenerated cell appended to its previous log (`seq` 0..9 for one cell generated twice); the
tool registry's later appends continue the sequence exactly as before.

*The tests* (`tests/test_run_harness.py`). Every visible `args_hash` is **reproduced from the
redacted manifest and the committed config alone** and must match; the truth-side log's
hashes are disjoint from the visible ones and its `channel_series` record hashes the scenario
id in — the negative control, so a redaction that emptied both logs cannot pass; on an S5-01
run integrated past its onset the full log has one record per segment and the visible log
exactly one; a cell generated twice has the same line count and `seq` 0..n−1.

**B4 — the AST checker missed the layout API.** `tests/test_truth_isolation.py` flagged only
imports of a `truth`/`truth_store` module and string literals with `truth` as a path segment.
`from sim.run.layout import RunPaths; RunPaths.for_run(id).truth / "faults.json"` spells no
such string, and the review's three-line module read S6-01's answer key with zero
violations. *The fix:* any import from `sim.run.layout` (by module, by `from sim.run import
layout`, or by name), the names `truth_store_for` / `TRUTH_STORE_DIR` / `TRUTH_STORE` /
`RunPaths` however reached, and any attribute access spelled `truth…` are violations. The
review's module is planted verbatim in shape and must be caught; seven distinct routes are
planted one per line and each line must be flagged (the first draft missed `from sim.run
import layout` and this test caught it); a module using only `open_run` must stay clean.

*Mutation results, each mutant built and run, not reasoned about:*

| mutant | test | result |
|---|---|---|
| scenario id added to a visible hash | `test_the_visible_log_says_nothing_the_manifest_does_not` | **fails** |
| logs not started fresh | `test_regenerating_a_cell_starts_its_logs_over` | **fails** |
| a visible record per segment | `test_the_visible_log_collapses_the_segments` | **fails** |
| checker without the attribute rule | `test_checker_catches_the_layout_api_bypass` | **fails** |

### Non-blocking, no ruling needed — done on the same branch

- **Generation order.** `generate_matrix` ran the cells in scenario-id order, so the public
  `created_utc` stamped the run set in ladder order and a sort by timestamp recovered each
  cell's rung. The *execution* order is now a seeded shuffle (`MATRIX_ORDER_SEED`, fixed and
  declared, rule 4); results are still returned in the order the cells were given.
  **Corrected at the final review (F1, 2026-09-10): this closed nothing.** A shuffle seeded
  with a committed constant over the public library is a reproducible permutation — the
  reviewer reproduced it — so the public timestamp still mapped position to cell exactly.
  The fix is in the entry "Final review at `99a8947`" below: the order is keyed with the
  store's secret salt AND the timestamps are gone from the visible surface.
- **`write_index_entry`** rewrites the id → cell map through a sibling temp file and
  `os.replace`, so a reader or a second generator never sees a half-written index.
- **Two stale notes** corrected: `sensors.yaml` still said the titrimetric transfer function
  was "NOT YET IMPLEMENTED"; the `channels.py` module docstring still defined `fos_tac` as
  true VFA over alkalinity.
- **The equalisation tank** is initialised from the whole-horizon mean of arrivals, so a
  future influent fault that changes deliveries after its onset would move the day-0 outflow.
  Dormant: no frozen scenario injects such a fault on a plant with a tank. **Recorded in the
  code and here, not changed** — the fix (initialise from the first hold-up window) moves
  every Plant B cell and is the lead's call.

`pytest -q` 345 passed, 2 skipped; `pytest -q -m g1` 13 passed; ruff clean.

## 2026-09-10 — The lead's rulings on the five review blockers, applied

The lead ruled on all five blockers of the whole-branch review at `f8b27c4` (relayed by the
coordinator 03:32 UTC). Every ruling is applied on `claude/g1-review-blockers`; every new
guard was mutation-checked by building the mutant and running the test, and the results are
tabulated below. The four-row measurements the rulings asked for were taken at the code
version that carries them and **recorded, not tuned**. Nothing was regenerated before the
rulings landed; the regeneration is the last action on the branch, after CI.

### B1 — the run id is a keyed HMAC over the public cell, with a per-store secret salt

**Ruling.** The id stays a truncated hash over the existing public tuple, but keyed: a
per-store secret salt generated at store creation with `secrets.token_bytes`, stored only at
`truth_store/salt`, gitignored, never in any manifest, log, index or visible file. Run ids
are therefore store-specific and the truth-side index is the only way back.

**Done.** `sim.run.layout.store_salt` reads or creates the 32-byte salt;
`run_id(..., key=)` is `HMAC-SHA256(salt, "scenario|plant|tier|seed|replicate")[:12]` and
refuses an empty key; `/truth_store/salt` is gitignored explicitly; the harness keys every id
with the salt of the store it writes to. The repository-literal salt is gone.

**Tests, each of the three the lead required.** (a) Every cell of the public tuple space
(every committed scenario × 3 plants × 3 tiers × 3 replicates, > 100 cells) gets a
different id under two salts, with no collisions under either. (b) Every file under
`runs/<id>/` is scanned for the salt as bytes and as hex, the scenario id as text, the seed as
any integer JSON value, and `seed`/`scenario` as any key or log field — none is there. (c)
The review's attack, run for real: the whole public tuple space is hashed under the old
scheme (the repository-literal salt, which recovered two ids at review) and under three
plausible wrong keys, and none matches a real id; the **negative control** hashes the same
space with the store's salt and finds the cell exactly once. The fresh-process determinism
test now runs its three generations in one store and checks the second-store case
separately: same record, different id.

**The additions to B2 the lead attached.** The visible call projection hides segment counts:
one visible `sim.simulate_truth` record per invocation, no segment index, no per-segment
span. Tested by generating S0-01 and S5-01 (integrated past its onset, so the truth-side log
has ≥ 2 segment records) and asserting the visible logs have the same record count, the same
names in the same order and the same field set.

### B3 — foaming is a hidden-state trigger; the 0.30 threshold stays visible and unwired

**Ruling.** Foaming fires on gas > 1.80× its 30-day trailing median **and** true VFA above
its own 30-day trailing median, both with the overload convention (previous 30 samples,
current excluded). Measure on all four rows, record, do not tune. The operator-visible
FOS/TAC > 0.30 flag stays visible but unwired; its structural deadness (titrimetric floor
~0.13–0.14) is written up as a measurement-model finding in the report and the card.

**Done.** `condition_flags` takes `gas_surge_ratio`, `gas_median_window_d` and the new
`foaming_vfa_ratio` and no longer takes `fos_tac_foaming`; it does not read the `fos_tac`
channel at all, and a channel set without that channel is accepted (tested). One trailing
VFA reference serves both flags. `sensors.yaml`: `gas_surge_ratio` 1.35 → **1.80**,
`gas_median_window_d` 14 → **30**, `foaming_vfa_ratio` **1.00** (schema: ≥ 1, foaming needs
VFA *above* its median), `fos_tac_foaming` 0.30 kept and marked operator-visible only. The
panel reports the foaming trigger and the 0.30 exceedance beside the overload pair.

**Measured, four rows, 24 seeds each, 180 d, clean Level-0, settled from day 30:**

| Plant | baseline | sound | overload trigger | foaming trigger | per-run range (foaming) | runs that foam | FOS/TAC > 0.40 | FOS/TAC > 0.30 |
|---|---|---|---:|---:|---|---:|---:|---:|
| B | — | 24/24 | 7.67 % | **7.20 %** | 1.32 – 16.56 % | 24/24 | 0.17 % | 0.25 % |
| C | — | 24/24 | 9.22 % | **7.67 %** | 3.97 – 11.92 % | 24/24 | 0.00 % | 0.00 % |
| A | `unadapted` | 24/24 | 1.49 % | **0.14 %** | 0.00 – 0.66 % | 5/24 | 0.00 % | 0.00 % |
| A | `adapted` | 24/24 | 0.28 % | **0.25 %** | 0.00 – 1.32 % | 7/24 | 0.00 % | 0.00 % |

**Reading the foaming rows.** On B and C the foaming trigger fires at about the overload rate (7.20 % and 7.67 % against 7.67 % and 9.22 %), in every sound run, with per-run ranges of the same width: on a batch-fed plant a top-decile gas day is usually a day the acids are also up, because both follow the arrival of a large delivery. They are not the same days — the flags are computed separately, and the missingness model compounds the multipliers when they coincide — but they are the same kind of event. On Plant A both rows are far below B and C, as overload is, and the pathway ordering **reverses**: the `unadapted` (SAO) baseline overloads 5.3× more often than `adapted` but foams *less* often (0.14 % against 0.25 %, 5 against 7 firing runs of 24). The foaming trigger needs a gas surge, and gas surges on Plant A follow the weekday silage feeding, which is the same on both baselines; what the SAO baseline adds is VFA excursions that relax slowly *after* the load rather than gas that rises with it, so its extra overload days are not gas-surge days. Two panels of 24 runs at rates below 0.3 % are thin evidence and this is recorded as an observation, not a finding. Nothing was tuned: 1.80× and 1.00× are the lead's figures as written. identical to the overload table above to the last digit. That is the check that nothing in the B1, B3 and B5 changes moved the simulator: the run-id scheme, the foaming rule and the location of the plant record are not inputs to the truth model.

**Tests.** The plain-definition check on an irregular grid covers both flags with the current
sample excluded from both windows, and re-runs the flags on a channel set with no `fos_tac`
at all; a gas surge while the VFA is stepping up fires, the same surge fifty days later on a
settled VFA does not, dropping either condition puts the flag out, and a surge that persists
past the window becomes its own median and stops; the reported ratio pinned at 5.0 raises
nothing and pinned at 0.001 does not stop the flag.

| mutant | result |
|---|---|
| the old rule (`fos_tac > 0.30` in place of the VFA condition) | **fails** |
| gas surge alone, VFA condition dropped | **fails** |
| VFA condition inclusive (`>=`) | **fails** |
| gas window including the current sample (the old convention) | **fails** |
| gas ratio read from the overload ratio | **fails** |
| `foaming_vfa_ratio` ignored (overload ratio used) | **fails** |

### B5 — option two: the visible-information contract

**Ruling.** (i) Speciated VFA sensors stay true-plus-noise. (ii) Strip every per-baseline
numeric table from the visible `configs/plants/plant_A.yaml`, declare the two community
states qualitatively, move the numbers to a truth-side plant record the harness reads (not
in `configs/`). (iii) Bar workflows from `scenarios/` with the same AST and runtime checks as
truth. (iv) The benchmark card states what a workflow may and may not see.

**Done.** (ii) `Baseline` is `name`/`description`/`note`, extra fields forbidden;
`PlantConfig.adaptation` is gone; `sim/plants/truth/plant_A.yaml` (schema and loader in
`sim.plants.truth`, both spelling `truth`) carries `K_I_nh3`, the expected digestate TAN and
the measured table of each baseline, and `load_plant_truth` refuses a record whose baselines
are not exactly the contract's, or a plant that declares baselines without a record;
`apply_adaptation` resolves the name against the contract and the constant against the
record. The record is deliberately not under `configs/` (the visible contract) and not under
`truth_store/` (per-run truth): it is a property of the plant. (iii) `scenarios` joins
`truth`/`truth_store` in the checker's module set and path regex; ten routes planted one per
line (both import forms, the schema module, the aliased import, path literals in every
spelling including upper case and traversal, the plant record's path, and the record's
loader by attribute) are each flagged, while prose containing the word stays clean; the
loader bypass suite asks for the scenario files and the plant record by traversal and is
refused. (iv) Benchmark card §4.1.

**Guards.** No visible plant file spells `K_I_nh3`, `X_ac`, `X_sao`, `expected_digestate_tan`
or `adaptation:` anywhere — code, comment or prose; no baseline description or note carries a
digit; the schema cannot load a table. The truth record is the negative control: it spells
all of them and the harness reads the constant from it.

| mutant | result |
|---|---|
| `adaptation: {K_I_nh3: 0.02}` restored in the visible file | **fails** (schema and sentinel) |
| the measured table restored as a YAML comment | **fails** |
| a number written into a baseline's description | **fails** |
| `scenarios` dropped from the checker's module set | **fails** |
| `scenarios` dropped from the checker's path regex | **fails** |

### B2 and B4 — approved as prepared

No change beyond the B2 addition recorded under B1.

### Carried

The non-blocking items (seeded execution order, atomic index writes, the two stale notes,
the equalisation-tank initialisation recorded as dormant) were already on the branch.

## 2026-09-10 — Final review at `99a8947`: the timestamp leak (F1) and four smaller findings, fixed; F2 with the lead

The coordinator ran the independent whole-branch review at `99a8947` in parallel with the
regeneration and stopped the regeneration when the review found a leak that changes what a
regeneration writes. The regeneration was killed a few cells in and its partial output
discarded. Everything below is fixed, mutation-checked and documented; **F2 is with the lead
and nothing here touches it**: the public horizon partitions the ladder (180 d for Levels 0–4
and 8, 240 d for Levels 5–7), durations cannot change after the tag, and no scenario's
`duration_days` was changed.

### F1 — blocker: the shuffled generation order was reproducible, so the timestamps leaked

**The finding.** `generate_matrix` shuffled the execution order with a committed seed
(`MATRIX_ORDER_SEED`), but the group list is a pure function of the public library and the
seed is public, so the permutation is reproducible — the reviewer reproduced it — and a sort
of the run set by the visible `created_utc`, or by `t_utc` in the visible `calls.jsonl`,
mapped position to cell exactly. A public salt over a public space, the same class as B1,
and the "Generation order" entry above claimed it closed. It did not; that entry is
annotated.

**The fix, both halves as the reviewer preferred.** (i) The order of a *written* matrix is
keyed with the store's secret salt (`sim.run.matrix.execution_order`: a seed derived from
SHA-256 over the salt); a `write=False` generation has no store and falls back to the
declared constant, reproducibly. (ii) The wall-clock is gone from the visible surface:
`created_utc` is redacted from `PublicManifest` (it is now in `REDACTED_FIELDS`, so the
existing "no field for the answer" test covers it); the visible `calls.jsonl` is a
**projection** (`CallLog(projection=True)`) whose records carry no `t_utc` — the key is
absent, not null; and every file and directory under `runs/<id>/` is given one fixed
modification time (`VISIBLE_MTIME`, 2000-01-01T00:00Z), because an mtime is a timestamp a
workflow can read without opening anything. The complete manifest, the truth-side log and
the truth-side tree keep all of it.

**Tests.** `execution_order` on the full matrix under two salts and under none gives three
different permutations of the same groups, none the library order, each deterministic; end
to end, two stores with two salts (the second chosen by construction to give a different
order — with two groups a random pair agrees half the time) generate the same small matrix
and the truth-side `created_utc` orders each store's runs exactly as `execution_order`
predicts for its salt, while neither visible manifest nor visible log carries a timestamp.
And on a three-tier cell: the public manifest has no `created_utc` attribute, no visible
file matches an ISO timestamp, every visible file and directory has the fixed mtime; the
truth-side manifest and log do carry timestamps and real mtimes (the negative control).

### F3 — the visible runtime marked the two-zone row

The burn-in's visible arguments are identical across scenarios on a plant, but its runtime
was not (0.55 s against 1.53 s at 40 d; the integration 3.07 against 6.74 s), and S6-03 is
the only non-ideal-mixing row. The projection now carries **no `runtime_s`** either (omitted
rather than coarsened: any bucket boundary is a place two rows can straddle); the
truth-side log keeps the true value, and rule 3's runtime is there for the evaluator.

### F4 — Tier B/C logs carried no simulator calls

The tiers of a cell share one integration, so only the first tier's logs recorded it; the
evaluator, which reads logs only, saw no integration behind two of three tiers, and the
harness docstring's "each directory is self-contained" was false for the log. The shared
integration's records are now **copied into every tier's logs** (`RunLogs.copy_truth_calls`,
`CallLog.copy`: same calls, same hashes, new sequence numbers; the truth-side copy keeps the
original timestamps, the projection drops them), and the docstring says so. Tested on all
three tiers: every tier's visible log is the five-record sequence, every full log carries
the segments, the hashes up to the observation are identical across tiers, and the
observation's differs.

### F5 — `write=False` still wrote

`generate_run` called `store_salt` before the `if write` branch, so a no-write call created
`<runs_root>/../truth_store/salt` — with the default root, the repository's own truth store.
`store_salt(create=False)` now returns `None` for a store without a salt; a no-write
generation into such a store keys its id with a declared, non-secret `NO_WRITE_KEY` (the id
names nothing on disk), and into a store that has a salt with the salt, so an in-memory
generation agrees with the written one. The salt file is created `O_EXCL` with mode
**0600**. Tested: a no-write generation leaves no directory behind; the mode is 0600;
`create=False` creates nothing.

### F6 — docs stale at the freeze

`scenarios/README.md`: the S4-02 "known gap" said the titrimetric convention was "not yet
implemented" and the flag "fires on no day at all" — both false since the rulings of
2026-09-09 — and its baseline table republished the superseded Plant A numbers and the
truth-side constant; the entry now states the measured rates and the table is qualitative,
pointing at the truth-side record. `docs/g1_anchor_report.md` §5.4 now quotes the
re-measured biomass and the detached `| *anchor* |` row is back in its table. The 2026-09-09
baseline table in this log is annotated as superseded (left as the record of the day).

### Mutants, each built and run

| mutant | result |
|---|---|
| order: salt ignored, constant seed used for a written matrix | **fails** |
| order: `generate_matrix` passes no key | **fails** |
| manifest: `created_utc` field restored on `PublicManifest` and passed | **fails** (two tests) |
| log: visible log opened without `projection=True` | **fails** |
| mtimes: not fixed | **fails** |
| runtime kept in the projection | **fails** |
| shared calls not copied into the later tiers | **fails** |
| salt created on a no-write generation | **fails** |
| salt written with the default mode | **fails** |

(A tenth mutant — `created_utc=self.created_utc` passed to a `PublicManifest` that has no
such field — survived, because `extra="ignore"` drops it: it is not a leak, and it is
recorded so the survivor is not mistaken for a gap.)

## 2026-09-11 — RULING 1 (the lead): the influent generator is prefix-stable in the horizon, and the blend tank starts from its first window

**Decision.** Two changes to frozen components, on `docs/f2_horizon_report.md` §15.
(1) `sim/influent/generator.py`: every per-feed block (delivery days, amount AR(1),
moisture AR(1), unrecorded-delivery uniforms and normals, mis-log uniforms and normals) is
drawn from its own child stream keyed by `(seed, 1 + k_feed, block)`, and each assay's
noise from `(seed, 1000 + k_feed, k_assay)`; the true-fractionation draw stays at the head
of the run's main stream and the fault layer keeps its own seed. (2)
`sim/plants/equalisation.py`: the tank's hold-up is set from the first 30 days of arrivals
(`INITIALISATION_WINDOW_D`) and its day-0 level and load from the first hold-up window,
instead of the whole-horizon mean of arrivals; the harness passes the same window for the
ash tracer's tank.

**Reason.** With one shared stream a block of length `n_days` shifted every later block, so
a change of horizon re-rolled every feed from day 0 — verified directly: the same seed at
190 and 200 d on Plant B gave deliveries that differed on every feed from day 0 — and every
horizon was a different 24-seed panel. That is what made the anchored `biogas_mean` jump by
±5 % between horizons ten days apart (1.449 / 1.523 / 1.455 / 1.551 at 190 / 200 / 210 /
220 d) and what turned the F2 horizon question into a coin flip against the row's band
edge. With the prefix-stable layout the three horizons agree within 2 % on every quantity.
The tank initialisation contributes under a percent but is horizon-dependent by
construction (recorded as dormant at the review of 2026-09-10; it was not) and a window of
one hold-up is what the tank can actually know on day 0. Rule 4 holds as before: seeded,
ordered, reproducible; the new property is that a longer run *extends* a realisation.

**Alternatives considered.** Keep the layout and record the jitter as a property of the
panel (rejected by the lead: a horizon change should not re-roll the world, and the
measurement the F2 decision needs is impossible without prefix stability); the tank fix
alone (measured in §15.1: it does not touch the jitter).

**Consequences, stated.** Every cell's realisation changes once, on all plants. The
anchored rows re-measured under the new layout at 200 d: all inside their bands except
`biogas_mean` (ruling 2). The trigger rates move (Plant B ~7.1 % / 6.6 % rather than
~8.9 % / 8.7 % at 200 d). Tests: the fourteen equalisation tests are unchanged (they call
`buffer_series` with the old default); a prefix-stability test asserts that a 90-day run
is the first 90 days of a 130-day run on Plants A and B for deliveries, moisture, logs,
fractionation and assays, with a negative control; a tank test asserts the day-0 state
does not see a late change and that the old initialisation did. The generator's
"Randomness" paragraph is rewritten to the new layout.

**Scope of the prefix-stability, for the record** (the coordinator's independent check of
`1353341`, 2026-09-11: 3 plants × 4 seeds × 4 horizon pairs including 30/31 and 200/730,
deliveries, moisture, logs, unrecorded and mislogged days, assay records, influent series,
s_ca and fractionation, and the same with S3-01's influent fault plan on Plant A — passes).
The *generator* and the *tank* are prefix-stable; a whole run is not: the harness still takes
the truth parameters, the burn-in recipe, the S_ca extension state and the inert equivalent
from the horizon's mean recipe (`sim/run/harness.py` around lines 675, 682, 695 and 771), so
runs at 190, 200 and 210 d still differed by ~2 %. The commit message's "the digester's
starting point does not depend on the run's length" was true of the tank only at that
commit. CORRECTED by ruling 6 below: from that commit a whole run is prefix-stable, the
reference window being the first 200 days of the generated influent.

**One test is red at this commit and is left red.**
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings` runs seed 11 on
Plant B for 180 d, unbuffered, and asserts the same [0.6, 1.5] biogas ratio as the anchor
row; under the new layout that seed's realisation gives 3168 m³/d against 2111, ratio
1.5004. It is the `biogas_mean` excess (ruling 2) on one seed, not a regression in the
layout: the band is the lead's to move and the test is not weakened, per the standing
rule. The g1 gate (`-m g1`, deselected by default) is red for the same reason.
## 2026-09-11 — RULING 2 (the lead): `biogas_mean` — band and basis unchanged; the investigation's result

**Decision.** The `biogas_mean` band ([0.6, 1.5] on the ratio to the anchor) and its
comparison basis are unchanged until the cause of the excess is known. Two read-only checks
were ordered and made (`docs/f2_horizon_report.md` §16); no band, basis or feed centre was
touched. The row is recorded as **the row to watch**: 1.50–1.54 on a stable 24-seed panel
at 190–210 d under ruling 1, outside its band by 0.004–0.036.

**(a) The anchor column is total metered biogas** — the sum of the flow to the waste-gas
burner and the flow to the boiler, recorded as a daily total in cubic feet (the dataset's
SCADA and LABS data dictionaries; Schroer & Just 2023, *ACS ES&T Engineering*, PMC10928704).
No CHP, no net-of-flare accounting; the basis is right in kind. The meter's conditions
(neither temperature nor pressure stated) and the equal split over two digesters remain the
declared caveats.

**(b) The hidden degradability centres.** Weighting each stream's own fractionation by the
cited conversion fractions (lipid 94.8 %, protein 71 %, carbohydrate 50.4 %; Jeganathan et
al. 2006, Davidsson et al. 2008, Ziels et al. 2016 as cited in PMC8072289; brown grease
~90 % of theoretical, Frontiers Environ. Eng. 2024), the literature implies **HSW 0.84
against the truth's 0.95** and **FOG 0.92 against the truth's 0.98**. HSW is outside its
range; FOG is at the top edge. Moving both to the literature values would cut the degraded
COD by ~7 % (they carry 70 % of the load) and take the row to ~1.43 — an estimate, not a
measurement, and one that ignores ADM1's own kinetic limits. Meter conditions (10–13 % for
a warm, slightly pressurised meter) and the seasonal window are the other two contributors.

**Not done, and why.** The HSW (and FOG) inert shares are frozen feed centres; changing
them redistributes the lipid share to keep the ±10 % COD/VS check, moves every Plant B and
C cell, and re-opens every anchored row and pin. That is the lead's decision. Recorded for
it: the finding, the estimate, and the fact that with the band unchanged the g1 anchor
gate (`test_the_biogas_the_simulator_makes_is_the_biogas_the_plant_measures`) is red at the
new layout, which the coordinator has been told.

**Alternatives considered.** Widen the band (rejected by the lead: the width is a
declaration, not a dial); re-declare the basis as a seasonally matched window (deferred:
it would change the comparison rather than the model, and the cause was to be found
first).


## 2026-09-11 — RULING 3 (the lead): the horizon is the plant's — 200 d on Plants B and C, 365 d on Plant A

**Decision.** Every cell on Plants B and C runs for 200 days and every cell on Plant A for
365, whichever row it is. The horizon is declared per plant (`horizon_days` in
`configs/plants/plant_{A,B,C}.yaml`, a required field of `PlantConfig`), a scenario file's
`duration_days` is its horizon on its own plant and is checked to equal it
(`tests/test_scenarios_library.py`), and the matrix re-times a row generated on another
plant — a Plant B row at Tier A on Plant A — to that plant's horizon before it is generated
(`sim.run.matrix.at_plant_horizon`, applied in `generate_matrix`; a mutation test asserts
the harness receives the re-timed row). The sixteen B/C rows go from 180 d (Levels 0–4, 8)
or 240 d (Levels 5–7) to 200; the four Plant A rows (S5-01, S6-01, S6-04, S7-02) from 240
to 365. The redacted manifest still carries the horizon: uniform per plant, it says nothing
the visible plant id does not already say. The anchor's output panel runs at the Plant B
horizon (`OUTPUT_DAYS = 200`); Plant A's panels pass 365 explicitly.

**Why.** Review finding F2: `duration_days` is public and its two values partitioned the
ladder — a Plant B/C run at 240 d was exactly one of the four parameter or structural
rows. One value per plant removes the partition. A year on Plant A rather than 200 d
because its transition rows need it: the SAO takeover S5-01 and S7-02 inject reaches the
recorded X_sao 0.60 / X_ac 0.46 only by day ~300 / ~350 on the current feed (ruling 4,
below); at 200 d the compound row's structural half carried 0.4 % of the acetate flux.
Plants B and C have no transition row, and 200 d keeps every fault window whole (the
latest ends at d180) with the widest margin on the anchored rows other than `biogas_mean`
(`docs/f2_horizon_report.md` §3, §13–§14).

**What moved with it, measured and recorded, not tuned.** The four-row trigger tables
(24 clean Level-0 seeds each) at the matrix horizons under the prefix-stable generator of
ruling 1 — overload B 7.12 % (2.34–16.37 %, 24/24), C 9.82 % (6.43–14.04 %, 24/24),
A-unadapted 1.02 % (0.00–3.27 %, 21/24), A-adapted 0.22 % (0.00–1.19 %, 11/24); foaming
B 6.63 %, C 8.50 %, A-unadapted 0.09 % (5/24), A-adapted 0.20 % (10/24); operator FOS/TAC
> 0.40 and > 0.30 0.00 % on every row — replace the 180-d table of 2026-09-10 (B 7.67 /
C 9.22 / A-unadapted 1.49 / A-adapted 0.28 %; foaming 7.20 / 7.67 / 0.14 / 0.25 %) in
`docs/g1_anchor_report.md` §5.4, the benchmark card, `configs/observation/sensors.yaml`,
`sim/observation/channels.py` and `scenarios/README.md`; the old values stay beside them.
The B and C rates moved with the generator layout (ruling 1), not the horizon: Plant B is
7.04 / 7.12 / 6.86 % at 190 / 200 / 210 d. The pathway finding on Plant A stands at 4.6×
(was 5.3×), the SAO baseline still firing in three times as many runs. `biogas_mean` is
1.54 at 200 d (ruling 2).

**Expected regeneration wall-clock, for the lead.** The last full regeneration of 117 cells
(44 truth integrations) took ~13 min. Plant A's 13 truth integrations lengthen by 185 d
(nine Tier-A rows, 180 → 365) or 125 d (the four ammonia rows, 240 → 365): 2,165 more
integrated days in total, against 480 more on B and C (twelve rows × 2 plants × +20 d) and
320 fewer (four rows × 2 plants × −40 d). Measured on the panels, a 365-d Plant A run took
22 s end to end (535 s / 24, both baselines) against 30 s for a 200-d Plant B run: the
cost is dominated by the burn-in and the stiff transients, not the horizon. Expected impact
of the 365-d Plant A cells: under two minutes on a ~13-min regeneration; the measured
figure is reported with the regeneration.

**Alternatives considered.** A single horizon for every cell (200 d, the held F2 edit):
removes the partition too, but leaves S5-01 and S7-02 with a takeover that does not
complete (§11–§12 of the F2 report). A single 365-d horizon: doubles the B/C cost for rows
whose windows all end by d180 and moves `biogas_mean` further out. Keeping the horizon
per row: the partition. Rejected by the lead in that order.

## 2026-09-11 — RULING 4 (the lead): S7-02 stays, onset day 120, on Plant A's 365-d horizon; the takeover verified

**Decision.** `S7-02` (SAO omitted **and** a loss of adaptation, Plant A, Level 7) stays in
the frozen library as staged — onset day 120, `adapted` baseline — on the 365-d horizon of
ruling 3. Retirement (the outcome staged on 2026-09-10 as §12's option d) and the onset-30
re-staging (§12's option c) are both off the table. The record is corrected to what the
year reaches, measured through the harness at the row's own seed under the prefix-stable
generator of ruling 1 (`docs/f2_horizon_report.md` §17):

| row | X_sao ≥ 0.60 | X_ac ≤ 0.46 | SAO half the biomass | end X_ac / X_sao (share) | acetate before → peak (day) → end |
|---|---:|---:|---:|---|---|
| **S7-02** | day 348 | day 350 | day 338 | 0.371 / 0.691 (65 %) | 0.04 → 3.91 (158) → 0.31 kg COD/m³ |
| **S5-01** | day 298 | day 302 | day 291 | 0.139 / 0.778 (85 %) | 0.02 → 3.73 (201) → 0.19 |

Both runs are sound throughout. So the 0.60 / 0.46 first recorded on 2026-09-03 "in 240 d"
— not reproducible at any commit, corrected at `3be4ef9` — **is reached on the year**, by
day ~350 for S7-02 and ~300 for S5-01. The scenario headers, the truth-side record
(`sim/plants/truth/plant_A.yaml`), the S6-01 cross-reference and the `configs/runs/harness.yaml`
note now say that, with the monthly trajectory in the S7-02 file.

**Why the row means what its header says, on a year.** The structural half of S7-02 rests on
the pathway shift; at 200 d it carried 0.4 % of the acetate flux (§11) and a fitted model
without SAO reproduced every channel. On 365 d the share is 3.8 % at day 240, 27 % at 300,
45 % at 330 and 65 % at the end: a structural residual that is a **ramp through the last
four months**, on acetate first and then on the gas as the route changes — the "ramp that
follows the growing oxidiser population" the answer key describes. The parameter half is
unchanged: a step at day 120 on the adapted baseline, acetate up 100× within forty days.
Neither the onset-30 staging (a one-month clean baseline, acetate-only residual) nor the
`unadapted` staging (the parameter fault a phantom) is needed.

**What was not changed.** No onset, magnitude, baseline, seed, budget or answer key; no
tolerance. The `kinetic_update_allowed: true` / `abstain_on` structure of the row stands.

**Alternatives considered** (the lead's ruling closes them): retire the row and design the
Level-7 compound after the freeze (§12 d); move the onset to day 30 on 200 d (§12 c,
14 % of the flux at 200 d, acetate-only residual); re-stage on `unadapted` (§11, the
parameter fault becomes a phantom); keep 200 d and accept a `structural` label with nothing
under it (rejected on 2026-09-10).

## 2026-09-11 — RULING 5 (the lead): the hidden degradability centres of the high-strength waste and the FOG set to their cited values, 0.84 and 0.92

**Decision.** Two approved feed-centre corrections in `configs/influent/feed_fractionation.yaml`,
nothing else: the high-strength waste's non-inert COD share goes from 0.95 to **0.84** (inert
0.05 → 0.16, `f_xi` 0.03 → 0.14, `f_si` 0.02; the four degradable classes scaled by
0.84 / 0.95: `f_ch` 0.0884, `f_pr` 0.0531, `f_li` 0.6631, `f_vfa` 0.0354) and the FOG's from
0.98 to **0.92** (inert 0.02 → 0.08, `f_xi` 0.06, `f_si` 0.02; classes scaled by 0.92 / 0.98:
`f_ch` 0.0141, `f_pr` 0.0141, `f_li` 0.8918). The derived COD/VS checks hold without any
further redistribution: HSW 2.057 against the measured 2.234 (−7.9 %, was 2.186), FOG 2.593
against 2.80 (−7.4 %, was 2.741). The old values are kept beside the new in the catalogue.
**The band is unchanged**, as are the comparison basis, every tolerance, every other feed
centre, seed, kinetic constant and plant value. The lead's principle: every stream's centre is
derived the same way; the point is not that the row must pass.

**Reason.** Ruling 2's finding (`docs/f2_horizon_report.md` §16): the anchor column is total
metered biogas, so the comparison basis is right in kind, and the two centres sat above the
literature. The cited values are **derived, not measured**: the catalogue's assumed composition
of each stream weighted by cited conversion-to-biogas fractions — lipid 94.8 % (Jeganathan et
al. 2006, *Water Research* 40:3141), protein 71 % (Davidsson et al. 2008, *Waste Management*
28:986), carbohydrate 50.4 % (Ziels et al. 2016, *Water Research* 103:372), as compiled in the
FOG co-digestion review PMC8072289; acetate fully — HSW 0.75 × 0.948 + 0.10 × 0.504 + 0.06 ×
0.71 + 0.04 = 0.84, FOG 0.95 × 0.948 + 0.015 × 0.504 + 0.015 × 0.71 = 0.92, the latter
bracketed by brown grease at ~90 % of theoretical (354 mL CH₄/g COD at 35 °C, Frontiers Environ.
Eng. 2024) and 0.40–0.77 m³ CH₄/kg VS removed at pilot scale (Zhang et al. 2014). Muscatine
does not measure the composition of either stream; the catalogue says so.

**Measured at the committed head** (24 clean Level-0 seeds, 200 d, the prefix-stable
generator; §19 of the F2 report measured the same variant in a scratch worktree and the numbers
reproduce exactly):

| | before (`a91e71a`) | ruling 5 at the old FOG equivalent 1.42 (§20) | **as committed: ruling 5 + answer A (FOG equivalent 2.9)** |
|---|---:|---:|---:|
| `biogas_mean`, panel median → ratio to 2111 | 3244 → 1.536 FAIL | 2860 → 1.355 pass | **2899 → 1.373 pass** |
| 24-seed mean / min / max ratio | 1.509 / 1.221 / 1.840 | 1.379 / 1.077 / 1.720 | 1.397 / 1.091 / 1.743 |
| anchored rows inside their band | 22 / 23 | 23 / 23 | **23 / 23** (`hsw_cod_concentration` 1.09 and `organic_loading_rate` 1.15 unchanged from the middle column) |
| `test_plant_b_survives_the_generator_swings` (seed 11, 180 d) | FAIL (1.5004) | pass | **pass** |
| gate G1 biogas and match-count tests | FAIL | pass | **pass** |
| gate G1 `test_no_clean_level_0_seed_sours` | pass (min CH₄ 0.655) | FAIL on its declared margin (min CH₄ 0.6429) | **FAIL on its declared margin**: 24/24 sound, min pH 7.19, max pH 7.34, **min CH₄ fraction median 0.6437 against > 0.65** (answer B, below, re-declares the margin) |
| Plant B overload / foaming | 7.12 % / 6.63 % | 7.38 % / 6.34 % | **7.55 %** (2.92–19.30 %, 24/24) / **6.60 %** (2.34–13.45 %, 24/24) |
| Plant C overload / foaming | 9.82 % / 8.50 % | identical (neither stream) | identical to the last digit (neither stream) |
| Plant A | — | unchanged (neither stream) | unchanged (neither stream); re-measured under ruling 6 |

Answer A moved the gas, contrary to the expectation that it would not: the inert COD
equivalent sets how much COD a kilogram of FOG volatile solids carries (`ts × vs_of_ts ×
COD/VS`), so at the anchor-derived 2.0 % TS the same FOG delivery now carries 2.802 / 2.593
= 8 % more COD, of which the ruled 0.92 degrades — about 1.4 % more biogas on the panel
(1.355 → 1.373); the rows that read solids move with it and stay inside their bands.

**Two more pins record this ruling, flagged.** `tests/test_influent.py` asserted the lead's
2026-09-02 HSW lipid COD share 0.7–0.75; the ruled split scales it to **0.6631** (§19.1,
approved as "variant 2 exactly"), and the assertion now pins that value with the reason.
The same file's frozen-equivalent test pinned every non-lignocellulosic inert at 1.4–1.5
and now pins FOG at **2.9** per answer A, and its PR #7 negative control is evaluated at
the sludge equivalent that split was declared with, so it still fails the check it
motivated. The docstring of `REFERENCE_WINDOW_D` (ruling 6) named the run-level test's
file wrongly; corrected in this commit.
The known consequence, as the coordinator stated it: the gate's CH₄-fraction margin trips at
0.643. **Neither that margin, the band nor any tolerance is touched here**; the margin question
is with the lead separately. The anchor report's generated block, its §5.4 tables, the benchmark
card, `configs/observation/sensors.yaml`, `sim/observation/channels.py` and `scenarios/README.md`
carry the new numbers with the old beside them.

**Answer A (the lead, 2026-09-11 ~16:00 UTC): FOG's inert COD equivalent is 2.9 kg COD/kg VS
(lipid-like), superseding the sludge value 1.42 of the 2026-09-02 freeze** — an approved
change to a frozen feed value, made in this commit. Why it was necessary: with the ruled
split (`f_ch` 0.0141, `f_pr` 0.0141, `f_li` 0.8918, `f_vfa` 0, `f_xi` 0.06, `f_si` 0.02) the
derived COD/VS is 1 / Σ(fᵢ/eᵢ) with e = 1.19 / 1.42 / 2.90 / 1.07 for the degradable classes
and the feed's inert equivalent for `f_xi` and `f_si`:

| inert COD equivalent (kg COD/kg VS) | derived COD/VS | against the measured 2.80 | inside the lead's 2.7–2.9 target? |
|---:|---:|---:|---|
| 1.42 (sludge value, 2026-09-02) | **2.593** | −7.4 % | no |
| 2.0 | 2.708 | −3.3 % | yes |
| 2.2 | 2.735 | −2.3 % | yes |
| **2.9 (lipid-like, ruled)** | **2.802** | +0.1 % | yes |

At 1.42 no split at the ruled 0.08 inert share can reach 2.7: the cap, with every non-inert
unit lipid, is 1 / (0.92 / 2.90 + 0.08 / 1.42) = **2.677**. The 2.7–2.9 test range
(`tests/test_influent.py`) and the catalogue's ±10 % check are **unchanged**; the test
passes at 2.802. The inert equivalent feeds the solids channels and the COD the feed
carries, so the Plant B panel and both edge tests were re-measured at this head (the table
above, right-hand column).

**Alternatives considered.** HSW 0.84 alone (§19 variant 1): row 1.375, CH₄ margin unchanged
at 0.655, every gate test passing — **rejected by the lead on principle** (one stream's centre
corrected and the other's not, when both are derived the same way). Holding COD/VS at the
measured value by taking the inert share from carbohydrate and protein only: changes the
composition the cited weighting was applied to (0.78 by the same weighting); not run.
Widening the band: rejected under ruling 2.

## 2026-09-11 — RULING 6 (the lead): a whole run is prefix-stable — the reference recipe is the first 200 days, whatever the horizon

**Decision.** The run's reference quantities are derived from a **fixed 200-day window** of
the generated influent regardless of horizon, at the source: the generator's
`mean_recipe_kg_d` — and with it the truth inert nitrogen `N_I` — is the mean over the first
`min(REFERENCE_WINDOW_D, n_days)` days (`sim.influent.generator.REFERENCE_WINDOW_D = 200`, a
named constant with its reason in the docstring). Everything the harness derives from that
recipe follows without further change: the truth parameters (`truth_parameters`), the
burn-in's `constant_influent`, and the channels' influent inert COD equivalent
(`influent_inert_cod_equivalent`, `sim/run/harness.py` ~line 780 — the same principle,
flagged here as the coordinator asked). The one harness quantity that was not derived from
the recipe, the calcium extension's initial state (`_mean_s_ca`, the flow-weighted mean
dissolved calcium), is now taken over the same window. 200 because it is the shorter of the
two matrix horizons (ruling 3: Plants B and C 200 d, Plant A 365 d), so every cell's
reference window is the same first 200 days. For a 200-d cell nothing changes (the window
is the horizon); a 365-d Plant A cell now takes its parameters, burn-in and calcium state
from its first 200 days rather than its whole year.

**Reason.** Ruling 1 made the generator and the tank prefix-stable; the coordinator's
independent check of `1353341` found a whole run still was not — 190, 200 and 210 d differed
by ~2 % — because the harness took its reference quantities from the horizon's mean recipe.
With the window fixed, a run is the first N days of any longer run of the same seed, which
is what "prefix-stable" has to mean for a benchmark whose horizons were just changed and
may change again: a horizon change moves the end of every run and nothing else.

**Tests.** `tests/test_reference_window.py`: (1) the window is 200 and is the shorter
matrix horizon; (2) the generator's reference recipe and `N_I` of a 210-d run equal those
of the 200-d run of the same seed and equal the first-200-day mean, not the horizon mean,
while runs shorter than the window average their whole length (90 v 130 d differ: the
negative control); (3) one whole run per matrix horizon — S3-03 on Plant B at 200 against
210 d and S5-01 on Plant A at 365 against 375 d — with truth parameters, inert equivalent,
burn-in and initial state identical, and the state trajectory, ash, every truth channel and
both condition flags **bit-equal up to the shorter run's last output point**, which agrees
to solver tolerance (the shorter run reaches it by a final step clipped to its end, the
longer by dense-output interpolation; `rtol` 1e-6). Which of the two the coordinator asked
me to report: bit-equal, except that one point. The ruling-1 prefix tests are kept.
Mutation: with `REFERENCE_WINDOW_D` set beyond every horizon (the old behaviour) tests (2)
and (3) fail.

**Re-verified at this head, Plant A on 365 d** (its runs now take their reference from the
first 200 days): the ruling-4 trajectories and the two
baseline trigger tables were re-measured. S7-02: X_sao 0.60 on day **348**, X_ac 0.46 on day
**350**, half the biomass from day 338, end share 0.6509 (was 0.6509), acetate peak 3.912 on
day 158 (was 3.912), sound; S5-01: **298 / 302 / 291**, end share 0.8483 (0.8483), acetate
peak 3.729 on day 201, sound — every day unchanged, the state values moved in the fourth
significant figure (e.g. S7-02 end X_sao 0.69099 → 0.69100). The 24-seed clean panels at
365 d: `adapted` overload 0.22 % (0.00–1.19 %, 11/24), foaming 0.20 % (10/24);
`unadapted` overload 1.02 % (0.00–3.27 %, 21/24), foaming 0.09 % (5/24); operator
thresholds 0.00 % — **identical to the ruling-3 tables to every printed digit**. The
first-200-day recipe of a Plant A run differs from its 365-d mean by too little to move a
day count; no re-staging, no number in the record changes.

**One consumer corrected, flagged.** The anchor comparison's `organic_loading_rate` row
(`anchor/compare_generated.py`) took the two-year generator draw's `mean_recipe_kg_d`, which
under this ruling would have become the first-200-day reference recipe and moved the row
from 2.171 to 2.163 — a long-run plant statistic must not follow a run's reference window,
so that row now takes the mean over the whole two-year draw explicitly and reads 2.171 as
before. The generated block of the anchor report is unchanged by this ruling (every panel
run is 200 d, so its window is its horizon).

**Correction to the ruling-1 entry above.** Its sentence "a whole run is not [prefix-stable]…
true of the tank only" described the state at `1353341`; from this commit the truth of a
whole run is prefix-stable, with the reference window the first 200 days of the generated
influent. **Corrected again on 2026-09-12** (the whole-branch review, blocker 2): this
entry's "a whole run is prefix-stable" was true of the truth side only — the visible record
was not until ruling 7 (2026-09-14, below), from which it is true of both.

**Alternatives considered.** Deriving the reference quantities from the horizon mean (the
state before): not prefix-stable. A window of the full 365 d: not available to a 200-d cell.
The burn-in recipe from the plant's declared median recipe instead of the run's own draw:
would decouple the burn-in from the realisation the run then feeds, a bigger change than
the ruling asked for; not done.

## 2026-09-11 — ANSWER B (the lead): the gate's methane-fraction margin re-declared at 0.60

**Decision.** In `tests/test_g1_anchor.py::test_no_clean_level_0_seed_sours` the assertion
on the leanest clean Level-0 seed's methane fraction median goes from `> 0.65` to
`> 0.60`. Nothing else in that test changes: 24 of 24 seeds sound, min pH > 7.0, max pH
< 7.7 stand as declared.

**What this margin is.** A test guard *above* the soundness threshold: a run is sound at a
CH₄ fraction of 0.55 (`configs/runs/harness.yaml`, `assess_health`), and the lead's
acceptance condition of 2026-09-03 added a margin so that "no seed sours" could not be
satisfied by a run one bad week from souring. It is a declared margin, not a measurement
of the plant.

**Why it is re-declared, and why not to pass a failing run.** A principled feed correction
— ruling 5, the cited HSW and FOG degradability centres (0.84 and 0.92) with answer A's
lipid-like FOG inert equivalent — moved the leanest seed from 0.655 to **0.6437** at the
committed head (0.6429 at the old FOG equivalent): taking lipid out of the most
methane-rich streams lowers the panel's leanest methane fraction by a hundredth, while
every seed stays sound (min pH 7.19, max pH 7.34, CH₄ 0.64–0.69). The feed change was made
on the lead's principle that every stream's centre is derived the same way, not to move
this number; the margin is re-declared to sit where the corrected feed puts the leanest
sound seed with room to spare, at 0.60, still 0.05 above the soundness threshold.

**Measured at the head.** Leanest-seed CH₄ fraction median **0.6437** (seed 1003), panel
range 0.6437–0.692; 24/24 sound.

**Alternatives considered.** Keep 0.65 and correct HSW alone (§19 variant 1: leanest seed
0.655, every gate test passing) — **rejected by the lead on principle**, one stream's
centre corrected and the other's not. Keep 0.65 with both corrections: the gate stays red
on a guard, not on a soundness failure. Lower the soundness threshold: not on the table.

## 2026-09-12 — Blocker 1 of the whole-branch review: the workflow-side checker is an allow-list

**Finding** (the coordinator's fresh whole-branch review at `99b0547`, reproduced by the
coordinator). The AST checker in `tests/test_truth_isolation.py` denied only the tokens
`truth`, `truth_store`, `scenarios`, `sim.run.layout`, `RunPaths`, `truth_store_for`. A
workflow-side module importing only `sim.run.matrix.load_library`,
`sim.run.harness.generate_run`, `sim.plants.load_plant_config` and `state.run_view.open_run`
passed `find_truth_references()` with `[]` and, given only the visible `runs/<id>/`, read
every scenario's answer key and seed through `load_library` and — by regenerating candidate
cells with `write=False` and matching `sensors.json` bit for bit — recovered the run's
scenario id, level and all five derived seeds. Rule 1 and ruling B5(iii) were satisfied in
letter (no file under `truth_store/` or `scenarios/` was opened by path) and broken in
substance: the generation machinery *is* the answer key.

**The route**, in one sentence: the checker looked for the *names of the hidden things*,
and the hidden things are reachable without naming them, through the public generator.

**The fix** (tests only; the runtime guard `state.run_view` is unchanged). The checker is an
**allow-list**: a module under `workflows/` may import the standard library
(`sys.stdlib_module_names`), `numpy`, `scipy`, `pydantic`, the tool registry (`tools`), its
own package (`workflows`, relative imports included) and the workflow-facing run view
(`state.run_view`; from `state` itself only `RunView`, `TruthAccessError`, `open_run`).
Every other import — all of `sim`, `scenarios`, `anchor`, `eval`, `state.provenance`,
`import state` bare, and whatever is added later — is a finding without anyone having to
foresee it. The deny rules of 2026-09-10 stay as a second layer, and the names
`scenario_id`, `seeds`, `load_library`, `generate_run`, `generate_cells`, `RunManifest` are
findings as bare names, attributes or imported names. Fixtures: the reconstructed reviewer
module is a must-fail fixture (`_SNEAKY_SOURCE`, asserted to spell none of the old tokens
and to be reported on its three `sim` imports and its uses of `load_library`,
`generate_run` and `.seeds`); a module of everything the allow-list admits must stay clean;
a module of fourteen routes just outside it must be flagged on every line; every existing
fixture is kept and passes unchanged.

**Alternative considered: extend the deny-list** with the new tokens (`load_library`,
`generate_run`, `sim.run.matrix`, …). Weaker for the same reason the last extension was:
each finding adds the tokens *that* reviewer used, and the next module uses others
(`sim.run.harness.simulate_truth`, `sim.influent.generate_influent` and a hand-written
observer, `anchor.compare_generated.output_panel`, …). A workflow has a small, known
surface — the registry and the run view — so the surface is what the checker names.

## 2026-09-12 — Blocker 1, round two: dynamic import and code execution are findings; the checker's limit recorded

**Finding** (the coordinator, 15:30 UTC, verified on `bc7b73f`/`b808939`). The allow-list
covers import *statements* only. Six modules were tried; four passed with `[]`:
`importlib.import_module("sim.run." + "matrix")` with `getattr(m, "load_" + "library")`;
`__import__("sim.run.harness", fromlist=["x"])`; `sys.modules.get("sim.run.matrix") or
__import__(...)`; and `exec(compile("from sim.run.matrix import load_library…", "<x>",
"exec"))`. A fifth, a second interpreter through `subprocess.run([sys.executable, "-c",
"from sim.run.matrix import …"])`, passed too. The sixth (`pathlib` and `yaml` over the
`scenarios/` directory, spelled `"scen" "arios"`) was already reported and stays as the
positive control.

**The fix** (tests only, `tests/test_truth_isolation.py`; the allow-list stays the first
layer). A workflow module has no legitimate use for dynamic import or code execution, so
these are denied by **name and attribute wherever they appear**: the modules `importlib`
(and any submodule), `runpy`, `subprocess`, `ctypes`, `pkgutil`, `builtins` by any import
spelling or as a bare name; the callables `__import__`, `exec`, `eval`, `compile`;
`sys.modules`; `os.system`, `os.popen`, `os.exec*`, `os.spawn*`; and `getattr`/`setattr`/
`delattr` whose first argument is not a plain name or attribute or whose second is not a
string literal (plain `getattr(obj, "literal")` stays). A **string literal, or a `+`
concatenation of literals folded at check time**, that spells a forbidden module path —
exactly `sim`, `scenarios`, `anchor`, `eval`, `state`, `state.provenance`, a dotted path
under one, or an `import`/`from` statement of one inside a string — is a finding, and so
still is a path literal with `truth` or `scenarios` as a segment. Fixtures: the six
sources verbatim, each of (1)–(4) and (6) asserted to be reported on the route it uses
(`importlib`, `__import__`, `.modules`, `exec`/`compile`, `subprocess`, and the folded or
embedded `sim.run.…` literal), (5) asserted to stay reported; and a module of ordinary
code — `getattr(view.manifest, "plant")`, `os.path`, `sys.argv`, prose strings containing
the words — asserted clean. Every earlier fixture kept.

**The limit, recorded.** A static checker cannot prove the absence of every dynamic
route: a compiled extension, an environment trick, a second interpreter reached some way
the checker does not name, code assembled from characters. What this checker does is make
every *named* route a finding and make the module say plainly what it is doing. The
structural defence is that a workflow process must not have `sim`, `scenarios/` or
`truth_store/` importable or readable at all — workflows run against `tools/` and the run
view only, in a process or container where those paths are absent. That is a **design
requirement for the tool-registry and workflow-harness components** (CLAUDE.md rule 2),
recorded here and in the benchmark card §4.1 as a deferred requirement for the lead's
launch of those components, not something G1 can enforce.

**Alternatives considered.** Denying only the four routes found: the same deny-list
mistake one level down. Rejecting any `getattr` at all: would flag the run view's own use;
the literal-name form is kept. A runtime import hook in the workflow process: the right
shape, and it belongs to the workflow harness, not to a test.

## 2026-09-12 — Blocker 1, round three and last: dunder access and obfuscated literals are findings; hardening stops here

**Finding** (the coordinator, 18:10 UTC, on `9aa2ef8`). Two more routes passed the
round-two checker with `[]` and a third was reported only as a module literal: a module
name assembled from `chr` codes and handed to `__builtins__["__import__"]`; the builtins
reached through `getattr(open_run, "__globals__")["__builtins__"]` and `vars(...)`; and
`open_run.__globals__` itself.

**The fix** (tests only, `tests/test_truth_isolation.py`). Every `__x__` as a name, an
attribute or a string literal is a finding, except the ordinary few — `__name__`, `__doc__`,
`__file__`, `__version__`, `__all__` (an export list), `__main__` (the idiom) and
`__init__` as an attribute (`super().__init__()`); the calls `vars`, `globals`, `locals`,
`dir` and `chr` are findings wherever they appear; `.decode` and `.fromhex` as attributes;
`codecs`, `base64`, `binascii`, `zlib`, `marshal` and `pickle` by any import spelling or as
names. The three sources are fixtures verbatim: (7) reported on `chr`, `__builtins__` and
the `'__import__'` literal; (8) on `'__globals__'`, `'__builtins__'`, `vars(...)`,
`'__import__'` and the module literal — the dunder route, not only the literal; (9) on
`.__globals__`. A module of ordinary dunders (a docstring, `__all__`, `__version__`,
`__file__`, a class with `super().__init__()`, the main idiom) stays clean. Every earlier
fixture kept: 54 tests in the file.

**Hardening stops here**, by the coordinator's instruction. The round-two entry above
records why: a static checker cannot prove the absence of every dynamic route — these
three are the point at which the rounds were stopped, not the last routes that exist — and
the structural defence is a workflow process in which `sim`, `scenarios/` and
`truth_store/` are neither importable nor readable, a design requirement for the
tool-registry and workflow-harness components (rule 2), deferred to the lead's launch of
those components. **One unnamed sibling, recorded 2026-09-20** (the reviewer of the fresh
whole-branch review at `8909772`, a non-blocking finding fixed on the lead's approval as a
record correction, not a fourth round): `str(<bytes>, <encoding>)` — the `str(bytes,
"ascii")` form of decoding — is not among the denied `.decode` / `.fromhex` attributes, and
a checker-clean module that assembles the path at runtime and decodes with it reads
`faults.json`, `parameters.json`, `states.npz` and the salt from the sibling `truth_store/`;
this is the recorded blind spot above (a route the checker does not name), not a new class,
and the checker is not changed for it.

## 2026-09-14 — RULING 7 (the lead): the VISIBLE record made prefix-stable — every stream of the record keyed `SeedSequence([seed, key, block])` (blocker 2 of the 2026-09-12 review, option b)

**Finding** (the coordinator's whole-branch review at `99b0547`, 2026-09-12, blocker 2 of
2, reproduced). Ruling 6 made the truth of a run prefix-stable in its horizon, and the
decisions entry, §21/§23 of the F2 report and the `REFERENCE_WINDOW_D` docstring said "a
whole run is prefix-stable". That was false for what a workflow sees, and for the same
reason on each of three components — **the shared-stream shape**: one stream consumed in
sequence, so that the position of every draw depended on how many draws came before it,
and the horizon set that number. `sim/observation/model.py` drew a sensor's six
horizon-length blocks in sequence from one per-sensor stream, and the historian its two
blocks from one stream, so every visible sensor series of a 200-d Plant B cell differed
from the 210-d cell's from index 0; and `sim/run/notes.py` drew the operator-note days
with a horizon-sized `rng.choice`, so the note days moved with the horizon.

**Decision (the lead, 2026-09-14 05:57 UTC: option b).** Every stream of the visible
record is a child stream keyed by what it is for, in the shape of ruling 1, and no stream
is consumed by more than one block:

- each sensor's six blocks (flatline onsets, fouling onsets, drift walk, relative noise,
  absolute noise, missingness) come from `sensor_block_rng(seed, name, block)` —
  `SeedSequence([observation seed, sensor key, block])` — instead of in sequence from
  `sensor_rng(seed, name)` (kept for its identity);
- the historian's onset and length blocks come from `historian_block_rng(seed, block)` —
  `SeedSequence([observation seed, HISTORIAN_STREAM_KEY, block])`, the key a SHA-256 of
  the historian's own domain string, so it is keyed **consistently with the sensors**
  rather than by the plain integer offset `seed + 1_000_003` it had (the lead's
  requirement; the offset form the prepared option (b) still carried is retired);
- the operator log draws one uniform per day from the child stream keyed `(notes seed,
  stage 0)` and logs a benign note where it falls below `benign_per_100_d / 100`, handing
  out the texts, without repeats, in the order of a permutation from the child stream
  keyed `(notes seed, stage 1)`. **Why Bernoulli-per-day**: a Poisson count and a
  `choice` of days are both functions of the horizon, so no keying of that scheme could
  make the first n days of a longer log the first n days of a shorter one; a per-day draw
  is prefix-stable by construction. The expected number of benign notes is unchanged
  (`n_days × rate`, Binomial in place of Poisson); no two notes on one day; a run long
  enough to exhaust the catalogue stops logging benign notes.

The truth model is untouched: the state trajectory, times, ash, both condition flags and
every truth channel (27 keys) of an S3-03 cell on Plant B at tier C, generated at
`875fa2b` and at this commit, are **bit-equal**; all 15 visible sensor series of that cell
change, as they must. Every visible record changes, so the matrix is regenerated at the
committed CI-green head, on the coordinator's word, as the last action.

**Tests.** `tests/test_visible_prefix.py`, one cell per matrix horizon — S3-03 on Plant B
at 200 against 210 d and S5-01 on Plant A at 365 against 375 d, both at tier C: every
sensor series' times, values, missingness (the per-sensor process and the historian's
outages together), saturation, flatline and fouling flags bit-equal up to the shorter
run's last sample (that sample to 1e-9, as the truth's final point under ruling 6), the
operator log's note days and texts (the shorter run's notes are the longer run's notes
before its end, S5-01's false-cause note included), the feed log and the assays, with a
negative control on the comparison; and the historian mask alone, on a 15-min schedule
where outage lengths matter, prefix-stable across 200 v 210 d from the two keyed streams,
another seed giving another mask. Two existing tests changed, each with its reason in the
file: `test_observation.py`'s composite-loss lab-assay assertion was a one-sigma band that
the re-keyed seed lands outside (0.0256 against 0.02, 1.2 σ) and is now the binomial
three-sigma band plus "less than twice the rate"; `test_run_harness.py`'s "every run
carries notes" fixture generates its clean run at 100 d rather than 40 d, because under a
per-day draw a 40-d log is empty with probability 8 % and this seed's was. Every other
observation and notes test passes unchanged; `historian_outages` keeps its signature, with
the separately keyed lengths stream as an optional argument `observe` passes.

**Record corrected.** The ruling-6 entry, the `REFERENCE_WINDOW_D` docstring, §21/§23 of
the F2 report and the benchmark card (§9) now say that a whole run — truth AND visible
record — is prefix-stable, which is true from this commit.

**Alternative (option a)**: leave the visible record re-rolling with the horizon and
correct the record to "truth-side only". Rejected by the lead: a horizon change would
still be a different visible realisation of the same seed, which is what ruling 6 exists
to prevent.
