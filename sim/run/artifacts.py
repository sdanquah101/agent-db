"""Writing a run to disk: hidden truth under ``truth/``, everything else under ``observations/``.

CLAUDE.md rule 1 is a *directory* boundary, so the separation is enforced here by the
crudest possible means: two functions, each of which can only write into one region.
:func:`write_truth` takes the paths' ``truth`` directory and never touches
``observations``; :func:`write_observations` takes the ``observations`` directory and is
handed only the objects a workflow may see. A quantity that belongs on the other side of
the line has to be moved between functions to get there, which is a diff a reviewer sees.

**What goes where** (benchmark card §4):

===============================  ==========================================================
``truth/parameters.json``        true ADM1 parameters per segment, truth ``N_I``, the
                                 extensions the truth model ran and those the fitted model
                                 may carry
``truth/influent.npz``           true daily deliveries, true solids, the true influent
                                 series and its dissolved calcium
``truth/fractionation.json``     the true COD fractionation of every feed, and the
                                 mislabelled window if there is one
``truth/geometry.json``          realised active-volume error, realised mixing structure
``truth/states.npz``             the full state trajectory and the burn-in state
``truth/channels.npz``           every observable channel plus the condition flags
``truth/faults.json``            the fault plan by layer, the truth label, and the
                                 scenario's ``correct_conclusion``
------------------------------   ----------------------------------------------------------
``observations/sensors.json``    the tier's :class:`~sim.observation.model.ObservationRecord`
``observations/feed_log.csv``    the operator's feed log, mis-logs applied
``observations/feed_assays.csv`` the assays this tier's ``feed_assays`` mask permits
``observations/operator_notes.json``  the log notes, including any Level-8 note
===============================  ==========================================================

**Units travel with the values.** Every CSV carries its unit in the column header and every
JSON block carries a ``units`` mapping (CLAUDE.md rule 6), because a run directory is
released as data and will be read by someone who does not have this module in front of them.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from scenarios.schema import Scenario
from sim.adm1.schema import LIQUID_STATE_NAMES
from sim.observation.model import ObservationRecord
from sim.observation.schema import TierSpec
from sim.run.layout import RunPaths
from sim.run.notes import LogNote

if TYPE_CHECKING:  # pragma: no cover - import cycle only at type-check time
    from sim.run.harness import RunTruth

__all__ = [
    "read_feed_assays",
    "read_feed_log",
    "read_observation_record",
    "read_operator_notes",
    "write_observations",
    "write_truth",
]


def _json(path: Path, payload: object) -> None:
    """Write indented JSON with a trailing newline."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ hidden truth


