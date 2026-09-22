"""The evaluation suite (proposal §6.7, Appendix A, §7; milestone 6).

Every metric of families A-D is computed from records only -- the truth store, the task
state, the two call logs and the runner's summary (:mod:`eval.records`) -- by code that no
workflow can reach: nothing under ``workflows/`` may import or read ``eval/`` and nothing
here imports ``workflows/`` (``tests/test_eval_isolation.py``). Thresholds, windows,
mappings and the bootstrap seed live in ``configs/eval.yaml`` (:mod:`eval.config`).

Command line: ``python -m eval --workflow p0 --all --out reports/p0_pilot_scored.csv``.
"""

from __future__ import annotations

from eval.aggregate import aggregate
from eval.config import EvalConfig, load_eval_config
from eval.records import RunRecords, load_records
from eval.score import Scorer, score_records, score_runs

__all__ = [
    "EvalConfig",
    "RunRecords",
    "Scorer",
    "aggregate",
    "load_eval_config",
    "load_records",
    "score_records",
    "score_runs",
]
