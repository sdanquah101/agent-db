# ADM1 base-implementation comparison (Milestone 1, Task A)

**Status: recommendation in §6 accepted by the lead on 2026-09-02, with conditions; see
`docs/decisions.md` ("Base ADM1 implementation for the truth model").**
Session 2026-09-02. Harness and raw records: `scripts/adm1_candidates/` (`results/*.json`).
Environment: Ubuntu 24.04 container, 4 vCPU, Python 3.11.15, numpy 2.4.6, scipy 1.17.1.

## 1. What was evaluated

| Candidate | What it is | Version tested | Licence | Installed? | Probed? |
|---|---|---|---|---|---|
| **PyADM1** | Single-file Python port of the BSM2 ADM1 (Sadrimajd et al. 2021) | git `e7f806e1984a382ce6d6c17ad595561e3e8b293d` (2022-08-09) | MIT | yes (clone; numpy/scipy/pandas/matplotlib) | yes |
| **bsm2-python** | Maintained Python port of the full BSM2 plant incl. the ADM1 digester (FAU Erlangen) | PyPI `bsm2-python 0.0.16` | BSD-3-Clause | yes (`pip install bsm2-python`, ≈2 min) | yes |
| **QSDsan / EXPOsan** | Process-modelling framework (UIUC) with ADM1 as a Petersen-matrix `Processes` object, plus the ADM1-P/S/Fe extension; EXPOsan ships a ready AD example | PyPI `qsdsan 1.4.3`, `exposan 1.4.3` | UIUC/NCSA (permissive) | yes (`pip install qsdsan exposan`, ≈8 min, ≈1 GB) | yes |
| **ADM1F** | C++/PETSc "ADM1 Fast" (LANL/Argonne; Zhu et al. 2025, *Biotechnol. Bioeng.*) | git `a39394ff6c3c1164716288683e674a689849da4c` (2024-07-17) | BSD-3-Clause | **not as documented**; yes via system PETSc (see §4) | yes, both source variants |
| **Weinrich ADM1-R1…R4** | Mass-based ADM1 and its systematic simplifications (Weinrich & Nelles 2021) | git `f95da865bc609e743f9ca825b99f0c80206709f9` (2021-04-16) | MIT | n/a — **MATLAB/Simulink only**, no Python | no (source inspected) |
| PyADM1ODE *(other, found during search)* | Python framework for agricultural biogas plants implementing **ADM1da** (41-state Schlattmann 2011 variant), dgaida | git `89cb2d3efe2d2106e5af7dc62cea02ea428efb12` (2026-08-14) | MIT | yes (`pip install -e .`, ≈1 min) | test suite run; not probed (different model) |

Also seen but not pursued: *PyADM1-R2* (a Python ADM1-R2 described in a 2024 preprint; no
maintained public package found in the time box) and the Weinrich-derived ADM1-R4
variants in the pump-mixed-digester literature (paper code only).

## 2. Probes and gate

Both probes use the same feed, volumes and initial state for every candidate, defined once
in `scripts/adm1_candidates/common.py`:

- **Plant.** BSM2 digester: V_liq = 3400 m³, V_gas = 300 m³, 35 °C, Q = 170 m³ d⁻¹.
- **Feed.** The constant sewage-sludge feed of the ADM1 STR benchmark (Batstone et al.
  2002), which is also EXPOsan's default: S_su 0.01, S_aa…S_ac 0.001, S_h2 1e-8,
  S_ch4 1e-5, S_IC 0.04 kmol m⁻³, S_IN 0.01 kmol m⁻³, S_I 0.02, X_xc 2, X_ch 5,
  X_pr 20, X_li 5, X_aa…X_h2 0.01, X_I 25 kg COD m⁻³, S_cat 0.04, S_an 0.02 kmol m⁻³.
