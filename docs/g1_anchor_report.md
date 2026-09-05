# Gate G1 — anchor comparison report

**Date:** 2026-09-04 (revised after the lead's rulings of 2026-09-03 and the remediation
rulings of 2026-09-04) · **Gate:** G1 (proposal §11) · **Status:** infrastructure criterion
**met**; plant criterion **met** — the Plant B souring that failed the first pass is fixed
and the acceptance condition is satisfied. Two output rows still fail their declared
tolerance and are the subject of `docs/vfa_gap.md`; one row (`alkalinity_median`) is
calibrated to the anchor and is reported without being counted as a match; one scenario row
(S6-01) is inert and needs a decision.

None of the numbers in the generated block moved under the remediation of 2026-09-04: the
truth store, the loader and the per-sensor observation streams change where truth is
written and how a *sensor* is realised, not what the digester does.

> **G1.** Simulator generates all scenarios with logged truth, and influent statistics
> match anchor within declared tolerance. *Fail → fix realism before any workflow work.*

Everything in the generated block is produced by `anchor/compare_generated.py`, written
into this file by `python scripts/g1_report.py`, and recomputed and compared verbatim by
`tests/test_g1_anchor.py`. The report cannot go stale without a test failing.

## 1. How to read this, and what "declared" means

Every tolerance in the table was **declared before anything was measured** and none has
been changed since. They live in `anchor.compare_generated.TOLERANCES` with a stated
rationale each, and most are **inherited rather than invented**:

| Rows | Bound | Where it comes from |
|---|---|---|
| per-stream delivery medians | ± 15 % | the bound `tests/test_generator.py` already applies to this quantity |
| per-stream log spreads | ± 30 % | as above |
| per-stream zero fractions | ± 0.04 | as above |
| total feed flow | ± 15 % | as above |
| biogas | ratio 0.6–1.5 | the band `tests/test_plausibility.py` applies to a generator-driven run |
| digester pH | ± 0.4 pH | ≈ twice the plant's own day-to-day spread; the probe's noise is 0.02 |
| alkalinity | ± 35 % | **calibrated to this column** (ruling 3, 2026-09-03), so the row is reported and **not counted as an anchor match**. The bound was declared when `S_cat` was a design value; it is not a fit's own tolerance |
| VFA | ratio 0.25–4.0 | deliberately generous: residual VFA is the least identifiable ADM1 output |
| FOS/TAC | ratio 0.5–2.0 | a factor of two, the natural band for a dimensionless ratio |

A test reads the inherited literals out of the test files themselves, so widening one "for
consistency" fails rather than passes quietly.

**Two procedural changes are recorded rather than hidden, and neither touched a
tolerance.** (i) The output statistics were first measured on a single clean Level-0 run at
that scenario's own seed. That seed turned out to be one of the Plant B seeds that
acidified, so every output row failed for the wrong reason; the measurement was widened to
a declared panel with each run labelled sound or soured. (ii) The panel was widened again
from twelve seeds to **twenty-four** when the lead made "zero souring on clean Level-0
seeds" the acceptance condition: twelve seeds could show a 40 % failure rate but could not
support a claim that the rate is zero.

**What did change, on the lead's rulings of 2026-09-03, is the simulator** — the feed's
strong-cation content is now calibrated to the anchor's own digester alkalinity, and Plant
B's blend tank is declared in the plant contract. Both are recorded in §3.

## 2. What is compared, and against what

* **Anchor:** the Muscatine WRRF daily file, `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`
  (Schroer & Just 2024, ODC-By 1.0), 1,103 days, 2020-01-01 to 2023-03-31, read through
  `anchor/ingest_muscatine.py`. Plant totals are divided by the two parallel digesters.
* **Generated influent:** a 730-day draw of the influent generator alone, no digester, at
  seed 7 — the same seed and horizon `tests/test_generator.py` uses, so the two
  descriptions are of one realisation.
* **Generated output:** a twenty-four-run panel of clean Level-0 runs on Plant B (base
  seeds 1000–1023, 180 days each) through the whole chain — burn-in, hidden active-volume
  error, stochastic influent, blend tank, truth model, channels. Statistics are medians
  across the runs that are working digesters, which is now all of them.

**Plant C is not separately anchored on the output side, and the report does not pretend
otherwise.** Plant C is Plant B fed only its sludge streams — a counterfactual the real
plant never ran, so there is no measured pH, alkalinity or biogas to compare it against.
Its *feed* streams (primary sludge, thickened WAS) are the same anchored columns as Plant
B's. Plant A is statistics-anchored throughout (§8 of the proposal) and has no time series
at all.

