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
    COD_EQUIVALENTS_KG_COD_PER_KG,
    COD_STATES,
    FEED_FRACTIONATION,
    FRACTION_NAMES,
    CODFractionation,
    FeedFractionation,
    FeedFractionationCatalogue,
    cod_loading_rate,
    constant_influent,
    extension_influent,
    feed_cod_per_m3,
    feed_tkn,
    implied_tkn,
    load_feed_fractionation,
    mix_feeds,
    nominal_mass_rates,
    organic_loading_rate,
    sample_true_fractionations,
    tkn_consistent,
    truth_inert_nitrogen,
    truth_parameters,
)
from sim.influent.schema import FeedKind
from sim.plants import KG_N_PER_KMOL, load_all_plants, load_plant_a_statistics
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
    from sim.influent.generator import (
        AmountModel,
        AssayModel,
        AssayRecord,
        AssaySchedule,
        DeliveryModel,
        LoggingModel,
        MoistureModel,
    )

    unit = re.compile(r"kg|kmol|m3|pH units|, -|, d\b|, 1/d|own unit|in `unit`")
    for model_cls in (
        FeedFractionation,
        CODFractionation,
        AssayModel,
        AssaySchedule,
        DeliveryModel,
        AmountModel,
        MoistureModel,
        LoggingModel,
        AssayRecord,
    ):
        for name, field in model_cls.model_fields.items():
            annotation = str(field.annotation)
            if "float" in annotation or "int" in annotation:
                desc = field.description or ""
                assert unit.search(desc), f"{model_cls.__name__}.{name}: {desc}"


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


def test_true_fractionation_moves_cod_between_classes_and_changes_total_cod(catalogue, plants):
    """VS is what a feed delivers; COD follows the (true) composition through COD/VS."""
    cfg = plants["A"]
    rates = nominal_mass_rates(cfg, catalogue)
    declared, q = mix_feeds(catalogue, rates)
    truth = sample_true_fractionations(catalogue, rates, 3)
    true, q_true = mix_feeds(catalogue, rates, truth.fractionations)
    assert q_true == q
    cod = [i for n, i in _L.items() if n in COD_STATES]
    assert not np.allclose(declared[cod], true[cod], rtol=1e-3)
    # total COD moves with the derived COD/VS, bounded by the class equivalents
    ratio = true[cod].sum() / declared[cod].sum()
    assert ratio != pytest.approx(1.0, rel=1e-6)
    equivalents = list(COD_EQUIVALENTS_KG_COD_PER_KG.values())
    assert min(equivalents) / max(equivalents) < ratio < max(equivalents) / min(equivalents)
    # and exactly: per feed, COD/m3 = TS x VS/TS x COD/VS(true) x density
    for fid in rates:
        spec = catalogue.feeds[fid]
        expected = spec.ts * spec.vs_of_ts * truth[fid].cod_per_vs * spec.density
        assert feed_cod_per_m3(spec, truth[fid]) == pytest.approx(expected)
    other = [i for n, i in _L.items() if n not in COD_STATES]
    np.testing.assert_array_equal(declared[other], true[other])  # dissolved species untouched


# ------------------------------------------------------- derived COD/VS (task 2)


