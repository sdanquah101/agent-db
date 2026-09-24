"""The controlled abstention vocabulary (``configs/abstentions.yaml``; ruling A3 of 2026-09-24).

One spelling for every quantity an answer key may ask a workflow to decline and a
workflow may decline. The scenario schema validates every ``abstain_on`` against it
(:mod:`scenarios.schema`); the runner hands it to a workflow's sandbox with its
configuration (:func:`tools.workflow_config.sandbox_config`). Templated terms expand over
the declared sensors (``configs/observation/sensors.yaml``) and the fitted model's output
channels (``configs/tools/model.yaml``), read as plain YAML: nothing here imports the
simulator.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

__all__ = ["ABSTENTIONS_CONFIG", "abstention_vocabulary"]

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
ABSTENTIONS_CONFIG = CONFIG_DIR / "abstentions.yaml"


def _names(over: str) -> list[str]:
    if over == "sensors":
        raw = yaml.safe_load((CONFIG_DIR / "observation" / "sensors.yaml").read_text("utf-8"))
        return sorted(raw["sensors"])
    if over == "channels":
        raw = yaml.safe_load((CONFIG_DIR / "tools" / "model.yaml").read_text("utf-8"))
        return list(raw["outputs"])
    raise ValueError(f"unknown template range {over!r}; expected 'sensors' or 'channels'")


@lru_cache(maxsize=4)
def abstention_vocabulary(path: Path = ABSTENTIONS_CONFIG) -> dict[str, str]:
    """Every term of the vocabulary, templates expanded, mapped to its one-line meaning.

    Raises:
        ValueError: If the file is malformed or two entries spell the same term.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("terms"), dict):
        raise ValueError(f"{path}: expected a mapping with a `terms` mapping")
    vocabulary: dict[str, str] = {}
    for term, meaning in raw["terms"].items():
        if not isinstance(meaning, str) or not meaning.strip():
            raise ValueError(f"{path}: term {term!r} has no meaning")
        vocabulary[str(term)] = meaning.strip()
    for template in raw.get("templates") or []:
        pattern, meaning = str(template["pattern"]), str(template["meaning"]).strip()
        for name in _names(str(template["over"])):
            term = pattern.format(name=name)
            if term in vocabulary:
                raise ValueError(f"{path}: {term!r} is spelled twice")
            vocabulary[term] = meaning
    return vocabulary
