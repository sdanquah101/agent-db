"""mass_balance: COD, N and charge closure over windows -- physical admissibility (§6.2).

Per window, from daily load series and observed series:

- **COD**: ``in = sum(cod_in)``; ``out = CH4 as COD + effluent COD``, where methane is
  ``gas_flow x ch4_fraction x 2.857 kg COD/m3`` (0 degC, 1 atm, dry) and the effluent
  COD is ``cod_total x q_in`` (the digester's outflow equals its inflow at constant
  volume). Closure ``(in - out) / in``; admissible within ``cod_closure_band``. Without a
  gas record or a COD record the window is not evaluable.
- **N**: ``in = TKN load``, ``out = TAN x q``; only ammoniacal N is observed, so the closure
  *is* the organic-N share of the digestate and is admissible inside the expected range
  ``n_closure_expected``. A closure outside it in either direction is a violated balance
  (an unrecorded delivery shows up here).
- **Charge**: the digestate's strong-ion difference implied by electroneutrality from pH,
  total alkalinity, VFA and TAN under the given pK_a values:
  ``SID = HCO3- + VFA- - NH4+ + OH- - H+`` (keq/m3). It is a state of the liquor, so its
  relative range across windows (``charge_drift``) is the check: a steady feed cannot
  move it, and a record in which it swings is inconsistent with itself or with its feed.

Costs no simulator evaluation. Units are stated on every field.
"""

from __future__ import annotations

import numpy as np

from tools.registry import ToolArgumentError, ToolContext
from tools.schemas import MassBalanceInput, MassBalanceOutput, ObservedSeries, Window
from tools.schemas.tools import WindowBalance

__all__ = ["implied_sid", "mass_balance_cost", "run_mass_balance"]

KG_HAC_PER_KMOL = 60.05
"""Molar mass of acetic acid, kg/kmol (VFA is reported as acetic acid)."""


def mass_balance_cost(inp: MassBalanceInput, ctx: ToolContext) -> int:
    """No simulator evaluation."""
    return 0


def _window_mean(series: ObservedSeries | None, w: Window) -> tuple[float | None, int]:
    if series is None:
        return None, 0
    obs = series.observed
    inside = obs[(series.t[obs] >= w.start) & (series.t[obs] <= w.end)]
    if inside.size == 0:
        return None, 0
    return float(np.mean(series.value[inside])), int(inside.size)


def implied_sid(
    ph: float,
    alkalinity_kg_caco3_m3: float,
    vfa_kg_hac_m3: float,
    tan_kg_n_m3: float,
    pK_a_ac: float,
    pK_a_co2: float,
    pK_a_IN: float,
    kg_caco3_per_keq: float,
    kg_n_per_kmol: float,
) -> float:
    """Strong-ion difference of the liquor implied by electroneutrality, keq/m3.

    Total alkalinity is bicarbonate plus VFA anions (the titration end point is below
    the VFA pK_a), so ``HCO3- = alk - VFA-``; ammonium is TAN times its ionised fraction.
    """
    h = 10.0**-ph
    vfa_total = vfa_kg_hac_m3 / KG_HAC_PER_KMOL
    vfa_ion = vfa_total / (1.0 + h / 10.0**-pK_a_ac)
    alk = alkalinity_kg_caco3_m3 / kg_caco3_per_keq
    hco3 = max(alk - vfa_ion, 0.0)
    tan = tan_kg_n_m3 / kg_n_per_kmol
    nh4 = tan / (1.0 + 10.0**-pK_a_IN / h)
    oh = 1e-14 / h
    return hco3 + vfa_ion - nh4 + oh - h


