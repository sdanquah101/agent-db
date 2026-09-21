"""The VISIBLE record is prefix-stable in the horizon, as the truth beneath it is (ruling 7).

The whole-branch review of 2026-09-12 (blocker 2) found that ruling 6 had made the truth
prefix-stable while what a workflow sees was not: the observation model drew a sensor's six
horizon-length blocks in sequence from one per-sensor stream, the historian its two blocks
from one stream, and the operator log its note days with a horizon-sized ``choice``, so every
visible sensor series of a 200-d run differed from the 210-d run's from index 0 and the note
days moved. Ruling 7 (2026-09-14, the lead's option b) keyed every stream of the visible
record ``SeedSequence([seed, key, block])`` — ``sensor_block_rng`` per sensor block,
``historian_block_rng`` for the historian's onsets and lengths, the notes' per-day draw and
text order by ``(seed, stage)`` — so a cell at its plant's horizon is, in everything a
workflow can read, the first days of the same cell run longer. Two cells, one per horizon in
the matrix: Plant B at 200 d against 210 d and Plant A at 365 d against 375 d, each at the
tier with the most sensors; the truth-side prefix test lives in
``tests/test_reference_window.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.observation.model import historian_block_rng, historian_outages, sample_times
from sim.observation.schema import HistorianDropout
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from tests.conftest import REPO_ROOT

CELLS = [
    pytest.param("S3-03", "B", 200.0, 210.0, id="plant-B-200-vs-210"),
    pytest.param("S5-01", "A", 365.0, 375.0, id="plant-A-365-vs-375"),
]


@pytest.mark.parametrize(("scenario_id", "plant_id", "short_d", "long_d"), CELLS)
def test_the_visible_record_of_a_run_is_the_prefix_of_a_longer_one(
    scenario_id: str, plant_id: str, short_d: float, long_d: float
):
    scenario = load_scenario(REPO_ROOT / "scenarios" / f"{scenario_id}.yaml")
    plant = load_plant_config(plant_id)

    def cell(days: float):
        return generate_run(
            scenario.model_copy(update={"duration_days": days}), "C", plant=plant, write=False
        )

    short, long = cell(short_d), cell(long_d)
    assert short.record.horizon_d == short_d and long.record.horizon_d == long_d

    # every sensor series: times, values, missingness (the per-sensor process and the
    # historian's outages together, in ``missing``) -- equal over the shared prefix
    assert set(short.record.sensors) == set(long.record.sensors)
    for name, series in short.record.sensors.items():
        other = long.record.sensors[name]
        n = series.sample_t.size
        assert other.sample_t.size > n, name
        for field in (
            "sample_t",
            "report_t",
            "value",
            "missing",
            "saturated",
            "flatlined",
            "fouled",
        ):
            mine, theirs = getattr(series, field), getattr(other, field)
            # bit-equal up to the shorter run's last sample; that sample reads the truth at
            # the run's end, which the shorter run reaches by a solver step clipped to it and
            # the longer by dense output (tests/test_reference_window.py), so it agrees to
            # solver tolerance, not bit for bit
            assert np.array_equal(mine[: n - 1], theirs[: n - 1], equal_nan=True), (name, field)
            if mine.dtype.kind == "f":
                np.testing.assert_allclose(mine[n - 1], theirs[n - 1], rtol=1e-9, atol=1e-12)
            else:
                assert mine[n - 1] == theirs[n - 1], (name, field)
    # the missingness compared above was not vacuous: some online sample was lost
    assert any(s.missing.any() for s in short.record.sensors.values()), (
        "no missing sample at tier C, nothing compared"
    )

    # the operator log: the notes of the shorter run are the longer run's notes before its
    # end -- days AND texts (S3-03 has no false-cause note; S5-01's is written on the onset
    # day, inside both horizons)
    before_end = tuple(note for note in long.notes if note.day < short_d)
    assert short.notes == before_end
    assert [n.day for n in short.notes] == [n.day for n in before_end]
    assert [n.text for n in short.notes] == [n.text for n in before_end]
    assert short.notes, "a run must still carry notes"
    assert any(n.author == "operator" for n in short.notes), "no benign note drawn"

    # the feed record: log and assays (ruling 1's generator, seen through the run)
    s_obs, l_obs = short.truth.influent.observed, long.truth.influent.observed
    for fid, logged in s_obs.feed_log_kg_wet_d.items():
        assert np.array_equal(logged, l_obs.feed_log_kg_wet_d[fid][: logged.size]), fid
    early = {r for r in s_obs.assays if r.sample_day < short_d - 10}
    assert early == {r for r in l_obs.assays if r.sample_day < short_d - 10}

    # negative control on the comparison itself: the longer run's tail is not its head
    for name, series in long.record.sensors.items():
        tail = series.value[-min(20, series.value.size) :]
        head = series.value[: tail.size]
        finite = np.isfinite(tail) & np.isfinite(head)
        if finite.sum() >= 5:
            assert not np.array_equal(tail[finite], head[finite]), name
            break


def test_the_historian_mask_alone_is_prefix_stable_and_keyed_by_seed():
    """The plant-level outage mask, on its own.

    The shorter horizon's mask is the prefix of the longer's, from the same two keyed
    streams, and another seed gives another mask.
    """
    dropout = HistorianDropout(
        rate_by_tier={"A": 0.05, "B": 0.05, "C": 0.05}, gap_lengths_min=(1.0, 2.0, 9.8, 421.0)
    )
    interval = 1.0 / 96.0  # a 15-min schedule, so that outage lengths matter too

    def mask(seed: int, horizon: float) -> np.ndarray:
        t = sample_times(interval, horizon)
        return historian_outages(
            dropout, "C", t, historian_block_rng(seed, 0), historian_block_rng(seed, 1)
        )

    short, long = mask(7, 200.0), mask(7, 210.0)
    assert short.size < long.size
    # an outage starting in the last minutes of the shorter horizon can run past its end
    # in the longer mask, but never changes a sample inside the horizon
    assert np.array_equal(short, long[: short.size])
    assert short.any(), "a 5 % rate over 200 d of 15-min samples drew no outage"
    # negative control: another seed, another mask; onsets and lengths from distinct streams
    assert not np.array_equal(short, mask(8, 200.0))
    assert historian_block_rng(7, 0).uniform() != historian_block_rng(7, 1).uniform()
