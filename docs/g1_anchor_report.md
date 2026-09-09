# Gate G1 — anchor comparison report

**Date:** 2026-09-09 (revised after the lead's rulings of 2026-09-03, the remediation
rulings of 2026-09-04, and the four rulings, the close-out rulings and the M2 ruling of
2026-09-09) · **Gate:** G1 (proposal §11) ·
**Status:** infrastructure criterion
**met**; plant criterion **met** — the Plant B souring that failed the first pass is fixed
and the acceptance condition is satisfied. **All 22 independent rows are now inside their
declared tolerance**: the two VFA rows joined them when the convention on *our* side of the
comparison was corrected, with no bound moved and no kinetic parameter touched (§5.1). One
row (`alkalinity_median`) is calibrated to the anchor and is reported without being counted
as a match. S6-01 is no longer inert.

**No kinetic parameter has been changed at any point**, and no plant geometry. Most of what
these rulings moved is not the model at all: where truth is written, how a *sensor* is
realised, which quantity the VFA rows compare against the anchor, and what raises the
missingness flag.

**One feed value did move, on the lead's M2 ruling of 2026-09-09, and it is not hidden in
this report** (§3.3). The high-strength waste's inorganic carbon was paired to the strong
cations ruling 3 had calibrated, because the two descriptions of that stream — the assay a
workflow reads and the charge the simulator is fed — had drifted 503× apart, and the
composition as it stood implied a pH of 13. `S_cat` is unchanged, so the strong-ion
difference reaching the digester is still exactly ruling 3's calibration; alkalinity and pH
land where ruling 3 put them; the visible consequence is 2.2 points of methane fraction
traded for CO₂ and a biogas ratio of 1.45 against its 1.5 bound. Everything that moved is
tabulated in §3.3 and nothing was tuned to compensate.

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

**Finding: the high-strength waste supplies 91 % of the `S_cat` increment this calibration
added.** That is the basis the lead ruled this share is reported on (2026-09-09), and the
basis is stated wherever the number appears: 91 % is a share of the *increment*, not of the
blend's absolute cation charge, and the two are different quantities that happen to be
percentages. The calibration is flow-weighted, but the weight it puts on the industrial
stream is extreme, and that is a property of the plant model worth stating rather than a
consequence to be inherited quietly. Measured three ways (Plant B, base seed 1000, 180 d,
settled from d 30), with the ruled basis in bold:

| Basis | High-strength waste | The two sludges | FOG |
|---|---:|---:|---:|
| share of the blend's net strong-cation excess (flow-weighted, medians of §4) | 78 % | 22 % | 0 % |
| **share of the `S_cat` increment the calibration added** — *the ruled basis* | **91 %** | 9 % | 0 % |
| share of the digester alkalinity the calibration added (5.63 with, 3.65 without any of it) | 86 % (5.63 → 3.92 when HSW alone is reverted) | 15 % (5.63 → 5.34) | 0 % |

So the anchor's alkalinity column is, in this model, very nearly a measurement of one
trucked industrial stream's caustic load. Two consequences follow and are for the lead:
**Plant C is fed the sludges alone**, so it inherits only the 9 % share of the increment
(15 % of the alkalinity the calibration added) and its alkalinity is an assumption with no
anchor behind it at all; and a Level-3 fault that alters the high-strength waste moves the
digester's whole buffer capacity, which may make those rows easier than intended.

**Ruled 2026-09-09.** The lead's earlier statement of this share as ~95 % is superseded by
the ruling that it is reported **on the `S_cat`-increment basis, 91 %, with the basis
stated** — never as a bare percentage, and not on the absolute-charge basis, because the
three bases above genuinely differ and a number without its basis cannot be checked. The
measurement method stays written out here so a later session can reproduce all three.

The **ruled basis is unaffected by the M2 fix below**: it is arithmetic on `S_cat`, which
that fix did not move. The other two rows are the **pre-M2 measurement** and are labelled
so rather than silently refreshed — the third one's counterfactual has actually changed
meaning, because "revert the calibration" now leaves behind the inorganic carbon that was
paired to it, so re-running it would answer a different question than the one it was asked.