## 3. Plant B: what was wrong, what fixed it, and which change did the work

The first pass of this report found that a clean Level-0 run on **Plant B** acidified
within 180 days on **5 of 12 seeds** — median pH 4.6–5.0 with 0.0–0.31 methane. It
reproduced with the declared geometry, the published initial state and no burn-in, so it
was a property of the configuration and not of the harness, and
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings` had missed it
because it tests one seed, which happens to be one of the seven that survived.

The lead ruled two changes. **Both were made, and it turns out that either one alone would
have been enough.** Measured on the twelve-seed panel with the other held back:

| | no blend tank | with blend tank |
|---|---|---|
| **original strong cations** | **7/12 sound**, min pH 4.50, worst p95 FOS/TAC 2.93 | 12/12, min pH 6.53, 0.111 |
| **anchor-calibrated cations** | 12/12, min pH 7.06, 0.078 | **12/12, min pH 7.13, 0.044** |

On the full twenty-four-seed panel with both changes in place: **24 of 24 sound**, median
pH 7.24–7.40, methane 0.70–0.73. The acceptance condition is met, and met with margin
rather than scraped.

**Stated plainly, because it matters for who gets the credit:** the calibrated feed with
**no tank at all is already 12 of 12 sound**. The alkalinity calibration removes the
souring on its own. So does the tank on its own, on the uncalibrated feed. Neither is
redundant and neither should be credited with the other's work — the tank is a
plant-contract correction justified by the plant's own description, and it happens also to
be sufficient; the calibration is an anchor-driven correction, and it happens also to be
sufficient. Together they leave the most margin (min pH 7.13 against 6.53 and 7.06), which
is why both are kept.

### 3.1 The blend tank (ruling 1)

`configs/plants/plant_B.yaml` had always described the high-strength waste as "trucked
deliveries **blended in a 65,000-gal tank**", and the simulator had never implemented it:
truck arrivals reached the biomass on the day they arrived, as an acid pulse rather than as
a week of slightly heavier feeding. The tank is now part of the **declared contract**
(`sim/plants/equalisation.py`) — visible to a workflow like the digester's volume, because
what is hidden is the composition of what was delivered, not the existence of the tank.
65,000 gal is 246.05 m³ for the plant, halved to 123.02 m³ for the modelled unit, giving
about 4–5 days of hold-up. It is one well-mixed buffer: inflow is the day's arrivals,
outflow is proportional to level, mass closes to machine precision, and at zero volume it
reduces to a pass-through exactly.

**The influent generator is untouched**, as ruled. Every anchored delivery statistic still
describes arrivals, so the influent half of the table below is unaffected by this change —
which the table confirms: those rows are identical to the first pass.

FOG is trucked too and is **not** buffered, because the plant description names a tank only
for the high-strength waste. That is the reading closest to the evidence; widening it is a
one-line change.

### 3.2 The alkalinity calibration (ruling 3)

The anchor measures the digester's own alkalinity — median 5.04 kg CaCO₃ m⁻³ — and the
simulator was producing 2.78. An under-buffered digester is exactly one that acidifies
under a load pulse, so this was the same finding from the other side. Calibrating the feed's
strong-cation content to that column lands alkalinity at **5.12** and pH at **7.29**
against the plant's **7.27**.

**That pH agreement is not independent corroboration, and this report no longer claims it
is** (the lead's ruling M1, 2026-09-04). An earlier draft read the two landing together as
"the sign that the calibration is physically coherent rather than a fitted offset". In a
bicarbonate-buffered digester pH is a function of alkalinity and the partial pressure of
CO₂; fixing the alkalinity to a measured value and then observing that the pH comes out
right is one measurement reported as two. The alkalinity row is likewise **excluded from
the anchor-match count** and labelled *calibrated to anchor* rather than *pass* in §4: it
says the fit converged, not that the simulator reproduces a measurement it was not shown.
It is still reported, because a large residual would still be a finding — the fit could
fail, or drift under a later change.

The anchor constrains only the **flow-weighted** cation excess of the blend, not its split
between streams, and the split is an assumption stated as such: nothing on the FOG, a
modest rise on the two sludges (0.04 → 0.05 kmol m⁻³, ~1,500 mg L⁻¹ as CaCO₃ in the
liquor), and the remainder on the high-strength waste (0.03 → 0.225), on the grounds that
clean-in-place caustic is the usual source of alkalinity in food and beverage industrial
waste and that this stream carries 137 kg COD m⁻³. **Inert-N was left alone**: S_cat alone
reaches the anchor, and inert-N carries the deliberate truth/fitted mismatch of 2026-09-02.

**Finding: one stream now supplies almost all of the digester's buffering.** The
calibration is flow-weighted, but the weight it puts on the industrial stream is extreme,
and that is a property of the plant model worth stating rather than a consequence to be
inherited quietly. Measured three ways (Plant B, base seed 1000, 180 d, settled from d 30):

| Basis | High-strength waste | The two sludges | FOG |
|---|---:|---:|---:|
| share of the blend's net strong-cation excess (flow-weighted, medians of §4) | **78 %** | 22 % | 0 % |
| share of the `S_cat` **increment** the calibration added | **91 %** | 9 % | 0 % |
| share of the digester alkalinity the calibration added (5.63 with, 3.65 without any of it) | **86 %** (5.63 → 3.92 when HSW alone is reverted) | 15 % (5.63 → 5.34) | 0 % |

So the anchor's alkalinity column is, in this model, very nearly a measurement of one
trucked industrial stream's caustic load. Two consequences follow and are for the lead:
**Plant C is fed the sludges alone**, so it inherits only the 15 % share and its alkalinity
is an assumption with no anchor behind it at all; and a Level-3 fault that alters the
high-strength waste moves the digester's whole buffer capacity, which may make those rows
easier than intended.

**The ruling states this share as ~95 %.** The three bases above give 78 %, 91 % and 86 %,
and none of them reproduces 95 %; the closest is the share of the `S_cat` increment. The
measurement method is written out above so the basis can be settled rather than argued.
Reported, not resolved here.

**One difference from the coordinator's own calibration sweep, flagged for checking.** That
sweep varied `S_cat` *uniformly* across the Muscatine feeds and found +0.05 kmol m⁻³ hits
alkalinity 5.024 and pH 7.29. This implementation applies the same **+0.05 flow-weighted**
but splits it unevenly, for the physical reasons above. Plant B is identical either way —
only the flow-weighted total reaches its digester — but **Plant C differs**, because it is
fed the sludges alone: uniform would give it alkalinity 7.77, the split used here gives
5.85, which is the more defensible figure for a sludge-only municipal digester. Plant C has
no output anchor, so this is a judgement rather than a fit, and it is recorded as one.

## 4. The comparison

<!-- BEGIN GENERATED: g1 anchor comparison -->

### Comparison against the declared tolerances

| Statistic | Unit | Generated | Anchor | Ratio | Declared tolerance | Result |
|---|---|---:|---:|---:|---|---|
| `feed_volume_median_primary_sludge` | m3/d per digester | 28.81 | 30.28 | 0.95 | +/- 15 % | pass |
| `feed_volume_log_sigma_primary_sludge` | - (sd of ln amount on delivery days) | 0.4406 | 0.4363 | 1.01 | +/- 30 % | pass |
| `delivery_zero_fraction_primary_sludge` | - (fraction of days with no delivery) | 0 | 0 | - | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_thickened_was` | m3/d per digester | 17.06 | 17.42 | 0.98 | +/- 15 % | pass |
| `feed_volume_log_sigma_thickened_was` | - (sd of ln amount on delivery days) | 0.5632 | 0.5268 | 1.07 | +/- 30 % | pass |
| `delivery_zero_fraction_thickened_was` | - (fraction of days with no delivery) | 0 | 0 | - | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_high_strength_waste` | m3/d per digester | 23.5 | 23.58 | 1.00 | +/- 15 % | pass |
| `feed_volume_log_sigma_high_strength_waste` | - (sd of ln amount on delivery days) | 0.791 | 0.7786 | 1.02 | +/- 30 % | pass |
| `delivery_zero_fraction_high_strength_waste` | - (fraction of days with no delivery) | 0.07945 | 0.1006 | 0.79 | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_fog` | m3/d per digester | 31.74 | 33.27 | 0.95 | +/- 15 % | pass |
| `feed_volume_log_sigma_fog` | - (sd of ln amount on delivery days) | 0.7601 | 0.7059 | 1.08 | +/- 30 % | pass |
| `delivery_zero_fraction_fog` | - (fraction of days with no delivery) | 0.3123 | 0.3073 | 1.02 | +/- 0.04 - (fraction of days with no delivery) | pass |
| `total_feed_flow_median` | m3/d per digester | 101.2 | 94.1 | 1.08 | +/- 15 % | pass |
| `vs_fraction_primary_sludge` | kg VS/kg wet | 0.03129 | 0.0295 | 1.06 | +/- 20 % | pass |
| `vs_fraction_thickened_was` | kg VS/kg wet | 0.03199 | 0.0312 | 1.03 | +/- 20 % | pass |
| `vs_fraction_high_strength_waste` | kg VS/kg wet | 0.06548 | 0.06485 | 1.01 | +/- 25 % | pass |
| `hsw_cod_concentration` | kg COD/m3 | 133.3 | 136.8 | 0.97 | +/- 25 % | pass |
| `organic_loading_rate` | kg VS/m3/d | 2.131 | 1.885 | 1.13 | +/- 30 % | pass |
| `biogas_mean` | m3/d per digester at the meter's conditions | 2984 | 2111 | 1.41 | ratio in [0.6, 1.5] | pass |
| `digester_pH_median` | pH units | 7.293 | 7.27 | 1.00 | +/- 0.4 pH units | pass |
| `alkalinity_median` | kg CaCO3/m3 | 5.12 | 5.043 | 1.02 | +/- 35 % | calibrated to anchor |
| `vfa_median` | kg/m3 as acetic acid | 0.06717 | 1.178 | 0.06 | ratio in [0.25, 4] | **FAIL** |
| `fos_tac_median` | - (VFA as acetic over alkalinity as CaCO3) | 0.01302 | 0.2323 | 0.06 | ratio in [0.5, 2] | **FAIL** |

