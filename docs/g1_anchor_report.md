# Gate G1 — anchor comparison report

**Date:** 2026-09-11 (revised after the lead's rulings of 2026-09-03, the remediation
rulings of 2026-09-04, the four rulings, the close-out rulings and the M2 ruling of
2026-09-09, the calcium and liquor rulings of 2026-09-10, and rulings 1–3 and 5 of
2026-09-11: the prefix-stable generator, the per-plant horizons and the cited degradability
centres) · **Gate:** G1 (proposal §11) ·
**Status:** infrastructure criterion
**met**; plant criterion **met** — the Plant B souring that failed the first pass is fixed
and the acceptance condition is satisfied (24 of 24 panel runs sound). **22 of the 22
independent rows are inside their declared tolerance**. The two VFA rows joined them when
the convention on *our* side of the comparison was corrected, with no bound moved and no
kinetic parameter touched (§5.1). **`biogas_mean` is 1.37** against [0.6, 1.5] at the
200-d matrix horizon (pass): it was 1.54 under the prefix-stable generator with the
old feed centres, and the lead's ruling 5 of 2026-09-11 set the hidden degradability centres
of the high-strength waste and the FOG to their cited values (0.84 and 0.92, from 0.95 and
0.98; `docs/f2_horizon_report.md` §16 and §19) as feed-centre corrections — every stream's
centre derived the same way — and answer A set FOG's inert COD equivalent to the lipid-like
2.9, with the band unchanged; the anchor column is total metered
biogas (burner plus boiler), so the basis is right in kind. One row
(`alkalinity_median`) is calibrated to the anchor and is reported without being counted as
a match. S6-01 is no longer inert.

**No kinetic parameter has been changed at any point**, and no plant geometry. Most of what
these rulings moved is not the model at all: where truth is written, how a *sensor* is
realised, which quantity the VFA rows compare against the anchor, and what raises the
missingness flag.

**Feed values did move, on the lead's M2, B1, calcium and liquor rulings, and none of it is
hidden in this report** (§3.3). The catalogue's dissolved calcium was a total-calcium number
on every stream; it is now the calcite-saturated value derived at each stream's own pH, the
inorganic carbon of every buffered stream is the root of that stream's own charge balance,
and dissolved species scale with a delivery's liquor rather than its solids. `S_cat` is
unchanged everywhere, so the strong-ion difference reaching each digester is still exactly
ruling 3's calibration; Plant B's alkalinity and pH land where ruling 3 put them; and the
visible consequence is methane fraction traded for CO₂ — at the calcium round a biogas ratio
of 1.489 against its 1.5 bound, then the least margin anywhere in this report; **since ruling
5 the ratio is 1.373** (§3.3, §4), and the row nearest its bound is now
`total_feed_flow_median` at 1.12 against ± 15 % (§5). Everything that moved is tabulated
in §3.3 and nothing was tuned to compensate.

**M2 is closed.** The assay a workflow reads and the charge the simulator is fed are one
quantity on every catalogue stream and at every delivery, the fed calcium included, and the
guards that assert it were mutation-checked rather than assumed. §3.3 has the history,
including the review that found the first fix wanting.

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
  seeds 1000–1023, 200 days each — the Plant B/C matrix horizon of ruling 3) through the
  whole chain — burn-in, hidden active-volume
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

### 3.3 M2: closed, in three rounds