def test_cod_per_vs_is_derived_and_checked_against_the_literature(catalogue):
    """COD/VS = 1 / sum(f_i / e_i); the literature value is a check within the tolerance."""
    for fid, spec in catalogue.feeds.items():
        f = spec.fractionation
        by_hand = 1.0 / sum(
            getattr(f, n) / COD_EQUIVALENTS_KG_COD_PER_KG[n] for n in FRACTION_NAMES
        )
        assert spec.cod_per_vs == pytest.approx(by_hand), fid
        gap = abs(spec.cod_per_vs - spec.cod_per_vs_literature) / spec.cod_per_vs_literature
        assert gap <= spec.cod_per_vs_tolerance <= 0.10, (fid, gap)
        assert sum(f.mass_shares().values()) == pytest.approx(1.0)
        assert "cod_per_vs" not in FeedFractionation.model_fields  # derived, never declared
    # the lead's targets: FOG near 2.7-2.9, HSW against the measured 2.23, primary 1.60
    assert 2.7 <= catalogue.feeds["fog"].cod_per_vs <= 2.9
    assert catalogue.feeds["high_strength_waste"].cod_per_vs_literature == pytest.approx(2.234)
    assert catalogue.feeds["primary_sludge"].cod_per_vs_literature == pytest.approx(1.60)
    assert 0.7 <= catalogue.feeds["high_strength_waste"].fractionation.f_li <= 0.75
    # the check is enforced by the schema, not only by this test
    fog = catalogue.feeds["fog"]
    with pytest.raises(ValidationError, match="COD/VS derived"):
        FeedFractionation.model_validate(fog.model_dump() | {"cod_per_vs_literature": 2.0})
    # PR #7's FOG (lipid COD share 0.85 read as a mass share) fails the check it motivated
    old = {"f_ch": 0.05, "f_pr": 0.05, "f_li": 0.85, "f_xi": 0.04, "f_si": 0.01, "f_vfa": 0.0}
    with pytest.raises(ValidationError, match="COD/VS derived"):
        FeedFractionation.model_validate(fog.model_dump() | {"fractionation": old})
    assert CODFractionation(**old).cod_per_vs == pytest.approx(2.43, abs=0.01)


# --------------------------------------------- cattle slurry re-centred (task 3)


def test_cattle_slurry_inert_share_is_centred_at_0_40_with_the_decided_spread(catalogue):
    """Lead's answer 2: inerts 0.40, measured VFA/protein/lipid kept, kappa ~100 -> sd ~0.05."""
    spec = catalogue.feeds["cattle_slurry"]
    f = spec.fractionation
    assert f.f_xi + f.f_si == pytest.approx(0.40)
    assert (f.f_vfa, f.f_pr, f.f_li) == (0.12, 0.17, 0.13)
    assert f.f_ch == pytest.approx(1.0 - 0.40 - 0.12 - 0.17 - 0.13)
    assert spec.fractionation_concentration == 100.0
    draws = [sample_true_fractionations(catalogue, ["cattle_slurry"], s) for s in range(600)]
    inert = np.array([d["cattle_slurry"].f_xi + d["cattle_slurry"].f_si for d in draws])
    assert inert.mean() == pytest.approx(0.40, abs=0.01)
    assert inert.std() == pytest.approx(np.sqrt(0.4 * 0.6 / 101.0), rel=0.2)
    lo, hi = np.percentile(inert, [2.5, 97.5])
    assert 0.28 <= lo <= 0.33 and 0.47 <= hi <= 0.52
    # Tisocco's fitted DQ_XC 0.69 (inert ~0.24 with these fractions) is inside the draws
    assert inert.min() < 0.27


# ------------------------------------------ Plant A nitrogen basis (task 4)


def test_plant_a_nitrogen_is_on_the_2024_total_n_basis(catalogue):
    """Tkn = Tisocco 2024 Table 1 N (g N per kg TS, read as total N) x TS; tan by a cited ratio."""
    env = load_plant_a_statistics()["plants"]["afbi_hillsborough"]["ammonia_envelope"]
    n_per_ts = env["feed_TAN_g_N_per_kg_TS"]  # the file's field name; total N per the decision
    for fid, ratio in (("cattle_slurry", 0.55), ("grass_silage", 0.10)):
        spec = catalogue.feeds[fid]
        mean_g_per_kg_ts = float(np.mean(n_per_ts[fid]))
        tkn = mean_g_per_kg_ts * spec.ts * spec.density / 1000.0 / KG_N_PER_KMOL
        assert spec.tkn == pytest.approx(tkn, rel=0.01), fid
        assert spec.tan == pytest.approx(ratio * spec.tkn, rel=0.02), fid
    # the untraced 7.28 g/L is gone from the catalogue
    text = FEED_FRACTIONATION.read_text(encoding="utf-8")
    assert "tan: 0.043" not in text and "DROPPED" in text
    # the silage column equals XP / 6.25 in the 2024 table: the arithmetic behind the reading
    assert pytest.approx(25.6) == 160 / 6.25 and pytest.approx(21.6, abs=0.3) == 135 / 6.25


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
    assert implied_tkn(silage, bsm2) * 14.007 > 10.0  # ~11 g N/L against the declared 7.6