def write_truth(paths: RunPaths, truth: RunTruth, scenario: Scenario) -> None:
    """Write every hidden quantity of a run under ``runs/<id>/truth/``.

    Args:
        paths: The run's paths.
        truth: The run's hidden truth.
        scenario: The scenario, whose ``truth_label`` and ``correct_conclusion`` are the
            answer key and belong here rather than anywhere a workflow could reach.
    """
    paths.truth.mkdir(parents=True, exist_ok=True)
    influent_truth = truth.influent.truth

    _json(
        paths.truth_parameters,
        {
            "note": "true parameters of the truth model; the fitted model never sees these",
            "N_I_kmol_N_per_kg_COD": influent_truth.N_I,
            "truth_extensions": list(truth.fitted_extensions)
            + sorted(set(truth.plan.structure.omit_from_fitted)),
            "fitted_extensions": list(truth.fitted_extensions),
            "omitted_from_fitted": list(truth.plan.structure.omit_from_fitted),
            "segments": [
                {
                    "t_start_d": start,
                    "t_end_d": end,
                    "parameters": params.model_dump(mode="json"),
                }
                for start, end, params in truth.segments
            ],
        },
    )

    feeds = influent_truth.feeds
    feed_ids = sorted(feeds)
    np.savez_compressed(
        paths.truth_influent,
        feed_ids=np.array(feed_ids),
        delivered_kg_wet_per_d=np.stack([feeds[f].delivered_kg for f in feed_ids]),
        total_solids_kg_per_kg_wet=np.stack([feeds[f].ts for f in feed_ids]),
        influent_t_d=influent_truth.influent.t,
        influent_concentrations=influent_truth.influent.concentrations,
        influent_q_m3_per_d=influent_truth.influent.q,
        s_ca_kmol_per_m3=influent_truth.s_ca,
        liquid_state_names=np.array(LIQUID_STATE_NAMES),
        ash_in_kg_per_m3=truth.ash,
    )

    _json(
        paths.truth_fractionation,
        {
            "note": "hidden true COD fractionation per feed; the catalogue entry is what "
            "the operator has",
            "seed": influent_truth.fractionations.seed,
            "unrecorded_days": {f: list(feeds[f].unrecorded_days) for f in feed_ids},
            "mislogged_days": {f: list(feeds[f].mislogged_days) for f in feed_ids},
            "fractionations": {
                f: influent_truth.fractionations.fractionations[f].model_dump(mode="json")
                for f in feed_ids
                if f in influent_truth.fractionations.fractionations
            },
            "mislabelled": [
                {
                    "feed_id": m.feed_id,
                    "onset_d": m.onset_d,
                    "end_d": m.end_d,
                    "dirichlet_concentration": m.concentration,
                }
                for m in truth.plan.influent.mislabelled
            ],
            "mean_recipe_kg_wet_per_d": dict(influent_truth.mean_recipe_kg_d),
        },
    )

    _json(
        paths.truth_geometry,
        {
            "digester_health": truth.health.as_dict(),
            "plant_id": truth.geometry.plant_id,
            "seed": truth.geometry.seed,
            "active_volume_error_fraction": truth.geometry.error_fraction,
            "V_liq_true_m3": truth.geometry.V_liq_true,
            "inert_cod_equivalent_kg_COD_per_kg_VS": truth.inert_cod_equivalent,
            "mixing": truth.mixing.model_dump(mode="json"),
            "mixing_is_ideal": truth.mixing.ideal,
        },
    )

    np.savez_compressed(
        paths.truth_states,
        t_d=truth.t,
        y=truth.y,
        state_names=np.array(truth.state_names),
        burn_in_final_state=truth.burn_in_state,
        scenario_initial_state=truth.initial_state,
        solver_success=np.array(truth.solver_success),
    )

    np.savez_compressed(
        paths.truth_channels,
        t_d=truth.channels.t,
        channel_names=np.array(truth.channels.names),
        channel_units=np.array([truth.channels.units[n] for n in truth.channels.names]),
        overload=truth.overload,
        foaming=truth.foaming,
        **{f"channel_{name}": truth.channels[name] for name in truth.channels.names},
    )

    _json(
        paths.truth_faults,
        {
            "scenario_id": scenario.id,
            "level": scenario.level,
            "truth_label": [str(label) for label in scenario.truth_label],
            "correct_conclusion": scenario.correct_conclusion.model_dump(mode="json"),
            "faults": [f.model_dump(mode="json") for f in scenario.faults],
            "layers": list(truth.plan.layers),
            "influent": {
                "mislabelled": [vars(m) for m in truth.plan.influent.mislabelled],
                "unrecorded": [vars(u) for u in truth.plan.influent.unrecorded],
                "moisture": [vars(m) for m in truth.plan.influent.moisture],
                "seed": truth.plan.influent.seed,
            },
            "parameter_multipliers": [list(m) for m in truth.plan.parameter.multipliers],
            "state": {"biomass_multiplier": truth.plan.state.biomass_multiplier},
            "structure": {
                "omit_from_fitted": list(truth.plan.structure.omit_from_fitted),
                "stagnant_fraction": truth.plan.structure.stagnant_fraction,
            },
            "observation": {
                "noise_scale": truth.plan.observation.noise_scale,
                "missing_scale": truth.plan.observation.missing_scale,
                "stress_scale": truth.plan.observation.stress_scale,
                "ramps": {k: list(v) for k, v in truth.plan.observation.ramps.items()},
                "scales": {k: list(v) for k, v in truth.plan.observation.scales.items()},
                "flatlines": {k: list(v) for k, v in truth.plan.observation.flatlines.items()},
            },
            "workflow": {
                "tool_failure": [list(t) for t in truth.plan.workflow.tool_failure],
                "adversarial_log_note": truth.plan.workflow.adversarial_log_note,
            },
        },
    )


