"""Do the virtual plants behave like the plants they are anchored to?

This is the check PR #7 carried as a "100-day plausibility table" and the salvage session
deferred to the influent generator (`docs/milestones.md`, fifth session). It is the
Milestone-2 exit criterion in test form: *reproduces published steady-state ranges;
stochastic influent statistics match anchor*.

It is not a unit test of any one module — it runs the whole chain (catalogue → recipe →
truth parameters → extended ADM1 with all four extensions) and asks whether the answer
resembles the real plant:

* **Plant B** must reproduce the biogas the Muscatine daily file actually measures. This
  is what caught the FOG solids content: at the assumed 10 % TS the declared median
  recipe delivered twice the anchor's COD and the digester collapsed under the
  generator's swings (`configs/influent/feed_fractionation.yaml`, `fog.ts`).
* **Plant A** must sit inside the published OLR envelope (tested in `test_influent.py`)
  and run at a plausible pH and methane content for slurry/silage co-digestion.
* **Plant C** must be the steadier, more lightly loaded control of the pair.
* No plant may sour at its own declared median feed.

The runs are ~250 d to steady state at a constant median feed and take a few seconds each.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from sim.adm1 import (
    compile_extended,
    extended_state,
    load_extensions,
    load_matrix,
    load_solver_config,
    simulate_extended,
)
from sim.influent import (
    constant_influent,
    extension_influent,
    generate_influent,
    load_feed_fractionation,
    load_generator_config,
    nominal_mass_rates,
    truth_parameters,
)
from sim.plants import declared_geometry, load_all_plants
from tests.conftest import REPO_ROOT

MUSCATINE_DAILY = REPO_ROOT / "anchor" / "raw" / "iowa-muscatine-wrrf" / "LABS-raw.csv"
CFM_TO_M3_PER_D = 0.0283168 * 1440.0
DIGESTERS = 2
CH4_ENERGY_FRACTION = 0.62
"""Methane fraction used to convert the anchor's biogas to destroyed COD, - (the model
returns 0.67-0.70, so this is the conservative end)."""
M3_CH4_PER_KG_COD = 0.35
"""Theoretical methane yield at STP, m3 CH4 per kg COD destroyed."""


@pytest.fixture(scope="module")
def catalogue():
    return load_feed_fractionation()


@pytest.fixture(scope="module")
def plants():
    return load_all_plants()


def _steady_state(plant, catalogue, params, y0, days: float = 250.0):
    """Run one plant at its declared median recipe to steady state."""
    rates = nominal_mass_rates(plant, catalogue)
    influent = constant_influent(catalogue, rates)
    u_ext = extension_influent(catalogue, rates)
    truth = truth_parameters(params, catalogue, rates)
    geometry = declared_geometry(plant)
    model = compile_extended(
        truth, geometry, load_matrix(), load_solver_config(), load_extensions(),
        plant.truth_model.extensions,
    )  # fmt: skip
    result = simulate_extended(
        y0=extended_state(model, y0, {}),
        influent=influent,
        model=model,
        t_span=(0.0, days),
        t_eval=np.array([days]),
        u_ext=u_ext,
    )
    assert result.success, plant.id
    d = result.derived
    return {
        "pH": float(d["pH"][-1]),
        "q_gas": float(d["q_gas_stp_dry"][-1]),
        "ch4": float(d["p_ch4"][-1] / (d["P_gas"][-1] - d["p_h2o"][-1])),
        "cod_in": float(influent.q[0] * influent.concentrations[0].sum()),
    }


def measured_biogas_per_digester() -> float:
    """Mean measured biogas of one Muscatine digester, m3/d at the meter's conditions."""
    rows = list(csv.DictReader(MUSCATINE_DAILY.open(encoding="utf-8-sig")))
    values = np.array([float(r["Biogas"]) for r in rows if r["Biogas"] not in ("", "NA")])
    return float(values.mean()) * CFM_TO_M3_PER_D / DIGESTERS