**One difference from the coordinator's own calibration sweep, flagged for checking.** That
sweep varied `S_cat` *uniformly* across the Muscatine feeds and found +0.05 kmol m⁻³ hits
alkalinity 5.024 and pH 7.29. This implementation applies the same **+0.05 flow-weighted**
but splits it unevenly, for the physical reasons above. Plant B is identical either way —
only the flow-weighted total reaches its digester — but **Plant C differs**, because it is
fed the sludges alone: uniform would give it alkalinity 7.77, the split used here gives
5.85, which is the more defensible figure for a sludge-only municipal digester. Plant C has
no output anchor, so this is a judgement rather than a fit, and it is recorded as one.

### 3.3 M2: the assay and the fed charge now describe the same stream

The review of 2026-09-04 found that ruling 3's calibration had pulled the high-strength
waste's two descriptions apart. **The lead ruled on it on 2026-09-09, as an amendment to
ruling 3**, and this is what was done.

**The defect.** Ruling 3 raised the stream's `S_cat` from 0.03 to 0.225 kmol m⁻³. The
routine alkalinity assay — the number a *workflow* reads — was the bicarbonate alkalinity of
`S_IC` alone, which the calibration never touched. So the visible record said
**0.0214 kg CaCO₃ m⁻³** while the digester was handed **10.75** of cation charge to
balance: a factor of **503**, on the one stream the plant's whole buffer capacity rests on.

**Part 1 — the assay is computed from the full charge balance.** `total_alkalinity` now
reports what a titration to the CO₂ end point measures at the stream's own pH — bicarbonate,
the free acetate the fractionation carries, and water — in the same convention as the
effluent channel `alkalinity_total`. Its pair, `feed_cation_charge`, is what ADM1's charge
balance must balance: `S_cat − S_an + [NH₄⁺]`. Electroneutrality makes the two equal when a
stream's declared pH is consistent with its declared composition, and
`tests/test_generator.py::test_every_feed_assay_describes_the_charge_the_simulator_is_fed`
asserts that on **every** catalogue stream within 1.5×, so a future calibration to any feed
cannot reopen this quietly. Run against the pre-ruling catalogue it fails on two streams and
names both, which is how it was checked before the fix was applied.

| stream | before | after | what changed |
|---|---:|---:|---|
| `high_strength_waste` | **4.00×** (503× against the old assay) | **1.00×** | `S_IC` paired to `S_cat`; declared pH 5.0 → 7.0 |
| `food_waste` | **0.33×** | **1.00×** | `S_cat` 0.05 → 0.152 kmol m⁻³ (assumed value; the cited pH is kept) |
| `cattle_slurry` | 1.39× | 1.39× | — |
| `thickened_was` | 1.35× | 1.35× | — |
| `primary_sludge` | 1.47× | 1.47× | — |
| `grass_silage` | 1.16× | 1.16× | — |
| `fog` | 0 / 0 | 0 / 0 | carries no liquor; the guard's absolute floor |

**Part 2 — the stream had to be a physically possible waste.** The ruling was conditional on
the implied pH, so it was computed: at the declared composition the high-strength waste's
own charge balance closes only at **pH 13.04**. 0.205 kmol m⁻³ of net strong-cation charge
against 0.01 kmol C m⁻³ of inorganic carbon leaves nothing but hydroxide to balance it —
that is a caustic solution, not a food or beverage waste, so the condition was met and the
redistribution was made. Ruling 3's caustic is spent neutralising the stream's own acidity
and arrives as sodium **bi**carbonate, so:

| | before | after |
|---|---:|---:|
| `S_cat` | 0.225 kmol m⁻³ | **0.225 — unchanged** |
| `S_IC` | 0.01 kmol C m⁻³ | **0.1607** |
| declared pH | 5.0 | **7.0** |
| implied pH | **13.04** | **7.00** |
| visible assay | 0.0214 kg CaCO₃ m⁻³ | **10.75** |
| fed cation charge | 10.75 kg CaCO₃ m⁻³ | **10.75 — unchanged** |

`S_IC` is not fitted: it is the inorganic carbon that closes the stream's charge balance at
the declared pH. **`S_cat` did not move**, so the strong-ion difference reaching the digester
is exactly ruling 3's calibration; what changed is that the counter-ion is bicarbonate
rather than nothing.

