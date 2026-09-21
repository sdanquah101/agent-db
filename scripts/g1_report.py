"""Regenerate the generated block of ``docs/g1_anchor_report.md``.

Run from the repository root::

    python scripts/g1_report.py

The prose of the report is written by hand; everything between the
``<!-- BEGIN/END GENERATED: g1 anchor comparison -->`` markers comes from
:mod:`anchor.compare_generated` and is recomputed here.
``tests/test_g1_anchor.py`` compares the committed block with a fresh computation, so a
change to the simulator that moves a number fails a test rather than leaving a stale
report in the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

from anchor.compare_generated import (
    anchor_available,
    anchor_statistics,
    compare,
    extract_block,
    generated_influent_statistics,
    generated_output_statistics,
    output_panel,
    report_block,
)

REPORT = Path(__file__).resolve().parents[1] / "docs" / "g1_anchor_report.md"


def main() -> int:
    """Recompute the block and write it into the report in place."""
    if not anchor_available():
        print("the Muscatine daily file is absent; fetch it with `python -m anchor.fetch`")
        return 1
    panel = output_panel()
    generated = {**generated_influent_statistics(), **generated_output_statistics(panel=panel)}
    anchor = anchor_statistics()
    comparisons = compare(generated, anchor)
    extra = {k: v for k, v in generated.items() if k not in {c.name for c in comparisons}}
    block = report_block(comparisons, panel, extra)

    if REPORT.exists():
        text = REPORT.read_text(encoding="utf-8")
        REPORT.write_text(text.replace(extract_block(text), block), encoding="utf-8")
    else:
        REPORT.write_text(block + "\n", encoding="utf-8")
    failed = [c.name for c in comparisons if not c.passed]
    print(f"{len(comparisons) - len(failed)}/{len(comparisons)} rows inside their declared bound")
    if failed:
        print("outside: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
