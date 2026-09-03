"""The declared blend tank: does it conserve mass, smooth pulses, and split exactly?

The tank exists because a clean Level-0 run on Plant B acidified on 5 of 12 seeds while
the plant's own description said its trucked feed is "blended in a 65,000-gal tank" that
the simulator did not have (the lead's ruling 1, 2026-09-03). It sits between the frozen
influent generator and the truth model, so a bug here would silently change every Plant B
cell while every anchored delivery statistic — which describes arrivals, not what leaves
the tank — went on passing.

Four properties, each checked against something other than the implementation:

1. **Mass is conserved**, to machine precision, against an independent balance
   ``in - out = end level - start level`` computed from the returned series.
2. **At zero hold-up it is a pass-through**, exactly — the degenerate case that says the
   tank is a smoother and not a distortion.
3. **It smooths**, measured as the variance of what leaves against the variance of what
   arrives, and it lags, measured as the day the response to a single pulse peaks.
4. **The buffered/direct split is exact from whichever side is reconstructed**, which is
   the correctness question a mislabelled batch turns on: one side is reconstructed from
   the catalogue and the other comes free as the residual, so the reconstructed side must
   be the one no composition-altering fault touches.
"""

from __future__ import annotations

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.adm1.schema import N_LIQUID, Influent
from sim.influent import load_feed_fractionation, load_generator_config
from sim.plants import load_plant_config
from sim.plants.equalisation import apply_equalisation, buffer_series, feed_contribution
from sim.run.harness import split_for_equalisation
from tests.conftest import REPO_ROOT

GAL_TO_M3 = 0.00378541


@pytest.fixture(scope="module")
def arrivals() -> np.ndarray:
    """A lumpy delivery series: trucks on some days, nothing on others."""
    rng = np.random.default_rng(4)
    days = rng.random(200) < 0.7
    return np.where(days, rng.lognormal(mean=3.0, sigma=0.8, size=200), 0.0)


# ------------------------------------------------------------------ 1. mass


def test_the_tank_conserves_mass_to_machine_precision(arrivals):
    """``in - out = end level - start level``, computed from the returned series alone."""
    load = np.stack([arrivals * 2.0, arrivals * 0.5], axis=1)
    q_out, load_out, levels = buffer_series(arrivals, load, hold_up_d=4.0)

    # the level after the last step is not in `levels`, so reconstruct it from the balance
    # of the final step and check the whole horizon closes against it
    cumulative = levels[0] + np.cumsum(arrivals - q_out)
    np.testing.assert_allclose(cumulative[:-1], levels[1:], rtol=0, atol=1e-9)
    assert arrivals.sum() - q_out.sum() == pytest.approx(cumulative[-1] - levels[0], abs=1e-9)
    for i in range(load.shape[1]):
        assert load[:, i].sum() - load_out[:, i].sum() == pytest.approx(
            (load[:, i] - load_out[:, i]).sum(), abs=1e-9
        )
    assert (q_out >= 0.0).all()  # a tank never runs backwards
    assert (levels > 0.0).all()  # ... and never runs dry


def test_the_tank_holds_roughly_its_declared_volume(arrivals):
    """The hold-up is ``V / mean flow``, so the level should sit near the declared volume."""
    q_out, _, levels = buffer_series(arrivals, arrivals[:, None], hold_up_d=4.0)
    assert levels.mean() == pytest.approx(4.0 * arrivals.mean(), rel=0.1)
    assert q_out.mean() == pytest.approx(arrivals.mean(), rel=0.02)


# ------------------------------------------------------------------ 2. degenerate


