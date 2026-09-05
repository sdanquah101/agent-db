"""Write the committed SCADA artefacts the observation model's anchor is checked against.

The 1-minute SCADA file is 88.8 MB and git-ignored (decisions log 2026-09-02, "Anchor data
are manifest-driven"), so ``tests/test_observation.py`` could only re-derive the anchored
sensor values when a contributor had fetched it. This script produces the two artefacts
that *are* committed, so the anchor is reproducible from a fresh clone:

``anchor/derived/muscatine-scada-window.csv.gz``
    A 60-day extract — days 240-300 of the record, three columns, the biogas column
    rounded to 1e-3 cfm (three orders of magnitude below the channel's own noise). Chosen
    by measurement, not convenience: of the candidate windows it is the one that
    reproduces **both** anchored noise values inside the tolerances the test already uses
    (temperature exactly; gas within 0.0013 of the year's cv). Under 1 MB and ODC-By, so
    it is committed with its attribution.

``anchor/derived/muscatine-scada-sensor-statistics.json``
    The same statistics over the **full** record, plus the row-dropout statistics and the
    parent file's SHA-256. These are the numbers ``configs/observation/sensors.yaml``
    declares.

What the window cannot do is stated in the JSON and asserted in the tests: the flatline
occupancies are rare-event statistics (a 60-day window holds either none or a handful of
stuck runs) and the dropout rate is unrepresentative over 60 days, so both stay
full-record figures.

Usage (from the repository root, after ``python -m anchor.fetch``)::

    python scripts/muscatine_scada_observation.py            # write both artefacts
    python scripts/muscatine_scada_observation.py --check    # recompute and compare

Pure I/O plus the statistics of :mod:`anchor.ingest_muscatine`; no randomness.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import gzip
import io
import json
import sys
from pathlib import Path

from anchor.fetch import sha256_of
from anchor.ingest_muscatine import (
    SCADA_FILE,
    SCADA_WINDOW_FILE,
    scada_noise_statistics,
    scada_row_gap_statistics,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATISTICS_FILE = REPO_ROOT / "anchor" / "derived" / "muscatine-scada-sensor-statistics.json"
WINDOW_START_DAY = 240
WINDOW_DAYS = 60
WINDOW_COLUMNS = ("Timestamp", "D1_TEMPERATURE", "Biogas")
BIOGAS_DECIMALS = 3
CHANNELS = ("D1_TEMPERATURE", "Biogas")


def write_window(source: Path = SCADA_FILE, target: Path = SCADA_WINDOW_FILE) -> int:
    """Write the committed 60-day extract; returns the number of rows."""
    with source.open(encoding="utf-8-sig", newline="") as fh:
        rows = [[row[c] for c in WINDOW_COLUMNS] for row in csv.DictReader(fh)]
    rows.sort(key=lambda r: r[0])
    start = dt.datetime.strptime(rows[0][0], "%Y-%m-%d %H:%M:%S") + dt.timedelta(
        days=WINDOW_START_DAY
    )
    end = start + dt.timedelta(days=WINDOW_DAYS)
    kept = [
        [r[0], r[1], f"{float(r[2]):.{BIOGAS_DECIMALS}f}"]
        for r in rows
        if start <= dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") < end
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 so the bytes, and therefore the committed file's SHA-256, are reproducible
    with gzip.GzipFile(target, "wb", compresslevel=9, mtime=0) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        writer = csv.writer(text)
        writer.writerow(WINDOW_COLUMNS)
        writer.writerows(kept)
        text.flush()
    return len(kept)


def statistics(source: Path = SCADA_FILE, window: Path = SCADA_WINDOW_FILE) -> dict:
    """The full-record and window statistics, as the committed JSON records them."""
    return {
        "schema_version": 1,
        "source": {
            "dataset": "iowa-muscatine-wrrf",
            "file": source.name,
            "sha256": sha256_of(source),
            "licence": "Open Data Commons Attribution (ODC-By) v1.0",
            "citation": (
                "Schroer, H. W. and Just, C. L. (2024). Laboratory, operational, and SCADA "
                "datasets for anaerobic co-digestion at the Muscatine, IA Water Resource "
                "Recovery Facility. University of Iowa. https://doi.org/10.25820/data.006715"
            ),
        },
        "window": {
            "file": str(window.relative_to(REPO_ROOT)),
            "sha256": sha256_of(window),
            "start_day": WINDOW_START_DAY,
            "days": WINDOW_DAYS,
            "note": (
                "Days 240-300 of the record; the biogas column is rounded to "
                f"1e-{BIOGAS_DECIMALS} cfm before compression. Committed so the anchored "
                "NOISE values can be re-derived offline. It does NOT reproduce the "
                "flatline occupancies (a rare-event statistic: this window contains no "
                "stuck run of 10+ minutes) or the dropout rate (18 of the record's 19 "
                "gaps fall in its first 90 days), which stay full-record figures."
            ),
            "channels": {
                c: dataclasses.asdict(scada_noise_statistics(c, path=window)) for c in CHANNELS
            },
        },
        "full_record": {
            "channels": {c: dataclasses.asdict(scada_noise_statistics(c)) for c in CHANNELS},
            "row_gaps": dataclasses.asdict(scada_row_gap_statistics(source)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Write (or check) the window extract and the statistics JSON.

    Returns:
        ``0`` on success, ``1`` when the source is missing or ``--check`` finds a change.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=SCADA_FILE)
    parser.add_argument("--check", action="store_true", help="recompute and compare, write nothing")
    args = parser.parse_args(argv)
    if not args.source.is_file():
        print(f"{args.source} is missing; run `python -m anchor.fetch` first", file=sys.stderr)
        return 1
    if not args.check:
        rows = write_window(args.source)
        print(f"wrote {SCADA_WINDOW_FILE.relative_to(REPO_ROOT)} ({rows} rows)")
    text = json.dumps(statistics(args.source), indent=2, sort_keys=True) + "\n"
    if args.check:
        if STATISTICS_FILE.read_text(encoding="utf-8") != text:
            print("statistics differ from the committed file", file=sys.stderr)
            return 1
        print("statistics match the committed file")
        return 0
    STATISTICS_FILE.write_text(text, encoding="utf-8")
    print(f"wrote {STATISTICS_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
