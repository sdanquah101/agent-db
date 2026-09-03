# Gate G1 — anchor comparison report

**Date:** 2026-09-03 · **Gate:** G1 (proposal §11) · **Status:** the gate's stated
criterion is **met**; one **blocking** realism finding is recorded below and needs the
lead's decision before the benchmark is usable on Plant B.

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
| alkalinity | ± 35 % | alkalinity follows design values (`s_ic`, `S_cat`) rather than fits |
| VFA | ratio 0.25–4.0 | deliberately generous: residual VFA is the least identifiable ADM1 output |
| FOS/TAC | ratio 0.5–2.0 | a factor of two, the natural band for a dimensionless ratio |

A test reads the inherited literals out of the test files themselves, so widening one "for
consistency" fails rather than passes quietly.

**One procedural change is recorded rather than hidden.** The output statistics were first
measured on a single clean Level-0 run at that scenario's own seed. That seed turned out to
be one of the Plant B seeds that acidifies (§3), so every output row failed for the wrong
reason. The measurement was widened to a declared twelve-seed panel with each run labelled
sound or soured, and the output rows are now taken across the runs that are working
digesters, with the soured fraction reported beside them. **No tolerance was touched when
that changed.**

## 2. What is compared, and against what

* **Anchor:** the Muscatine WRRF daily file, `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`
  (Schroer & Just 2024, ODC-By 1.0), 1,103 days, 2020-01-01 to 2023-03-31, read through
  `anchor/ingest_muscatine.py`. Plant totals are divided by the two parallel digesters.
* **Generated influent:** a 730-day draw of the influent generator alone, no digester, at
  seed 7 — the same seed and horizon `tests/test_generator.py` uses, so the two
  descriptions are of one realisation.
* **Generated output:** a twelve-run panel of clean Level-0 runs on Plant B (base seeds
  1000–1011, 180 days each) through the whole chain — burn-in, hidden active-volume error,
  stochastic influent, truth model, channels. Statistics are medians across the runs that
  are working digesters.

**Plant C is not separately anchored on the output side, and the report does not pretend
otherwise.** Plant C is Plant B fed only its sludge streams — a counterfactual the real
plant never ran, so there is no measured pH, alkalinity or biogas to compare it against.
Its *feed* streams (primary sludge, thickened WAS) are the same anchored columns as Plant
B's. Plant A is statistics-anchored throughout (§8 of the proposal) and has no time series
at all.

## 3. The finding: Plant B sours on 5 of 12 seeds

**This is the most important number in this report and it is not in the tolerance table,
because nothing thought to declare a tolerance for it.**

Under the frozen feed catalogue, plant configuration and influent generator, a clean
Level-0 run on **Plant B** acidifies within 180 days on **5 of the 12 declared seeds**:
median pH 4.6–5.0 with 0.0–0.31 methane content, against 6.9–7.1 and 0.68–0.70 on the
seven that survive. The gap between the two groups is wide — there is nothing marginal
about the classification. Plants A and C are **12 of 12 sound**.

Across the full generation matrix the same thing shows up as **87 of 114 cells sound**: all
27 soured cells are Plant B, being 9 of its 16 scenarios at 3 tiers each.

**It is not an artefact of the run harness.** It reproduces with the declared geometry (no
hidden volume error), the published Rosen & Jeppsson initial state (no burn-in), no
extension influent and no injected fault: five of twelve small integer seeds crash the same
way. It is not driven by mean load either — seed 1002 is sound at an organic loading rate
of 2.66 kg VS m⁻³ d⁻¹ while seed 1006 sours at 1.77 — but by *runs of consecutive
high-load days*.

**Why the existing tests did not catch it.**
`tests/test_plausibility.py::test_plant_b_survives_the_generator_swings` tests exactly one
seed (11), which is one of the seven that survive. A single-seed plausibility check on a
stochastic generator cannot see a 40 % failure rate. That test is correct and is not
weakened here; it is extended by a panel.