@pytest.mark.skipif(not MUSCATINE_DAILY.exists(), reason="Muscatine daily file not present")
def test_plant_b_reproduces_the_measured_biogas(plants, catalogue, adm1_params, rj2006_state):
    """Plant B's declared median feed must give the biogas its anchor measures (+/- 40 %).

    The band is wide because the comparison carries the plant's own meter convention and
    our conversion assumptions, but it is narrow enough to have caught a feed that was
    2.1x too strong: at the previously assumed FOG solids of 10 % this run produced
    4,395 m3/d against a measured 2,111.
    """
    measured = measured_biogas_per_digester()
    assert 2000.0 < measured < 2250.0  # 2,111 m3/d; pins the anchor value itself
    state = _steady_state(plants["B"], catalogue, adm1_params, rj2006_state)
    ratio = state["q_gas"] / measured
    assert 0.6 < ratio < 1.4, (state["q_gas"], measured, ratio)
    assert 6.8 < state["pH"] < 7.6, state["pH"]
    assert 0.55 < state["ch4"] < 0.75, state["ch4"]


def test_no_plant_sours_at_its_declared_median_feed(plants, catalogue, adm1_params, rj2006_state):
    """Every plant is a working digester at its own median recipe."""
    for pid in ("A", "B", "C"):
        state = _steady_state(plants[pid], catalogue, adm1_params, rj2006_state)
        assert 6.8 < state["pH"] < 8.0, (pid, state["pH"])
        assert 0.5 < state["ch4"] < 0.8, (pid, state["ch4"])
        assert state["q_gas"] > 0.0, pid


def test_b_and_c_are_the_loaded_and_control_pair(plants, catalogue, adm1_params, rj2006_state):
    """The controlled pair differs only in the co-substrates, so B is the loaded one."""
    b = _steady_state(plants["B"], catalogue, adm1_params, rj2006_state)
    c = _steady_state(plants["C"], catalogue, adm1_params, rj2006_state)
    assert b["cod_in"] > 2.0 * c["cod_in"]
    assert b["q_gas"] > 2.0 * c["q_gas"]
    assert c["pH"] > b["pH"]  # the lightly loaded control sits higher


@pytest.mark.skipif(not MUSCATINE_DAILY.exists(), reason="Muscatine daily file not present")
def test_plant_b_survives_the_generator_swings(plants, catalogue, adm1_params, rj2006_state):
    """Under the stochastic influent Plant B stays a working digester for 180 days.

    Plant B is the load-swing plant, so this is the check that its swings are swings and
    not a collapse: with the pre-anchor FOG solids the same run ended at pH 4.50 with
    0.9 % methane.
    """
    generator = load_generator_config()
    plant = plants["B"]
    run = generate_influent(plant, catalogue, generator, adm1_params, seed=11, n_days=180)
    truth = truth_parameters(
        adm1_params, catalogue, run.truth.mean_recipe_kg_d, run.truth.fractionations.fractionations
    )
    geometry = declared_geometry(plant)
    model = compile_extended(
        truth, geometry, load_matrix(), load_solver_config(), load_extensions(),
        plant.truth_model.extensions,
    )  # fmt: skip
    result = simulate_extended(
        y0=extended_state(model, rj2006_state, {}),
        influent=run.truth.influent,
        model=model,
        t_span=(0.0, 180.0),
        t_eval=np.arange(0.0, 181.0),
    )
    assert result.success
    d = result.derived
    settled = slice(60, None)  # past the initial transient from the BSM2 state
    ch4 = d["p_ch4"] / (d["P_gas"] - d["p_h2o"])
    assert d["pH"][settled].min() > 6.5, d["pH"][settled].min()
    assert ch4[settled].mean() > 0.55, ch4[settled].mean()
    measured = measured_biogas_per_digester()
    assert 0.6 < d["q_gas_stp_dry"][settled].mean() / measured < 1.5
    # it does swing: the daily gas rate spans more than a factor of two
    gas = d["q_gas_stp_dry"][settled]
    assert np.percentile(gas, 95) / np.percentile(gas, 5) > 2.0
