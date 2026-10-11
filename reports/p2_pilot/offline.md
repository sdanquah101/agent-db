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

## What the live decider can change here (read from these records)

**Every run is `none` offline.** On three of them the null fails on exactly one channel
(NS), the S1 table **holds** (every coupled channel's after-fit mean is inside), and
only the offline `dq.coupled` reading (`insufficient`, its fallback) blocks `sensor`.

| run | NS channel | S1 table holds | live `coupled_inside` would give |
|---|---|---|---|
| S8-01 B/B r0 | gas_flow (coupled: CH4) | yes | `sensor`: **correct** |
| S2-01 B/B r1 | ph (coupled: alkalinity, VFA, TAN) | yes | `sensor`: **correct** |
| S0-01 B/B r1 | ph (coupled: alkalinity, VFA, TAN) | yes | `sensor`: **wrong** (a clean cell) |

The other three runs:
- S0-01 B/B r0 and S8-01 B/B r1: the null stands.
- S2-01 B/B r0: NM, where no `sensor` can be admitted.

No decision a model makes changes these three.

**The go/no-go cannot stop the pilot on these records.** S0-01 B/B r0's null stands, so
at most one seed of the go/no-go cell can be labelled.

**Comparison with the power run.** Replicate 0 of S2-01 B/B and of S8-01 B/B also
appears in the power run, which had all roles on and predated F-B. Both are `none`
there and here. The configurations differ (three roles here, all roles there), so the
agreement is reported, not used.