**20 of 22 independent rows are inside their declared tolerance.** A further 1 row was calibrated to the very anchor column it is compared against, and is excluded from that count: agreeing with a column you were fitted to is not evidence.

| Generated statistic with no anchor row | Value |
|---|---:|
| `ch4_fraction_median` | 0.7223 |
| `foaming_day_fraction` | 0 |
| `fos_tac_exceedance_fraction` | 0 |
| `overload_day_fraction` | 0 |
| `sound_run_fraction` | 1 |
| `vs_fraction_fog` | 0.01984 |

### The output panel, run by run

| Base seed | Verdict | median pH | mean CH4 | median VFA (kg/m3) | median FOS/TAC |
|---|---|---:|---:|---:|---:|
| 1000 | sound | 7.33 | 0.712 | 0.088 | 0.015 |
| 1001 | sound | 7.29 | 0.727 | 0.073 | 0.015 |
| 1002 | sound | 7.32 | 0.725 | 0.078 | 0.015 |
| 1003 | sound | 7.29 | 0.711 | 0.083 | 0.016 |
| 1004 | sound | 7.28 | 0.725 | 0.058 | 0.012 |
| 1005 | sound | 7.24 | 0.718 | 0.058 | 0.013 |
| 1006 | sound | 7.26 | 0.725 | 0.054 | 0.012 |
| 1007 | sound | 7.26 | 0.701 | 0.059 | 0.012 |
| 1008 | sound | 7.27 | 0.707 | 0.058 | 0.012 |
| 1009 | sound | 7.30 | 0.711 | 0.063 | 0.012 |
| 1010 | sound | 7.32 | 0.720 | 0.071 | 0.013 |
| 1011 | sound | 7.37 | 0.730 | 0.071 | 0.012 |
| 1012 | sound | 7.40 | 0.730 | 0.074 | 0.012 |
| 1013 | sound | 7.25 | 0.701 | 0.062 | 0.013 |
| 1014 | sound | 7.30 | 0.723 | 0.062 | 0.012 |
| 1015 | sound | 7.34 | 0.722 | 0.083 | 0.015 |
| 1016 | sound | 7.29 | 0.711 | 0.063 | 0.013 |
| 1017 | sound | 7.32 | 0.731 | 0.072 | 0.014 |
| 1018 | sound | 7.39 | 0.728 | 0.100 | 0.016 |
| 1019 | sound | 7.24 | 0.725 | 0.058 | 0.013 |
| 1020 | sound | 7.29 | 0.705 | 0.063 | 0.012 |
| 1021 | sound | 7.25 | 0.704 | 0.054 | 0.011 |
| 1022 | sound | 7.24 | 0.723 | 0.072 | 0.017 |
| 1023 | sound | 7.36 | 0.723 | 0.097 | 0.017 |

