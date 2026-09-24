"""The fitted model with a parameter change at a known day (review of PR #25, item 4).

A Level-5 truth is a parameter shift at a known onset. A constant multiplier cannot
represent it, so this subclass gives the parameter class its representable form. The
defaults hold until ``onset_d``, and ``theta`` holds after it. It uses the harness's own
segment helpers (``sim.run.harness``, read-only): one integration per segment, stitched
with no repeated time.
"""

from __future__ import annotations

import numpy as np

from sim.adm1 import compile_extended, extended_state, load_initial_state, simulate_extended
from sim.adm1.schema import N_STATES
from sim.observation import ash_trajectory, channel_series
from sim.run.harness import _segment_grid, _stitch_extended
from tools.fitted import FittedADM1

__all__ = ["ChangePointADM1"]


class ChangePointADM1(FittedADM1):
    """``FittedADM1`` whose ``theta`` applies from ``onset_d`` on; the defaults before."""

    def __init__(self, *args: object, onset_d: float, **kwargs: object) -> None:
        """Build the fitted model and remember the change point."""
        super().__init__(*args, **kwargs)
        if not 0.0 < float(onset_d) < self.horizon_d:
            raise ValueError(f"onset {onset_d} d is outside the record (0, {self.horizon_d})")
        self.onset_d = float(onset_d)

    def evaluate(self, theta: np.ndarray, **options: object) -> dict[str, np.ndarray]:
        """Burn-in and the first segment at the defaults, the second at ``theta``."""
        if options:
            raise ValueError(f"the change-point model takes no options, got {sorted(options)}")
        before = self._parameters(self.defaults)
        after = self._parameters(theta)
        models = [
            compile_extended(
                p, self.geometry, self._matrix, self._solver, self._ext_config, self.extensions
            )
            for p in (before, after)
        ]
        ext_states = set(models[0].state_names[N_STATES:])
        u_ext = {k: v for k, v in self._u_ext_all.items() if k in ext_states}
        init_ext = {
            k: v for k, v in self.config.initial_extension_states.items() if k in ext_states
        }
        y0 = extended_state(models[0], load_initial_state(), init_ext)
        burn = simulate_extended(
            y0=y0,
            influent=self._burn_influent,
            model=models[0],
            t_span=(0.0, self.config.burn_in_days),
            t_eval=np.arange(
                0.0, self.config.burn_in_days + 1e-9, self.config.burn_in_output_interval_d
            ),
            u_ext=u_ext,
        )
        y_start = np.array(burn.y[:, -1], dtype=float)
        parts = []
        bounds = [(0.0, self.onset_d), (self.onset_d, self.horizon_d)]
        for k, (model, (start, end)) in enumerate(zip(models, bounds, strict=True)):
            grid = _segment_grid(self.t, start, end, first=k == 0)
            part = simulate_extended(
                y0=y_start, influent=self._influent, model=model,
                t_span=(start, end), t_eval=grid, u_ext=u_ext,
            )  # fmt: skip
            parts.append(part)
            y_start = np.array(part.y[:, -1], dtype=float)
            if abs(float(part.t[-1]) - end) > 1e-9:
                raise ValueError(f"segment {k} ended at {part.t[-1]}, not {end}")
        result = _stitch_extended(parts)
        self._last = (bool(burn.success and result.success), str(result.message))
        grid = np.asarray(result.t, dtype=float)
        ash = ash_trajectory(grid, self._influent, self.geometry.V_liq, self._ash_in)
        channels = channel_series(
            result,
            T_op=self.geometry.T_op,
            inert_cod_equivalent=self._inert,
            ash=ash,
            physchem=after.physchem,
        )
        out = {}
        for name in self.output_names:
            series = np.asarray(channels[name], dtype=float)
            if series.size < self.t.size:
                series = np.concatenate([series, np.full(self.t.size - series.size, series[-1])])
            out[name] = series
        return out
