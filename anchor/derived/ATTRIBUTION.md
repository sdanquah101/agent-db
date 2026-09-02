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
| `muscatine-scada-window.csv.gz` | The first 60 days of the SCADA record (2022-03-18 to 2022-05-17, 85,933 rows), sorted chronologically, with three of the 27 columns kept — `Timestamp`, `D1_TEMPERATURE`, `D2_TEMPERATURE`, `Biogas` — and the biogas column rounded to 1e-3 cfm, three orders of magnitude below the channel's own noise. Values are otherwise the provider's. |
| `muscatine-scada-sensor-statistics.json` | Sensor-noise, quantisation, flatline, instrument-limit and dropout statistics over the **full** record and over the window, with the parent's SHA-256. |

Both are produced by `python scripts/muscatine_scada_observation.py` after
`python -m anchor.fetch`, and `python scripts/muscatine_scada_observation.py --check`
recomputes the statistics and compares them. `configs/observe/observation.yaml`
declares the full-record values; `tests/test_observe.py` checks the configuration
against the JSON and re-derives the window's statistics offline (the 88.8 MB parent
is git-ignored, decisions log 2026-09-02).
