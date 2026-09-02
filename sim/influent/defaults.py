"""Loader for the declared feed-fractionation catalogue under ``configs/influent/``.

The only function in :mod:`sim.influent` that touches the filesystem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sim.influent.schema import FeedFractionationCatalogue

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "influent"
FEED_FRACTIONATION = CONFIG_DIR / "feed_fractionation.yaml"


def load_feed_fractionation(path: Path = FEED_FRACTIONATION) -> FeedFractionationCatalogue:
    """Parse and validate the feed-fractionation catalogue."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return FeedFractionationCatalogue.model_validate(raw)