# ---------------------------------------- per-feed inert N in the truth (task 1)


def test_truth_inert_nitrogen_is_the_inert_cod_weighted_mean(catalogue, plants, adm1_params):
    """Truth N_I = sum(w_k N_I,k) / sum(w_k) with w_k the inert COD load of feed k."""
    rates = nominal_mass_rates(plants["B"], catalogue)
    num = den = 0.0
    for fid, m in rates.items():
        spec = catalogue.feeds[fid]
        f = spec.fractionation
        w = m / spec.density * spec.cod_per_m3 * (f.f_xi + f.f_si)
        num += w * spec.inert_N_I
        den += w
    n_i = truth_inert_nitrogen(catalogue, rates)
    assert n_i == pytest.approx(num / den)
    values = [catalogue.feeds[f].inert_N_I for f in rates]
    assert min(values) < n_i < max(values)
    # a recipe's true fractionation changes the weights, not the per-feed values
    truth = sample_true_fractionations(catalogue, rates, 11)
    assert truth_inert_nitrogen(catalogue, rates, truth.fractionations) != pytest.approx(n_i)
    degradable = CODFractionation(f_ch=0.5, f_pr=0.3, f_li=0.1, f_xi=0.0, f_si=0.0, f_vfa=0.1)
    no_inert = {
        fid: s.model_copy(update={"fractionation": degradable})
        for fid, s in catalogue.feeds.items()
    }
    with pytest.raises(ValueError, match="no inert COD"):
        truth_inert_nitrogen(no_inert, rates)
    with pytest.raises(ValueError, match="unknown feeds"):
        truth_inert_nitrogen(catalogue, {"cake": 1.0})


def test_fitted_default_untouched_and_the_mismatch_is_real(catalogue, plants, adm1_params):
    """The truth carries the per-feed N_I; the BSM2 set the fitted model keeps does not."""
    from sim.adm1 import load_parameters
    from sim.adm1.defaults import PARAMS_BSM2

    bsm2_n_i = 0.06 / 14.0
    before = PARAMS_BSM2.read_bytes()
    truths = {}
    for pid, cfg in plants.items():
        rates = nominal_mass_rates(cfg, catalogue)
        truth = truth_parameters(adm1_params, catalogue, rates)
        truths[pid] = truth
        assert pytest.approx(truth_inert_nitrogen(catalogue, rates)) == truth.stoichiometry.N_I
        # only N_I differs
        assert truth.stoichiometry.model_dump() | {"N_I": adm1_params.stoichiometry.N_I} == (
            adm1_params.stoichiometry.model_dump()
        )
        assert truth.kinetics == adm1_params.kinetics and truth.physchem == adm1_params.physchem
    # the fitted default is untouched: in memory, on disk, and on re-load
    assert pytest.approx(bsm2_n_i) == adm1_params.stoichiometry.N_I
    assert PARAMS_BSM2.read_bytes() == before
    assert pytest.approx(bsm2_n_i) == load_parameters().stoichiometry.N_I
    # the mismatch is real where the catalogue says so, and absent for the sludge-only plant
    assert 0.3 * bsm2_n_i > truths["A"].stoichiometry.N_I
    assert bsm2_n_i > truths["B"].stoichiometry.N_I
    assert pytest.approx(bsm2_n_i) == truths["C"].stoichiometry.N_I  # both sludges are BSM2
    # the reported (assay) TKN is the per-feed one; the fitted N_I cannot reproduce it
    n_aa = adm1_params.stoichiometry.N_aa
    for fid, spec in catalogue.feeds.items():
        own = feed_tkn(spec, n_aa)
        assert own == pytest.approx(
            implied_tkn(spec, adm1_params.stoichiometry.model_copy(update={"N_I": spec.inert_N_I}))
        )
        fitted = implied_tkn(spec, adm1_params.stoichiometry)
        if fid in {"primary_sludge", "thickened_was"}:
            assert fitted == pytest.approx(own)
        else:
            assert abs(fitted - own) / own > spec.tkn_tolerance, fid
    # the module says the gap is intentional
    import sim.influent.nitrogen as nitrogen

    assert "intentional" in (nitrogen.__doc__ or "") and "must not" in (nitrogen.__doc__ or "")


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
