# Gate G1 — anchor comparison report

**Date:** 2026-09-09 (revised after the lead's rulings of 2026-09-03, the remediation
rulings of 2026-09-04 and the four rulings of 2026-09-09) · **Gate:** G1 (proposal §11) ·
**Status:** infrastructure criterion
**met**; plant criterion **met** — the Plant B souring that failed the first pass is fixed
and the acceptance condition is satisfied. **All 22 independent rows are now inside their
declared tolerance**: the two VFA rows joined them when the convention on *our* side of the
comparison was corrected, with no bound moved and no kinetic parameter touched (§5.1). One
row (`alkalinity_median`) is calibrated to the anchor and is reported without being counted
as a match. S6-01 is no longer inert.

**The digester has not changed.** Nothing in the truth model moved under any of these
rulings: not a kinetic parameter, not a feed value, not a plant geometry. What moved is
where truth is written, how a *sensor* is realised, which quantity the VFA rows compare
against the anchor, and what raises the missingness flag. Plant B's pH, gas, alkalinity and
every influent statistic are the numbers they were on 2026-09-03.

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
| `vfa_median` | kg/m3 as acetic acid | 0.7753 | 1.178 | 0.66 | ratio in [0.25, 4] | pass |
| `fos_tac_median` | - (VFA as acetic over alkalinity as CaCO3) | 0.1495 | 0.2323 | 0.64 | ratio in [0.5, 2] | pass |

**22 of 22 independent rows are inside their declared tolerance.** A further 1 row was calibrated to the very anchor column it is compared against, and is excluded from that count: agreeing with a column you were fitted to is not evidence.

| Generated statistic with no anchor row | Value |
|---|---:|
| `ch4_fraction_median` | 0.7223 |
| `foaming_day_fraction` | 0 |
| `fos_tac_exceedance_fraction` | 0 |
| `fos_tac_true_vfa_median` | 0.01302 |
| `overload_day_fraction` | 0.07285 |
| `sound_run_fraction` | 1 |
| `vfa_true_median` | 0.06717 |
| `vs_fraction_fog` | 0.01984 |

### The output panel, run by run

| Base seed | Verdict | median pH | mean CH4 | titrimetric FOS (kg/m3) | true VFA (kg/m3) | FOS/TAC | trigger days | FOS/TAC > 0.40 days |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1000 | sound | 7.33 | 0.712 | 0.866 | 0.0879 | 0.150 | 15.23 % | 0.00 % |
| 1001 | sound | 7.29 | 0.727 | 0.759 | 0.0733 | 0.151 | 11.92 % | 0.00 % |
| 1002 | sound | 7.32 | 0.725 | 0.821 | 0.0780 | 0.151 | 12.58 % | 0.00 % |
| 1003 | sound | 7.29 | 0.711 | 0.787 | 0.0826 | 0.152 | 7.95 % | 0.00 % |
| 1004 | sound | 7.28 | 0.725 | 0.713 | 0.0584 | 0.149 | 3.97 % | 0.00 % |
| 1005 | sound | 7.24 | 0.718 | 0.664 | 0.0579 | 0.151 | 3.97 % | 0.00 % |
| 1006 | sound | 7.26 | 0.725 | 0.693 | 0.0543 | 0.149 | 3.31 % | 0.00 % |
| 1007 | sound | 7.26 | 0.701 | 0.742 | 0.0593 | 0.149 | 5.96 % | 0.00 % |
| 1008 | sound | 7.27 | 0.707 | 0.735 | 0.0580 | 0.149 | 2.65 % | 0.00 % |
| 1009 | sound | 7.30 | 0.711 | 0.790 | 0.0628 | 0.148 | 7.28 % | 0.00 % |
| 1010 | sound | 7.32 | 0.720 | 0.805 | 0.0710 | 0.148 | 7.28 % | 0.00 % |
| 1011 | sound | 7.37 | 0.730 | 0.855 | 0.0712 | 0.147 | 7.95 % | 0.00 % |
| 1012 | sound | 7.40 | 0.730 | 0.914 | 0.0740 | 0.146 | 10.60 % | 0.00 % |
| 1013 | sound | 7.25 | 0.701 | 0.725 | 0.0618 | 0.151 | 11.26 % | 0.00 % |
| 1014 | sound | 7.30 | 0.723 | 0.746 | 0.0618 | 0.149 | 5.96 % | 0.00 % |
| 1015 | sound | 7.34 | 0.722 | 0.838 | 0.0835 | 0.150 | 9.27 % | 0.00 % |
| 1016 | sound | 7.29 | 0.711 | 0.780 | 0.0633 | 0.150 | 10.60 % | 0.00 % |
| 1017 | sound | 7.32 | 0.731 | 0.771 | 0.0715 | 0.149 | 5.96 % | 0.00 % |
| 1018 | sound | 7.39 | 0.728 | 0.941 | 0.1001 | 0.150 | 9.27 % | 0.00 % |
| 1019 | sound | 7.24 | 0.725 | 0.665 | 0.0584 | 0.151 | 6.62 % | 0.00 % |
| 1020 | sound | 7.29 | 0.705 | 0.798 | 0.0630 | 0.149 | 4.64 % | 0.00 % |
| 1021 | sound | 7.25 | 0.704 | 0.732 | 0.0543 | 0.149 | 15.89 % | 3.97 % |
| 1022 | sound | 7.24 | 0.723 | 0.689 | 0.0719 | 0.154 | 5.96 % | 0.00 % |
| 1023 | sound | 7.36 | 0.723 | 0.891 | 0.0973 | 0.151 | 3.97 % | 0.00 % |

