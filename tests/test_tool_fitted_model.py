"""The fitted ADM1, the assay channel and the privileged registry on a generated run.

1. ``adm1_fitted`` is built from declared quantities only, evaluates every channel of
   ``configs/tools/model.yaml`` on the daily grid with units, is bit-reproducible, and a
   parameter multiplier moves the output; a product fraction keeps its group summing to one.
2. On a real Level-0 run of Plant C the fitted model's outputs sit near the truth channels
   (the background differences -- hidden volume error, true fractionation, unrecorded
   deliveries -- are the only ones), and ``feed_loads`` is the catalogue's arithmetic.
3. ``open_registry`` reads the cell from the truth-side index, carries the Level-8
   directive of S8-01 and the scenario's budget, continues the harness's visible log, and
   registers nothing a workflow could read the rung from: the parameter list is the same
   on a Level-6 cell as on a Level-0 one.
4. ``request_assay`` serves the truth channel with the lab sensor's noise, prices it from
   the assay budget, reports it after the turnaround, repeats a day identically, and
   refuses a day outside the record.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.adm1.schema import LIQUID_STATE_NAMES
from sim.influent import COD_STATES, load_feed_fractionation, nominal_mass_rates
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from state.provenance import read_calls
from tests.conftest import REPO_ROOT
from tools import BudgetExceededError, ToolArgumentError, open_registry
from tools.fitted import FittedADM1
from tools.privileged import registry_seed

SCENARIOS = REPO_ROOT / "scenarios"
SHORT_DAYS = 40.0


def _short(scenario_id: str, days: float = SHORT_DAYS):
    scenario = load_scenario(SCENARIOS / f"{scenario_id}.yaml")
    faults = tuple(
        f.model_copy(update={"onset_day": min(f.onset_day, days / 2)}) for f in scenario.faults
    )
    return scenario.model_copy(update={"duration_days": days, "faults": faults})


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("store") / "runs"
    scenario = _short("S0-01")
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=root)
    return run, scenario, root


@pytest.fixture(scope="module")
def fitted_c():
    plant = load_plant_config("C")
    rates = nominal_mass_rates(plant, load_feed_fractionation())
    log = {fid: np.full(int(SHORT_DAYS), r) for fid, r in rates.items()}
    return FittedADM1(
        plant=plant, feed_log=log, extensions=plant.truth_model.extensions, horizon_d=SHORT_DAYS
    )


# ------------------------------------------------------------------ 1. the model


def test_the_fitted_model_is_declared_reproducible_and_responsive(fitted_c):
    m = fitted_c
    assert m.parameter_names == tuple(m.config.parameters)
    assert np.all(m.defaults == 1.0)
    assert all("multiplier" in u for u in m.parameter_units.values())
    assert m.t[0] == 0.0 and m.t[-1] == SHORT_DAYS and m.t.size == int(SHORT_DAYS) + 1
    out = m.evaluate(m.defaults)
    assert set(out) == set(m.config.outputs)
    for name, series in out.items():
        assert series.shape == m.t.shape and np.all(np.isfinite(series)), name
        assert m.output_units[name]
    assert m.last_status()[0]
    assert 6.5 < out["pH"][-1] < 8.0 and 0.5 < out["ch4_fraction"][-1] < 0.8
    again = m.evaluate(m.defaults)
    assert all(np.array_equal(out[k], again[k]) for k in out)
    theta = m.defaults.copy()
    theta[m.parameter_names.index("k_m_ac")] = 0.5
    slower = m.evaluate(theta)
    assert slower["vfa_ac"][-1] > out["vfa_ac"][-1]


def test_a_product_fraction_multiplier_keeps_its_group_summing_to_one(fitted_c):
    m = fitted_c
    theta = m.defaults.copy()
    theta[m.parameter_names.index("f_li_xc")] = 1.4
    params = m._parameters(theta)
    s = params.stoichiometry
    assert s.f_li_xc == pytest.approx(1.4 * m._base.stoichiometry.f_li_xc)
    assert s.f_si_xc + s.f_xi_xc + s.f_ch_xc + s.f_pr_xc + s.f_li_xc == pytest.approx(1.0)
    # the others kept their ratios
    b = m._base.stoichiometry
    assert s.f_ch_xc / s.f_pr_xc == pytest.approx(b.f_ch_xc / b.f_pr_xc)


def test_the_fitted_model_takes_an_initial_state_and_a_biomass_scale(fitted_c):
    m = fitted_c
    base = m.evaluate(m.defaults)
    starved = m.evaluate(m.defaults, biomass_scale=0.3)
    assert starved["vfa_ac"][:10].max() > base["vfa_ac"][:10].max()
    override = m.evaluate(m.defaults, initial_state={"S_ac": 2.0})
    assert override["vfa_ac"][0] > base["vfa_ac"][0]
    with pytest.raises(ValueError):
        m.evaluate(m.defaults, initial_state={"no_such_state": 1.0})
    short = m.evaluate(m.defaults, t_end=10.0)
    assert short["pH"].shape == m.t.shape
    np.testing.assert_allclose(short["pH"][:11], base["pH"][:11], rtol=1e-6)
    assert np.all(short["pH"][11:] == short["pH"][10])


# ------------------------------------------------------------------ 2. against a run


def test_the_fitted_model_of_a_clean_run_sits_near_the_truth(clean_run):
    run, scenario, root = clean_run
    reg = open_registry(run.run_id, runs_root=root, scenario=scenario)
    sim = reg.call("simulate", model="adm1_fitted")
    truth = run.truth.channels
    settled = sim.t >= 10.0
    for name in ("pH", "q_gas_stp_dry", "ch4_fraction", "tan", "cod_total"):
        fitted = sim.outputs[name][settled]
        true = np.interp(sim.t[settled], truth.t, truth[name])
        ratio = np.mean(fitted) / np.mean(true)
        assert 0.7 < ratio < 1.3, (name, ratio)
    assert abs(np.mean(sim.outputs["pH"][settled]) - np.mean(truth["pH"])) < 0.3
    assert sim.units["q_gas_stp_dry"].startswith("m3/d")
    loads = reg.call("feed_loads")
    assert loads.t.size == int(SHORT_DAYS)
    # the declared COD of the logged feed against the truth's fed COD load: same order
    true_q = run.truth.influent.truth.influent.q
    true_conc = run.truth.influent.truth.influent.concentrations
    idx = [LIQUID_STATE_NAMES.index(s) for s in COD_STATES]
    true_cod = true_q * true_conc[:, idx].sum(axis=1)
    assert 0.6 < loads.cod_kg_d.mean() / true_cod.mean() < 1.4
    assert reg.remaining().simulator_evals == scenario.budget.simulator_evals - 1


# ------------------------------------------------------------------ 3. the privileged side


def test_open_registry_reads_the_cell_the_directive_and_the_budget(clean_run, tmp_path):
    run, scenario, root = clean_run
    reg = open_registry(run.run_id, runs_root=root)  # the cell through the index
    assert reg.budget.simulator_evals == scenario.budget.simulator_evals
    assert reg.budget.assay_units == scenario.budget.assay_units
    assert reg._failures == {}
    # the visible log continues the harness's records
    before = read_calls(run.paths.root)
    reg.call("describe_model")
    after = read_calls(run.paths.root)
    assert [r.name for r in after] == [*[r.name for r in before], "describe_model"]
    assert after[-1].seq == len(before) and after[-1].t_utc is None
    assert read_calls(run.paths.truth)[-1].name == "describe_model"
    # the registry seed is a keyed child of the observation stream
    assert reg.seed == registry_seed(run.manifest.seeds["observation"])
    assert reg.seed != run.manifest.seeds["observation"]

    # S8-01: the directive rides in memory and never in the visible tree
    faulted = generate_run(
        _short("S8-01"), "B", plant=load_plant_config("C"), runs_root=tmp_path / "runs"
    )
    reg8 = open_registry(faulted.run_id, runs_root=tmp_path / "runs", scenario=_short("S8-01"))
    assert set(reg8._failures) == {"bayes_mcmc"} and reg8._failures["bayes_mcmc"][0] == 1.0
    blob = "\n".join(
        p.read_text(encoding="utf-8") for p in faulted.paths.root.rglob("*") if p.is_file()
    )
    assert "bayes_mcmc" not in blob and "injected" not in blob


def test_a_level_six_cell_exposes_the_same_interface_as_a_level_zero_one(clean_run, tmp_path):
    run, scenario, root = clean_run
    plant = load_plant_config("C")
    six = generate_run(_short("S6-02"), "B", plant=plant, runs_root=tmp_path / "runs")
    assert set(six.truth.fitted_extensions) < set(plant.truth_model.extensions)
    reg0 = open_registry(run.run_id, runs_root=root, scenario=scenario)
    reg6 = open_registry(six.run_id, runs_root=tmp_path / "runs", scenario=_short("S6-02"))
    d0 = reg0.call("describe_model").model_dump(mode="json")
    d6 = reg6.call("describe_model").model_dump(mode="json")
    for key in ("parameter_names", "defaults", "lower", "upper", "output_names", "output_units"):
        assert d0[key] == d6[key], key
    # ... and the fitted model of the Level-6 cell really lacks the extension
    assert reg6._models["adm1_fitted"].extensions == six.truth.fitted_extensions


# ------------------------------------------------------------------ 4. assays


def test_request_assay_serves_the_truth_channel_with_the_sensor_noise(clean_run):
    run, scenario, root = clean_run
    # the budget is the scenario's, not the run's: a wider assay envelope for this test
    wider = scenario.model_copy(
        update={"budget": scenario.budget.model_copy(update={"assay_units": 6})}
    )
    reg = open_registry(run.run_id, runs_root=root, scenario=wider)
    catalogue = reg.configs.assays
    units = 6
    out = reg.call("request_assay", assay="alkalinity", day=20.0)
    spec = catalogue.assays["alkalinity"]
    assert out.report_day == 20.0 + spec.turnaround_d and out.unit_cost == spec.unit_cost
    assert reg.remaining().assay_units == units - spec.unit_cost
    result = out.results[0]
    truth = float(np.interp(20.0, run.truth.channels.t, run.truth.channels["alkalinity_total"]))
    sensor = reg._assay_server.sensors.sensors[spec.sensor]
    assert result.sd == pytest.approx(np.hypot(sensor.noise.cv * truth, sensor.noise.sd_abs))
    assert abs(result.value - truth) < 5 * result.sd
    assert result.value != truth
    assert result.unit.startswith("kg CaCO3/m3")
    # the same day again is the same number, from the same keyed stream
    again = reg.call("request_assay", assay="alkalinity", day=20.0)
    assert again.results[0].value == result.value
    # a different day is a different draw
    other = reg.call("request_assay", assay="alkalinity", day=21.0)
    assert other.results[0].value != result.value
    # both logged, visible and truth side
    names = [r.name for r in read_calls(run.paths.root)]
    assert names.count("request_assay") == 3
    with pytest.raises(ToolArgumentError, match="outside the record"):
        reg.call("request_assay", assay="alkalinity", day=SHORT_DAYS + 5)
    # spend the rest and hit the budget
    while reg.remaining().assay_units >= 1:
        reg.call("request_assay", assay="tan", day=5.0)
    with pytest.raises(BudgetExceededError, match="assay"):
        reg.call("request_assay", assay="tan", day=5.0)
    # the visible log carries the refusal, not the assay value
    last = read_calls(run.paths.root)[-1]
    assert last.outcome == "budget_exceeded"
    line = run.paths.calls.read_text().splitlines()[-1]
    assert "value" not in json.loads(line)


def test_a_speciation_request_returns_its_companions(clean_run):
    run, scenario, root = clean_run
    reg = open_registry(run.run_id, runs_root=root, scenario=scenario)
    out = reg.call("request_assay", assay="vfa_speciation", day=15.0)
    assert [r.channel for r in out.results] == ["vfa_ac", "vfa_pro", "vfa_bu", "vfa_va"]
    assert all(r.sd > 0 for r in out.results)
