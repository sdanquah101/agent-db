"""Derive the observation model's Plant B/C sensor statistics from the Muscatine SCADA file.

The 1-minute SCADA file is 88.8 MB and git-ignored (decisions log 2026-09-02, "Anchor
data are manifest-driven"), so this script produces the two artefacts that *are*
committed and that ``tests/test_observe.py`` reads:

``anchor/derived/muscatine-scada-window.csv.gz``
    A 60-day extract (the first 60 days of the record, three columns, biogas rounded to
    1e-3 cfm — three orders of magnitude below the channel's noise). Under 1 MB and
    ODC-By, so it is committed with its attribution; the offline test re-derives the
    noise, quantisation and flatline statistics from it.

``anchor/derived/muscatine-scada-sensor-statistics.json``
    The same statistics over the **full** record plus the dropout statistics, with the
    SHA-256 of the parent file. These are the numbers ``configs/observe/observation.yaml``
    declares; the always-on test checks the config against this file, and the full-file
    test re-derives it when ``SCADA-raw.csv`` is present.

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
    SCADA_COLUMNS,
    SCADA_FILE,
    SCADA_WINDOW_FILE,
    dropout_statistics,
    load_scada,
    sensor_noise_statistics,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATISTICS_FILE = REPO_ROOT / "anchor" / "derived" / "muscatine-scada-sensor-statistics.json"
WINDOW_DAYS = 60
WINDOW_COLUMNS = ("Timestamp", "D1_TEMPERATURE", "D2_TEMPERATURE", "Biogas")
BIOGAS_DECIMALS = 3
CHANNELS = ("dig1_T_K", "dig2_T_K", "biogas_m3_d")


def write_window(source: Path = SCADA_FILE, target: Path = SCADA_WINDOW_FILE) -> int:
    """Write the committed 60-day extract; returns the number of rows."""
    with source.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [[row[c] for c in WINDOW_COLUMNS] for row in reader]
    rows.sort(key=lambda r: r[0])
    end = dt.datetime.strptime(rows[0][0], "%Y-%m-%d %H:%M:%S") + dt.timedelta(days=WINDOW_DAYS)
    kept = [
        [r[0], r[1], r[2], f"{float(r[3]):.{BIOGAS_DECIMALS}f}"]
        for r in rows
        if dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") < end
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 so the bytes (and the SHA-256) are reproducible
    with gzip.GzipFile(target, "wb", compresslevel=9, mtime=0) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        writer = csv.writer(text)
        writer.writerow(WINDOW_COLUMNS)
        writer.writerows(kept)
        text.flush()
    return len(kept)


def statistics(source: Path = SCADA_FILE, window: Path = SCADA_WINDOW_FILE) -> dict:
    """The full-record and window statistics, as the committed JSON records them."""
    full = load_scada(source)
    extract = load_scada(window)
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
            "start": full.start.isoformat(sep=" "),
            "span_d": full.span_d,
            "columns": {c: dataclasses.asdict(s) for c, s in SCADA_COLUMNS.items()},
        },
        "window": {
            "file": str(window.relative_to(REPO_ROOT)),
            "sha256": sha256_of(window),
            "days": WINDOW_DAYS,
            "start": extract.start.isoformat(sep=" "),
            "note": (
                "The first 60 days of the record; the biogas column is rounded to "
                f"1e-{BIOGAS_DECIMALS} cfm before conversion. Committed so the noise, "
                "quantisation and flatline statistics can be re-derived offline; the "
                "dropout statistics are NOT representative over 60 days (18 of the "
                "record's 19 gaps fall in the first 90 days) and the configuration uses "
                "the full-record values."
            ),
            "sensors": {
                c: dataclasses.asdict(sensor_noise_statistics(extract, c)) for c in CHANNELS
            },
            "dropouts": dataclasses.asdict(dropout_statistics(extract)),
        },
        "full_record": {
            "sensors": {c: dataclasses.asdict(sensor_noise_statistics(full, c)) for c in CHANNELS},
            "dropouts": dataclasses.asdict(dropout_statistics(full)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Write (or check) the window extract and the statistics JSON.

    Returns:
        ``0`` on success, ``1`` when ``--check`` finds a difference.
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
    stats = statistics(args.source)
    text = json.dumps(stats, indent=2, sort_keys=True) + "\n"
    if args.check:
        current = STATISTICS_FILE.read_text(encoding="utf-8")
        if current != text:
            print("statistics differ from the committed file", file=sys.stderr)
            return 1
        print("statistics match the committed file")
        return 0
    STATISTICS_FILE.write_text(text, encoding="utf-8")
    print(f"wrote {STATISTICS_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