def run_mass_balance(inp: MassBalanceInput, ctx: ToolContext) -> MassBalanceOutput:
    """Closure per window."""
    conf = ctx.configs.mass_balance
    t = np.asarray(inp.t, dtype=float)
    for name in ("q_in_m3_d", "cod_in_kg_d", "tkn_in_kg_n_d"):
        if getattr(inp, name).shape != t.shape:
            raise ToolArgumentError(f"{name} must be on the same daily grid as t")
    out: list[WindowBalance] = []
    sids: list[float] = []
    admissible = True
    for w in inp.windows:
        days = (t >= w.start) & (t <= w.end)
        if not days.any():
            raise ToolArgumentError(f"window {w.start}-{w.end} d contains no day of the load grid")
        cod_in = float(np.sum(inp.cod_in_kg_d[days]))
        n_in = float(np.sum(inp.tkn_in_kg_n_d[days]))
        q_mean = float(np.mean(inp.q_in_m3_d[days]))
        n_days = int(days.sum())

        gas, n_gas = _window_mean(inp.gas_flow, w)
        ch4, n_ch4 = _window_mean(inp.ch4_fraction, w)
        cod_eff, n_cod = _window_mean(inp.cod_out, w)
        tan_eff, n_tan = _window_mean(inp.tan_out, w)
        n_samples = min([n for n in (n_gas, n_ch4, n_cod) if n > 0], default=0)

        cod_ch4 = cod_out = closure = None
        cod_ok = None
        if (
            gas is not None
            and ch4 is not None
            and cod_eff is not None
            and n_samples >= conf.min_samples_per_window
        ):
            cod_ch4 = gas * ch4 * conf.cod_per_m3_ch4_stp * n_days
            cod_out = cod_eff * q_mean * n_days
            if cod_in > 0.0:
                closure = (cod_in - cod_ch4 - cod_out) / cod_in
                cod_ok = bool(abs(closure) <= conf.cod_closure_band)
                admissible = admissible and cod_ok

        n_out = n_closure = None
        n_ok = None
        if tan_eff is not None and n_tan >= conf.min_samples_per_window and n_in > 0.0:
            n_out = tan_eff * q_mean * n_days
            n_closure = (n_in - n_out) / n_in
            lo, hi = conf.n_closure_expected
            n_ok = bool(lo <= n_closure <= hi)
            admissible = admissible and n_ok

        sid = None
        ph, n_ph = _window_mean(inp.ph, w)
        alk, n_alk = _window_mean(inp.alkalinity, w)
        vfa, n_vfa = _window_mean(inp.vfa, w)
        tan, _ = _window_mean(inp.tan_out, w)
        if None not in (ph, alk, vfa, tan) and min(n_ph, n_alk, n_vfa) >= 1:
            sid = implied_sid(
                ph,
                alk,
                vfa,
                tan,
                inp.pK_a_ac,
                inp.pK_a_co2,
                inp.pK_a_IN,
                conf.kg_caco3_per_keq,
                conf.kg_n_per_kmol,
            )
            sids.append(sid)

        out.append(
            WindowBalance(
                window=w,
                n_samples=n_samples,
                cod_in_kg=cod_in,
                cod_out_ch4_kg=cod_ch4,
                cod_out_effluent_kg=cod_out,
                cod_closure=closure,
                cod_admissible=cod_ok,
                n_in_kg=n_in,
                n_out_tan_kg=n_out,
                n_closure=n_closure,
                n_admissible=n_ok,
                implied_sid_keq_m3=sid,
            )
        )
    drift = None
    consistent = None
    if len(sids) >= 2:
        scale = float(np.mean(np.abs(sids)))
        drift = float((max(sids) - min(sids)) / scale) if scale > 0 else 0.0
        consistent = bool(drift <= conf.charge_drift_band)
        admissible = admissible and consistent
    units = {
        "cod_in_kg": "kg COD",
        "cod_out_ch4_kg": "kg COD",
        "cod_out_effluent_kg": "kg COD",
        "n_in_kg": "kg N",
        "n_out_tan_kg": "kg N",
        "implied_sid_keq_m3": "keq/m3",
        "cod_closure": "-",
        "n_closure": "-",
        "charge_drift": "-",
    }
    return MassBalanceOutput(
        windows=tuple(out),
        charge_drift=drift,
        charge_consistent=consistent,
        admissible=admissible,
        units=units,
    )
