"""Writing the per-run and aggregate tables as CSV and JSON."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["columns_of", "write_tables"]


def columns_of(rows: Sequence[dict[str, Any]]) -> list[str]:
    """The union of the rows' keys, in first-seen order."""
    columns: list[str] = []
    for row in rows:
        for name in row:
            if name not in columns:
                columns.append(name)
    return columns


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return value


def write_tables(rows: Sequence[dict[str, Any]], csv_path: Path) -> Path:
    """Write ``rows`` to ``csv_path`` and the same rows to the ``.json`` beside it.

    Returns:
        The JSON path.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns_of(rows)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(row.get(k)) for k in columns})
    json_path = csv_path.with_suffix(".json")
    json_path.write_text(json.dumps(list(rows), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return json_path