**The most likely cause, for the lead.** `configs/plants/plant_B.yaml` describes the
high-strength waste as "trucked deliveries **blended in a 65,000-gal tank**", and the FOG
as trucked likewise. The influent generator feeds truck arrivals straight to the digester
on the day they arrive; the real plant damps them through a buffer with roughly six days of
hold-up (246 m³ against ~42 m³/d of HSW, plant total). The physical feature is documented
in the frozen plant configuration and is not implemented in the frozen generator, and its
absence is exactly what would turn a run of arrivals into an acid pulse.

**Not fixed here.** Adding a buffer tank changes the frozen influent generator and would
move every generated cell and every anchored delivery statistic. That is the lead's call.
This session instead labels every run (`sim.run.harness.assess_health`, written to
`runs/<id>/truth/geometry.json`), reports the counts, and pins the rate in
`tests/test_g1_anchor.py` so that a fix must come with an update to this record — the test
fails if the rate goes to **zero** as well as if it gets worse.

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
| `biogas_mean` | m3/d per digester at the meter's conditions | 2882 | 2111 | 1.37 | ratio in [0.6, 1.5] | pass |
| `digester_pH_median` | pH units | 7.005 | 7.27 | 0.96 | +/- 0.4 pH units | pass |
| `alkalinity_median` | kg CaCO3/m3 | 2.778 | 5.043 | 0.55 | +/- 35 % | **FAIL** |
| `vfa_median` | kg/m3 as acetic acid | 0.0538 | 1.178 | 0.05 | ratio in [0.25, 4] | **FAIL** |
| `fos_tac_median` | - (VFA as acetic over alkalinity as CaCO3) | 0.02099 | 0.2323 | 0.09 | ratio in [0.5, 2] | **FAIL** |

| Generated statistic with no anchor row | Value |
|---|---:|
| `ch4_fraction_median` | 0.6846 |
| `foaming_day_fraction` | 0.006623 |
| `fos_tac_exceedance_fraction` | 0 |
| `overload_day_fraction` | 0 |
| `sound_run_fraction` | 0.5833 |
| `vs_fraction_fog` | 0.01984 |

### The output panel, run by run

| Base seed | Verdict | median pH | mean CH4 | median VFA (kg/m3) | median FOS/TAC |
|---|---|---:|---:|---:|---:|
| 1000 | sound | 7.11 | 0.685 | 0.069 | 0.019 |
| 1001 | **soured** | 5.04 | 0.314 | 8.674 | 1.686 |
| 1002 | sound | 6.96 | 0.692 | 0.070 | 0.027 |
| 1003 | sound | 7.00 | 0.679 | 0.063 | 0.022 |
| 1004 | **soured** | 4.84 | 0.026 | 9.107 | 2.002 |
| 1005 | sound | 6.92 | 0.691 | 0.052 | 0.023 |
| 1006 | **soured** | 4.89 | 0.021 | 9.375 | 1.921 |
| 1007 | **soured** | 4.60 | 0.000 | 12.901 | 2.612 |
| 1008 | sound | 6.95 | 0.678 | 0.054 | 0.021 |
| 1009 | sound | 7.01 | 0.681 | 0.050 | 0.018 |
| 1010 | **soured** | 4.81 | 0.002 | 10.589 | 2.067 |
| 1011 | sound | 7.03 | 0.696 | 0.051 | 0.017 |

**7 of 12 runs are working digesters.**

<!-- END GENERATED: g1 anchor comparison -->

## 5. Reading the failures

**Every influent row passes.** That is gate G1's literal criterion: delivery medians,
spreads and zero fractions per stream, total feed flow, volatile-solids fractions, the
high-strength-waste COD and the organic loading rate are all inside bounds declared in
advance. The biogas a working digester makes is inside the band too, at 1.37 × the plant's
measured mean.

Three output rows fail, and they are **one finding, not three**: a converged ADM1 carries
far less residual VFA than a real digester, and less alkalinity with it.

* **`vfa_median` 0.054 against 1.178 kg m⁻³ (ratio 0.05).** A converged ADM1 steady state
  holds VFA as a small difference between large production and consumption terms, and it
  settles far lower than a plant does. The plant's titrimetric method also over-reads true
  VFA — but not by a factor of twenty.