**24 of 24 runs are working digesters.**

<!-- END GENERATED: g1 anchor comparison -->

## 5. Reading the failures

**Every influent row passes**, and so do **biogas and pH**; **alkalinity is inside its
bound but is a calibrated row, not a match** (§3.2). Twenty of the twenty-two independent
rows are inside their declared tolerance. The two that fail are **one finding**: a
converged ADM1 carries far less residual VFA than a real digester.

* **`vfa_median` 0.067 against 1.178 kg m⁻³ (ratio 0.06).** A converged ADM1 steady state
  holds VFA as a small difference between large production and consumption terms, and it
  settles far lower than a plant does. The plant's titrimetric method also over-reads true
  VFA — but not by a factor of eighteen.
* **`fos_tac_median` 0.013 against 0.232 (ratio 0.06).** VFA over alkalinity. Note that
  this ratio got *worse* than the first pass (0.09), and that is a good sign rather than a
  bad one: the denominator is now right, so the discrepancy is no longer split between two
  causes and sits entirely where it belongs, in the numerator.
* **`alkalinity_median` is inside its bound** at 5.12 against 5.043 (was 2.78, ratio 0.55)
  — but it is **not a pass and not an anchor match**, because the feed's `S_cat` was fitted
  to this column (§3.2). The calibration the lead approved closed this half of the gap by
  construction; what the row now reports is that the fit converged and has stayed
  converged.

