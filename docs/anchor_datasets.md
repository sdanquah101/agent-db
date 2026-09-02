# Open datasets for the real-data anchor (proposal §8)

Milestone 1/2 deliverable. Every property stated here comes from a page or file that
was actually read on 2026-09-02; the source is cited beside it. Where a page could not
be read from this environment, the entry says so instead of guessing.

**Bottom line.** No openly licensed, full-scale, daily time series exists for the
agricultural co-digestion configuration of Plant A. One excellent open dataset exists
for a sewage-sludge plant with heavy industrial co-digestion (Plant C, and a
reasonable stand-in for Plant B's high-load episodes): the Muscatine WRRF datasets
(ODC-By 1.0; daily 2020–2023 plus 1-minute SCADA 2022–2023). The recommendation
(§4) is to anchor Plants B and C to Muscatine, to anchor Plant A to the published
summary statistics of the two Tisocco et al. papers while requesting their plant data,
and to write §8 of the paper accordingly.

---

## 1. Search scope and what was actually checked

Starting points from proposal §8: the Tisocco et al. papers (2023/2024 and 2026), the
Weinrich group (DBFZ / Münster / Rostock) plant papers, Zenodo, Mendeley Data,
figshare, OSF, and the ADM1 benchmark literature (BSM2). Additional cross-repository
searches: DataCite (covers Zenodo, figshare, Mendeley, Dryad, Dataverse), the Zenodo
REST API (four queries, paginated), the figshare search API, the OSF nodes API,
DBFZ's DataLab, and GitHub.

Network: at session start every data host was blocked by the egress policy
(`zenodo.org`, `data.mendeley.com`, `figshare.com`, `osf.io`, `doi.org`,
`ars.els-cdn.com`, `static-content.springer.com`, `frontiersin.org`, `mdpi.com` all
returned `000` / CONNECT 403). The allowlist was widened mid-session and the check
re-run; all of those hosts then answered, and the downloads below were made through
`anchor/fetch.py`. Still unreachable from this environment at the end of the session:
`www.mdpi.com` and `iwaponline.com` (HTTP 403), `www.sciencedirect.com` (bot wall),
`datalab.dbfz.de` (JavaScript application; no listing could be obtained).

---

## 2. Comparison table

Scale: *full* = plant; *small* = household/farm digester; *lab* = bench reactors.
"Daily ≥ 6 mo" is the §8 requirement (daily or finer, six months or more).

| # | Dataset | Source (DOI / URL) | Licence | Scale, plant, feedstock | Variables | Resolution | Duration | Gaps / missingness | Download without registration | Fit to Plants A/B/C |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Muscatine WRRF lab + SCADA** (Schroer & Just 2024) | [10.25820/data.006715](https://doi.org/10.25820/data.006715) → [Iowa Research Online record](https://iro.uiowa.edu/esploro/outputs/dataset/Laboratory-operational-and-SCADA-datasets-for/9984462455902771) | **ODC-By v1.0** (DataCite record) | Full. Municipal WRRF, 5.5 MGD; two 485,000-gal (≈1,836 m³) CSTRs, mesophilic 36 °C; primary sludge + thickened WAS + trucked high-strength industrial organic waste + FOG [PMC10928704] | Daily: feed volumes (TWAS, PS, HSW, FOG), digester T and pH (×2), SRT, HSW VS and COD, alkalinity, total VFA, FOS/TAC (×2), plant influent flow and BOD, sludge VS, daily-mean biogas flow (25 columns). SCADA: digester T, all sludge/HSW/RAS/WAS flows, tank levels, lid heights, biogas to burner and boiler (27 columns) | Daily; 1-minute | Daily 2020-01-01 → 2023-03-31 (1,103 rows, 1,186 calendar days); SCADA 2022-03-18 → 2023-02-28 (500,400 rows) | Daily file: 2021-04-06 → 2021-06-27 removed by provider (no gas data); VFA/FOS-TAC missing on 242 days (method change before 2020-04-21); alkalinity 143; PS-VS 377; HSW-COD 471. SCADA: 485 rows deleted by provider (power surges); largest remaining gap 422 min (2022-04-08); ~20 other steps of 2–14 min; file not chronologically ordered | **Yes** (fetched; 5 files) | **C: strong. B: partial** (industrial food-processing waste + FOG co-digestion, load swings). A: no |
| 2 | Muscatine forecasting code archive (Schroer 2023) | [10.5281/zenodo.8360096](https://zenodo.org/records/8360096) | **MIT** (LICENSE in archive; Zenodo "other-open") | Same plant | LABS-raw (byte-identical to #1), interpolated and lagged variants, notebooks for MLR / TPOT / MLP forecasts | Daily | As #1 | As #1 | Yes (fetched) | Provides the published forecasting baseline for §8 step 3 |
| 3 | **ILRI farm-scale digesters + weather** (Mulat 2025) | [10.17632/gk3f363sfg.1](https://data.mendeley.com/datasets/gk3f363sfg/1) | **CC BY 4.0** (Mendeley record) | Small. Four unheated livestock-manure digesters (two flexible-bag, two fixed-dome) at an ILRI "Mazingira" site; ~20 kg manure + 30 kg water per feed; digester T 23–28 °C in the first rows; volumes not stated | Date/time, manure fed, water added, cumulative gas-meter reading, air T, digester T, pH; TS/ash/VS columns largely empty; manure and bio-slurry characterisation sheets are headers only; gas-composition sheet has unresolved `#DIV/0!` cells. Weather: solar, rain, wind, air T, vapour and atmospheric pressure | Irregular, near-daily manual readings; weather 5-min | R1/R2 2024-01-04 → 2025-01-14 (306 dated rows); R3/R4 from 2024-03 (~260 rows); weather 2024-04-21 → 2024-10-18 | Many blank cells; feeding recorded as strings ("20kg"); one bad date (1900-01-10) in R4 | Yes (fetched; 12 MB zip, SHA-256 matches the published value) | None of A/B/C. Relevant to Tier A sparsity and to Phase 3 (unheated tropical digesters) |
| 4 | Tisocco et al. 2023/2024, AFBI Hillsborough | [10.1007/s11783-024-1810-9](https://link.springer.com/article/10.1007/s11783-024-1810-9) | Article CC BY 4.0; **data: not deposited** | Full. Two 650 m³ CSTRs, primary heated 41 ± 0.2 °C, secondary unheated; cattle slurry 11–18 m³/d + grass silage 2 t FM/d Mon–Fri; OLR 1.4 / 2.1 kg VS m⁻³ d⁻¹; HRT 28 d per reactor | Daily feed inputs; biogas rate and CH₄ content from an in-line analyser (continuous); weekly NH₄-N and pH of primary digestate; weekly TS/VS of feeds; weekly N, NH₄-N, VFA of slurry | Daily (gas), weekly (chemistry) | 8 months: 2018-03-01 → 05-31 (set A) and 2019-03-01 → 07-31 (set B) | Weekend silage omissions produce gas drops; paper notes inconsistent measurements and "missing information (soluble VFAs or alkalinity)" | No data file exists; ESM (read) has model inputs and figures only | **A: exact match**, but not open |
| 5 | Tisocco et al. 2026, AU Foulum | [10.1016/j.ese.2026.100662](https://pmc.ncbi.nlm.nih.gov/articles/PMC12874345/) | Article CC BY 4.0; **data: not deposited** | Full. Primary CSTR 1,200 m³ at 53 °C (thermophilic), secondary 30 m³ at 48 °C; HRT 13–15 d + 30 d; cattle slurry, deep litter, maize and grass silage and other feedstocks; mean OLR 6.1 kg VS m⁻³ d⁻¹; load follows campus heat demand | Daily: mass of each feedstock, biogas (m³ d⁻¹), electricity and heat; weekly-to-monthly TS, VS, NH₄-N, total N, fibre, VFA of feedstocks | Daily (gas, feed), weekly–monthly (chemistry) | 2023 (n = 365) calibration, 2024 (n = 366) validation | Not stated | No data file; supplement mmc1.docx (read) has feedstock tables and metrics only | A: close (thermophilic, maize-heavy), not open |
| 6 | Dittmer et al. 2021, Hohenheim "Unterer Lindenhof" | [10.3390/microorganisms9020324](https://pmc.ncbi.nlm.nih.gov/articles/PMC7915957/) | Article CC BY; **Data Availability Statement: "Not applicable"** | Full. Three 923 m³ tanks, 43 ± 4 °C; solid and liquid agricultural substrates | Hourly solid-feed mass and biogas volume (standard conditions), per digester | Hourly | Year 2018 | Not stated | No | A: close, not open |
| 7 | Meola & Weinrich 2025 (DBFZ), three full-scale plants | [10.1016/j.apenergy.2025.125781](https://www.sciencedirect.com/science/article/pii/S0306261925005112) | unknown (page unreadable here); data "available on request" (search index) | Full, intra-day | Methane yield, fed VS, lab measurements | Intra-day | Not readable | — | No | A: likely, not open |
| 8 | Chiguer et al. 2026, `biogas_dataset.csv` on GitHub | [github.com/aminechiguerdoc23-eng/adm1-am2-validation](https://github.com/aminechiguerdoc23-eng/adm1-am2-validation) | **None** ("No license has been added yet") | Claimed full-scale multi-substrate digester; plant not identified | Daily masses of ten feedstocks (pig manure … banana shafts), water, diesel, electricity, ambient T/humidity/rain, C/N, digester T, biogas | Several rows per calendar date | Header rows from 2010 | Provenance unclear: 8-decimal feed masses, duplicated dates | Readable but not redistributable | Not usable |
| 9 | BSM2 dynamic digester influent (PyADM1 example files) | [github.com/CaptainFerMag/PyADM1](https://github.com/CaptainFerMag/PyADM1) | MIT | **Simulated**, not measured | ADM1 state vector at 15-min steps | 15 min | 609 d (BSM2) | n/a | Yes | Not an anchor; needed for the Milestone-2 ring test only |
| 10 | Isenkul et al. 2025, industrial UASB (citrus wastewater) | [10.1088/2515-7620/ade03b](https://iopscience.iop.org/article/10.1088/2515-7620/ade03b) | Article CC BY 4.0; data "included within the article" | Full, UASB (not CSTR) | COD in/out, sCOD, vOLR, HRT, biogas — summary statistics only | 300 daily averages over 3 years | Non-contiguous | — | Only a stats table | No |
| 11 | Holliger et al. 2017, two Swiss plants | [10.3389/fenrg.2017.00012](https://www.frontiersin.org/journals/energy-research/articles/10.3389/fenrg.2017.00012/full) | Article CC BY | Full (one wet sludge co-digestion, one dry green/food waste) | Weekly CH₄ production, figures only | Weekly | 29 and 39 weeks | — | No file | No (weekly) |
| 12 | Zenodo 15691684 "Pilot-scale AD of on-farm agro-residues" (Sempre-Bio) | [zenodo.org/records/15691684](https://zenodo.org/records/15691684) | CC BY 4.0 | Lab (reactors fed 0.1–2.2 kg d⁻¹ despite the title) | BMP tests; daily feed, OLR, biogas, CH₄, H₂S, VFA for meso- and thermophilic reactors | Daily | 2023-02-13 → 2023-07-30 (< 6 mo) | — | Yes (read, not kept) | No |
| 13 | Zenodo 22232790 ecoTrace household digesters, Kiambu (Kenya) | [10.5281/zenodo.22232790](https://zenodo.org/records/22232790) | CC BY 4.0 | Small (household); 22 devices | Sensor flow and CH₄ composition telemetry, gas reference measurements, survey | Sub-hourly telemetry | 2026-01-27 → 2026-07-19 (2,975 device-days) | Raw columns corrupted by a firmware channel swap; correction code supplied | Yes (142 MB; not fetched) | Not for A/B/C; Phase-3 candidate |
| 14 | Zenodo (Leitat) 12805035, 14921811 | CC BY 4.0 | Lab | Lab reactor and BMP series | | | | | Yes | No |
| 15 | Mendeley 8795jgp8cv, mm2bpsgpsc, r35tshpftb, zmryw9dfpw | CC BY 4.0 (all) | Lab / ≤ 3 m³ / weekly | | | | | | Yes | No |
| 16 | Wechselberger et al. Zenodo 7474131 / 14197882 (methane-loss emission factors) | CC BY 4.0 | Full-plant *emission* measurements, not process time series | | | | | | Yes | No |
| 17 | EPA AgSTAR livestock digester database; Kaggle "US Biogas Projects" | — | Plant inventories, not time series | | | | | | | No |

Not readable from this environment (recorded, not characterised): *Energies* 2026,
19(5), 1377 (year-round sewage-sludge digester monitoring; MDPI returned 403);
Delory, Neubauer & Weinrich 2025 *Water Sci. Technol.* 92(4):610 (CC BY 4.0 article on
lab co-digestion of maize silage and cattle slurry; IWA returned 403); Weinrich et al.
2021 *Bioresour. Technol.* 333:125104 (lab-scale, Elsevier). Sappl et al. 2023 (six
years of WWTP digester data, Innsbruck), Wang et al. 2021 (8 years, EBMUD Oakland), Zou
et al. 2024 (1.5 years, four dry digesters) and Long et al. 2025 (6 years, 18
feedstocks) describe long full-scale series but no deposit was found for any of them.

---

## 3. Dataset notes

### 3.1 Muscatine WRRF (Iowa Research Online) — *fetched*

Five files were downloaded from the record's delivery URLs (obtained from the
institution's OAI-PMH `oai_dc` record, since the Esploro landing page is a JavaScript
application) and verified against their SHA-256 in `anchor/MANIFEST.json`. The
DataCite record states the licence (ODC-By v1.0), creators, publisher (University of
Iowa, 2024), the collection dates (2020-01-01/2023-02-28) and a five-file listing.
The plant is described in the associated article [PMC10928704]: 5.5 MGD facility, two
485,000-gallon CSTRs at 36 °C digesting primary sludge and thickened WAS, plus trucked
high-strength waste blended in a 65,000-gallon tank and FOG. The daily file has 25
columns with a data dictionary (units, ranges, and the provider's cleaning steps); the
SCADA file has 27 columns at one-minute resolution with its own dictionary. Summary
statistics computed from the daily file this session (US units as delivered):
digester-1 pH mean 7.25 (sd 0.16, range 6.43–7.94); digester-1 temperature mean
95.5 °F (35.3 °C); total VFA mean 1,276 mg L⁻¹ (sd 582, max 3,635); alkalinity mean
5,039 mg CaCO₃ L⁻¹; FOS/TAC mean 0.25 (max 0.93); daily-mean biogas 103.6 cfm
(sd 41.5; ≈ 4,220 m³ d⁻¹ at the stated units, reference conditions not given); SRT
mean 24.7 d (range 3.6–165). These are exactly the influent-variability, feed-batch
(HSW/FOG delivery volumes vary 0–56,000 gal d⁻¹), missingness and sensor-noise
quantities that §8 step 2 asks us to fit.

Caveats: all quantities are in US customary units and the gas-volume reference
conditions are not stated, so ingestion must attach explicit unit metadata and flag the
standard-condition assumption (CLAUDE.md rule 6). Feed composition is given as volumes
plus VS/COD of the high-strength waste only; no COD fractionation. The SCADA rows are
not in chronological order.

### 3.2 Muscatine forecasting code (Zenodo) — *fetched*

MIT-licensed archive of the paper's code. It also contains `LABS-raw.csv`, byte-identical
(SHA-256 `fb677c03…`) to the Iowa Research Online copy, which cross-checks that
download. The SCADA CSV is not in the archive (its README points to Iowa Research
Online). Useful for §8 step 3: the published models forecast next-day biogas; the
paper reports adjusted R² 0.78 and MAPE 13.4 % on the SCADA hold-out set for the MLP
[PMC10928704].

### 3.3 ILRI farm-scale digesters (Mendeley Data) — *fetched*

CC BY 4.0. Two workbooks. The process workbook logs four unheated manure digesters
through 2024 with manual readings (feed mass as free text, cumulative gas-meter counts,
pH, air and digester temperature); the chemistry sheets are almost empty and the
gas-composition sheet contains spreadsheet errors, so only feed, cumulative gas,
temperature and pH are usable. The weather workbook is a clean 5-minute ATMOS-41
record for six months. Not a full-scale anchor, but it is the only open dataset found
that resembles the constrained, unheated, manually logged plants of Phase 3, and it is a
good source of *Tier A* sampling irregularity (readings on 306 of 377 days, at varying
clock times).

### 3.4 Tisocco et al. — the Plant-A papers (no data deposit)

Both papers were read in full (Springer HTML and PDF; PMC full text and the Elsevier
supplement). Neither carries a data-availability statement and no repository deposit
exists for either plant. What they do give is a complete published description of two
Plant-A-type facilities and their operating envelope: AFBI Hillsborough (2 × 650 m³,
41 °C, slurry 11–18 m³ d⁻¹ + silage 2 t FM d⁻¹, OLR 1.4–2.1 kg VS m⁻³ d⁻¹, HRT 28 d,
weekend silage omission) and AU Foulum (1,200 m³, 53 °C, mean OLR 6.1, HRT 13–15 d,
seasonal load following heat demand), with feedstock characterisation tables (TS, VS,
XA, N, NH₄-N, ADF/NDF/ADL) and daily/weekly NSE and RMSE values for ADM1, ADM1-R3, RF
and LSTM. These are the summary statistics to anchor Plant A to (§4).

### 3.5 Everything else

Rows 6–17 of the table: either not deposited (Hohenheim, DBFZ, Innsbruck, EBMUD), not
licensed (Chiguer), simulated (BSM2), not time series (emission factors, inventories),
sub-daily-resolution but weekly (Holliger), or lab/household scale.

---

## 4. Recommendation (needs domain sign-off)

1. **Primary anchor: Muscatine WRRF** for Plant C (sewage sludge) and, with stated
   caveats, for Plant B's high-nitrogen/overload character (industrial organic waste and
   FOG co-digestion, FOS/TAC excursions to 0.93, SRT down to 3.6 d). Licence (ODC-By)
   permits redistribution with attribution; daily coverage is 3.25 years; the 1-minute
   SCADA year gives empirical sensor-noise and dropout statistics for the observation
   model. §8 step 2 (fit influent variability, seasonal drift, missingness, sensor noise)
   is fully feasible on it. §8 step 3 (forecasting-only check) is feasible: run the same
   simplified ADM1 and the P0 pipeline on the daily file with HSW/FOG treated as a
   co-substrate COD stream, and report NSE/MAE for biogas next to the published MLP
   baseline (R² 0.78, MAPE 13.4 %). This shows the tool chain works on real data without
   claiming calibration success.
2. **Plant A: anchor becomes published summary statistics.** Use Tisocco et al.
   2023/2024 and 2026 (operating envelope, feedstock tables, weekend-feeding pattern,
   NSE/RMSE of ADM1-R3) as the quantitative target for Plant A's influent generator and
   for the expected forecasting skill. State plainly in the paper that no open
   full-scale agricultural co-digestion time series exists. In parallel, ask the authors
   (Teagasc/AFBI; Aarhus University) for the plant data under a data-use agreement
   (proposal §13 asks for agreements before week 6). If obtained, it does not need to be
   redistributed to be used for §8 step 2.
3. **Secondary: ILRI farm-scale set** for Tier-A sampling irregularity and for Phase 3
   realism. Do not use it for Plant A/B/C statistics.
4. Do **not** use the Chiguer GitHub CSV (no licence, provenance unclear) or any BSM2
   influent as an anchor.
5. The lead may prefer a stricter reading in which Plant B has no anchor at all; then
   §8 for Plant B also falls back to published summary statistics (food-waste plants in
   the review, Part 1) and the paper says so.

What §8 of the paper should then say: "The simulator is anchored to one open full-scale
dataset (Muscatine WRRF; sewage sludge with industrial co-digestion) for influent
variability, missingness and sensor noise, and to published summary statistics
(Tisocco et al. 2024, 2026) for agricultural co-digestion, because no open full-scale
agricultural time series exists. A forecasting-only check of the P0 tool chain is
reported on the Muscatine data."

---

## 5. Reproducibility

`anchor/MANIFEST.json` lists every fetched file (URL, licence, SHA-256, size, download
date) and every candidate not fetched with the reason. `python -m anchor.fetch`
re-downloads and verifies; `python -m anchor.fetch --verify` checks without network.
Small files (< 1 MB, ODC-By) are committed under `anchor/raw/iowa-muscatine-wrrf/` with
an `ATTRIBUTION.md`; large files are git-ignored.

## 6. Sources read this session

- DataCite record for 10.25820/data.006715 (`api.datacite.org/dois/10.25820/data.006715`)
- Iowa OAI-PMH `oai_dc` record `oai:alma.01IOWA_INST:11894605070002771` (file delivery URLs)
- PMC full texts: [PMC10928704](https://pmc.ncbi.nlm.nih.gov/articles/PMC10928704/) (Schroer & Just 2023), [PMC12874345](https://pmc.ncbi.nlm.nih.gov/articles/PMC12874345/) (Tisocco et al. 2026), [PMC7915957](https://pmc.ncbi.nlm.nih.gov/articles/PMC7915957/) (Dittmer et al. 2021)
- Springer HTML and PDF of [10.1007/s11783-024-1810-9](https://link.springer.com/article/10.1007/s11783-024-1810-9) and its ESM PDF
- Elsevier supplement `1-s2.0-S2666498426000074-mmc1.docx`
- Mendeley Data API records for gk3f363sfg, mm2bpsgpsc, r35tshpftb, zmryw9dfpw, 8795jgp8cv
- Zenodo API records 8360096, 10104840, 12805035, 14921811, 7474131, 15691684, 22232790 and four paginated searches
- IOP article page [10.1088/2515-7620/ade03b](https://iopscience.iop.org/article/10.1088/2515-7620/ade03b); Frontiers article [10.3389/fenrg.2017.00012](https://www.frontiersin.org/journals/energy-research/articles/10.3389/fenrg.2017.00012/full)
- GitHub pages for soerenweinrich/ADM1 (MIT; no data files), CaptainFerMag/PyADM1, wwtmodels/Anaerobic-Digestion-Models, aminechiguerdoc23-eng/adm1-am2-validation (README and `biogas_dataset.csv` head)
- Web-search snippets only (page unreadable here): Meola & Weinrich 2025 data statement; Energies 2026 19(5):1377; WST 2025 92(4):610; DBFZ DataLab description