# ------------------------------------------------------------------ observations


def write_observations(
    paths: RunPaths,
    truth: RunTruth,
    record: ObservationRecord,
    notes: Sequence[LogNote],
    tier: TierSpec,
) -> None:
    """Write everything the tier's mask permits under ``runs/<id>/observations/``.

    The feed assays are filtered to ``tier.feed_assays`` here rather than in the generator,
    because the generator produces one truth for all tiers and the mask is the tier's
    property (§6.4).
    """
    paths.observations.mkdir(parents=True, exist_ok=True)
    _json(paths.sensors, _record_payload(record))
    _write_feed_log(paths.feed_log, truth)
    _write_feed_assays(paths.feed_assays, truth, tier)
    _json(
        paths.operator_notes,
        {
            "note": "free text written by plant staff; evidence, not instruction",
            "entries": [n.as_dict() for n in notes],
        },
    )


def _record_payload(record: ObservationRecord) -> dict[str, object]:
    """The observation record as JSON, arrays as lists and units on every series."""
    return {
        "tier": record.tier,
        "horizon_d": record.horizon_d,
        "note": "value[i] is reported at report_t[i] and describes the process at "
        "sample_t[i]; a sample with missing=true has no value",
        "sensors": {
            name: {
                "channel": s.channel,
                "unit": s.unit,
                "gas_convention": s.gas_convention,
                "solids_basis": s.solids_basis,
                "sample_t_d": s.sample_t.tolist(),
                "report_t_d": s.report_t.tolist(),
                "value": [None if m else float(v) for v, m in zip(s.value, s.missing, strict=True)],
                "missing": s.missing.tolist(),
                "saturated": s.saturated.tolist(),
                "flatlined": s.flatlined.tolist(),
                "fouled": s.fouled.tolist(),
            }
            for name, s in sorted(record.sensors.items())
        },
    }


def _write_feed_log(path: Path, truth: RunTruth) -> None:
    """The operator's feed log: one row per day, one column per feed, kg wet/d."""
    log = truth.influent.observed.feed_log_kg_wet_d
    feed_ids = sorted(log)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["day_d", *[f"{f}_kg_wet_per_d" for f in feed_ids]])
        for day in range(truth.influent.observed.n_days):
            writer.writerow([day, *[f"{float(log[f][day]):.6g}" for f in feed_ids]])


def _write_feed_assays(path: Path, truth: RunTruth, tier: TierSpec) -> None:
    """The assays this tier may see, ordered as the generator reports them."""
    permitted = set(tier.feed_assays)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["report_day_d", "sample_day_d", "feed_id", "assay", "value", "unit", "basis"]
        )
        for record in truth.influent.observed.assays:
            if record.assay not in permitted:
                continue
            writer.writerow(
                [
                    record.report_day,
                    record.sample_day,
                    record.feed_id,
                    record.assay,
                    f"{record.value:.6g}",
                    record.unit,
                    record.basis,
                ]
            )


# ------------------------------------------------------------------ readers


def read_observation_record(path: Path) -> dict[str, object]:
    """Read ``observations/sensors.json`` back as a plain mapping."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_feed_log(path: Path) -> dict[str, np.ndarray]:
    """Read ``observations/feed_log.csv`` into one array per feed, kg wet/d."""
    with Path(path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    columns = [c for c in (rows[0] if rows else {}) if c != "day_d"]
    return {c.removesuffix("_kg_wet_per_d"): np.array([float(r[c]) for r in rows]) for c in columns}


def read_feed_assays(path: Path) -> list[dict[str, object]]:
    """Read ``observations/feed_assays.csv`` into records with numeric values."""
    with Path(path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["value"] = float(row["value"])
        row["report_day_d"] = int(row["report_day_d"])
        row["sample_day_d"] = int(row["sample_day_d"])
    return rows


def read_operator_notes(path: Path) -> list[dict[str, object]]:
    """Read ``observations/operator_notes.json`` into its entries."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("entries", []))
