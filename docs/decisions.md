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
