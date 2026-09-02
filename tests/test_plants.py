"""Plant configurations A/B/C: load, consistency, and re-derivation from the anchor data.

B/C's numbers must be what the committed Muscatine daily file actually says:
dataset-anchored means the config can be regenerated from the data, so drift is caught.
"""

from __future__ import annotations

import contextlib
import csv

import numpy as np
import pytest

from scenarios.schema import Plant
from sim.adm1 import compile_extended, load_extensions
from sim.plants import (
    PLANT_IDS,
    Anchoring,
    declared_geometry,
    load_all_plants,
    load_plant_a_statistics,
    load_plant_config,
    plant_a_digestate_tan,
    sample_hidden_geometry,
    true_geometry,
)
from sim.plants.schema import HiddenActiveVolume, PlantConfig
from tests.conftest import REPO_ROOT

MUSCATINE_DAILY = REPO_ROOT / "anchor" / "raw" / "iowa-muscatine-wrrf" / "LABS-raw.csv"
GAL_TO_M3 = 0.00378541


@pytest.fixture(scope="module")
def plants() -> dict[str, PlantConfig]:
    return load_all_plants()


def _column(rows, name):
    out = []
    for r in rows:
        with contextlib.suppress(ValueError, KeyError):
            out.append(float(r[name]))
    return np.array(out)


def _stats(a):
    return float(np.median(a)), float(np.percentile(a, 10)), float(np.percentile(a, 90))


# ------------------------------------------------------------------ loading


def test_all_three_plants_load_and_match_the_scenario_enum(plants):
    assert set(plants) == set(PLANT_IDS) == {p.value for p in Plant}
    for pid, cfg in plants.items():
        assert cfg.id == pid
        assert cfg.feeds and cfg.anchor_sources
        assert set(cfg.truth_model.extensions) == {
            "sao",
            "ionic_strength",
            "carbonate",
            "precipitation",
        }


def test_anchoring_status_follows_the_decision(plants):
    assert plants["A"].anchoring is Anchoring.STATISTICS
    assert plants["B"].anchoring is Anchoring.DATASET
    assert plants["C"].anchoring is Anchoring.DATASET
    assert not plants["A"].scenario_subset.factorial
    assert plants["B"].scenario_subset.factorial and plants["C"].scenario_subset.factorial
    assert plants["A"].scenario_subset.tiers == ("A",)
    ammonia = {"ammonia_inhibition_shift", "omitted_sao", "compound_sao_inhibition_shift"}
    assert ammonia <= set(plants["A"].scenario_subset.assigned_scenarios)
    for pid in ("B", "C"):
        assert ammonia <= set(plants[pid].scenario_subset.excluded_scenarios)
        assert plants[pid].scenario_subset.assigned_scenarios == ()


def test_b_and_c_are_a_controlled_pair(plants):
    """Same geometry, temperature and hidden-error distribution; only the feeds differ."""
    b, c = plants["B"], plants["C"]
    assert b.geometry == c.geometry.model_copy(update={"note": b.geometry.note})
    assert b.temperature == c.temperature
    assert b.hidden_active_volume == c.hidden_active_volume
    assert {f.name for f in c.feeds} < {f.name for f in b.feeds}
    for feed in c.feeds:
        assert feed == next(f for f in b.feeds if f.name == feed.name)


def test_headspace_is_the_bsm2_ratio(plants):
    """Headspace volumes are assumed at the BSM2 ratio 300/3400 (answer 5), and say so."""
    for cfg in plants.values():
        assert cfg.geometry.V_gas == pytest.approx(
            cfg.geometry.V_liq_declared * 300 / 3400, rel=5e-3
        )
        assert "ASSUMED" in (cfg.geometry.note + _config_path(cfg.id).read_text())


def _config_path(pid: str):
    return load_plant_config.__globals__["CONFIG_DIR"] / f"plant_{pid}.yaml"


def test_every_dataset_anchored_number_names_its_source(plants):
    for pid in ("B", "C"):
        cfg = plants[pid]
        keys = {c.key for c in cfg.anchor_sources}
        assert cfg.hydraulics.feed_flow_m3_d.source.split(":")[0] in keys
        assert cfg.temperature.source.split(":")[0] in keys
        for feed in cfg.feeds:
            assert feed.volume_m3_d is not None and feed.source in keys


def test_hrt_consistency_is_enforced(plants):
    cfg = plants["B"]
    bad = cfg.model_copy(
        update={"geometry": cfg.geometry.model_copy(update={"V_liq_declared": 4000.0})}
    )
    with pytest.raises(ValueError, match="disagrees with the HRT"):
        PlantConfig.model_validate(bad.model_dump())


