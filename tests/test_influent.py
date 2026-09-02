"""The feed-fractionation catalogue and the influent mapping (sim/influent, configs/influent).

What is tested and why it cannot pass vacuously:

* the catalogue loads, covers every feed of every frozen plant with the right kind, and
  every numeric leaf is marked ``# DESIGN`` and ``provisional`` (the values are PR #7's,
  pending the lead's review);
* the seeded true-fractionation draw is deterministic in the seed and independent of
  the order feeds are listed in, differs between seeds, sums to one, and keeps
  catalogue zeros at zero (over many seeds); the Dirichlet is centred on the catalogue
  with the declared spread;
* the influent builder is flow-weighted and COD-consistent, the true fractionation moves
  COD between classes but never creates or destroys it, and the plant recipes at the
  declared medians reproduce the plants' declared feed flows;
* every catalogue entry's TKN is consistent with the ADM1 N contents under the inert N
  content it declares, a deliberately wrong TKN is shown to fail, and the
  lignocellulosic entries are shown to be inconsistent under the BSM2 ``N_I`` (the
  finding that motivates the field);
* nothing under ``sim/influent`` or ``sim/plants`` writes files (CLAUDE.md rule 1).
"""

from __future__ import annotations

import ast
import re
import typing
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from sim.adm1 import LIQUID_STATE_NAMES
from sim.influent import (
    COD_STATES,
    FEED_FRACTIONATION,
    FRACTION_NAMES,
    CODFractionation,
    FeedFractionation,
    FeedFractionationCatalogue,
    cod_loading_rate,
    constant_influent,
    extension_influent,
    implied_tkn,
    load_feed_fractionation,
    mix_feeds,
    nominal_mass_rates,
    organic_loading_rate,
    sample_true_fractionations,
    tkn_consistent,
)
from sim.influent.schema import FeedKind
from sim.plants import load_all_plants, load_plant_a_statistics
from sim.plants.schema import FeedStream, PlantConfig
from tests.conftest import REPO_ROOT

_L = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}


@pytest.fixture(scope="module")
def catalogue() -> FeedFractionationCatalogue:
    return load_feed_fractionation()


@pytest.fixture(scope="module")
def plants() -> dict[str, PlantConfig]:
    return load_all_plants()


# ------------------------------------------------------------------ catalogue


def test_catalogue_covers_every_frozen_plant_feed_with_the_right_kind(catalogue, plants):
    for cfg in plants.values():
        for feed in cfg.feeds:
            spec = catalogue.for_stream(feed)
            assert spec.feed_id == feed.name and spec.kind == feed.kind
    # kinds of the plant contract are a subset of the catalogue's kinds
    contract_kinds = set(typing.get_args(FeedStream.model_fields["kind"].annotation))
    assert contract_kinds <= set(typing.get_args(FeedKind))
    assert "food_waste" in catalogue.feeds  # carried from PR #7, used by no frozen plant
    assert not any(f.name == "food_waste" for cfg in plants.values() for f in cfg.feeds)


def test_for_stream_rejects_unknown_feed_and_wrong_kind(catalogue, plants):
    feed = plants["A"].feeds[0]
    with pytest.raises(KeyError, match="no feed_fractionation entry"):
        catalogue.for_stream(feed.model_copy(update={"name": "cake"}))
    with pytest.raises(ValueError, match="catalogue kind"):
        catalogue.for_stream(feed.model_copy(update={"kind": "fog"}))


def test_every_value_is_provisional_and_marked_design(catalogue):
    """Every numeric leaf carries `# DESIGN` (the lead reviews them); status is provisional."""
    assert all(s.status == "provisional" for s in catalogue.feeds.values())
    text = FEED_FRACTIONATION.read_text(encoding="utf-8")
    body = text[text.index("\nfeeds:") :]
    leaf = re.compile(r"^\s+([A-Za-z_]+):\s+[-0-9.]+\s*(#.*)?$")
    unmarked = []
    for line in body.splitlines():
        m = leaf.match(line)
        if not m:
            continue
        key = m.group(1)
        if key in FRACTION_NAMES:
            continue  # the `fractionation:` parent line carries the marker
        if "# DESIGN" not in line:
            unmarked.append(line.strip())
    assert not unmarked, unmarked
    frac_lines = [ln for ln in body.splitlines() if ln.strip().startswith("fractionation:")]
    assert len(frac_lines) == len(catalogue.feeds)
    assert all("# DESIGN" in ln for ln in frac_lines)
    assert "PROVISIONAL" in text


def test_units_in_every_numeric_field_description():
    """CLAUDE.md rule 6: a unit (or an explicit '-') in every numeric field description."""
    for model_cls in (FeedFractionation, CODFractionation):
        for name, field in model_cls.model_fields.items():
            if "float" in str(field.annotation):
                desc = field.description or ""
                assert re.search(r"kg|kmol|m3|, -", desc), f"{model_cls.__name__}.{name}: {desc}"


