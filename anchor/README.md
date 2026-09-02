# `anchor/` — real-data anchor (proposal §8)

Open real-plant datasets that the simulator's statistics are checked against.
Which datasets, why, and what they contain is documented in
[`docs/anchor_datasets.md`](../docs/anchor_datasets.md).

```
anchor/
  MANIFEST.json   every fetched file: URL, licence, SHA-256, size, download date
                  + every candidate that was examined and deliberately not fetched
  manifest.py     Pydantic schema for MANIFEST.json
  fetch.py        reproduces the download and verifies checksums (pure I/O)
  raw/<id>/       the bytes; large files are git-ignored, small ones committed
```

Reproduce or verify the download from the repository root:

```
python -m anchor.fetch            # download what is missing, verify everything
python -m anchor.fetch --verify   # verify only, no network
python -m anchor.fetch --dataset iowa-muscatine-wrrf
```

Rules:

- Nothing in `anchor/` may read `runs/<id>/truth/` (CLAUDE.md rule 1).
- Only files whose licence permits redistribution go in the manifest's
  `datasets`; everything else is recorded under `not_fetched` with a reason.
- Simulated inputs (for example the BSM2 influent) are never listed as
  anchors, even when their licence is open.
- Raw files are never edited in place. Unit conversion (the Muscatine files use
  °F, gallons and cubic feet per minute) happens in ingestion code with explicit
  unit metadata (CLAUDE.md rule 6).