- **Initial state.** The Rosen & Jeppsson (2006) BSM2 steady state (Table 5 of that
  report; identical in PyADM1's `digester_initial.csv`, bsm2-python's `DIGESTERINIT`
  and EXPOsan's `default_init_conds`).
- **Probe 1.** 100 d at default parameters.
- **Probe 2.** 20 d; every feed concentration ×3 from day 10 at constant Q (organic
  loading ≈ 3.1 → 9.3 kg COD m⁻³ d⁻¹).

*Caveat on Probe 1.* The published R&J steady state has S_cat ≈ 0 and S_an = 0.0052,
i.e. it was produced with a different strong-ion loading than the STR feed. Probe 1 is
therefore a 100-day transient from that state to the STR feed's steady state, **not** a
digit-for-digit ring test against the report. Candidates are compared with each other
and against the plausibility ranges below; four independent implementations agreeing to
three significant figures is the evidence of correctness here.

**Plausibility gate** (final state of Probe 1) and sources:

| Quantity | Range | Source |
|---|---|---|
| pH | 6.5 – 7.8 | Methanogenesis operates 6.5–8.0, optimum 7.0–7.2 (Appels et al. 2008, *Prog. Energy Combust. Sci.* 34:755); BSM2 steady state 7.26 for its own feed (Rosen & Jeppsson 2006) |
| CH₄ fraction, dry | 0.55 – 0.72 | 55–70 % v/v typical sludge biogas (Appels et al. 2008; Batstone et al. 2002 STR); BSM2 p_CH₄/p_dry ≈ 0.64 |
| Biogas flow (BSM2 convention: at T_op, normalised to P_atm) | 2200 – 3300 m³ d⁻¹ | BSM2 report: q_gas = 2955.7 m³ d⁻¹, P_gas = 1.069 bar, k_p = 5·10⁴ m³ d⁻¹ bar⁻¹ |
| Total VFA (va+bu+pro+ac as COD) | 1 – 1000 g COD m⁻³ | R&J steady state 133 g COD m⁻³; stable digesters ≪ 1 g L⁻¹ (Appels et al. 2008) |

Gas volumes are reported in two conventions: the BSM2 convention above, and dry gas at
0 °C / 1 atm (`q_gas_STP_dry_m3_d`), per CLAUDE.md rule 6.

## 3. Results

### 3.1 Probe 1 — 100 d sludge, default parameters (final values)

| Candidate [mode] | Solver | Wall-clock / sim-day | pH | CH₄ dry | q_gas (BSM2) m³ d⁻¹ | VFA g COD m⁻³ | Gate |
|---|---|---|---|---|---|---|---|
| PyADM1 [DOP853, as shipped] | explicit RK8 per 15-min step + Newton DAE for H⁺, S_h2 | 0.20 s | 7.464 | 0.642 | 2956 | 237 | pass |
| PyADM1 [BDF] | scipy BDF per 15-min step + Newton DAE | 0.23 s | 7.464 | 0.642 | 2956 | 237 | pass |
| bsm2-python [shipped] | odeint/LSODA per 15-min step, rtol=atol=1e-6 | 0.079 s | 7.464 | 0.642 | 2956 | 237 | pass |
| bsm2-python [bdf] | one solve_ivp BDF call, rtol 1e-6, atol 1e-8 | **0.002 s** | 7.464 | 0.642 | 2956 | 237 | pass |
| QSDsan/EXPOsan | solve_ivp BDF (rtol 1e-6, atol 1e-8), pH by brenth in the RHS | 0.023 s | 7.466 | 0.644 | 2951 | 238 | pass |
| ADM1F (`adm1f.cxx`, standard kinetics) | PETSc TSARKIMEX + ADOL-C Jacobian, default TSAdapt tolerances | **0.005 s** | 7.472 | 0.641 | 2949 | 237 | pass |
| ADM1F (`adm1f_srt.cxx`, makefile default) | as above | 0.006 s | 7.092 | 0.596 | 2611 | **5296** | **fails VFA** |

### 3.2 Probe 2 — 3× feed concentration step at day 10 (final values at day 20, and minimum pH)

| Candidate [mode] | Wall-clock / sim-day | pH (min) | S_ac g COD m⁻³ | q_gas m³ d⁻¹ | Step-size / failure notes |
|---|---|---|---|---|---|
| PyADM1 [DOP853] | 0.20 s | 7.364 (7.251) | 6180 | 7750 | 5 759 inner steps in 1 920 outer; nfev 119 688; no failure |
| PyADM1 [BDF] | 0.26 s | 7.365 (7.251) | 6181 | 7812 | 12 594 inner steps; min dt 1.4e-7 d; no failure |
| bsm2-python [shipped] | 0.075 s | 7.364 (7.251) | 6104 | 7801 | 67 262 LSODA steps, all in stiff (BDF) mode; no failure |
| bsm2-python [bdf] | **0.005 s** | 7.364 (7.251) | 6104 | 7801 | nfev 737, njev 21, nlu 102; no failure |
| QSDsan/EXPOsan | 0.14 s | 7.364 (7.261) | 6251 | 7779 | 346 accepted steps, min dt 1.3e-7 d at the step; no failure |
| ADM1F (standard) | 0.045 s | 7.370 (7.258) | 6087 | 7800 | 27 accepted steps, min dt 1e-3 d, max 9.3 d; no failure |
| ADM1F (srt) | 0.047 s | 7.054 (6.858) | 10 955 | 7541 | 29 steps; no failure (different model) |

**No candidate showed step-size collapse or integrator failure on either probe.** The
stiffness is real — bsm2-python's LSODA spent every one of its 331 845 steps in BDF mode
on Probe 1 and needed 3.3 M RHS evaluations, versus 538 for a single BDF call over the
same horizon — but every implicit solver handled the 3× overload without incident, and
even PyADM1's explicit DOP853 survived because its 15-minute outer steps cap the step
size. The overload itself behaves as expected: acetate rises to ≈6 g COD L⁻¹ within
10 days while pH stays above 7.25 because the ×3 feed also triples the strong-cation
load (S_cat), i.e. the probe stresses the integrator, not the buffer capacity.

### 3.3 Agreement between implementations

PyADM1, bsm2-python, QSDsan and ADM1F-standard agree on Probe 1 to three significant
figures (pH 7.464–7.472; q_gas 2949–2956; VFA 237–238) and on Probe 2 to within 3 %
(S_ac 6087–6251; q_gas 7750–7812). PyADM1 and bsm2-python are essentially identical
(both are line-by-line ports of the same BSM2 MATLAB code). QSDsan differs slightly on
the overload (its own pKa/Henry temperature corrections and a solved-for pH inside the
RHS); ADM1F differs slightly because its `params.dat` deviates from BSM2 defaults in five
entries (f_XI_xc 0.25 vs 0.2, f_LI_xc 0.25 vs 0.3, N_bac, K_I,h2,pro, K_A,B,va) and it
uses Metcalf & Eddy Henry-constant and Antoine vapour-pressure forms.

**ADM1F's makefile builds `adm1f_srt.cxx`, which is not ADM1.** Verified from source
(commit `a39394f`). In `adm1f.cxx` acetate uptake is Monod (line 1107):

```c
proc11 = k_m_ac*x[6]/(K_S_ac+x[6])*x[21]*inhib[4];          // inhib[4] = I_pH_ac*I_IN_lim*I_nh3
```

In `adm1f_srt.cxx` (line 1131, repeated in the two ADOL-C copies at 1561 and 2042) it is
Haldane on the *undissociated* fraction S_ac,u = S_ac·(1 − 1/(1 + 10^(pKa − pH))):

```c
proc11 = k_m_ac * S_ac,u / (K_S_ac + S_ac,u + S_ac,u^2 / pH_UL_ac)   // denominator K_S + S + S^2/K_I
       * x[21] * (2370*x[18] / (2370*x[18] + x[2]^2))                // LCFA inhibition, Palatsi 2010
       * inhib[4] * exp(8184*(T_op-T_base)/(T_op*T_base));            // inhib[4] = I_IN_lim*I_nh3 (no I_pH_ac)
/* pH_UL_ac repurposed to represent Haldane inhibition constant K_I_ac_ac */
```

The `S²/K_I` term makes it substrate-inhibited (Haldane), not Monod; the BSM2 default
`pH_UL_ac = 7` is then read as K_I = 7 kg COD m⁻³, the pH inhibition on acetoclastic
methanogens is removed, and the third copy (line 2042) has the biomass and LCFA
indices transposed relative to the other two (`x[18]*(2370*x[21]/(2370*x[18]+…))`),
which looks like a transcription error. It also adds SRT/HRT decoupling for particulates
(`t_resx`). With the shipped parameters it accumulates
5.3 g COD L⁻¹ acetate at the sludge steady state and fails the VFA gate. Anyone using
ADM1F "as documented" gets this variant. The paper's claim of <1 % agreement with the
BSM2 benchmark refers to the standard `adm1f.cxx`, which our probe confirms.

## 4. Per-candidate assessment

Criteria from the task: solver; wall-clock per simulated day; step-size collapse or
failures; licence; code quality; test coverage; ease of wrapping behind a pure-function
tool interface; ease of adding SAO, ionic-strength correction and a precipitation sink.

### PyADM1 (`CaptainFerMag/PyADM1`, MIT)
- **Solver.** `scipy.integrate.solve_ivp`, shipped with `DOP853` (explicit), stepped
  every 15 minutes with a Newton solve for H⁺ and S_h2 between steps (the R&J 2006 DAE
  formulation, S_h2 algebraic). 0.20–0.26 s per simulated day (both solvers) — slow
  because of the per-step Python overhead and 38 module-level globals.
- **Code quality.** One 736-line script; all state and parameters are module globals
  mutated by functions with `global` declarations; reads CSVs at import; runs the
  simulation at import; `ADM1_ODE` reads the feed from a global list built in the main
  loop rather than from the `*_in` globals its own `setInfluent` sets; ignores the feed
  file's Q column (q_ad is a constant). Ring-tested against the BSM2 MATLAB
  implementation (`ringtest.csv` shipped). Last commit 2022.
- **Tests.** None.
- **Wrappability.** Poor. It cannot be imported without side effects; our adapter had
  to `exec` the definitions and re-implement the stepping loop.
- **Extensibility.** Poor. Stoichiometry is hand-expanded in 26 `diff_*` expressions;
  adding SAO means editing several of them by hand, adding ionic strength means editing
  the Newton solve, adding precipitation means new globals and new hand-written terms.
- **Verdict.** Useful as a second reference for ring tests, not as a base.

### bsm2-python (`bsm2-python 0.0.16`, BSD-3-Clause)
- **Solver.** `scipy.integrate.odeint` (LSODA) called once per plant time step (default
  1 min; 15 min here) on a numba-jitted 42-state RHS; ion states are ODE states with
  fast acid–base kinetics (the R&J "ODE implementation"), S_h2 is an ODE state. As
  shipped: 0.08 s per simulated day. The same RHS in one `solve_ivp(BDF)` call:
  **0.002 s per simulated day**, 538 RHS evaluations for 100 days.
- **Code quality.** Clean, typed-by-docstring, index-named 42-vector layout with named
  constants; `ADM1Reactor` is a class wrapping ASM1↔ADM1 interfaces and the RHS;
  parameters and initial state are module-level arrays in `adm1init_bsm2.py` with unit
  docstrings. Active maintenance (2025–26 releases). Petersen matrix is hand-expanded
  inside the jitted function (~370 lines of `reac*`/`proc*` arithmetic).
- **Tests.** The GitHub project has a test suite and CI; the wheel does not ship tests.
  Not run here.
- **Wrappability.** Good for the RHS: `adm1equations(t, y, y_in, par, T, dim)` is a
  pure function of arrays and is directly usable behind a tool interface. The
  `ADM1Reactor.output` stepping API is stateful and tied to the BSM2 plant (ASM1 influent
  through the interface), which we would not use.
- **Extensibility.** Moderate. Adding a process means editing the jitted arithmetic and
  the state layout by hand; there is no matrix to add a row to. Ionic strength and
  precipitation would touch the hard-coded acid–base rates.
- **Verdict.** Best *reference* implementation for validation: fastest, cleanest of the
  BSM2 ports, permissive licence, active. Not the base for an extensible truth model.

### QSDsan / EXPOsan (`qsdsan 1.4.3`, UIUC/NCSA)
- **Solver.** `solve_ivp` on the system DAE assembled by biosteam (BDF here); pH solved
  algebraically inside the RHS by `brenth` on the charge balance; S_h2 optionally
  algebraic (`algebraic_h2`, default off). 0.023 s per simulated day on Probe 1,
  0.14 s on Probe 2 (the framework's per-call overhead dominates; 247 accepted steps).
- **Code quality.** High. ADM1 is a `CompiledProcesses` object built from a Petersen
  matrix loaded from `process_data/_adm1.tsv`; components carry measured-as, COD, N and
  charge; kinetics are a separate rate function with named parameter dictionary; a
  documented API to change rate constants, half-saturations, pKa and pH limits.
  **`_adm1_p_extension.py` already implements ionic speciation (K, Mg, Ca, Na, Cl) and
  seven mineral precipitation/dissolution processes (CaCO₃, struvite, newberyite, ACP,
  MgCO₃, AlPO₄, FePO₄) as additional Petersen rows** — the Flores-Alsina et al. (2016)
  physico-chemical extension. Active development, documented, peer-reviewed (Li et al.
  2022, *Environ. Sci. Technol.*).
- **Tests.** QSDsan has a pytest suite with CI on GitHub (not shipped in the wheel; not
  run here). EXPOsan's `adm` example carries a steady-state benchmark vector.
- **Wrappability.** Mixed. The *model* (Petersen matrix + rate function) is exactly the
  pure-function shape we need. The *simulation* goes through biosteam's global flowsheet
  registry, `WasteStream` objects with dynamic state arrays, and a `System` with
  cached state — global mutable state that a pure-function tool interface would have
  to isolate (fresh flowsheet per call, `_init_state()` after changing an influent, as
  our adapter had to discover). Dependency footprint ≈ 1 GB (thermosteam, biosteam,
  CoolProp, numba, scikit-learn, matplotlib…), and import time is several seconds.
- **Extensibility.** Best of all candidates: SAO is one new process row plus one biomass
  component; ionic strength (Davies/Debye–Hückel activity correction) can be added in
  the speciation code that ADM1p already centralises; precipitation exists.
- **Verdict.** The right *design* — but a heavy dependency for a benchmark that must run
  ~1 700 × N simulator evaluations, be Dockerised, and be deployable in a
  resource-constrained setting (§2). Its framework state is the opposite of the
  pure-function registry in §6.2.

### ADM1F (`lanl/ADM1F`, BSD-3-Clause)
- **Solver.** PETSc `TSARKIMEX` (implicit–explicit additive Runge–Kutta) with an ADOL-C
  automatic-differentiation Jacobian; `-steady` uses `TSPSEUDO`. 0.005 s per simulated
  day — but with PETSc's default TSAdapt tolerances it took **17 accepted steps for the
  100-day transient (max step 62 d)**; the steady state is right because it is an
  attractor, not because the transient was resolved. A wrapper would have to tighten
  `-ts_rtol/-ts_atol` and re-time.
- **Build / deployability.** The documented route (clone PETSc v3.14, `--download-mpich
  --download-adolc --download-colpack`) failed here in 1.5 min because the container's
  network policy blocks the tarball hosts. The shipped makefile does not work with
  PETSc ≥ 3.15 (`target 'clean' has both : and :: entries`). It built by compiling the
  source directly against Ubuntu's `petsc-dev 3.19.6` + `libadolc-dev 2.7.2` after
  copying `adolc-utils/` out of the PETSc source tree (the README says "make sure
  adolc-utils is in build/" but the repo does not contain it). Total ≈ 5 min, with the
  environment doing most of the work; on a machine without a packaged PETSc this is a
  multi-hour toolchain. **A PETSc + MPI + ADOL-C + ColPack toolchain for a 45-state ODE
  is itself a mark against deployability in a resource-constrained setting (§2).**
- **Code quality.** One 2 500-line C++ file per variant with the RHS written out three
  times (passive, and two ADOL-C "active" copies for tracing); parameters by index into
  a 100-vector; output via one ASCII file per step. The SRT variant silently changes
  the model (see §3.3). Last commit 2024-07.
- **Tests.** None in the repository (notebooks and calibration scripts only).
- **Wrappability.** Poor: file I/O + subprocess, one influent per run (a step change
  needs chained runs with the final state written back as `ic.dat`), parameters only
  through a positional file. Could be wrapped, but every call touches the filesystem.
- **Extensibility.** Poor for us: C++ edits in three places per process, and rebuilding
  the ADOL-C tapes; no matrix to add a row to.
- **Verdict.** A fast, correct reference (standard variant) for cross-checking, and a
  cautionary example of how much toolchain a "fast" solver can drag in. Not the base.

### Weinrich ADM1-R1…R4 (`soerenweinrich/ADM1`, MIT)
- **What is public.** MATLAB ODE functions (`ADM1_mass.m`, `ADM1_R1…R4_mass.m`,
  99–223 lines each), Simulink S-functions in C with Windows `.mexw64` binaries, `.mat`
  parameter/input files, and two PDFs documenting the model structures and parameters.
  **No Python.** No tests. Last commit 2021-04.
- **Model.** Mass-based (kg m⁻³, not COD) reformulation; R3 has 17 states with a single
  acetoclastic methanogenesis step and first-order hydrolysis of ch/pr/li, kinetic
  acid–base reactions, gas phase; R4 has 10 states (hydrolysis + methanogenesis as
  first-order sum reactions). Both are documented well enough to port in a day or two.
- **Role for us.** These are the natural *fitted* models for the structural-mismatch
  scenarios (§6.1: "the fitted model (standard or simplified ADM1) is structurally
  wrong by design") and for Plant A/B where full ADM1 defaults are weak. They are not
  candidates for the *truth* model, and would have to be ported by us (MIT permits it;
  the port then needs its own validation against the published `.mat` outputs).

### PyADM1ODE (`dgaida/PyADM1ODE`, MIT) — found during the search
- Well-engineered (`pyproject`, ruff/black, CI, docs in DE/EN, **790 tests pass in 20 s
  at 92 % coverage**), scipy BDF solver with explicit tolerances, substrate database,
  plant components (CHP, storage, sensors), and a built-in LLM benchmark harness. But it
  implements **ADM1da** (Schlattmann 2011, 41 states, sub-fraction hydrolysis, mass
  units, agricultural substrates), not standard ADM1; it ships compiled C# DLLs for
  physico-chemistry (apparently legacy — nothing in the Python package imports them);
  and it is a whole-plant framework, not a bare model. Worth revisiting as a *source of
  agricultural substrate characterisations* for Plant A, and as prior art on
  LLM-agent evaluation against ADM1-family models. Not a base.

## 5. Summary against the selection criteria (§6.1)

| Criterion | PyADM1 | bsm2-python | QSDsan | ADM1F | Weinrich | PyADM1ODE |
|---|---|---|---|---|---|---|
| Numerical stability under stiff transients | ok (DAE split; explicit solver survives only via 15-min outer steps) | good (BDF: 538 nfev / 100 d) | good | good (but under-resolved at default tolerances) | untested (no Python) | untested |
| Wall-clock per sim-day (best mode) | 0.20 s | **0.002 s** | 0.023 s | 0.005 s | — | — |
| Licence | MIT | BSD-3 | UIUC/NCSA | BSD-3 | MIT | MIT |
| Published validation | BSM2 ring test | BSM2 port | Li et al. 2022; BSM2 benchmark vector | Zhu et al. 2025 (<1 % vs BSM2) | Weinrich & Nelles 2021 | Gaida (docs) |
| Code quality | script, globals | clean, hand-expanded | Petersen matrix + components | 2.5 kLOC C++ ×2 | tidy MATLAB | high |
| Tests | none | upstream only | upstream only | none | none | 790, 92 % |
| Pure-function wrap | poor | good (RHS) | mixed (model yes, framework no) | poor (files) | — | — |
| Add SAO / ionic strength / precipitation | poor | moderate | **best (precipitation + speciation exist)** | poor | — | — |
| Dependency footprint | numpy/scipy | + numba | ≈ 1 GB | PETSc + ADOL-C + MPI | MATLAB | + pandas/networkx |

## 6. Recommendation (for domain sign-off)

**Do not adopt any candidate as the truth-model base. Write our own ADM1 in `sim/` as a
Petersen-matrix model, and use the candidates as follows:**

1. **Structure from QSDsan.** Express ADM1 as a stoichiometric matrix stored as data
   under `configs/` (components × processes, with COD/C/N/charge conservation checked
   by a test) and a rate function; take QSDsan's `_adm1.tsv` and `_adm1_p_extension.py`
   as the structural reference for how ionic speciation and precipitation are added as
   *rows*, not as edits to hand-expanded derivatives. This is what makes the three
   required extensions (SAO: +1 process, +1 biomass; ionic strength: activity
   correction in one speciation routine; precipitation: +1–2 processes and a mineral
   state) tractable and auditable.
2. **Numerics.** `scipy.integrate.solve_ivp(method="BDF")` (Radau as the cross-check)
   over whole horizons, with rtol/atol in `configs/`, algebraic pH by a bracketed
   root-find, S_h2 as an ODE state (the choice QSDsan and bsm2-python make; it avoids
   the nested Newton loops PyADM1 needs). bsm2-python demonstrates that this costs
   ≈ 2 ms per simulated day for the 42-state BSM2 system with a jitted RHS, which puts a
   4 000-evaluation budget (Appendix B) at ≈ 25 CPU-minutes per 180-day scenario before
   any optimisation — inside the proposal's envelope. Numba is optional; measure first.
3. **Validation.** Ring-test the new model against `results/bsm2python.json` and
   `results/adm1f.json` on both probes (agreement to 3 s.f. at the sludge steady state;
   within 3 % on the overload) as the first tests in `tests/` for `sim/`. Keep
   bsm2-python (and PyADM1 as a second, independent-lineage port) in the candidate
   venvs for future ring tests; neither becomes a runtime dependency.
4. **Fitted models.** Port Weinrich's ADM1-R3 and R4 (MIT) into `sim/` as the
   simplified fitted models for Level-6 structural scenarios and for Plants A/B,
   validated against the published `.mat` outputs. Budget: 1–2 days each.
5. **Do not use ADM1F.** Its toolchain is disproportionate to a 45-state ODE, it does
   not build as documented, and its default build is a modified model.

**Why not simply use QSDsan?** Its model layer is exactly right, but its simulation layer
(global flowsheet registry, stateful streams and systems, ≈ 1 GB of dependencies,
multi-second import) is incompatible with CLAUDE.md rule 2 (pure, budget-enforced
registry functions) and with the proposal's deployability constraint. Re-implementing
ADM1 as a matrix model is roughly a week of work with the references above, and it is
work we would have to do anyway to add SAO, ionic strength and precipitation with the
determinism, unit metadata and test coverage the benchmark requires.

**Risks to flag for the reviewer.** (a) A home-grown ADM1 needs domain review of the
matrix and the extensions — the ring tests catch transcription errors in standard ADM1
but cannot validate SAO/precipitation stoichiometry, for which QSDsan's ADM1p and the
Flores-Alsina et al. (2016) paper are the references. (b) Probe 1 is not a strict ring
test against the R&J report (feed differs; see §2); if the reviewer prefers a strict
ring test, re-run the harness with the BSM2 dynamic influent file that PyADM1 ships.
(c) All timings are single-run, warm-cache figures on a 4-vCPU container.

## References

- Batstone, D. J. et al. (2002). *Anaerobic Digestion Model No. 1 (ADM1)*. IWA STR 13.
- Rosen, C. & Jeppsson, U. (2006). *Aspects on ADM1 implementation within the BSM2
  framework*. Lund University.
- Appels, L. et al. (2008). Principles and potential of the anaerobic digestion of
  waste-activated sludge. *Prog. Energy Combust. Sci.* 34, 755–781.
- Flores-Alsina, X. et al. (2016). Modelling phosphorus (P), sulfur (S) and iron (Fe)
  interactions for dynamic simulations of anaerobic digestion processes. *Water Res.* 95.
- Sadrimajd, P. et al. (2021). PyADM1: a Python implementation of ADM1. bioRxiv
  2021.03.03.433746.
- Li, Y. et al. (2022). QSDsan: an integrated platform for quantitative sustainable
  design of sanitation and resource recovery systems. *Environ. Sci. Technol.* 56.
- Weinrich, S. & Nelles, M. (2021). Systematic simplification of the ADM1 — model
  development and stoichiometric analysis. *Bioresour. Technol.* 333, 125124.
- Zhu, W. et al. (2025). Open-source anaerobic digestion modeling platform, ADM1F.
  *Biotechnol. Bioeng.* 122, doi:10.1002/bit.28906.