def test_schema_rejections(catalogue):
    with pytest.raises(ValidationError, match="sum to 1"):
        CODFractionation(f_ch=0.5, f_pr=0.5, f_li=0.1, f_xi=0.0, f_si=0.0, f_vfa=0.0)
    spec = catalogue.feeds["cattle_slurry"]
    with pytest.raises(ValidationError, match="exceeds TKN"):
        spec.model_copy(update={"tan": spec.tkn * 2}).model_validate(
            spec.model_dump() | {"tan": spec.tkn * 2}
        )
    with pytest.raises(ValidationError, match="feed_id"):
        FeedFractionationCatalogue(version=1, feeds={"slurry": spec})
    with pytest.raises(ValidationError):
        FeedFractionation.model_validate(spec.model_dump() | {"extra": 1})
    with pytest.raises(ValidationError):
        FeedFractionation.model_validate(spec.model_dump() | {"status": "frozen"})


# ------------------------------------------------------------ true fractionation


def test_true_fractionation_is_seeded_order_independent_and_bounded(catalogue):
    ids = list(catalogue.feeds)
    a = sample_true_fractionations(catalogue, ids, 12345)
    assert a == sample_true_fractionations(catalogue, reversed(ids), 12345)
    assert a != sample_true_fractionations(catalogue, ids, 12346)
    assert a.seed == 12345 and set(a.fractionations) == set(ids)
    # sorted-order consumption: a feed's draw does not depend on which later feeds are listed
    first = sorted(ids)[0]
    assert sample_true_fractionations(catalogue, [first], 12345)[first] == a[first]
    for seed in range(200):
        t = sample_true_fractionations(catalogue, ids, seed)
        for fid, spec in catalogue.feeds.items():
            drawn = t[fid]
            assert sum(drawn.as_tuple()) == pytest.approx(1.0, abs=1e-9)
            for fname in FRACTION_NAMES:
                if getattr(spec.fractionation, fname) == 0.0:
                    assert getattr(drawn, fname) == 0.0, (fid, fname)
                else:
                    assert getattr(drawn, fname) > 0.0
    with pytest.raises(ValueError, match="unique"):
        sample_true_fractionations(catalogue, ["fog", "fog"], 1)
    with pytest.raises(KeyError, match="no feed_fractionation entry"):
        sample_true_fractionations(catalogue, ["cake"], 1)


def test_true_fractionation_scatters_around_the_catalogue(catalogue):
    """The Dirichlet draws are centred on the catalogue and have the declared spread."""
    spec = catalogue.feeds["food_waste"]  # the most variable feed (kappa 40)
    draws = np.array(
        [sample_true_fractionations(catalogue, ["food_waste"], s)["food_waste"].as_tuple()
         for s in range(400)]
    )  # fmt: skip
    mean = np.array(spec.fractionation.as_tuple())
    np.testing.assert_allclose(draws.mean(axis=0), mean, atol=0.02)
    kappa = spec.fractionation_concentration
    expected_sd = np.sqrt(mean * (1 - mean) / (kappa + 1))
    positive = mean > 0
    np.testing.assert_allclose(draws.std(axis=0)[positive], expected_sd[positive], rtol=0.25)
    assert np.all(draws.std(axis=0)[positive] > 0.01)


# ------------------------------------------------------------------- mapping


def test_mixed_influent_is_flow_weighted_and_cod_consistent(catalogue, plants):
    cfg = plants["C"]
    rates = nominal_mass_rates(cfg, catalogue)
    inf = constant_influent(catalogue, rates)
    c, q = inf.concentrations[0], inf.q[0]
    V = cfg.geometry.V_liq_declared
    total_cod = sum(c[_L[n]] for n in COD_STATES) * q
    assert total_cod == pytest.approx(cod_loading_rate(catalogue, rates, V) * V)
    assert q == pytest.approx(sum(m / catalogue.feeds[n].density for n, m in rates.items()))
    assert c[_L["S_IN"]] == pytest.approx(0.01)  # both sludges carry the BSM2 S_IN
    assert organic_loading_rate(catalogue, rates, V) > 0
    assert extension_influent(catalogue, rates)["S_ca"] == pytest.approx(0.02)
    # no composite: everything particulate goes to X_ch / X_pr / X_li / X_I
    assert c[_L["X_xc"]] == 0.0 and c[_L["X_ch"]] > 0 and c[_L["X_I"]] > 0
    for fn in (mix_feeds, extension_influent):
        with pytest.raises(ValueError, match="unknown feeds"):
            fn(catalogue, {"cake": 1.0})
        with pytest.raises(ValueError, match="negative"):
            fn(catalogue, {"fog": -1.0})
        with pytest.raises(ValueError, match="zero"):
            fn(catalogue, {"fog": 0.0})


