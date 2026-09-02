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

## 2026-09-02 — Plant configurations A/B/C — **proposed, not frozen** (design content for the lead)

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