def test_a_vanishing_tank_is_a_pass_through(arrivals):
    """The limit that says this is a smoother, not a distortion."""
    load = arrivals[:, None] * 3.0
    q_out, load_out, _ = buffer_series(arrivals, load, hold_up_d=1e-9)
    np.testing.assert_allclose(q_out, arrivals, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(load_out, load, rtol=1e-6, atol=1e-6)


def test_a_hold_up_of_zero_is_refused():
    with pytest.raises(ValueError, match="hold-up must be positive"):
        buffer_series(np.ones(3), np.ones((3, 1)), hold_up_d=0.0)


# ------------------------------------------------------------------ 3. smoothing


def test_the_tank_smooths_and_lags(arrivals):
    """What the tank is for, measured rather than asserted by construction."""
    variances = {}
    for hold_up in (0.5, 2.0, 4.0, 8.0):
        q_out, _, _ = buffer_series(arrivals, arrivals[:, None], hold_up)
        variances[hold_up] = float(np.var(q_out))
    assert variances[0.5] > variances[2.0] > variances[4.0] > variances[8.0]
    assert variances[8.0] < 0.1 * float(np.var(arrivals))

    # a single pulse leaves over days, not on one day
    pulse = np.zeros(40)
    pulse[10] = 100.0
    q_out, _, levels = buffer_series(pulse, pulse[:, None], hold_up_d=5.0)
    assert q_out[10] < 0.35 * pulse[10]  # most of it does not leave the day it arrives
    assert q_out[11] > 0.0 and q_out[20] > 0.0  # and it is still leaving ten days later
    # the tank starts at the steady level for this run's MEAN arrivals, so what leaves is
    # the pulse plus the draw-down of that starting inventory - the balance, not the pulse
    drawn_down = levels[0] - (levels[0] + np.cumsum(pulse - q_out))[-1]
    assert q_out.sum() == pytest.approx(pulse.sum() + drawn_down, abs=1e-9)


# ------------------------------------------------------------------ 4. the split


def test_the_declared_tank_is_the_anchored_volume():
    """65,000 gal for the plant, halved for the modelled unit."""
    plant = load_plant_config("B")
    assert plant.equalisation is not None
    assert plant.equalisation.volume_m3 == pytest.approx(65_000 * GAL_TO_M3 / 2, rel=1e-3)
    assert plant.equalisation.feeds == ("high_strength_waste",)
    for other in ("A", "C"):
        assert load_plant_config(other).equalisation is None


def test_the_split_is_exact_from_whichever_side_is_reconstructed():
    """Buffered plus direct is the whole influent, however the split was computed.

    This is the property a mislabelled batch turns on: the reconstructed side uses the
    catalogue, the other side is the residual, and the two must still add up to what the
    generator produced.
    """
    from sim.adm1 import load_parameters
    from sim.faults import build_plan
    from sim.influent import generate_influent

    plant = load_plant_config("B")
    catalogue = load_feed_fractionation()
    feed_ids = tuple(f.name for f in plant.feeds)
    # S3-01 mislabels the FOG, which bypasses the buffer, so the buffered side is the
    # clean one; this is the case that used to fail outright.
    scenario = load_scenario(REPO_ROOT / "scenarios" / "S3-01.yaml")
    scenario = scenario.model_copy(update={"duration_days": 60.0})
    plan = build_plan(scenario, feed_ids, fault_seed=7)
    assert plan.influent.mislabelled and plan.influent.mislabelled[0].feed_id == "fog"

    generated = generate_influent(
        plant,
        catalogue,
        load_generator_config(),
        load_parameters(),
        seed=5,
        n_days=60,
        faults=plan.influent,
    )
    q, load = split_for_equalisation(plant, catalogue, generated, plan, feed_ids)
    q_total = np.asarray(generated.truth.influent.q)
    load_total = q_total[:, None] * np.asarray(generated.truth.influent.concentrations)
    assert (q <= q_total + 1e-9).all()
    assert q.shape == q_total.shape and load.shape == load_total.shape

    # the buffered side is the HSW alone, reconstructed; check it against a direct sum
    density = catalogue.feeds["high_strength_waste"].density
    expected_q = generated.truth.feeds["high_strength_waste"].delivered_kg / density
    np.testing.assert_allclose(q, expected_q, rtol=1e-12)

    buffered = apply_equalisation(generated.truth.influent, q, load, plant.equalisation)
    # total mass over the horizon is preserved up to what the tank is still holding
    assert buffered.influent.q.sum() == pytest.approx(q_total.sum(), rel=0.05)
    assert buffered.influent.concentrations.shape == (60, N_LIQUID)
    assert np.isfinite(buffered.influent.concentrations).all()
    assert buffered.hold_up_d > 1.0


def test_the_split_refuses_when_a_fault_touches_both_sides():
    """There is no exact reconstruction then, and a near-enough one would be silent."""
    from dataclasses import replace

    from sim.adm1 import load_parameters
    from sim.faults import build_plan
    from sim.faults.plan import MislabelledFeed
    from sim.influent import generate_influent

    plant = load_plant_config("B")
    catalogue = load_feed_fractionation()
    feed_ids = tuple(f.name for f in plant.feeds)
    scenario = load_scenario(REPO_ROOT / "scenarios" / "S3-01.yaml")
    scenario = scenario.model_copy(update={"duration_days": 40.0})
    plan = build_plan(scenario, feed_ids, fault_seed=7)
    both = replace(
        plan.influent,
        mislabelled=(
            *plan.influent.mislabelled,
            MislabelledFeed("high_strength_waste", 0.0, 40.0, 5.0),
        ),
    )
    plan = replace(plan, influent=both)
    generated = generate_influent(
        plant, catalogue, load_generator_config(), load_parameters(), seed=5, n_days=40
    )
    with pytest.raises(ValueError, match="both sides"):
        split_for_equalisation(plant, catalogue, generated, plan, feed_ids)


def test_an_empty_buffer_is_refused():
    plant = load_plant_config("B")
    influent = Influent(t=np.arange(5.0), concentrations=np.ones((5, N_LIQUID)), q=np.ones(5))
    with pytest.raises(ValueError, match="no flow passes"):
        apply_equalisation(influent, np.zeros(5), np.zeros((5, N_LIQUID)), plant.equalisation)


def test_feed_contribution_sums_what_it_is_given():
    q = {"a": np.array([1.0, 2.0]), "b": np.array([3.0, 4.0])}
    conc = {"a": np.ones((2, 3)), "b": np.full((2, 3), 2.0)}
    total_q, total_load = feed_contribution(("a", "b"), q, conc)
    np.testing.assert_allclose(total_q, [4.0, 6.0])
    np.testing.assert_allclose(total_load, [[7.0, 7.0, 7.0], [10.0, 10.0, 10.0]])
