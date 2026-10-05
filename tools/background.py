"""``declared_background``: the null band of a clean record, per plant and tier (§6.2).

Decision 1 of ``docs/decisions.md`` (2026-09-30). The benchmark publishes, per plant and
per tier, the COD-closure band and the per-channel standardised-residual envelope that a
**clean** record on that plant shows under the tools' own fitted model, at the default
parameters and after a declared screened fit. It is computed offline from seeded clean
generator runs (``scripts/declared_background.py``; the runs are recorded under
``reports/background/``), committed as ``configs/background.yaml``, published in the
benchmark card beside the declared instrument noise, and served here as one more
versioned, logged registry tool.

**What it is not.** It is not among the frozen tools of ``tools/impl/``: it lives beside
the table as a new entry (:func:`full_specs`), so no existing tool's output changes and
P0's plan and outputs stay byte-identical (the two-head freeze test). P0 does not call
it; the frozen P1 does not call it (its tool list is committed and hashed); P2's verifier
and influent role read it.

**Rule 1.** The tool is a pure function of ``(plant, tier)`` and the committed
configuration: it reads nothing of the run, so it answers the same on every run of that
plant at that tier, and the band carries nothing per cell or per scenario (the
configuration's keys are plant and tier; tested with a negative control).
"""

from __future__ import annotations

from collections.abc import Mapping

from tools.registry import ToolArgumentError, ToolContext, ToolSpec
from tools.schemas import DeclaredBackgroundInput, DeclaredBackgroundOutput

__all__ = ["SPEC", "TOOL_NAME", "background_cost", "full_specs", "run_background"]

TOOL_NAME = "declared_background"

UNITS: dict[str, str] = {
    "mean_z": "- (multiples of the declared measurement sd)",
    "rms_z": "- (multiples of the declared measurement sd)",
    "cod_closure": "- ((in - out) / in over a window)",
    "cod_closure_windows": "- ((in - out) / in over a window)",
    "n_closure": "- ((TKN in - TAN out) / TKN in over a window)",
    "charge_drift": "- (relative range of the implied SID across windows)",
    "horizon_d": "d",
    "calibration_window": "d",
    "balance_window_d": "d",
    "n_samples": "count",
    "n_cod_windows": "count",
    "n_cod_evaluable": "count",
    "n_cod_inadmissible": "count",
    "n_fitted": "count",
}


def background_cost(inp: DeclaredBackgroundInput, ctx: ToolContext) -> int:
    """No simulator evaluation: the band is read from the committed configuration."""
    return 0


def run_background(inp: DeclaredBackgroundInput, ctx: ToolContext) -> DeclaredBackgroundOutput:
    """The band of ``(plant, tier)`` with the procedure that produced it.

    Raises:
        ToolArgumentError: If no band was computed for that plant and tier.
    """
    config = ctx.configs.background
    band = config.band(inp.plant, inp.tier)
    if band is None:
        have = sorted(f"{p}/{t}" for p, tiers in config.bands.items() for t in tiers)
        raise ToolArgumentError(
            f"no declared background for plant {inp.plant} at tier {inp.tier}; "
            f"the configuration carries {have}"
        )
    return DeclaredBackgroundOutput(
        plant=inp.plant,
        tier=inp.tier,
        status=config.provenance.status,
        band_seeds=config.provenance.seeds,
        procedure=config.procedure,
        units=dict(UNITS),
        **band.model_dump(),
    )


SPEC = ToolSpec(
    name=TOOL_NAME,
    input_model=DeclaredBackgroundInput,
    output_model=DeclaredBackgroundOutput,
    run=run_background,
    cost=background_cost,
)
"""The tool, as the registry takes it."""


def full_specs(base: Mapping[str, ToolSpec] | None = None) -> dict[str, ToolSpec]:
    """The frozen tool table (:data:`tools.impl.SPECS`) with the declared background beside it.

    The frozen table is left as it is (``tools/impl/`` does not change); this is the one
    place the new entry joins it, and both registry builders read the table from here.
    """
    if base is None:
        from tools.impl import SPECS

        base = SPECS
    if TOOL_NAME in base:
        raise ValueError(f"{TOOL_NAME!r} is already in the table")
    return {**base, TOOL_NAME: SPEC}
