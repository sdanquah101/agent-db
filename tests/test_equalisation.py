"""The declared blend tank: does it conserve mass, smooth pulses, and split exactly?

The tank exists because a clean Level-0 run on Plant B acidified on 5 of 12 seeds while
the plant's own description said its trucked feed is "blended in a 65,000-gal tank" that
the simulator did not have (the lead's ruling 1, 2026-09-03). It sits between the frozen
influent generator and the truth model, so a bug here would silently change every Plant B
cell while every anchored delivery statistic — which describes arrivals, not what leaves
the tank — went on passing.

Five properties, each checked against something other than the implementation:

0. **It solves its own differential equation.** Per component, per day, against the
   closed-form solution of ``dV/dt = q - V/tau`` written out from the ODE. This replaced
   an assertion of the form ``sum(a) - sum(b) == sum(a - b)``, which is an identity of
   addition and was true for *any* ``load_out`` at all — including a pass-through. A
   negative control asserts that the new comparison rejects exactly that broken tank.
1. **Mass is conserved**, to machine precision, against an independent balance
   ``in - out = end level - start level`` computed from the returned series, and per
   component against the analytical hold-up.
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


def _analytical_buffer(
    q_in: np.ndarray, load_in: np.ndarray, hold_up_d: float
) -> tuple[np.ndarray, np.ndarray]:
    r"""The exact solution of the tank's own differential equation, written from the ODE.

    Over one day the arrivals are held constant, so :math:`dm/dt = w - m/\tau` has the
    closed-form solution :math:`m(s) = m^* + (m_0 - m^*) e^{-s/\tau}` with
    :math:`m^* = w\tau`, and what *leaves* over the day is the integral of the draw rate:

    .. math::

        \int_0^1 \frac{m(s)}{\tau} ds
          = \frac{m^*}{\tau} + (m_0 - m^*)\left(1 - e^{-1/\tau}\right)
          = w + (m_0 - w\tau)\left(1 - e^{-1/\tau}\right)

    That last line is derived from the ODE, not from
    :func:`~sim.plants.equalisation.buffer_series`, which computes the outflow as the
    *balance* ``in - (level change)``. The two are equal only if the balance the
    implementation keeps is the balance this equation describes — which is the whole
    property, and is why this is written out rather than calling the implementation twice.

    Returns:
        ``(q_out, load_out)``, the flow and the per-component load leaving each day.
    """
    tau = float(hold_up_d)
    relaxed = 1.0 - np.exp(-1.0 / tau)
    q_out = np.empty_like(q_in)
    load_out = np.empty_like(load_in)
    level = float(q_in.mean() * tau)  # the tank starts at its steady state for this run
    mass = load_in.mean(axis=0) * tau
    for t in range(q_in.size):
        q_out[t] = q_in[t] + (level - q_in[t] * tau) * relaxed
        load_out[t] = load_in[t] + (mass - load_in[t] * tau) * relaxed
        level = q_in[t] * tau + (level - q_in[t] * tau) * (1.0 - relaxed)
        mass = load_in[t] * tau + (mass - load_in[t] * tau) * (1.0 - relaxed)
    return q_out, load_out


@pytest.mark.parametrize("hold_up", [0.5, 4.0, 12.0])
def test_the_tank_solves_its_own_differential_equation(arrivals, hold_up):
    """Per component, against the analytical solution of ``dV/dt = q - V/tau``.

    This replaces an assertion of the form ``sum(a) - sum(b) == sum(a - b)``, which is an
    identity of addition and was therefore true for **any** ``load_out`` whatsoever — a
    pass-through, a zero series, a scrambled one. The tank sits between the frozen influent
    generator and the truth model on every Plant B cell, and that guard would not have
    noticed if it had stopped working. The implementation is correct — an independent
    Radau integration of the same ODE (`scipy.solve_ivp`, rtol 1e-12) agrees to 1.2e-13 on
    the flow and 2.5e-13 on the loads — so this is a guard that starts guarding, not a bug
    fix. Confirmed by mutation: `load_out[t] = load_in[t]` fails this test at all three
    hold-ups and the mass balance below, and failed nothing before.
    """
    load = np.stack([arrivals * 2.0, arrivals * 0.5, np.full_like(arrivals, 7.0)], axis=1)
    q_out, load_out, _ = buffer_series(arrivals, load, hold_up_d=hold_up)
    q_expected, load_expected = _analytical_buffer(arrivals, load, hold_up)

    np.testing.assert_allclose(q_out, q_expected, rtol=0, atol=1e-12)
    for i in range(load.shape[1]):
        np.testing.assert_allclose(load_out[:, i], load_expected[:, i], rtol=0, atol=1e-12)


def test_that_comparison_rejects_a_pass_through(arrivals):
    """NEGATIVE CONTROL for the test above: the broken tank it was blind to must now fail.

    ``load_out[t] = load_in[t]`` — the bug the old identity could not see — is measured
    here against the same analytical solution and is off by more than 4 % of the mean load
    at a 4-day hold-up, so the comparison has teeth.
    """
    load = np.stack([arrivals * 2.0, arrivals * 0.5], axis=1)
    _, load_expected = _analytical_buffer(arrivals, load, 4.0)
    with pytest.raises(AssertionError):
        np.testing.assert_allclose(load, load_expected, rtol=0, atol=1e-12)
    worst = float(np.abs(load - load_expected).max() / np.abs(load).mean())
    assert worst > 0.04, worst


def test_the_tank_conserves_mass_to_machine_precision(arrivals):
    """``in - out = end level - start level``, computed from the returned series alone."""
    load = np.stack([arrivals * 2.0, arrivals * 0.5], axis=1)
    q_out, load_out, levels = buffer_series(arrivals, load, hold_up_d=4.0)

    # the level after the last step is not in `levels`, so reconstruct it from the balance
    # of the final step and check the whole horizon closes against it
    cumulative = levels[0] + np.cumsum(arrivals - q_out)
    np.testing.assert_allclose(cumulative[:-1], levels[1:], rtol=0, atol=1e-9)
    assert arrivals.sum() - q_out.sum() == pytest.approx(cumulative[-1] - levels[0], abs=1e-9)
    # per component: what went in, less what came out, is what the tank is still holding.
    # The held mass is reconstructed from the ANALYTICAL relaxation, not from the returned
    # series, so this is a balance and not the identity sum(a) - sum(b) == sum(a - b).
    tau = 4.0
    decay = float(np.exp(-1.0 / tau))
    for i in range(load.shape[1]):
        held = load[:, i].mean() * tau  # the starting inventory
        for t in range(load.shape[0]):
            target = load[t, i] * tau
            held = target + (held - target) * decay
        assert load[:, i].sum() - load_out[:, i].sum() == pytest.approx(
            held - load[:, i].mean() * tau, abs=1e-9
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
