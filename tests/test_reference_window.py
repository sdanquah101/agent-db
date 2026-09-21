"""A whole run is prefix-stable in its horizon (the lead's ruling 6, 2026-09-11).

Ruling 1 made the influent generator and the blend tank prefix-stable; the coordinator's
check of that commit found that a whole run still was not, because the harness took the
truth parameters, the burn-in recipe, the calcium extension state and the channels' inert
COD equivalent from the mean recipe over the WHOLE horizon, so 190-, 200- and 210-d runs of
one seed differed by ~2 %. Ruling 6 derives all of those from a fixed reference window — the
first ``REFERENCE_WINDOW_D`` (200) days of the generated influent, the shorter of the two
matrix horizons — at the source, the generator's ``mean_recipe_kg_d``, so nothing downstream
can drift.

Two levels are tested: the generator's reference recipe (fast), and one whole run per matrix
horizon — a Plant B row at 200 against 210 d and a Plant A row at 365 against 375 d — whose
truth trajectory, channels and flags over the shared prefix must agree. The solver takes the
same steps over the shared span, so the agreement is bit-exact except at the shorter run's
final output point, which the shorter run reaches by a step clipped to its end and the longer
run by dense-output interpolation; that last point agrees to solver tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.adm1 import load_parameters
from sim.influent import generate_influent, load_feed_fractionation, load_generator_config
from sim.influent.generator import REFERENCE_WINDOW_D
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from tests.conftest import REPO_ROOT

SCENARIOS = REPO_ROOT / "scenarios"


def test_the_reference_window_is_the_shorter_matrix_horizon():
    """200 d: the shorter matrix horizon, so every cell's window is the same first 200 days.

    B and C run 200 d and A 365 (ruling 3), so every cell's first 200 days exist.
    """
    assert REFERENCE_WINDOW_D == 200
    assert min(load_plant_config(p).horizon_days for p in "ABC") == REFERENCE_WINDOW_D


def test_the_reference_recipe_is_the_first_window_whatever_the_horizon():
    """The reference recipe of a 210-d run is the 200-d run's, and the first-200-day mean.

    The truth ``N_I`` it sets follows. A run shorter than the window averages its whole
    length, so 90 and 130 d differ: the negative control.
    """
    catalogue, generator = load_feed_fractionation(), load_generator_config()
    params = load_parameters()
    plant = load_plant_config("B")

    def run(n_days: int):
        return generate_influent(
            plant, catalogue, generator, params, seed=1004, n_days=n_days
        ).truth

    r200, r210 = run(200), run(210)
    assert r200.mean_recipe_kg_d == r210.mean_recipe_kg_d
    assert r200.N_I == r210.N_I
    for fid, mean in r210.mean_recipe_kg_d.items():
        assert mean == float(r210.feeds[fid].delivered_kg[:REFERENCE_WINDOW_D].mean())
        assert mean != float(r210.feeds[fid].delivered_kg.mean())  # not the horizon mean

    r90, r130 = run(90), run(130)
    assert r90.mean_recipe_kg_d != r130.mean_recipe_kg_d
    for fid, mean in r90.mean_recipe_kg_d.items():
        assert mean == float(r90.feeds[fid].delivered_kg.mean())


@pytest.mark.parametrize(
    ("scenario_id", "plant_id", "short", "long"),
    [("S3-03", "B", 200.0, 210.0), ("S5-01", "A", 365.0, 375.0)],
    ids=["S3-03 on B, 200 v 210 d", "S5-01 on A, 365 v 375 d"],
)
def test_a_whole_run_is_the_prefix_of_a_longer_one(scenario_id, plant_id, short, long):
    """Truth parameters, burn-in, state trajectory, channels and flags over the shared prefix."""
    scenario = load_scenario(SCENARIOS / f"{scenario_id}.yaml")
    plant = load_plant_config(plant_id)

    def truth(days: float):
        cell = scenario.model_copy(update={"duration_days": days})
        return generate_run(cell, "A", plant=plant, write=False).truth

    a, b = truth(short), truth(long)

    n = a.t.size
    assert b.t.size > n
    assert np.array_equal(a.t, b.t[:n])
    # everything derived from the reference recipe is identical, not merely close
    assert a.parameters == b.parameters
    assert a.inert_cod_equivalent == b.inert_cod_equivalent
    assert np.array_equal(a.burn_in_state, b.burn_in_state)
    assert np.array_equal(a.initial_state, b.initial_state)
    assert [s[2] for s in a.segments] == [s[2] for s in b.segments][: len(a.segments)]

    # the trajectory: bit-equal up to the shorter run's last output point, which agrees to
    # solver tolerance (clipped final step against dense-output interpolation)
    assert np.array_equal(a.y[:, : n - 1], b.y[:, : n - 1])
    np.testing.assert_allclose(a.y[:, n - 1], b.y[:, n - 1], rtol=1e-6, atol=1e-9)
    assert np.array_equal(a.ash[: n - 1], b.ash[: n - 1])
    for name in a.channels.names:
        va, vb = np.asarray(a.channels[name]), np.asarray(b.channels[name])
        assert np.array_equal(va[: n - 1], vb[: n - 1]), name
        np.testing.assert_allclose(va[n - 1], vb[n - 1], rtol=1e-6, atol=1e-9, err_msg=name)
    assert np.array_equal(a.overload[: n - 1], b.overload[: n - 1])
    assert np.array_equal(a.foaming[: n - 1], b.foaming[: n - 1])