> **Status: closed on 2026-09-10.** The first fix (below) closed 503× to 1.0× on the
> high-strength waste. An independent review then found three defects in it, listed here as
> they were found; all three are now fixed and their fixes measured. Read the rest of this
> section as the history of how it got there.
>
> * **B1 — the charge side omitted the fed calcium. Fixed, in two steps.** The truth
>   model's own balance (`sim/adm1/physchem_ext.py::_residual`) carries `+ 2.0 * tot.ca`,
>   all three plants enable the precipitation extension and the harness feeds `S_ca`, so
>   `feed_cation_charge` now computes `50 × (S_cat + 2 S_ca − S_an + [NH₄⁺])`. Counted that
>   way, four of seven streams breached the band (primary sludge 2.94×, thickened WAS
>   2.71×, cattle slurry 1.83×, silage 1.69×) — and the first attempt to redistribute them
>   against the catalogue's calcium **broke three things** (biogas 1.532 against its 1.5
>   bound, the B/C control pair inverted, 15 % of HSW records outside the band). The reason
>   was the calcium itself: the catalogue carried **total** calcium (0.4–1.6 g Ca/L) in a
>   field declared as **dissolved** calcium. The lead ruled it be *derived*: the
>   calcite-saturated value at each stream's declared pH, solved jointly with its
>   inorganic carbon. The round below is the result, and both of the lead's tests of it —
>   biogas back in band, the pair restored — passed.
> * **B2 — the invariant held at catalogue TS only. Fixed at the root.** Dissolved species
>   now scale with a delivery's **liquor**, `(1 − ts)/(1 − ts_catalogue)`, rather than
>   sitting fixed while the acetate scaled with solids; the charge ratio is exactly
>   invariant to moisture, and on real assay records the share outside 1.5× went
>   27 → 0.00 % (slurry), 45 → 0.31 % (primary sludge), 15 → **0.88 %** (HSW). The HSW
>   remainder is the per-run Dirichlet draw of its true fractionation, recorded as a
>   finding and not widened.
> * **B3 — the ratio guard was vacuous, and this one is fixed.** An implementation
>   returning 0.0 for both quantities was skipped by the guard's floor on every stream and
>   passed the whole suite; so did `total_alkalinity` returning `feed_cation_charge(...)`.
>   `tests/test_generator.py::test_the_feed_alkalinity_assay_is_pinned_and_the_two_quantities_are_independent`
>   now pins both absolute values and asserts the two read different fields. Both mutants
>   were rebuilt and both now fail.
>
> Also corrected: this section previously said the `s_cat` mutation check was "10 of 10 on
> five fed streams". It is **10 of 12 on six** — FOG is a Plant B feed, and cattle slurry
> at half its cations survives, moving 1.39x to 1.11x, towards the centre of the band.


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

That first round reconfirmed ruling 3's digester (alkalinity 5.125, pH 7.262, 24/24 sound)
and moved biogas 1.41 → 1.45 against its 1.5 bound. The review then found B1–B3 above, and
the round that closed them is the one whose numbers stand:

#### The calcium round (2026-09-10): what the catalogue now says, and why