def test_true_fractionation_moves_cod_between_classes_but_conserves_it(catalogue, plants):
    cfg = plants["A"]
    rates = nominal_mass_rates(cfg, catalogue)
    declared, q = mix_feeds(catalogue, rates)
    truth = sample_true_fractionations(catalogue, rates, 3)
    true, q_true = mix_feeds(catalogue, rates, truth.fractionations)
    assert q_true == q
    cod = [i for n, i in _L.items() if n in COD_STATES]
    assert declared[cod].sum() == pytest.approx(true[cod].sum(), rel=1e-12)
    assert not np.allclose(declared[cod], true[cod], rtol=1e-3)
    other = [i for n, i in _L.items() if n not in COD_STATES]
    np.testing.assert_array_equal(declared[other], true[other])  # dissolved species untouched


def test_plant_recipes_reproduce_the_declared_feed_flows(catalogue, plants):
    for pid, cfg in plants.items():
        rates = nominal_mass_rates(cfg, catalogue)
        assert set(rates) == {f.name for f in cfg.feeds}
        _, q = mix_feeds(catalogue, rates)
        # medians of the parts vs the median of the daily sum: within a few per cent
        assert q == pytest.approx(cfg.hydraulics.feed_flow_m3_d.median, rel=0.03), pid
    silage = next(f for f in plants["A"].feeds if f.name == "grass_silage")
    assert silage.volume_m3_d is None and silage.mass_t_fm_d is not None
    assert nominal_mass_rates(plants["A"], catalogue)["grass_silage"] == pytest.approx(2000.0)
    bad = plants["A"].feeds[0].model_copy(update={"volume_m3_d": None, "mass_t_fm_d": None})
    with pytest.raises(ValueError, match="no volume or mass"):
        nominal_mass_rates(plants["A"].model_copy(update={"feeds": (bad,)}), catalogue)


def test_plant_a_loading_lands_in_the_published_olr_range(catalogue, plants):
    """Provisional catalogue x frozen feed medians gives Tisocco 2024's OLR envelope."""
    lo, hi = load_plant_a_statistics()["plants"]["afbi_hillsborough"]["loading"]["OLR_kgVS_m3_d"]
    cfg = plants["A"]
    olr = organic_loading_rate(
        catalogue, nominal_mass_rates(cfg, catalogue), cfg.geometry.V_liq_declared
    )
    assert lo <= olr <= hi, olr


# ------------------------------------------------------------------- nitrogen


def test_catalogue_nitrogen_is_consistent_under_its_declared_inert_n(catalogue, adm1_params):
    bsm2 = adm1_params.stoichiometry
    for fid, spec in catalogue.feeds.items():
        assert sum(spec.fractionation.as_tuple()) == pytest.approx(1.0, abs=1e-9), fid
        assert 0.9 < spec.cod_per_vs < 3.0, fid  # between carbohydrate and lipid
        own = bsm2.model_copy(update={"N_I": spec.inert_N_I})
        assert tkn_consistent(spec, own), (fid, spec.tkn, implied_tkn(spec, own))
        # the check is not vacuous: a wrong TKN fails it
        wrong = spec.model_copy(update={"tkn": spec.tkn * 2.0})
        assert not tkn_consistent(wrong, own)
    # PR #7's finding: the BSM2 inert N over-counts lignocellulosic / food-waste inerts
    sludge = {"primary_sludge", "thickened_was"}
    for fid, spec in catalogue.feeds.items():
        if fid in sludge:
            assert spec.inert_N_I == pytest.approx(bsm2.N_I)
            assert tkn_consistent(spec, bsm2)
        else:
            assert spec.inert_N_I < bsm2.N_I
            assert not tkn_consistent(spec, bsm2), fid
    silage = catalogue.feeds["grass_silage"]
    assert implied_tkn(silage, bsm2) * 14.007 > 10.0  # ~11 g N/L against the declared 6.6


# ------------------------------------------------------------ rule 1 hygiene


_WRITERS = {"open", "write_text", "write_bytes", "to_csv", "dump", "safe_dump", "savetxt", "save"}


def _write_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name in _WRITERS:
                found.append(f"{path.name}:{node.lineno}: {name}")
    return found


@pytest.mark.parametrize("package", ["influent", "plants"])
def test_truth_producing_packages_never_write_files(package, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from pathlib import Path\nPath('x').write_text('truth')\nopen('y', 'w')\n")
    assert len(_write_calls(bad)) == 2  # the checker sees both patterns
    modules = sorted((REPO_ROOT / "sim" / package).glob("*.py"))
    assert modules
    calls = [c for m in modules for c in _write_calls(m)]
    assert not calls, calls
    for m in modules:
        assert "truth/" not in m.read_text(encoding="utf-8").replace("runs/<id>/truth/", "")
