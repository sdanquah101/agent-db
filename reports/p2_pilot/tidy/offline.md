# P2 pilot runs, offline (B-2)

The six pilot runs with the offline decider: three-role minimum, every decision at
its code fallback, no model. The power-run column (replicate 0 only) is the
full-role run of `reports/p2_power/` before F-B, shown where the cell overlaps.

| cell | seed | truth | offline outcome | rule | failed channels | power run |
|---|---|---|---|---|---|---|
| S0-01 B/B | 0 | none | none | null_stands | [] | — |
| S0-01 B/B | 1 | none | none | null_failed_unexplained | ['ph'] | — |
| S2-01 B/B | 0 | sensor | none | null_failed_unexplained | ['gas_flow', 'ph'] | none |
| S2-01 B/B | 1 | sensor | none | null_failed_unexplained | ['ph'] | — |
| S8-01 B/B | 0 | sensor | none | null_failed_unexplained | ['gas_flow'] | none |
| S8-01 B/B | 1 | sensor | none | null_stands | [] | — |

## What a live decider can change here (generated from the rows above)

`sensor` can be admitted only where NS failed and the S1 table holds; there the
offline `dq.coupled` reading (`insufficient`) is all that blocks it.

| run | NB | NS | NS channel | coupled channels | S1 table holds | offline reading | live `coupled_inside` would give |
|---|---|---|---|---|---|---|---|
| S0-01 B/B r0 | False | False | — | — | — | — | — |
| S0-01 B/B r1 | False | True | ph | alkalinity, vfa_total, tan | True | insufficient | `sensor`: **wrong** |
| S2-01 B/B r0 | False | False | — | — | — | — | — |
| S2-01 B/B r1 | False | True | ph | alkalinity, vfa_total, tan | True | insufficient | `sensor`: **correct** |
| S8-01 B/B r0 | True | True | gas_flow | ch4_fraction | True | insufficient | `sensor`: **correct** |
| S8-01 B/B r1 | False | False | — | — | — | — | — |

A run whose null stands is `none` whatever a decision says. S0-01 B/B r0: the null stands, so at most 1 seed(s) of the go/no-go cell can be labelled.
