r"""The declared blend tank: trucked deliveries reach the digester smoothed, not as pulses.

A trucked feed does not go straight into a digester. It is discharged into a receiving or
blend tank and drawn from there, and Muscatine's own plant description says so — its
high-strength waste is "blended in a 65,000-gal tank". The benchmark's plant contract
recorded that in a comment and its simulator did not implement it, and the consequence was
measured at gate G1: a clean Level-0 run on Plant B acidified on **5 of 12 seeds**, because
a run of large arrivals reached the biomass as an acid pulse rather than as a week of
slightly heavier feeding (the lead's ruling 1, 2026-09-03).

**The influent generator is untouched.** It still draws the same deliveries, with the same
statistics, anchored to the same columns; the operator's feed log still records what the
trucks brought. What changes is only what the *digester* sees, which is what a tank does.
That also means every anchored delivery statistic is unaffected: those describe arrivals,
not what leaves the tank.

**The model.** One continuously stirred buffer per plant, holding the feeds the contract
names. Over a day, with the day's arrivals held constant,

.. math::

    \frac{dV}{dt} = q_\\text{in} - \frac{V}{\tau}, \qquad
    \frac{dm_i}{dt} = (qc)_{\\text{in},i} - \frac{m_i}{\tau}

integrated exactly, where :math:`\tau` is the hold-up implied by the declared volume and
the long-run buffered flow. Drawing in proportion to level is what a level-controlled pump
does, and it makes the tank unconditionally stable: it cannot run dry or overflow, and in
steady state it passes exactly what it receives. Mass is conserved to machine precision on
every step, because the outflow is computed *from* the balance rather than alongside it.

At :math:`\tau \to 0` the tank reduces to a pass-through, exactly; the test asserts it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from sim.adm1.schema import Influent
from sim.plants.schema import Equalisation

__all__ = [
    "INITIALISATION_WINDOW_D",
    "BufferedInfluent",
    "apply_equalisation",
    "buffer_series",
    "feed_contribution",
]

INITIALISATION_WINDOW_D = 30
"""Days of arrivals the tank's hold-up is set from (the "long-run buffered flow").

The hold-up and the day-0 tank state used to be taken from the WHOLE-HORIZON mean of
arrivals, which made the digester's starting point a function of the run's length: two
runs of the same seed at 200 and 240 d started from different tank contents and their
starting points differed (`docs/f2_horizon_report.md` section 15; the lead's ruling 1 of
2026-09-11). The hold-up is
now set from the first 30 days of arrivals (three hold-ups of the Muscatine tank) and the
tank's initial level and load from the first hold-up window, so neither depends on how
long the run is."""


@dataclass(frozen=True)
class BufferedInfluent:
    """What the digester receives once the trucked feeds have passed through the tank."""

    influent: Influent
    """The influent series to integrate, buffered feeds smoothed and direct feeds untouched."""
    tank_volume_m3: np.ndarray
    """Tank level at the start of each day, m3. Declared, so a workflow may be shown it."""
    hold_up_d: float
    """``V_declared / mean buffered flow``: the tank's time constant, d."""
    buffered_feeds: tuple[str, ...]
    passthrough_q_m3_d: np.ndarray
    """Buffered flow *into* the tank per day, m3/d — the unsmoothed arrivals."""