* **`alkalinity_median` 2.78 against 5.04 kg CaCO₃ m⁻³ (−45 %).** The simulated digester is
  less buffered than the plant. This is the same story from the other side: alkalinity here
  is bicarbonate plus VFA anions, and both terms are low.
* **`fos_tac_median` 0.021 against 0.232 (ratio 0.09).** The ratio of the two, so it
  inherits both. The PR-#11 review recorded 0.01–0.07 for a healthy simulated digester; the
  panel gives 0.017–0.027, inside that range.

**The consequence, and it matters for a scenario.** The overload flag fires when FOS/TAC
exceeds 0.40. Across the panel it is **bimodal, not uniformly low**:

| | overload flag raised on |
|---|---|
| five of the seven **sound** runs | **0 % of days** |
| the other two sound runs (seeds 1000, 1002) | 8.6 % and 9.3 % — about the plant's own ~8 % |
| all five **soured** runs | 63–100 % of days |

So conditional missingness — the §6.1 property that "instruments are more likely to fail
during foaming and overload", and the whole subject of the Level-4 `informative_missingness`
row (S4-02) — has **nothing to act on in most healthy runs**, roughly the right amount in a
minority of them, and far too much in a crashed one. The foaming flag is similar but never
quite zero (0–1.3 % on sound runs). S4-02 is generated on every cell, and on most healthy
Plant B cells it is currently a near-duplicate of Level 1. This is stated rather than
glossed, and pinned by
`tests/test_g1_anchor.py::test_the_overload_flag_is_all_or_nothing_across_the_panel`.

## 6. What closing the gap would take

None of the following is a threshold change, and none was done here.

1. **Load the digesters harder, or feed them more degradable material.** FOS/TAC rises with
   loading. The PR-#11 review measured Plant B reaching only 0.15 even at 2.5 × the
   declared feed, so this alone does not close a factor of ten and it would break the
   anchored loading rates, which currently pass.
2. **Change the kinetics.** Lower `k_m_ac` (acetate uptake) or a higher `K_S_ac` leaves more
   residual acetate at the same load and lifts both VFA and FOS/TAC without touching the
   feed. This is the most direct lever and the most consequential, because the same
   constants are what the Level-5 parameter scenarios move: it must be a deliberate,
   documented re-anchoring of the truth model, not a nudge.
3. **Raise the feed's alkalinity.** The catalogue's `s_ic` and `S_cat` are design values
   with sources but no fit. Raising them lifts the denominator, which *lowers* FOS/TAC —
   so it works only together with (1) or (2), and it would improve the `alkalinity_median`
   row on its own.
4. **Model the buffer tank** (§3). This is the change most likely to be simply *right*: it
   is a physical feature the anchored plant has and the simulator does not, and it would
   address the souring rate directly. Its effect on FOS/TAC is not obvious in advance —
   smoothing the load could lower peak VFA further — so it must be measured, not assumed.
5. **Accept the gap and declare it.** The benchmark's claims are about attribution,
   calibrated uncertainty and abstention, not about reproducing a plant's VFA distribution.
   If the lead takes this route, the consequence to state in the benchmark card is that
   conditional missingness is inert on a healthy digester and S4-02 does not test what the
   ladder says it tests.

Options 2 and 4 are the two that change the answer; 1 and 3 alone do not.

## 7. Provenance

| | |
|---|---|
| Anchor file | `anchor/raw/iowa-muscatine-wrrf/LABS-raw.csv`, ODC-By 1.0, checksums in `anchor/MANIFEST.json` |
| Comparison code | `anchor/compare_generated.py` |
| Report generator | `python scripts/g1_report.py` |
| Test that recomputes it | `tests/test_g1_anchor.py` |
| Influent draw | seed 7, 730 d, Plant B |
| Output panel | base seeds 1000–1011, 180 d, Plant B, clean Level-0 |
| Related decisions | `docs/decisions.md`, entries of 2026-09-03 |
