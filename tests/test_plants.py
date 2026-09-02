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
    load_plant_config,
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
    assert "omitted_sao" in plants["A"].scenario_subset.structural_scenarios
    for pid in ("B", "C"):
        assert "omitted_sao" not in plants[pid].scenario_subset.structural_scenarios


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
