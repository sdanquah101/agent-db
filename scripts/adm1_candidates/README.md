# ADM1 candidate probes (Milestone 1)

Harness used to compare candidate open ADM1 implementations for the truth model
(proposal §6.1). Results are written up in `docs/adm1_comparison.md`; the raw records
this harness produced are committed under `results/` so the comparison is reproducible.

Every probe uses the same feed, initial state, horizon and plausibility gate, defined
once in `common.py`:

- **Probe 1** — 100 d, mesophilic (35 °C) sewage sludge, constant ADM1-STR/BSM2 feed,
  default parameters, initialised at the Rosen & Jeppsson (2006) steady state.
- **Probe 2** — 20 d, all feed concentrations ×3 from day 10 at constant flow
  (organic loading ≈ 3.1 → 9.3 kg COD m⁻³ d⁻¹), to probe stiffness.

Each `probe_<candidate>.py` is a thin adapter around the candidate's own right-hand side
or executable and records: solver and settings, wall-clock per simulated day, step /
function-evaluation counts, final and extreme values of pH, biogas flow, CH₄ fraction
and total VFA, and the gate outcome. Nothing here is imported by the benchmark.

## Milestone-2 oracle (ring tests for `sim/adm1`)

bsm2-python is the primary oracle of the accepted ADM1 decision (`docs/decisions.md`).
Two records under `results/` are read by `tests/test_adm1_ring.py`:

- `bsm2python.json` — Probes 1 and 2 (`probe_bsm2python.py`), now also carrying the full
  35-state vector at the end of each probe under `stats.final_state`.
- `bsm2python_dynamic.json` — the BSM2 dynamic digester influent
  (`probe_bsm2python_dynamic.py`): 280 d at 15-minute resolution, from PyADM1's
  `src/digester_influent.csv`, trimmed to the 26 ADM1 states + Q + T and committed as
  `data/bsm2_digester_influent_15min.csv.gz` (SHA-256 of the original and of the trimmed
  file are recorded in the JSON). Three ways of applying the series are recorded:
  sample-and-hold with one BDF call per segment (`hold`, primary), sample-and-hold with
  `odeint` per segment as the package ships (`shipped`), and linear interpolation in a
  single BDF call (`linear`). Daily samples of pH, q_gas, S_ac and others plus the final
  35-state vector are stored.

Re-generate them in the bsm2-python venv from this directory:

```bash
python probe_bsm2python.py
python probe_bsm2python_dynamic.py          # ~2 min; or: ... hold linear
```

## Running

Each candidate needs its own virtual environment; none is a dependency of this
repository. From this directory:

```bash
# PyADM1 (git clone https://github.com/CaptainFerMag/PyADM1)
pip install numpy scipy pandas matplotlib
python probe_pyadm1.py /path/to/PyADM1

# bsm2-python
pip install bsm2-python pandas
python probe_bsm2python.py

# QSDsan + EXPOsan (adm example)
pip install qsdsan exposan
python probe_qsdsan.py

# ADM1F (git clone https://github.com/lanl/ADM1F; needs PETSc + ADOL-C, see the
# comparison document for the build that worked)
python probe_adm1f.py /path/to/ADM1F adm1f_orig adm1f      # standard kinetics
python probe_adm1f.py /path/to/ADM1F adm1f      adm1f_srt  # SRT variant (makefile default)
```

Weinrich ADM1-R3/R4 has no public Python implementation (MATLAB/Simulink only) and is
assessed from source in the comparison document; PyADM1ODE implements a different
model (ADM1da) and was installed and its test suite run, but not probed.