**The consequence, and it costs the benchmark a scenario.** The overload flag fires when
FOS/TAC exceeds 0.40. Across the twenty-four sound runs the median run raises it on **no
day at all**, most runs never raise it, and the worst raises it on **3.3 %** of days —
against ~8 % of the plant's own days. Conditional missingness — the §6.1 property that
"instruments are more likely to fail during foaming and overload", and the entire subject
of the Level-4 `informative_missingness` row (S4-02) — therefore has **almost nothing to
act on on a healthy Plant B**, and S4-02 is close to a duplicate of Level 1. Pinned by
`tests/test_g1_anchor.py::test_the_overload_flag_never_fires_on_a_healthy_plant_b`.

In the first pass this was masked: the flag fired on 63–100 % of days in the *soured* runs
and on 0–9 % of the sound ones, so the panel looked bimodal. With no soured runs left, the
picture is unambiguous.

## 6. What closing the VFA gap would take — the list exists, and it rules out kinetics

**The list is `docs/vfa_gap.md` (branch `claude/vfa-gap-list`), written by the coordinator
under the lead's ruling 3. It supersedes what this section previously speculated.** No
kinetic parameter has been touched here, and on the list's evidence none should be.

Its findings that bear on this report:

1. **Kinetics cannot close the gap, and this is measured rather than argued.** No value of
   `k_m_ac` works: ×0.40 gives VFA 0.183 kg m⁻³ at pH 6.95, and ×0.35 gives 10.08 at
   pH 4.60. The model is **bistable**, and the anchor's 1.18 lies *between* the two
   branches — there is no parameter value that lands on it. `k_hyd` at ×2 and ×4 changes
   residual VFA not at all. An earlier draft of this section proposed a lower `k_m_ac` or
   a higher `K_S_ac` as "the most direct lever"; that was wrong and is withdrawn.
2. **The gap is a measurement-convention question**, now with the lead: what the plant's
   titrimetric method reports as "VFA" and what a converged ADM1 carries as residual
   volatile acids are not the same quantity.
3. **The alkalinity lever is spent.** It is calibrated to the anchor and passing (§3.2);
   raising it further pushes FOS/TAC *down*, not up.
4. **Loading is not the lever either.** The PR-#11 review measured Plant B reaching only
   FOS/TAC 0.15 at 2.5× the declared feed, and the anchored loading rates currently pass,
   so buying VFA with load would break a row that works.

**The declared VFA tolerance stays at ratio 0.25–4.0 and is left to fail.** A declared
bound is not widened to accommodate a known, reported gap; the failure is the report, and
this section is the pointer to why it is not being fixed here.

**FOS/TAC getting worse is expected and is not compensated for.** The calibration moved it
from 0.021 to 0.013 because alkalinity is the denominator. That is correct behaviour: the
denominator is now anchored, so the whole discrepancy sits in the numerator where it
belongs instead of being split between two causes.

**The 0.40 overload threshold has not moved and is not proposed to move** (ruling 3). Its
consequence — conditional missingness firing on almost no day of a healthy digester, and
S4-02 therefore sitting close to a duplicate of Level 1 — stands as recorded in §5 and in
the benchmark card, for the lead to weigh against whatever the convention question settles.

## 7. Provenance

| | |
|---|---|
| Anchor file | `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`, ODC-By 1.0, checksums in `anchor/MANIFEST.json` |
| Comparison code | `anchor/compare_generated.py` |
| Report generator | `python scripts/g1_report.py` |
| Test that recomputes it | `tests/test_g1_anchor.py` |
| Influent draw | seed 7, 730 d, Plant B |
| Output panel | base seeds 1000–1023 (24 runs), 180 d, Plant B, clean Level-0 |
| Related decisions | `docs/decisions.md`, entries of 2026-09-03 and 2026-09-04 |