def test_bad_file_id_is_rejected(tmp_path, plants):
    text = (load_plant_config.__globals__["CONFIG_DIR"] / "plant_B.yaml").read_text()
    (tmp_path / "plant_A.yaml").write_text(text)
    with pytest.raises(ValueError, match="declares id"):
        load_plant_config("A", tmp_path)


# ------------------------------------------------------- dataset re-derivation


@pytest.mark.skipif(not MUSCATINE_DAILY.exists(), reason="Muscatine daily file not present")
def test_plant_b_and_c_statistics_match_the_muscatine_daily_file(plants):
    rows = list(csv.DictReader(MUSCATINE_DAILY.open(encoding="utf-8-sig")))
    assert len(rows) == 1103
    per_unit = 2  # two parallel digesters, the benchmark models one

    def flow(cols):
        total = np.array(
            [sum(float(r[c]) if r[c] not in ("", "NA") else 0.0 for c in cols) for r in rows]
        )
        return total[total > 0] * GAL_TO_M3 / per_unit

    b_feed = flow(("V-TWAS_gal", "V-PS_gal", "V-HSW_gal", "FOG_gal"))
    c_feed = flow(("V-TWAS_gal", "V-PS_gal"))
    for pid, feed in (("B", b_feed), ("C", c_feed)):
        cfg = plants[pid].hydraulics.feed_flow_m3_d
        med, p10, p90 = _stats(feed)
        assert cfg.median == pytest.approx(med, rel=0.02), pid
        assert cfg.p10 == pytest.approx(p10, rel=0.02), pid
        assert cfg.p90 == pytest.approx(p90, rel=0.02), pid
        V = plants[pid].geometry.V_liq_declared
        assert plants[pid].hydraulics.hrt_d.median == pytest.approx(V / med, rel=0.02)
        assert pytest.approx(485_000 * GAL_TO_M3, rel=1e-3) == V

    t_k = (_column(rows, "Dig1-T_degF") - 32.0) * 5.0 / 9.0 + 273.15
    med, p10, p90 = _stats(t_k)
    for pid in ("B", "C"):
        t = plants[pid].temperature
        assert t.setpoint_K == pytest.approx(med, abs=0.05)
        assert t.p10_K == pytest.approx(p10, abs=0.05)
        assert t.p90_K == pytest.approx(p90, abs=0.05)
        assert t.day_sd_K == pytest.approx(float(t_k.std()), abs=0.05)

    srt = plants["B"].hydraulics.srt_d
    assert srt is not None
    med, p10, p90 = _stats(_column(rows, "SRT"))
    assert (srt.median, srt.p10, srt.p90) == pytest.approx((med, p10, p90), rel=0.02)

    for name, col in (("high_strength_waste", "V-HSW_gal"), ("fog", "FOG_gal")):
        feed = next(f for f in plants["B"].feeds if f.name == name)
        a = _column(rows, col)
        assert feed.zero_days_fraction == pytest.approx(float((a == 0).mean()), abs=0.01)


# ------------------------------------------------------------- hidden truth


def test_hidden_active_volume_is_seeded_bounded_and_two_sided(plants):
    cfg = plants["B"]
    a = sample_hidden_geometry(cfg, seed=7)
    b = sample_hidden_geometry(cfg, seed=7)
    assert a == b
    assert sample_hidden_geometry(cfg, seed=8) != a
    hav = cfg.hidden_active_volume
    errors = np.array([sample_hidden_geometry(cfg, s).error_fraction for s in range(200)])
    assert np.all((np.abs(errors) >= hav.error_min) & (np.abs(errors) <= hav.error_max))
    assert (errors < 0).any() and (errors > 0).any()
    assert a.V_liq_true == pytest.approx(cfg.geometry.V_liq_declared * (1.0 + a.error_fraction))
    # the declared config is untouched by sampling
    assert declared_geometry(cfg).V_liq == cfg.geometry.V_liq_declared


def test_signed_error_modes():
    hav = HiddenActiveVolume(error_min=0.05, error_max=0.15, sign="negative")
    cfg = load_plant_config("C").model_copy(update={"hidden_active_volume": hav})
    errors = [sample_hidden_geometry(cfg, s).error_fraction for s in range(50)]
    assert all(e < 0 for e in errors)
    with pytest.raises(ValueError, match="error_min"):
        HiddenActiveVolume(error_min=0.2, error_max=0.1, sign="random")