`s_ca` is **dissolved** calcium, and on every stream it is now derived or declared as an
assumption, never a total-calcium number in a dissolved-calcium field. For the three
calcite-buffered streams it is the calcite-saturated value at the declared pH — `K_sp` from
the truth model's own `pK_sp_calcite` (Plummer & Busenberg 1982; 8.480 at 25 °C, the feed
taken cold), `pK_a2` 10.33, activity coefficient 1 at the feed (**ASSUMED**), supersaturation
**2.5× (ASSUMED; the 2–3× bracket moves primary sludge's value 0.169–0.232 g/L)** — solved
jointly with the inorganic carbon that closes the stream's own charge balance. The mechanism
is Hjorth et al. 2010 (*Agron. Sustain. Dev.* 30:153–180): calcite precipitation in slurry is
calcium-controlled because carbonate is in excess. The lead's sewage-liquor range of
0.05–0.15 g Ca/L is a **plausibility check only**: flow-weighted, Plant B lands at 0.083 and
Plant C at 0.138 g/L, inside it; Plant A at 0.026 g/L, below it, because slurry at pH 7.5
carries so much carbonate that calcite pins its dissolved calcium very low — which is what
the mechanism says it should do.

| stream | pH | `s_cat` | `s_ic` old → new | `s_ca` old → new (g Ca/L) | implied pH old → new | assay | charge | ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `primary_sludge` | 6.0 | 0.05 | 0.04 → **0.1140** | 0.0200 → **0.00503** (0.80 → 0.20) | 12.16 → 6.00 | 2.503 | 2.503 | **1.000** |
| `thickened_was` | 6.8 | 0.05 | 0.04 → **0.0560** | 0.0200 → **0.00068** (0.80 → 0.03) | 12.48 → 6.80 | 2.067 | 2.066 | **1.000** |
| `cattle_slurry` | 7.5 | 0.10 | 0.05 → **0.1249** | 0.0400 → **0.00005** (1.60 → 0.002) | 10.05 → 7.50 | 12.503 | 12.504 | **1.000** |
| `grass_silage` | 4.28 | 0.10 | 0.0 | 0.0200 → **0.00499** (0.80 → 0.20, ASSUMED) | 4.28 → 4.20 | 6.357 | 4.899 | 0.771 |
| `high_strength_waste` | 7.0 | 0.225 | 0.1607 → **0.1638** | 0.0100 → **0.00125** (0.40 → 0.05, ASSUMED low) | 7.00 → 7.00 | 10.874 | 10.872 | **1.000** |
| `food_waste` | 5.1 | 0.152 | 0.0 | 0.0150 → **0.00125** (0.60 → 0.05, ASSUMED low) | — | 7.589 | 7.725 | 1.018 |
| `fog` | 5.0 | 0.005 | 0.0 | 0.0 | — | 0 | 0 | floor |

`s_cat` did not move on any stream, so every strong-ion difference is still ruling 3's.
Silage keeps its accepted 4.28 (the lead's ruling: a lactic-acid-preserved feed is what it
is); with its assumed calcium its balance would close at 4.20, and at 4.28 it now carries
more acetate anion than cations — 0.771×, inside the band, reported rather than moved.

**Both of the lead's tests of the correction passed, and nothing was tuned towards them.**

| | before any M2 work | after the first B1 attempt | after the calcium round (historical) | **after ruling 5 (current, at `7637f7a`)** | bound | |
|---|---:|---:|---:|---:|---|---|
| `biogas_mean` ratio | 1.45 | 1.532 ✗ | 1.489 | **1.373** | 0.6 – 1.5 | inside; was 0.7 % of margin at the calcium round, now 74.6 % of the allowance used (§5) |
| `ch4_fraction_median` | 0.700 | 0.666 | 0.680 | **0.681** | no anchor row | |
| `digester_pH_median` | 7.262 | 7.212 | 7.232 | **7.232** | ± 0.4 pH | inside; ruling 3's ~7.3 |
| `alkalinity_median` | 5.125 | 5.131 | 5.116 | **5.051** | ± 35 %, calibrated | ruling 3's ~5.0 |
| `vfa_median` | 0.7778 | 0.7834 | 0.7804 | **0.7564** | ratio 0.25 – 4 | inside |
| `fos_tac_median` | 0.1501 | 0.1511 | 0.1507 | **0.1508** | ratio 0.5 – 2 | inside |
| Plant B sound runs | 24/24 | 24/24 | 24/24 | **24/24** | acceptance condition | met |
| B/C control pair, pH C > pH B | 7.336 > 7.269 | 7.196 < 7.216 ✗ | 7.252 > 7.238 | **7.252 > 7.244** | `test_plausibility` | restored, holds |

The first three columns are history (the M2 and calcium rounds of 2026-09-09/10); the fourth
is the state at the regenerated head (`docs/f2_horizon_report.md` §25, the 24-seed Plant B
panel at 200 d; the control pair re-measured at the declared median feed on 2026-09-20 as
`tests/test_plausibility.py` measures it). Ruling 5 (the cited HSW and FOG degradability
centres) and answer A (FOG's inert COD equivalent) are what moved `biogas_mean` from 1.489 to
1.373 and alkalinity from 5.116 to 5.051; pH, CH₄ fraction and FOS/TAC are unchanged to the
printed digit.

Per plant at the declared median feed, before → after the calcium round → current: A pH
7.681 → 7.656 → 7.656, CH₄ 0.658 → 0.612 → 0.612; B 7.269 → 7.238 → 7.244, 0.697 → 0.675 →
0.675; C 7.336 → 7.252 → 7.252, 0.687 → 0.619 → 0.619 (ruling 5 touches only the streams
Plant B takes, so A and C do not move). The methane fractions are lower than before any M2
work and higher than after the first attempt, which is the expected shape: the inorganic
carbon the streams were missing now leaves as CO₂, and there is about half as much of it as
the uncorrected calcium demanded.

**All 23 rows are inside their declared bounds and no tolerance was touched.** The rows to
watch, as the lead ruled they be named: on the **anchor side**, at the calcium round it was
`biogas_mean` at 1.489 against its unchanged 0.6–1.5 band, the least margin anywhere in this
report; since ruling 5 `biogas_mean` reads **1.373** (74.6 % of its allowance above 1 used)
and the row nearest its bound is **`total_feed_flow_median` at 1.12 against ± 15 %** (78.9 %
of its allowance used), with `fos_tac_median` at 0.65 in [0.5, 2] third (70.1 %) — re-derived
from the current table (§4; `docs/f2_horizon_report.md` §25 has every row at the regenerated
head), with the margin measured as the fraction of the declared allowance the deviation
consumes; on the **catalogue side, re-checked after the redistribution, `grass_silage` at
0.771×** — every derived stream
sits at 1.000× and `primary_sludge`, which was the closest at 1.470× before B1, is now exactly
on the balance, so silage is the one nearest a band edge, because its accepted pH of 4.28 was
kept while its assumed calcium fell. The four-row missingness table is re-measured in §5.4.

**Plant A's baseline tables were re-measured on this feed** (2026-09-10; the calcium and
liquor changes altered what the plant is fed): adapted X_ac 1.129 → 1.065, unadapted X_sao
0.910 → 0.853, pH down 0.07 and CH₄ down 6 points on both, TAN within 0.01 on both. Both
baselines are still the communities they declare — SAO share 0.000 and 0.998 — so the lead's
stop condition was not met and `K_I_nh3` was not touched. The truth-side plant record
`sim/plants/truth/plant_A.yaml` carries the numbers with the old ones beside them; the
visible contract no longer carries any of them (lead's ruling B5, 2026-09-10).

## 4. The comparison

<!-- BEGIN GENERATED: g1 anchor comparison -->

### Comparison against the declared tolerances

| Statistic | Unit | Generated | Anchor | Ratio | Declared tolerance | Result |
|---|---|---:|---:|---:|---|---|
| `feed_volume_median_primary_sludge` | m3/d per digester | 31.54 | 30.28 | 1.04 | +/- 15 % | pass |
| `feed_volume_log_sigma_primary_sludge` | - (sd of ln amount on delivery days) | 0.4529 | 0.4363 | 1.04 | +/- 30 % | pass |
| `delivery_zero_fraction_primary_sludge` | - (fraction of days with no delivery) | 0 | 0 | - | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_thickened_was` | m3/d per digester | 17.23 | 17.42 | 0.99 | +/- 15 % | pass |
| `feed_volume_log_sigma_thickened_was` | - (sd of ln amount on delivery days) | 0.5156 | 0.5268 | 0.98 | +/- 30 % | pass |
| `delivery_zero_fraction_thickened_was` | - (fraction of days with no delivery) | 0 | 0 | - | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_high_strength_waste` | m3/d per digester | 23.78 | 23.58 | 1.01 | +/- 15 % | pass |
| `feed_volume_log_sigma_high_strength_waste` | - (sd of ln amount on delivery days) | 0.8021 | 0.7786 | 1.03 | +/- 30 % | pass |
| `delivery_zero_fraction_high_strength_waste` | - (fraction of days with no delivery) | 0.1192 | 0.1006 | 1.18 | +/- 0.04 - (fraction of days with no delivery) | pass |
| `feed_volume_median_fog` | m3/d per digester | 33.64 | 33.27 | 1.01 | +/- 15 % | pass |
| `feed_volume_log_sigma_fog` | - (sd of ln amount on delivery days) | 0.7596 | 0.7059 | 1.08 | +/- 30 % | pass |
| `delivery_zero_fraction_fog` | - (fraction of days with no delivery) | 0.3164 | 0.3073 | 1.03 | +/- 0.04 - (fraction of days with no delivery) | pass |
| `total_feed_flow_median` | m3/d per digester | 105.2 | 94.1 | 1.12 | +/- 15 % | pass |
| `vs_fraction_primary_sludge` | kg VS/kg wet | 0.0307 | 0.0295 | 1.04 | +/- 20 % | pass |
| `vs_fraction_thickened_was` | kg VS/kg wet | 0.03191 | 0.0312 | 1.02 | +/- 20 % | pass |
| `vs_fraction_high_strength_waste` | kg VS/kg wet | 0.0693 | 0.06485 | 1.07 | +/- 25 % | pass |
| `hsw_cod_concentration` | kg COD/m3 | 149.2 | 136.8 | 1.09 | +/- 25 % | pass |
| `organic_loading_rate` | kg VS/m3/d | 2.171 | 1.885 | 1.15 | +/- 30 % | pass |
| `biogas_mean` | m3/d per digester at the meter's conditions | 2899 | 2111 | 1.37 | ratio in [0.6, 1.5] | pass |
| `digester_pH_median` | pH units | 7.232 | 7.27 | 0.99 | +/- 0.4 pH units | pass |
| `alkalinity_median` | kg CaCO3/m3 | 5.051 | 5.043 | 1.00 | +/- 35 % | calibrated to anchor |
| `vfa_median` | kg/m3 as acetic acid | 0.7564 | 1.178 | 0.64 | ratio in [0.25, 4] | pass |
| `fos_tac_median` | - (VFA as acetic over alkalinity as CaCO3) | 0.1508 | 0.2323 | 0.65 | ratio in [0.5, 2] | pass |

**22 of 22 independent rows are inside their declared tolerance.** A further 1 row was calibrated to the very anchor column it is compared against, and is excluded from that count: agreeing with a column you were fitted to is not evidence.

| Generated statistic with no anchor row | Value |
|---|---:|
| `ch4_fraction_median` | 0.681 |
| `foaming_day_fraction` | 0.06433 |
| `fos_tac_exceedance_fraction` | 0 |
| `fos_tac_foaming_exceedance_fraction` | 0 |
| `fos_tac_true_vfa_median` | 0.0131 |
| `overload_day_fraction` | 0.07018 |
| `sound_run_fraction` | 1 |
| `vfa_true_median` | 0.06676 |
| `vs_fraction_fog` | 0.01948 |

### The output panel, run by run

| Base seed | Verdict | median pH | mean CH4 | titrimetric FOS (kg/m3) | true VFA (kg/m3) | FOS/TAC | overload days | foaming days | FOS/TAC > 0.40 days | FOS/TAC > 0.30 days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1000 | sound | 7.31 | 0.670 | 0.933 | 0.0887 | 0.150 | 8.19 % | 5.85 % | 0.00 % | 0.00 % |
| 1001 | sound | 7.21 | 0.687 | 0.709 | 0.0636 | 0.152 | 4.68 % | 4.68 % | 0.00 % | 0.00 % |
| 1002 | sound | 7.25 | 0.685 | 0.795 | 0.0746 | 0.152 | 9.36 % | 8.77 % | 0.00 % | 0.00 % |
| 1003 | sound | 7.21 | 0.644 | 0.801 | 0.0692 | 0.152 | 7.02 % | 6.43 % | 0.00 % | 0.00 % |
| 1004 | sound | 7.23 | 0.686 | 0.734 | 0.0642 | 0.151 | 6.43 % | 5.85 % | 0.00 % | 0.00 % |
| 1005 | sound | 7.22 | 0.678 | 0.738 | 0.0633 | 0.151 | 7.02 % | 10.53 % | 0.00 % | 0.00 % |
| 1006 | sound | 7.20 | 0.687 | 0.679 | 0.0589 | 0.152 | 4.09 % | 2.92 % | 0.00 % | 0.00 % |
| 1007 | sound | 7.34 | 0.684 | 0.945 | 0.0811 | 0.148 | 8.19 % | 6.43 % | 0.00 % | 0.00 % |
| 1008 | sound | 7.21 | 0.665 | 0.734 | 0.0635 | 0.152 | 19.30 % | 13.45 % | 0.00 % | 0.00 % |
| 1009 | sound | 7.22 | 0.666 | 0.744 | 0.0609 | 0.151 | 10.53 % | 9.94 % | 0.00 % | 0.00 % |
| 1010 | sound | 7.24 | 0.683 | 0.755 | 0.0654 | 0.151 | 2.92 % | 2.34 % | 0.00 % | 0.00 % |
| 1011 | sound | 7.30 | 0.682 | 0.878 | 0.0773 | 0.150 | 5.85 % | 4.68 % | 0.00 % | 0.00 % |
| 1012 | sound | 7.30 | 0.685 | 0.846 | 0.0703 | 0.149 | 5.85 % | 6.43 % | 0.00 % | 0.00 % |
| 1013 | sound | 7.23 | 0.676 | 0.755 | 0.0681 | 0.151 | 9.94 % | 8.77 % | 0.00 % | 0.00 % |
| 1014 | sound | 7.25 | 0.678 | 0.758 | 0.0609 | 0.149 | 9.94 % | 9.94 % | 0.00 % | 0.00 % |
| 1015 | sound | 7.23 | 0.692 | 0.729 | 0.0772 | 0.153 | 7.02 % | 4.09 % | 0.00 % | 0.00 % |
| 1016 | sound | 7.23 | 0.663 | 0.786 | 0.0638 | 0.151 | 4.09 % | 3.51 % | 0.00 % | 0.00 % |
| 1017 | sound | 7.28 | 0.692 | 0.799 | 0.0683 | 0.150 | 6.43 % | 4.09 % | 0.00 % | 0.00 % |
| 1018 | sound | 7.29 | 0.686 | 0.846 | 0.0859 | 0.152 | 10.53 % | 8.19 % | 0.00 % | 0.00 % |
| 1019 | sound | 7.23 | 0.680 | 0.745 | 0.0619 | 0.151 | 7.60 % | 6.43 % | 0.00 % | 0.00 % |
| 1020 | sound | 7.23 | 0.662 | 0.787 | 0.0606 | 0.150 | 7.02 % | 6.43 % | 0.00 % | 0.00 % |
| 1021 | sound | 7.21 | 0.664 | 0.739 | 0.0586 | 0.151 | 8.19 % | 11.11 % | 0.00 % | 0.00 % |
| 1022 | sound | 7.19 | 0.667 | 0.744 | 0.0814 | 0.156 | 3.51 % | 2.34 % | 0.00 % | 0.00 % |
| 1023 | sound | 7.32 | 0.683 | 0.910 | 0.0907 | 0.151 | 7.60 % | 5.26 % | 0.00 % | 0.00 % |

**24 of 24 runs are working digesters.**

**Four rates, and they are two different kinds of thing** (lead's rulings B and C of 2026-09-09 and B3 of 2026-09-10). Across the 24 SOUND runs:

| | what it is | pooled | per-run min | per-run max | runs that fire |
|---|---|---:|---:|---:|---:|
| **overload trigger** (conditional missingness) | hidden true VFA > 2.00x its 30-d trailing median | **7.55 %** | 2.92 % | 19.30 % | 24 of 24 |
| **foaming trigger** (conditional missingness) | hidden gas > 1.80x its 30-d trailing median AND true VFA > its 30-d trailing median | **6.60 %** | 2.34 % | 13.45 % | 24 of 24 |
| operator-visible overload | titrimetric FOS/TAC > 0.40 | **0.00 %** | 0.00 % | 0.00 % | 0 of 24 |
| operator-visible foaming (unwired) | titrimetric FOS/TAC > 0.30 | **0.00 %** | 0.00 % | 0.00 % | 0 of 24 |

The anchor's own FOS/TAC exceedance is 8.25 % (Dig1) and 9.18 % (Dig2), and its 92nd percentile is what the 0.40 threshold is matched to. The triggers are not compared with that number: they fire on the hidden state, which no plant column reports. The operator-visible foaming threshold is wired to nothing: the titrimetric ratio has a bicarbonate floor near 0.13-0.14, so 0.30 is out of a working digester's reach under this measurement model (a finding, recorded in section 5.5 and the benchmark card, not a threshold to lower).

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

| Plant | baseline | horizon | sound | trigger, pooled | per-run range | runs that fire | VFA ratio p92 | operator FOS/TAC > 0.40 |
|---|---|---:|---|---:|---|---:|---:|---:|
| **B** | — | 200 d | 24/24 | **7.55 %** | 2.92 – 19.30 % | 24/24 | — | 0.00 % |
| **C** | — | 200 d | 24/24 | **9.82 %** | 6.43 – 14.04 % | 24/24 | — | 0.00 % |
| **A** | `unadapted` | 365 d | 24/24 | **1.02 %** | 0.00 – 3.27 % | **21/24** | — | 0.00 % |
| **A** | `adapted` | 365 d | 24/24 | **0.22 %** | 0.00 – 1.19 % | **11/24** | — | 0.00 % |
| *anchor* | | | | *7.78 %* | | | | *8.25 – 9.18 %* |

Measured on 2026-09-11 at the matrix horizons of the lead's ruling 3 (200 d on B and C, a
year on Plant A) under the prefix-stable generator of ruling 1, and — for B and C, the two
plants that take the corrected streams — re-measured after the lead's ruling 5 set the HSW
and FOG degradability centres to their cited values and the lead's answer A set FOG's inert
COD equivalent to the lipid-like 2.9 (before ruling 5: B 7.12 %, 2.34 – 16.37 %, 24/24;
C 9.82 %, 6.43 – 14.04 %, 24/24; at the ruled centres with the old equivalent 1.42, B
7.38 %; Plant C's feed has neither stream, and its rows are unchanged to the last digit);
the VFA-ratio p92 column
was not re-measured and is left blank rather than carried over from the earlier feed. The
180-d table of 2026-09-10, after the calcium and liquor rulings (§3.3) — B 7.67 %
(2.65 – 16.56 %, 24/24), C 9.22 % (6.62 – 16.56 %, 24/24), A-unadapted 1.49 % (0.00 –
3.97 %, 21/24), A-adapted 0.28 % (0.00 – 1.32 %, 7/24); operator FOS/TAC > 0.40 on B
0.17 % — and the earlier one — B 7.92 %, C 9.96 %, A-unadapted 2.54 %, A-adapted 0.52 % —
are in the decisions log (2026-09-10 and 2026-09-09). The B and C rates moved down by about
half a point with the generator layout, not with the horizon: at 190, 200 and 210 d the
Plant B rate is 7.04, 7.12 and 6.86 % (`docs/f2_horizon_report.md` §15).

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
differ in **one property**: the community's inhibition constant (truth-side since ruling
B5), and therefore which pathway carries the acetate flux — acetoclastic (`adapted`, X_ac
1.065, X_sao 6.9e-05) or syntrophic acetate oxidation (`unadapted`, X_sao 0.853, X_ac
0.0019), as re-measured on the current feed on 2026-09-10 (§3.3). Everything that would
otherwise explain a difference in VFA excursions is held fixed by construction.

| Plant A, 24 seeds each, 365 d | `unadapted` (SAO) | `adapted` (acetoclastic) | ratio |
|---|---:|---:|---:|
| trigger fires, pooled days | **1.02 %** | **0.22 %** | **4.6×** |
| per-run range | 0.00 – 3.27 % | 0.00 – 1.19 % | |
| runs in which it fires at all | **21 / 24** | **11 / 24** | |
| digestate TAN, median (kg N/m³) | 3.614 | 3.703 | 0.98× |

Both rows fell when cattle slurry's inorganic carbon was re-paired to its cations and its
calcium collapsed to the calcite-saturated value (2026-09-10) — the buffer got deeper, so
excursions relative to the trailing median got rarer on both baselines — and the ratio
between them **widened** from 4.9× to 5.3× (1.49 % against 0.28 % on the 180-d panels,
21/24 against 7/24 runs). Re-measured on 2026-09-11 at Plant A's 365-d matrix horizon
under the prefix-stable generator (rulings 1 and 3), both rows fell again — 1.02 % against
0.22 % — and the ratio is 4.6×, with the SAO baseline still firing in three times as many
runs. The finding survived two changes that moved both of its numbers — a change to the
feed and a change to the realisation and horizon — which is what a finding about the
pathway rather than the feed should do.

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

#### The foaming trigger, on the same four rows

**Foaming had never fired in any cell** (whole-branch review, 2026-09-10, finding B3): the
flag compared the titrimetric FOS/TAC with 0.30, and that ratio has a structural floor near
0.13–0.14 — the bicarbonate carry-over of the titration (§5.3) — and sits at 0.14–0.18 in
every sound run, so 0.30 was unreachable and the foaming stress multiplier was dead
everywhere. The lead's ruling B3 made foaming a **hidden-state trigger** like overload: the
gas rate above **1.80×** its 30-day trailing median **and** true VFA above its own 30-day
trailing median, both windows over the previous samples with the current one excluded. A
digester that is gassing hard while its acids are rising. Measured on the same four panels,
**recorded and not tuned**:

| Plant | baseline | horizon | sound | foaming trigger, pooled | per-run range | runs that fire | operator FOS/TAC > 0.30 (unwired) |
|---|---|---:|---|---:|---|---:|---:|
| **B** | — | 200 d | 24/24 | **6.60 %** | 2.34 – 13.45 % | 24/24 | 0.00 % |
| **C** | — | 200 d | 24/24 | **8.50 %** | 3.51 – 15.20 % | 24/24 | 0.00 % |
| **A** | `unadapted` | 365 d | 24/24 | **0.09 %** | 0.00 – 0.60 % | 5/24 | 0.00 % |
| **A** | `adapted` | 365 d | 24/24 | **0.20 %** | 0.00 – 1.19 % | 10/24 | 0.00 % |

Measured on 2026-09-11 at the matrix horizons, on the same panels as the overload table
(B re-measured after ruling 5 and answer A, as above; before ruling 5 6.63 %, 1.75 –
14.04 %, 24/24; at the old FOG equivalent 6.34 %).
The 180-d table of 2026-09-10 — B 7.20 % (1.32 – 16.56 %, 24/24), C 7.67 % (3.97 –
11.92 %, 24/24), A-unadapted 0.14 % (0.00 – 0.66 %, 5/24), A-adapted 0.25 % (0.00 –
1.32 %, 7/24); operator FOS/TAC > 0.30 on B 0.25 % — was measured on the same panels as
that day's overload table, whose rows (B 7.67 %, C 9.22 %, A-unadapted 1.49 %, A-adapted
0.28 %) it reproduced to the last digit: the check that nothing in the B1, B3 and B5
changes moved the simulator, since the run-id scheme, the foaming rule and the location of
the plant record are not inputs to the truth model.

**Reading the foaming rows.** On B and C the foaming trigger fires at about the overload rate (6.60 % and 8.50 % against 7.55 % and 9.82 %), in every sound run, with per-run ranges of the same width: on a batch-fed plant a top-decile gas day is usually a day the acids are also up, because both follow the arrival of a large delivery. They are not the same days — the flags are computed separately, and the missingness model compounds the multipliers when they coincide — but they are the same kind of event. On Plant A both rows are far below B and C, as overload is, and the pathway ordering **reverses**: the `unadapted` (SAO) baseline overloads 4.6× more often than `adapted` but foams *less* often (0.09 % against 0.20 %, 5 against 10 firing runs of 24; on the 180-d panels 0.14 % against 0.25 %, 5 against 7). The foaming trigger needs a gas surge, and gas surges on Plant A follow the weekday silage feeding, which is the same on both baselines; what the SAO baseline adds is VFA excursions that relax slowly *after* the load rather than gas that rises with it, so its extra overload days are not gas-surge days. Two panels of 24 runs at rates below 0.3 % are thin evidence and this is recorded as an observation, not a finding. Nothing was tuned: 1.80× and 1.00× are the lead's figures as written.

**The operator-visible foaming threshold is structurally dead, and that is a
measurement-model finding, not a threshold to lower.** FOS/TAC > 0.30 stays declared and
reported (the last column above: at the matrix horizons it fires on no day at all on any of the four rows; on the 180-d panel of 2026-09-10 it fired on 0.25 % of Plant B days, in 1 of 24 runs) and is wired to nothing. A
two-point Nordmann/Kapp titration counts everything titratable between pH 5.0 and 4.4, and
in a digester with 5 kg CaCO₃/m³ of alkalinity that is mostly bicarbonate: the "FOS" it
reports is ~0.7 kg/m³ before any volatile acid is present, so the ratio has a floor of about
0.13–0.14 that no working digester goes below and, on this feed, none goes far above. An
operator watching that ratio for foaming would see nothing until the digester was already
in trouble — which is a statement about the instrument, and the reason the plant's own
trigger reads the hidden state. It is recorded in the benchmark card (§5.4).

### 5.5 The operator-visible thresholds are a different thing

FOS/TAC > 0.40 stays as the **operator-facing** overload threshold and no longer drives
conditional missingness (ruling C). It is percentile-matched to the anchor: the anchor's own
titrimetric FOS/TAC has its 92nd percentile at 0.402 (Dig1) and 0.408 (Dig2), n = 861 each,
and the 92nd is the closest percentile to 0.40 of any between the 50th and the 99th.

On the panel it fires on **0.17 % of days pooled**, in 1/24 runs — far below
the plant's 8.25 %, because the simulated titrimetric distribution still sits ~1.5× below
the plant's (§5.2). The threshold is not moved to compensate. FOS/TAC > 0.30, the
operator-facing foaming threshold, is the same kind of thing and is treated the same way:
declared, reported, never a trigger (§5.4).

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
FOS/TAC row's residual is 1.54x, the same story one ratio along).
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
| Output panel | base seeds 1000–1023 (24 runs), 200 d (the Plant B/C matrix horizon), Plant B, clean Level-0 |
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