**Reconfirmed where ruling 3 put the digester.** On the same twenty-four-seed panel:
alkalinity **5.125** kg CaCO₃ m⁻³ (ruling 3's target ~5.0; it was 5.12) and median pH
**7.262** (target ~7.3; it was 7.293). **24 of 24 runs still sound.** Alkalinity barely
moves because it is set by the strong-ion difference, which was held fixed; the extra
inorganic carbon leaves as CO₂ instead.

**What moved, measured and not compensated for.** Only Plant B: Plant A is fed slurry and
silage, Plant C the two sludges, and `food_waste` is fed by no plant at all.

| | before M2 | after M2 | bound | |
|---|---:|---:|---|---|
| `biogas_mean` ratio | 1.41 | **1.45** | 0.6 – 1.5 | inside, and **closest to a bound of any row** |
| `ch4_fraction_median` | 0.722 | **0.700** | no anchor row | the added carbon leaves as CO₂ |
| `digester_pH_median` | 7.293 | **7.262** | ± 0.4 pH | inside |
| `alkalinity_median` | 5.12 | **5.125** | ± 35 %, calibrated | inside |
| `vfa_median` | 0.7753 | **0.7778** | ratio 0.25 – 4 | inside |
| `fos_tac_median` | 0.1495 | **0.1501** | ratio 0.5 – 2 | inside |
| missingness trigger, pooled | 7.92 % | **7.70 %** | — | anchor's own 7.78 % |
| operator overload, pooled | 0.17 % | **0.19 %** | — | 1 of 24 runs either way |

**All 23 rows stayed inside their declared bounds and no tolerance was touched.** The row to
watch is biogas: 1.45 against an upper bound of 1.5 is the least margin anywhere in this
report, and it is stated here rather than left for someone to notice. The extra gas is CO₂,
not methane — the methane fraction falls 0.722 → 0.700 while total gas rises — so it is the
expected consequence of putting the missing inorganic carbon in, not a new realism problem.

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
| `biogas_mean` | m3/d per digester at the meter's conditions | 3070 | 2111 | 1.45 | ratio in [0.6, 1.5] | pass |
| `digester_pH_median` | pH units | 7.262 | 7.27 | 1.00 | +/- 0.4 pH units | pass |
| `alkalinity_median` | kg CaCO3/m3 | 5.125 | 5.043 | 1.02 | +/- 35 % | calibrated to anchor |
| `vfa_median` | kg/m3 as acetic acid | 0.7778 | 1.178 | 0.66 | ratio in [0.25, 4] | pass |
| `fos_tac_median` | - (VFA as acetic over alkalinity as CaCO3) | 0.1501 | 0.2323 | 0.65 | ratio in [0.5, 2] | pass |

**22 of 22 independent rows are inside their declared tolerance.** A further 1 row was calibrated to the very anchor column it is compared against, and is excluded from that count: agreeing with a column you were fitted to is not evidence.

| Generated statistic with no anchor row | Value |
|---|---:|
| `ch4_fraction_median` | 0.6995 |
| `foaming_day_fraction` | 0 |
| `fos_tac_exceedance_fraction` | 0 |
| `fos_tac_true_vfa_median` | 0.01275 |
| `overload_day_fraction` | 0.06954 |
| `sound_run_fraction` | 1 |
| `vfa_true_median` | 0.06587 |
| `vs_fraction_fog` | 0.01984 |

### The output panel, run by run

| Base seed | Verdict | median pH | mean CH4 | titrimetric FOS (kg/m3) | true VFA (kg/m3) | FOS/TAC | trigger days | FOS/TAC > 0.40 days |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1000 | sound | 7.31 | 0.692 | 0.868 | 0.0855 | 0.150 | 14.57 % | 0.00 % |
| 1001 | sound | 7.25 | 0.706 | 0.761 | 0.0715 | 0.152 | 11.26 % | 0.00 % |
| 1002 | sound | 7.29 | 0.702 | 0.824 | 0.0766 | 0.151 | 11.92 % | 0.00 % |
| 1003 | sound | 7.26 | 0.687 | 0.790 | 0.0805 | 0.152 | 7.28 % | 0.00 % |
| 1004 | sound | 7.25 | 0.702 | 0.716 | 0.0580 | 0.149 | 3.97 % | 0.00 % |
| 1005 | sound | 7.21 | 0.699 | 0.666 | 0.0572 | 0.152 | 3.97 % | 0.00 % |
| 1006 | sound | 7.23 | 0.706 | 0.695 | 0.0539 | 0.150 | 3.31 % | 0.00 % |
| 1007 | sound | 7.23 | 0.680 | 0.746 | 0.0588 | 0.150 | 5.30 % | 0.00 % |
| 1008 | sound | 7.24 | 0.685 | 0.739 | 0.0570 | 0.150 | 2.65 % | 0.00 % |
| 1009 | sound | 7.27 | 0.690 | 0.792 | 0.0621 | 0.149 | 6.62 % | 0.00 % |
| 1010 | sound | 7.29 | 0.698 | 0.808 | 0.0699 | 0.149 | 7.28 % | 0.00 % |
| 1011 | sound | 7.33 | 0.706 | 0.859 | 0.0692 | 0.148 | 7.28 % | 0.00 % |
| 1012 | sound | 7.37 | 0.708 | 0.917 | 0.0721 | 0.147 | 10.60 % | 0.00 % |
| 1013 | sound | 7.22 | 0.679 | 0.728 | 0.0613 | 0.151 | 11.26 % | 0.00 % |
| 1014 | sound | 7.26 | 0.699 | 0.752 | 0.0610 | 0.149 | 5.96 % | 0.00 % |
| 1015 | sound | 7.30 | 0.700 | 0.843 | 0.0817 | 0.150 | 9.93 % | 0.00 % |
| 1016 | sound | 7.26 | 0.684 | 0.782 | 0.0625 | 0.150 | 10.60 % | 0.00 % |
| 1017 | sound | 7.29 | 0.712 | 0.774 | 0.0702 | 0.150 | 5.30 % | 0.00 % |
| 1018 | sound | 7.36 | 0.707 | 0.943 | 0.0967 | 0.150 | 8.61 % | 0.00 % |
| 1019 | sound | 7.21 | 0.706 | 0.668 | 0.0579 | 0.152 | 6.62 % | 0.00 % |
| 1020 | sound | 7.26 | 0.682 | 0.801 | 0.0616 | 0.149 | 4.64 % | 0.00 % |
| 1021 | sound | 7.22 | 0.685 | 0.734 | 0.0536 | 0.149 | 15.89 % | 4.64 % |
| 1022 | sound | 7.22 | 0.706 | 0.691 | 0.0710 | 0.155 | 5.96 % | 0.00 % |
| 1023 | sound | 7.33 | 0.703 | 0.893 | 0.0940 | 0.151 | 3.97 % | 0.00 % |

**24 of 24 runs are working digesters.**

**Two rates, and they are different things** (lead's rulings B and C, 2026-09-09). Across the 24 SOUND runs:

| | what it is | pooled | per-run min | per-run max | runs that fire |
|---|---|---:|---:|---:|---:|
| **conditional-missingness trigger** | hidden true VFA > 2.00x its 30-d trailing median | **7.70 %** | 2.65 % | 15.89 % | 24 of 24 |
| operator-visible overload | titrimetric FOS/TAC > 0.40 | **0.19 %** | 0.00 % | 4.64 % | 1 of 24 |

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
| our `vfa_median` | **true VFA**, 0.066 kg m⁻³ | **titrimetric FOS**, 0.778 kg m⁻³ |
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

A gap of **1.51×** remains: 0.778 against the anchor's 1.178. It is pinned in both
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

Measured across the twenty-four sound runs: it fires on **7.70 % of days pooled**, per-run
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

Measured on clean Level-0 panels of 24 seeds each, at the same 2.00× cut-off everywhere.
**Four rows, because Plant A is two digesters** (ruling 1): its `adapted` and `unadapted`
baselines are not the same plant and must not be averaged into one number.

| Plant | baseline | sound | trigger, pooled | per-run range | runs that fire | VFA ratio p92 | operator FOS/TAC > 0.40 |
|---|---|---|---:|---|---:|---:|---:|
| **B** | — | 24/24 | **7.70 %** | 2.65 – 15.89 % | 24/24 | 1.989 | 0.19 % |
| **C** | — | 24/24 | **9.96 %** | 6.62 – 16.56 % | 24/24 | 2.147 | 0.00 % |
| **A** | `unadapted` | 24/24 | **2.54 %** | 0.66 – 5.96 % | 24/24 | 1.635 | 0.00 % |
| **A** | `adapted` | 24/24 | **0.52 %** | 0.00 – 1.99 % | **11/24** | 1.435 | 0.00 % |
| *anchor* | | | *7.78 %* | | | | *8.25 – 9.18 %* |

**B and C bracket the anchor. Plant A is well below it, and the difference is the finding**
(the lead: differences between plants are to be recorded, not tuned away; there is no
per-plant cut-off and 2.00× stands on all four rows).

**Two things drive it, and the four-row table separates them.**

* **The feed pattern.** B and C take high-strength waste and FOG in **trucked batches**, so
  load and residual VFA are spiky. Plant A is fed steadily on slurry and silage. This is the
  larger effect: even Plant A's spikier baseline sits 3–4× below B and C.
* **The pathway.** Within Plant A, on the *same* feed pattern, the `unadapted`
  (SAO-dominated) baseline fires nearly five times as often as `adapted`. Neither
  explanation alone accounts for the spread. This one is a result about the model rather
  than a property of the panel, so it is written up on its own below.

#### Finding — the methanogenic pathway, not only the feed pattern, drives VFA excursions

**The comparison is controlled.** Plant A's two baselines are the same geometry, the same
feed streams, the same delivery schedule, the same seeds and the same 2.00× cut-off. They
differ in **one declared property**: `K_I_nh3`, and therefore which community carries the
acetate flux — acetoclastic (`adapted`, X_ac 1.129, X_sao 6.9e-05) or syntrophic acetate
oxidation (`unadapted`, X_sao 0.910, X_ac 9.9e-05). Everything that would otherwise explain
a difference in VFA excursions is held fixed by construction.

| Plant A, 24 seeds each | `unadapted` (SAO) | `adapted` (acetoclastic) | ratio |
|---|---:|---:|---:|
| trigger fires, pooled days | **2.54 %** | **0.52 %** | **4.9×** |
| per-run range | 0.66 – 5.96 % | 0.00 – 1.99 % | |
| runs in which it fires at all | **24 / 24** | **11 / 24** | |
| VFA ratio, 92nd percentile | 1.635 | 1.435 | |
| digestate TAN, median (kg N/m³) | 3.605 | 3.695 | 0.98× |

**What it means.** The trigger measures how far true VFA departs from its own recent
median — a *relative* excursion, so it is not reporting that the SAO baseline simply sits at
a higher VFA level. It is reporting that the same load fluctuations move the residual
acetate pool **further, relative to where it has been**, when that pool is drained through
syntrophic oxidation. The mechanism is the turnover rate: SAO is the slower route, so the
same perturbation takes longer to relax, and a 30-day trailing median that would have
absorbed it on the acetoclastic baseline no longer does. The two baselines are also
distinguishable *only* dynamically — the TAN medians differ by 2 % and both digesters are
sound — which is the same reason S6-01 and S6-04 are a pair rather than a duplicate.

**Why it is recorded rather than tuned.** It arrived as an apparent problem: Plant A fires
the flag far below the anchor, so the obvious move is a per-plant cut-off that brings it
into line. The lead's ruling forbids that (differences between plants are recorded, not
tuned away), and holding the cut-off fixed is what made the comparison say something —
a per-plant cut-off would have set both Plant A rows to ~8 % by construction and destroyed
exactly the signal in this table.

**Two consequences.** For the benchmark: a workflow that reads VFA variability as evidence
about the *feed* will misread this plant, and the correct inference — that the pathway is
what changed — is available in the record because the two baselines run the same feed.
For Level 6: it means the S6-01 / S6-04 pair differs in the observable record and not only
in the answer key, so the abstention row is not asking a workflow to distinguish two
identical datasets.

**The consequence, stated so the low numbers are not misread as a defect in the ladder.**
Conditional missingness is close to inert on Plant A's adapted baseline — well under 1 % of
days. **It does not weaken the §7 factorial**: the factorial is Plants B and C only, Plant A
contributes no factorial cells, and `S4-02` has **6 factorial cells on B and C** (three tiers
each) where the trigger fires in every sound run. Plant A additionally runs S4-02 as **one
Tier-A cell** in its separately-reported subset, and that single cell is thin. That is the
whole of the exposure, and it is reported rather than tuned.

### 5.5 The operator-visible threshold is a different thing

FOS/TAC > 0.40 stays as the **operator-facing** overload threshold and no longer drives
conditional missingness (ruling C). It is percentile-matched to the anchor: the anchor's own
titrimetric FOS/TAC has its 92nd percentile at 0.402 (Dig1) and 0.408 (Dig2), n = 861 each,
and the 92nd is the closest percentile to 0.40 of any between the 50th and the 99th.

On the panel it fires on **0.19 % of days pooled**, in 1 of 24 runs — far below the plant's
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

### 6.1 What closing the remaining 1.51x would take

The convention correction took the VFA gap from 17.5x to **1.51x** with nothing fitted (the
FOS/TAC row's residual is 1.55x, the same story one ratio along).
This section is about the residual, because a report that stops at "most of it was a
convention" has not said what the rest is.

**What the residual is.** A titrimetric FOS counts every species titratable between pH 5.0
and pH 4.4. The transfer function accounts for the two the truth model carries — bicarbonate
and the four VFA — and for free protons. It cannot account for what **ADM1 does not have**:
lactate, phenols, humic and fulvic acids, and the other weak organic acids a real digestate
carries. A residual of ~1.5x in a quantity that is 90 % bicarbonate carry-over is a plausible
size for exactly that, and it points at the truth model's component list rather than at any
of its parameters.

**The two ways to close it, and why neither is taken now.**

1. **Fit kappa.** One number would absorb the residual immediately. It is rejected, and the
   reason is structural rather than aesthetic: a fitted kappa makes `fos_tac_median` a row
   **calibrated to the very anchor column it is compared against**, which the lead's ruling
   M1 of 2026-09-04 requires be labelled *calibrated to anchor* and **excluded from the
   anchor-match count**. The benchmark would trade a real 1.51x residual for a row that
   agrees by construction and counts for nothing. kappa stays frozen at 1.0.
2. **Carry the missing species.** A truth-model extension for lactate and the other
   titratable non-VFA acids would close it *through the process* rather than through a
   conversion. That is a new component set, its own kinetics and its own identifiability
   work — the same size as the SAO or precipitation extensions — and it would change what
   Level-6 structural scenarios mean. **Phase 2 at the earliest.**

**So the residual stays, reported and pinned.** `tests/test_g1_anchor.py` bounds it in both
directions, exactly as it bounded the 17.5x failure before it, so it can neither grow nor be
quietly tuned to 1.0. And it is worth keeping in proportion: 1.51x on a titration whose
reading is 90 % carry-over is a far smaller claim than the 17.5x it replaced, and it was
reached without touching a single parameter of the model.

## 7. Provenance

| | |
|---|---|
| Anchor file | `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`, ODC-By 1.0, checksums in `anchor/MANIFEST.json` |
| Comparison code | `anchor/compare_generated.py` |
| Report generator | `python scripts/g1_report.py` |
| Test that recomputes it | `tests/test_g1_anchor.py` |
| Influent draw | seed 7, 730 d, Plant B |
| Output panel | base seeds 1000–1023 (24 runs), 180 d, Plant B, clean Level-0 |
| Related decisions | `docs/decisions.md`, entries of 2026-09-03, 2026-09-04 and 2026-09-09 |

### Which commit the shipped manifests carry

The §7 matrix is regenerated as the **last action before the merge**, so that every
`manifest.json` records the version of the code that actually produced it (lead's ruling,
2026-09-09). One consequence has to be stated rather than left to be discovered:

> **The `git_sha` in every manifest is the final BRANCH-HEAD commit of this pull request,
> not the merge commit.** The merge commit does not exist until after the merge, and
> regenerating after the merge would mean regenerating on `main` — a different tree from the
> one the branch was reviewed on.

The named SHA is an honest record of the code that ran — it is the tree the generator read.
A later session reproducing a cell should check out that SHA directly rather than looking for
it in `main`'s first-parent history. If `main` moves under `sim/`, `configs/` or `scenarios/`
between this regeneration and the merge, the merge commit's tree is no longer the tree these
manifests were produced from, and the matrix has to be regenerated again on `main`.