def test_plant_a_statistics_carry_the_transcribed_envelope():
    """The lead's transcription is present; pH and free ammonia stay null with reasons."""
    stats = load_plant_a_statistics()
    env = stats["plants"]["afbi_hillsborough"]["ammonia_envelope"]
    assert env["digestate_TAN_kg_N_m3"] == {"min": 2.3, "max": 4.3}
    assert env["digestate_pH"] is None and env["free_ammonia_kg_N_m3"] is None
    assert env["modelled_KI_NH3_acetoclastic_kg_m3"] == 1.0
    assert set(env["feed_TAN_g_N_per_kg_TS"]) == {"cattle_slurry", "grass_silage"}
    assert "AFBI-anchored" in env["notes"]


def test_sao_establishes_at_plant_a(plants, rj2006_state, probe_common):
    """The condition of the SAO scenario decision (2026-09-02): SAO takes over at Plant A.

    Plant A's declared geometry and median HRT (40 d), the ADM1 STR feed with its
    inorganic nitrogen set to the midpoint of the AFBI digestate TAN range read from
    configs/plant_a_statistics.yaml (2.3-4.3 kg N/m3 -> 3.3, Tisocco et al. 2024
    Section 3.2, transcribed by the lead), a 0.05 kg COD/m3 SAO seed, 180 d (a
    scenario horizon). Using the digestate TAN as the feed S_IN is a proxy: protein
    degradation adds nitrogen in the reactor, so the reactor TAN comes out a little above
    the anchor value, which errs towards stronger ammonia stress. With the fast-end SAO
    kinetics (mu_max 0.16 d^-1, answer 1) X_sao grows several-fold and removes most of
    the acetate that the ammonia-inhibited acetoclasts leave; with the earlier
    0.08 d^-1 it did not (scripts/plant_a_sao_probe.py).
    """
    from sim.adm1 import (
        LIQUID_STATE_NAMES,
        Influent,
        extended_state,
        load_matrix,
        load_parameters,
        load_solver_config,
        simulate,
        simulate_extended,
    )

    cfg = plants["A"]
    params, matrix, solver, ext = (
        load_parameters(),
        load_matrix(),
        load_solver_config(),
        load_extensions(),
    )
    geometry = declared_geometry(cfg)
    q = cfg.geometry.V_liq_declared / cfg.hydraulics.hrt_d.median
    u = np.array(probe_common.influent_vector(1.0))
    tan = plant_a_digestate_tan()
    assert tan == pytest.approx(3.3 / 14.007, rel=1e-6)  # 0.2356 kmol N/m3
    u[LIQUID_STATE_NAMES.index("S_IN")] = tan
    influent = Influent.constant(u, q)
    t_eval = np.array([180.0])
    base = simulate(
        y0=rj2006_state,
        influent=influent,
        params=params,
        plant=geometry,
        matrix=matrix,
        solver=solver,
        t_span=(0.0, 180.0),
        t_eval=t_eval,
    )
    assert float(base.S_nh3[-1]) * 14000.0 > 150.0  # free ammonia in the shift window
    model = compile_extended(params, geometry, matrix, solver, ext, ("sao",))
    r = simulate_extended(
        y0=extended_state(model, rj2006_state, {"X_sao": 0.05}),
        influent=influent,
        model=model,
        t_span=(0.0, 180.0),
        t_eval=t_eval,
    )
    assert r.success
    assert float(r.state("X_sao")[-1]) > 5.0 * 0.05
    assert float(r.state("S_ac")[-1]) < 0.1 * float(base.y[6, -1])


def test_true_geometry_feeds_the_truth_model_and_declared_the_workflow(plants):
    ext = load_extensions()
    from sim.adm1 import load_matrix, load_parameters, load_solver_config

    params, matrix, solver = load_parameters(), load_matrix(), load_solver_config()
    for cfg in plants.values():
        hidden = sample_hidden_geometry(cfg, seed=1)
        truth = true_geometry(cfg, hidden)
        seen = declared_geometry(cfg)
        assert truth.V_liq != seen.V_liq and truth.V_gas == seen.V_gas
        assert truth.T_op == seen.T_op == cfg.temperature.setpoint_K
        model = compile_extended(params, truth, matrix, solver, ext, cfg.truth_model.extensions)
        assert model.n_states == 29 + 3
    with pytest.raises(ValueError, match="hidden geometry is for plant"):
        true_geometry(plants["A"], sample_hidden_geometry(plants["B"], 1))
