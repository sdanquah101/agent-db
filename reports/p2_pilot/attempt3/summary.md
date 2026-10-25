# P2 live pilot (attempt3)

| cell | seed | truth | outcome | USD | requests | wall min |
|---|---|---|---|---|---|---|
| S0-01 B/B | 0 | none | none | 0.000464 | 2 | 46.0 |
| S0-01 B/B | 1 | none | sensor | 0.000922 | 4 | 49.9 |
| S2-01 B/B | 0 | sensor | none | 0.000762 | 4 | 57.2 |
| S2-01 B/B | 1 | sensor | sensor | 0.00099 | 4 | 46.8 |
| S8-01 B/B | 0 | sensor | sensor | 0.000657 | 3 | 36.8 |
| S8-01 B/B | 1 | sensor | none | 0.000351 | 2 | 55.5 |

Go/no-go: stop = False; USD 0.004146 on the finished runs; USD 0.004146 spent in all (the pilot's ledger), of which USD 0.0 metered on unfinished runs.

Wall min is the runner's `wall_s`: a cost (P2 has no wall-clock limit, the ruling of 2026-10-13), not compliance with the cell's allowance.
