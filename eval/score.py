"""One run, one row: the identity of the cell and the four metric families side by side."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.attribution import score_attribution
from eval.config import EvalConfig, load_eval_config
from eval.efficiency import score_efficiency
from eval.prediction import score_prediction
from eval.records import RunRecords, load_records
from eval.reliability import score_reliability
from sim.adm1 import load_parameters
from sim.run.layout import RUNS_ROOT, truth_store_for
from tools.config import FittedModelConfig, load_fitted_model

__all__ = ["Scorer", "score_records", "score_runs"]

IDENTITY = ("run_id", "workflow", "scenario_id", "level", "plant", "tier", "seed", "replicate")


class Scorer:
    """The configuration and the declared priors, loaded once for a batch."""

    def __init__(
        self,
        config: EvalConfig | None = None,
        model: FittedModelConfig | None = None,
        defaults: dict[str, float] | None = None,
    ) -> None:
        """Load ``configs/eval.yaml``, ``configs/tools/model.yaml`` and the BSM2 defaults."""
        self.config = config or load_eval_config()
        self.model = model or load_fitted_model()
        self.defaults = defaults if defaults is not None else load_parameters().namespace()

    def score(self, records: RunRecords) -> dict[str, Any]:
        """The row of one run."""
        row: dict[str, Any] = {
            "run_id": records.run_id,
            "workflow": records.workflow,
            "scenario_id": records.scenario_id,
            "level": records.level,
            "plant": records.plant,
            "tier": records.tier,
            "seed": records.seed,
            "replicate": records.replicate,
        }
        row.update(score_reliability(records, self.config))
        row.update(score_attribution(records, self.config.attribution, self.model))
        row.update(score_prediction(records, self.config, self.defaults))
        row.update(score_efficiency(records, self.config, self.model))
        return row


def score_records(records: RunRecords, scorer: Scorer | None = None) -> dict[str, Any]:
    """Score one loaded run."""
    return (scorer or Scorer()).score(records)


def score_runs(
    run_ids: Sequence[str],
    workflow: str,
    *,
    runs_root: Path = RUNS_ROOT,
    truth_store: Path | None = None,
    scorer: Scorer | None = None,
) -> list[dict[str, Any]]:
    """Score a batch of runs, one row each, in the order given."""
    store = truth_store_for(runs_root) if truth_store is None else Path(truth_store)
    scorer = scorer or Scorer()
    return [
        scorer.score(load_records(rid, workflow, runs_root=runs_root, truth_store=store))
        for rid in run_ids
    ]