def buffer_series(
    q_in: np.ndarray,
    load_in: np.ndarray,
    hold_up_d: float,
    *,
    init_window_d: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Push a flow and its component loads through one well-mixed tank.

    Args:
        q_in: Arrivals per day, m3/d, shape ``(n,)``.
        load_in: Component load per day, ``(n, k)``, in each component's own unit times
            m3/d (i.e. concentration x flow).
        hold_up_d: Tank time constant, d. Must be positive.
        init_window_d: Days of arrivals the tank's day-0 state is the steady state of.
            ``None`` uses the whole series (the behaviour before 2026-09-10, kept for the
            analytical tests); the harness passes the hold-up, so the initial state does not
            depend on the run's length.

    Returns:
        ``(q_out, load_out, level)``: the flow and load leaving the tank each day, and the
        tank level at the start of each day.

    Raises:
        ValueError: If the hold-up is not positive or the shapes disagree.
    """
    q_in = np.asarray(q_in, dtype=float)
    load_in = np.asarray(load_in, dtype=float)
    if hold_up_d <= 0.0:
        raise ValueError(f"hold-up must be positive, got {hold_up_d}")
    if load_in.shape[0] != q_in.shape[0]:
        raise ValueError(f"load {load_in.shape} does not match flow {q_in.shape}")

    decay = float(np.exp(-1.0 / hold_up_d))
    # the tank starts at its own steady state for the arrivals of its first window: the
    # plant has been running, so the buffer is not empty on day 0. It was the WHOLE-HORIZON
    # mean until 2026-09-11 (recorded as dormant at the review of 2026-09-10), which made
    # the day-0 state of every Plant B cell depend on the run's length
    # (docs/f2_horizon_report.md section 15; the lead's ruling 1); a window of one hold-up
    # is what the tank can actually "know" on day 0.
    n_init = (
        q_in.size if init_window_d is None else max(1, min(q_in.size, int(np.ceil(init_window_d))))
    )
    level = float(q_in[:n_init].mean() * hold_up_d)
    mass = load_in[:n_init].mean(axis=0) * hold_up_d

    q_out = np.empty_like(q_in)
    load_out = np.empty_like(load_in)
    levels = np.empty_like(q_in)
    for t in range(q_in.size):
        levels[t] = level
        target = q_in[t] * hold_up_d
        next_level = target + (level - target) * decay
        # the outflow IS the balance, so mass closes to machine precision
        q_out[t] = q_in[t] - (next_level - level)
        target_mass = load_in[t] * hold_up_d
        next_mass = target_mass + (mass - target_mass) * decay
        load_out[t] = load_in[t] - (next_mass - mass)
        level, mass = next_level, next_mass
    return q_out, load_out, levels


def apply_equalisation(
    influent: Influent,
    buffered_q_m3_d: np.ndarray,
    buffered_load: np.ndarray,
    config: Equalisation,
) -> BufferedInfluent:
    """Smooth the buffered share of an influent series through the declared tank.

    Takes the **buffered** share and derives the direct share as ``total - buffered``. Both
    sides are exact by mass balance, so the only question is which one the caller has to
    reconstruct from the catalogue and which comes free; the caller reconstructs whichever
    side no composition-altering fault touches (see
    :func:`sim.run.harness.split_for_equalisation`), and the residual is then correct
    whatever happened on the other side — including a mislabelled batch, whose redrawn
    fractionation this module never has to know.

    Args:
        influent: The generator's influent series (all feeds).
        buffered_q_m3_d: Flow of the feeds that pass through the tank, m3/d per day.
        buffered_load: Their component load, ``(n_days, 26)``.
        config: The plant's declared buffer.

    Returns:
        The buffered influent and the tank's own record.

    Raises:
        ValueError: If no flow passes through the buffer, or the shapes disagree.
    """
    q_total = np.asarray(influent.q, dtype=float)
    load_total = q_total[:, None] * np.asarray(influent.concentrations, dtype=float)
    q_buffered = np.asarray(buffered_q_m3_d, dtype=float)
    load_buffered = np.asarray(buffered_load, dtype=float)
    if q_buffered.shape != q_total.shape or load_buffered.shape != load_total.shape:
        raise ValueError("the buffered-feed arrays do not match the influent series")
    direct_q = np.maximum(q_total - q_buffered, 0.0)
    direct_load = load_total - load_buffered

    # the "long-run buffered flow" the hold-up is set from is the first INITIALISATION_WINDOW_D
    # days of arrivals, not the whole horizon: the same run at two lengths must be the same
    # tank (docs/f2_horizon_report.md section 14)
    mean_flow = float(q_buffered[: min(q_buffered.size, INITIALISATION_WINDOW_D)].mean())
    if mean_flow <= 0.0:
        raise ValueError("no flow passes through the declared buffer in its first window")
    hold_up = config.volume_m3 / mean_flow

    q_out, load_out, levels = buffer_series(
        q_buffered, load_buffered, hold_up, init_window_d=hold_up
    )
    q_new = direct_q + q_out
    load_new = direct_load + load_out
    conc = np.zeros_like(load_new)
    fed = q_new > 0.0
    conc[fed] = load_new[fed] / q_new[fed, None]
    return BufferedInfluent(
        influent=Influent(
            t=np.asarray(influent.t, dtype=float),
            concentrations=conc,
            q=q_new,
            interpolation=influent.interpolation,
        ),
        tank_volume_m3=levels,
        hold_up_d=hold_up,
        buffered_feeds=tuple(config.feeds),
        passthrough_q_m3_d=q_buffered,
    )


def feed_contribution(
    feed_ids: Sequence[str],
    per_feed_q: Mapping[str, np.ndarray],
    per_feed_conc: Mapping[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Sum the flow and load of a set of feeds.

    Args:
        feed_ids: The feeds to sum.
        per_feed_q: Feed id -> flow per day, m3/d.
        per_feed_conc: Feed id -> ``(n_days, 26)`` concentrations of that feed.

    Returns:
        ``(q, load)`` summed over them.
    """
    q = sum(np.asarray(per_feed_q[f], dtype=float) for f in feed_ids)
    load = sum(
        np.asarray(per_feed_q[f], dtype=float)[:, None] * np.asarray(per_feed_conc[f], dtype=float)
        for f in feed_ids
    )
    return np.asarray(q), np.asarray(load)
