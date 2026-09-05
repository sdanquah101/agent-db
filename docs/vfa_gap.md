# What closing the VFA / FOS-TAC gap would take

**For the lead, requested 2026-09-03 under ruling 3.** The 0.40 overload threshold does not
move. Calibrating `S_cat`/`S_an` and inert N to the Muscatine alkalinity is approved and is
being done. **No kinetic parameter moves until this list is answered.**

Every number below was measured for this note on Plant B at the declared feed, 200 d to
steady state, through `sim.observation.channels.channel_series` — the same path a scenario
uses. The anchor is the Muscatine daily file, Digester 1 medians.

## 1. Where the gap actually is

| | simulated (Plant B) | anchor (Dig1 median) | ratio |
|---|---|---|---|
| alkalinity, kg CaCO₃/m³ | 2.56 | 5.04 | 0.51 |
| **VFA, kg/m³ as acetic** | **0.0565** | **1.18** | **0.048** |
| FOS/TAC | 0.0221 | 0.23 | 0.096 |
| pH | 6.97 | 7.27 | — |

**The denominator is a factor of two out; the numerator is a factor of twenty-one.** The
gap is almost entirely residual VFA. Plant C, incidentally, already sits at alkalinity 5.35
against the anchor's 5.04 — it is Plant B's co-digestion feed, not the model, that carries
the alkalinity deficit.

## 2. The approved calibration lands cleanly — and widens the FOS/TAC gap

`S_cat` raised by **+0.05 kmol/m³** on Plant B's influent:

| S_cat | alkalinity | VFA | FOS/TAC | pH |
|---|---|---|---|---|
| declared | 2.56 | 0.0565 | 0.0221 | 6.97 |
| +0.02 | 3.55 | 0.0581 | 0.0164 | 7.12 |
| **+0.05** | **5.02** | 0.0623 | **0.0124** | **7.29** |
| +0.10 | 7.47 | 0.0716 | 0.0096 | 7.50 |

+0.05 hits the anchor's alkalinity (5.02 against 5.04) and its pH (7.29 against a median of
7.27, p10 7.04, p90 7.43) almost exactly. Both improve.

**But FOS/TAC gets worse, from 0.0221 to 0.0124** — alkalinity is the denominator, so
fixing it halves the ratio. This is worth stating plainly before the work lands: the
approved calibration moves two anchored quantities onto the anchor and moves the third
further away. That is the right trade — alkalinity and pH are directly measured and
directly comparable, FOS/TAC is a ratio of one of them with a quantity that is not — but it
should be an expected result rather than a surprise in the next report.

## 3. Kinetics cannot close it. This is the finding that matters.

Residual VFA in this model is set by acetoclastic uptake. Scanning `k_m_ac` downward:

| `k_m_ac` × | VFA | FOS/TAC | pH |
|---|---|---|---|
| 1.00 | 0.0565 | 0.0221 | 6.97 |
| 0.50 | 0.1248 | 0.0488 | 6.96 |
| 0.45 | 0.1477 | 0.0578 | 6.95 |
| **0.40** | **0.1831** | 0.0716 | **6.95** |
| **0.35** | **10.08** | 2.62 | **4.60** |
| 0.30 | 10.08 | 2.62 | 4.60 |
| 0.25 | 10.08 | 2.62 | 4.60 |

**The system is bistable and the anchor's 1.18 kg/m³ lies in the gap between the two
branches.** Between ×0.40 and ×0.35 it jumps from 0.18 to 10.08 and the digester sours to
pH 4.6. There is no value of `k_m_ac` that gives a healthy digester carrying the anchor's
residual VFA — the model goes from "too clean" straight to "dead", skipping the target.

Hydrolysis is not the lever either: `k_hyd` ×2 and ×4 leave VFA at 0.0565 to four decimal
places. Whatever hydrolysis releases, methanogenesis consumes; hydrolysis is not
rate-limiting for residual VFA at this loading.

**So "reduce k_m_ac until VFA matches" is not available, and neither is any nearby
single-parameter move.** That is why this note exists rather than a patch.

## 4. What could actually close it, ranked by what it costs

### (a) Report VFA as the titrimetric proxy the plant reports — *recommended*

The anchor's `Dig1-VFA_mgL` is not a chromatographic VFA. It is the FOS half of a
two-point Nordmann/Kapp titration, which systematically over-reads true VFA: it counts
bicarbonate carry-over, lactate, phenols and other titratable species, and is calibrated
against an empirical formula rather than against acetic acid. Over-reads of 2–5× at low
true VFA are routine in the AD literature, and the plant's own FOS/TAC column is computed
from it.

**Cost:** a measurement-model change in `sim/observation/channels.py` and one new sensor
convention — no kinetics, no frozen design value. The `vfa_total` *channel* stays true VFA
(it is hidden truth and should be); the `vfa_total` *sensor* gains a declared titrimetric
transfer function, and `fos_tac` is computed from the titrimetric reading, as at the plant.
**Risk:** the transfer function is itself assumed and would need its own tolerance and its
own `ASSUMED` marker. It cannot be anchored — the plant did not run both methods.

**This is the only option that is honest about *why* the numbers differ** rather than
bending the simulator until they agree.

### (b) Accept the gap and re-declare what FOS/TAC is for

Keep everything; state in the benchmark card that simulated FOS/TAC is a *true-VFA* ratio
on a different scale from a plant's titrimetric one, and that the 0.40 threshold is
therefore a **design threshold on the simulator's own distribution**, not a transferred
plant threshold. The overload flag then needs its own percentile, chosen on simulated runs.

**Cost:** near zero, and it costs the anchoring claim: §6.1's conditional missingness would
fire on a threshold with no external referent. **This is the honest fallback if (a) is
rejected**, and it is much better than quietly leaving a 0.40 threshold that almost never
fires.

### (c) Change the feed so the digester genuinely runs closer to its limit

Higher readily-degradable COD, shorter HRT, or a higher OLR would raise residual VFA
through the process rather than through a conversion. **Cost:** it re-opens the frozen feed
catalogue and the plant configurations, and Plant B is *already* the plant that sours on 5
of 12 seeds — pushing it harder is the opposite of ruling 1. **Not recommended while the
equalisation tank is the fix for souring.**

### (d) Structural: a VFA source the model lacks

Real digesters carry VFA from sources ADM1 omits — sulfate reduction, lactate
fermentation, a sludge-line return. **Cost:** a new extension, its parameters, its
identifiability. Large, and it would change what Level-6 structural scenarios mean.
**Not recommended for Phase 1.**

## 5. What I recommend, and what I need

**(a) plus (b):** give the VFA sensor a declared, `ASSUMED`, tested titrimetric transfer
function, *and* say in the benchmark card that the two conventions differ and which one
each channel carries. Then re-derive the overload threshold on the simulated distribution
and check it against the anchor's percentile rather than its absolute value.

**Decision needed:** whether to introduce a titrimetric convention at all. If yes, the
transfer function's form and its band are the next question and I will bring measurements.
If no, (b) alone, and the benchmark card says the threshold is a design value.

## 6. One interaction worth knowing before ruling 1 lands

The approved `S_cat` calibration raises Plant B's alkalinity from 2.56 to 5.02 — it roughly
doubles the buffer capacity of the plant that sours on 5 of 12 seeds. **It may reduce or
remove the souring on its own**, before the equalisation tank does anything. The two
interventions attack the same failure and should be measured together and separately, or
the tank will be credited with work the buffer did. Relayed to the G1 session.