**24 of 24 runs are working digesters.**

**Two rates, and they are different things** (lead's rulings B and C, 2026-09-09). Across the 24 SOUND runs:

| | what it is | pooled | per-run min | per-run max | runs that fire |
|---|---|---:|---:|---:|---:|
| **conditional-missingness trigger** | hidden true VFA > 2.00x its 30-d trailing median | **7.92 %** | 2.65 % | 15.89 % | 24 of 24 |
| operator-visible overload | titrimetric FOS/TAC > 0.40 | **0.17 %** | 0.00 % | 3.97 % | 1 of 24 |

The anchor's own FOS/TAC exceedance is 8.25 % (Dig1) and 9.18 % (Dig2), and its 92nd percentile is what the 0.40 threshold is matched to. The trigger is not compared with that number: it fires on the hidden state, which no plant column reports.

<!-- END GENERATED: g1 anchor comparison -->

## 5. Reading the rows

**Every influent row passes**, and so do **biogas and pH**. `alkalinity_median` is inside
its bound but is a **calibrated** row, not a match (§3.2). And since the lead's ruling A of
2026-09-09 the two VFA rows pass as well — **20 of 22 independent rows became 22 of 22**,
without a bound being moved or a kinetic parameter being touched.

### 5.1 What actually changed, because it was not the model

The simulator's residual VFA has not moved. What changed is **which quantity this report
compares against the anchor's VFA column**.

| | before 2026-09-09 | now |
|---|---|---|
| the anchor's `Dig1-VFA_mgL` | the FOS half of a two-point titration | unchanged |
| our `vfa_median` | **true VFA**, 0.067 kg m⁻³ | **titrimetric FOS**, 0.775 kg m⁻³ |
| ratio to the anchor | 0.06 (a factor of 17.5 out) | **0.66** |
| our `fos_tac_median` | 0.013 | **0.150** |
| ratio to the anchor | 0.06 | **0.64** |

The row was comparing a chromatographic VFA with a titration. A two-point Nordmann/Kapp
titration counts everything titratable between pH 5.0 and pH 4.4, and in a digester most of
that is **bicarbonate**: measured here, **90 %** of the reading is carry-over rather than
volatile acid.

**Nothing was fitted to achieve this.** `sim.observation.channels.titrimetric_fos` has no
free parameter — κ is frozen at 1.0 — and every equilibrium constant is the truth model's
own, through `sim.adm1.physchem.temperature_corrected`. At Plant B's 308.48 K that gives
pK_a(acetate) 4.760, pK_a(CO₂) 6.305, a carry-over fraction of 0.0349 of S_IC, and an
implicit scale-up of 1/f_ac = **3.02** — the Nordmann formula's own factor, *derived* rather
than asserted.

**True VFA remains the hidden channel and no sensor sees it.** The `vfa_total` channel is
unchanged; the `vfa_total` *sensor* reads `vfa_titrimetric`, and `fos_tac_true_vfa` is kept
beside `fos_tac` so the two conventions stay comparable rather than one silently replacing
the other.

### 5.2 The residual gap, pinned

A gap of **1.52×** remains: 0.775 against the anchor's 1.178. It is pinned in both
directions by `tests/test_g1_anchor.py`, exactly as the old failure was, so it can neither
grow nor be quietly tuned to 1.0.

`docs/vfa_gap.md` still stands and is now a **finding about the model** rather than a
failing row: no value of `k_m_ac` closes the *true-VFA* gap, because the model is bistable —
VFA jumps 0.183 → 10.08 kg m⁻³ and pH falls 6.95 → 4.60 between ×0.40 and ×0.35 — and the
anchor's value lies in the gap between the branches. **No kinetic parameter has been
changed at any point.**

### 5.3 The finding that corrects an earlier diagnosis

An earlier note reported a "variance deficit" in the model. **That was wrong and is not
recorded as a model finding.** Measured: true VFA's day-to-day spread is p92/median ≈ 2.1,
against the anchor's FOS/TAC spread of 1.74 — the model's VFA dynamics are if anything
*more* variable than the plant's.

What is flat is the **titrimetric FOS/TAC** (p92/median ≈ 1.1), and it is flat *because*
86–90 % of the reading is bicarbonate carry-over tracking slowly-varying alkalinity. The
finding for the paper is therefore:

> **The titrimetric convention masks the VFA dynamics it is meant to report.**

That is a property of the measurement, not a deficiency of the model — and it is the
independent justification for §5.4.

### 5.4 Conditional missingness now triggers on the hidden state

The §6.1 property is that instruments fail during the transients that identify the process.
That is a property of the **plant**, so the flag that drives it must read the plant, not a
reading a workflow happens to have taken — and certainly not a reading that masks the
dynamics (§5.3). Under the lead's ruling B the trigger is

> **true VFA above 2.00× its own 30-day trailing median**, the window excluding the current
> day so that an excursion cannot drag its own reference up and mask itself.

Measured across the twenty-four sound runs: it fires on **7.92 % of days pooled**, per-run
2.65–15.89 %, **in every one of the 24 runs**. The anchor's own FOS/TAC exceeds its 92nd
percentile on 8.25 % (Dig1) and 9.18 % (Dig2) of days. Nothing was tuned to reach that
agreement — 2.00× is the lead's cut-off as written.

**This gives S4-02 back.** The Level-4 `informative_missingness` row scales this flag, and
on the old trigger the flag fired on no day at all in 23 of 24 sound runs, which made the
row a near-duplicate of Level 1. It now has something to scale in every run.

**The two rejected candidates are recorded and not used**: gas > 1.35× trailing fires on
21.80 % of days, OLR above a design proxy on 37.20 %, and the OR of all three on 47.27 %.
Their equivalent 7.8 % cut-offs would be gas > 1.796× trailing and OLR > 1.871× mean.

**Cross-plant firing rates.** The cut-off is 2.00× on **every** plant: differences between
plants are to be recorded, not tuned away, and there is no per-plant cut-off.

Measured here on clean Level-0 panels, at the same 2.00× cut-off on every plant. The
coordinator is measuring the same quantity independently; where the two disagree, both
numbers should be looked at rather than either adopted.

| Plant | panel | sound | trigger, pooled | per-run range | runs that fire | operator FOS/TAC > 0.40 |
|---|---|---|---:|---|---:|---:|
| B | seeds 1000–1023, 180 d | 24 / 24 | **7.92 %** | 2.65 – 15.89 % | 24 / 24 | 0.17 % |
| C | seeds 1000–1023, 180 d | 24 / 24 | **9.96 %** | 6.62 – 16.56 % | 24 / 24 | 0.00 % |
| A | seeds 1000–1011, 180 d | 12 / 12 | **0.55 %** | 0.00 – 1.99 % | **5 / 12** | 0.00 % |

**Plants B and C bracket the anchor's 7.78–9.18 %; Plant A is an order of magnitude below
them, and that difference is recorded rather than tuned away** (the lead). It is not a
surprise once stated: B and C are fed by **trucked deliveries**, which arrive in lumps and
produce exactly the VFA excursions the trigger is looking for, while Plant A is fed
continuously on slurry and silage and its VFA is correspondingly smooth. C is slightly above
B because it has no blend tank — the tank exists on B precisely to damp those arrivals — so
its excursions reach the biomass less smoothed.

**FLAGGED, because it has a scoring consequence.** On Plant A the trigger fires on 0.55 % of
days and in only 5 of 12 runs, so conditional missingness has little to act on there. Plant
A hosts the Level-2–5 Tier-A subset, which includes **S4-02, the `informative_missingness`
row** — the row this trigger exists to give content to. It now works on B and C and is still
thin on A. The cut-off is not adjusted for it, as ruled; the observation is for the lead.

### 5.5 The operator-visible threshold is a different thing

FOS/TAC > 0.40 stays as the **operator-facing** overload threshold and no longer drives
conditional missingness (ruling C). It is percentile-matched to the anchor: the anchor's own
titrimetric FOS/TAC has its 92nd percentile at 0.402 (Dig1) and 0.408 (Dig2), n = 861 each,
and the 92nd is the closest percentile to 0.40 of any between the 50th and the 99th.

On the panel it fires on **0.17 % of days pooled**, in 1 of 24 runs — far below the plant's
8.25 %, because the simulated titrimetric distribution still sits ~1.5× below the plant's
(§5.2). The threshold is not moved to compensate.

## 6. `docs/vfa_gap.md`: a finding, not a defect

**The list is `docs/vfa_gap.md`, written by the coordinator under the lead's ruling 3 of
2026-09-03 and merged into this branch.** Its options (a) and (b) were both adopted by the
lead's ruling 4 of 2026-09-09, and (a) — the titrimetric convention — is what §5.1
implements.

Its central measurement is now recorded **for the paper as a property of the model**:

1. **Kinetics cannot close the true-VFA gap, and this is measured rather than argued.** No
   value of `k_m_ac` works: ×0.40 gives VFA 0.183 kg m⁻³ at pH 6.95, ×0.35 gives 10.08 at
   pH 4.60. The model is **bistable** and the anchor's 1.18 lies *between* the branches.
   `k_hyd` at ×2 and ×4 changes residual VFA not at all.
2. **The gap was a measurement-convention question**, and the convention is now declared
   chemistry rather than an open question.
3. **The alkalinity lever is spent** — it is calibrated to the anchor (§3.2), and raising it
   further pushes FOS/TAC down.
4. **Loading is not the lever either**: Plant B reaches only FOS/TAC 0.15 at 2.5× the
   declared feed, and the anchored loading rates pass.

**No kinetic parameter was touched at any point**, and the declared VFA tolerance was never
widened. What moved is which quantity the row measures.

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
