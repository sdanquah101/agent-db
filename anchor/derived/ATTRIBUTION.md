# Attribution — derived from the Muscatine WRRF SCADA dataset

Both files here are **derived** from `SCADA-raw.csv` of

Schroer, H. W. and Just, C. L. (2024). *Laboratory, operational, and SCADA
datasets for anaerobic co-digestion at the Muscatine, IA Water Resource Recovery
Facility.* University of Iowa. <https://doi.org/10.25820/data.006715>

redistributed under the **Open Data Commons Attribution License (ODC-By) v1.0**
(<https://opendatacommons.org/licenses/by/1.0>), which permits redistribution of
derived works with attribution. The parent file's SHA-256 is recorded in
`muscatine-scada-sensor-statistics.json` and in `anchor/MANIFEST.json`.

| File | What it is |
|---|---|
| `muscatine-scada-window.csv.gz` | Days 240–300 of the SCADA record (2022-11-13 to 2023-01-12, 86,400 rows), sorted chronologically, with three of the 27 columns kept — `Timestamp`, `D1_TEMPERATURE`, `Biogas` — and the biogas column rounded to 1e-3 cfm, three orders of magnitude below that channel's own noise. Values are otherwise the provider's. |
| `muscatine-scada-sensor-statistics.json` | The sensor statistics of the **full** record and of the window, the record's row-dropout statistics, and the parent's SHA-256. |

The window was chosen by measurement, not convenience: of the candidate windows
it is the one that reproduces **both** anchored noise values inside the tolerances
`tests/test_observation.py` already used against the full file — the temperature
noise exactly, the gas-flow cv within 0.0013 of the year's.

**What the window cannot carry**, stated here and asserted in the tests: the
flatline occupancies are rare-event statistics (this window contains no stuck run
of ten minutes or more) and the row-dropout rate is unrepresentative over 60 days
(18 of the record's 19 gaps fall in its first 90 days). Both stay full-record
figures, recorded in the JSON and checked against the parent when it is present.

Both files are produced by `python scripts/muscatine_scada_observation.py` after
`python -m anchor.fetch`; `--check` recomputes the statistics and compares.
