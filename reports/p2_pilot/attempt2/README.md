# P2 live pilot, attempt 2: COMPLETE (cost-and-wiring check)

**What this is.** The lead's pilot (option 1 of 2026-10-11): the three-role P2 (data quality, calibration, verification; coordination in code) on six runs, S0-01, S2-01 and S8-01 B/B × replicates 0 and 1, with the live decider. It checks cost and wiring; it is **development evidence, not a scored result**.

- **Launched once** at 2026-10-14T20:48:19Z from `8be6f55`, under the approval record of 2026-10-14 (digest `adf47dee…`), store `/home/user/p2_pilot_store_2`. The last run ended 2026-10-15T03:34:39Z.
- **Rulings in force:** no wall-clock limit for P2 (2026-10-13); the decision-layer fixes (a)–(c) and the JSON inputs (2026-10-14); freeze `fbe88dd0…`.
- **Model and caps:** `gpt-5.6-luna`, effort high; 60 requests, 6 M tokens, USD 0.25 per run.
- **Every run completed, and none abstained.** There was no transport or client error, no request refused by the gateway, and no cap or budget refusal.
- **Code refused seven of the model's proposals, as designed, and three decisions fell back to code:**

  | run | point | proposals refused | the reason | result |
  |---|---|---|---|---|
  | S0-01 B/B r0 | `cal.split` | 2 (`cod_total` + `tan`, day 105, both attempts) | `cod_total` below R4's threshold | **fallback** |
  | S2-01 B/B r1 | `dq.trust` (`gas_flow`) | 2 (both attempts include day 0) | a spike inside the first HRT; logged as `p2.dq.refused` | **fallback** |
  | S2-01 B/B r1 | `cal.split` | 2 (`tan` + `vfa_total`, day 84, both attempts) | a channel below R4's threshold | **fallback** |
  | S8-01 B/B r1 | `cal.split` | 1 (`alkalinity` + `gas_flow` + `ph`, day 62) | a channel below R4's threshold | accepted on attempt 2 (`gas_flow` + `ph`) |

## Cost and outcome per run

| run | run id | truth | outcome | rule | requests | tokens in / out | USD | wall min |
|---|---|---|---|---|---|---|---|---|
| S0-01 B/B r0 | `run_c7cd949b9d5a` | none | **none** | `null_stands` | 5 | 1669 / 842 | 0.001344 | 65.7 |
| S0-01 B/B r1 | `run_6ee91ae7e48e` | none | **none** | `null_failed_unexplained` | 5 | 1759 / 1394 | 0.002025 | 70.2 |
| S2-01 B/B r0 | `run_54eb8545baea` | sensor | **none** | `null_failed_unexplained` | 5 | 1791 / 706 | 0.001205 | 78.7 |
| S2-01 B/B r1 | `run_6750143da2a9` | sensor | **sensor** | `NS+sensor` | 8 | 2730 / 1637 | 0.002510 | 63.9 |
| S8-01 B/B r0 | `run_d3df41271c94` | sensor | **none** | `null_failed_unexplained` | 6 | 1749 / 1068 | 0.001631 | 49.8 |
| S8-01 B/B r1 | `run_f6053e789441` | sensor | **none** | `null_stands` | 7 | 2061 / 2613 | 0.003548 | 75.6 |
| **total** | | | | | 36 | 11759 / 8260 | **0.012263** | 403.9 |

| role | requests | tokens | simulator evaluations | wall min (registry-measured) |
|---|---|---|---|---|
| calibration | 12 | 7765 | 800 | 229.8 |
| data_quality | 17 | 7838 | 0 | 0.0 |
| identifiability | 0 | 0 | 552 | 171.6 |
| influent | 0 | 0 | 0 | 0.0 |
| verification | 7 | 4416 | 0 | 0.0 |

The pilot ledger (`spent_usd.json`) holds USD 0.012263, equal to the total above. **Wall min is the runner's `wall_s`: a cost, not compliance with an allowance** (P2 has no wall-clock limit); the role table's wall minutes are the registry's per-call runtimes.

## Against the offline baseline

The offline decider (every point takes its code fallback) labels all six runs `none` (`reports/p2_pilot/offline.md`; the re-run at `f5aa41f` agreed). Live, **one outcome changed: S2-01 B/B r1 → `sensor`, which is correct** (the cell's seeded fault is a pH sensor drift). The other five are `none` with the baseline's rule.

## The three `dq.coupled` readings (development evidence)

These are the three runs where the null fails on one channel, the S1 table holds, and only the offline `insufficient` reading blocks a `sensor` finding.

| run | truth | reading | admitted by code | the differential's choice | outcome |
|---|---|---|---|---|---|
| S0-01 B/B r1 | none (clean) | `coupled_inside` on `ph` | `sensor` | `none`, setting `sensor` aside as `holdout_passed` | `none`: **correct** |
| S2-01 B/B r1 | sensor (pH drift) | `coupled_inside` on `ph` | `sensor` | `sensor` | `sensor`: **correct** |
| S8-01 B/B r0 | sensor (gas scale) | `coupled_inside` on `gas_flow` | `sensor` | `none`, setting `sensor` aside as `holdout_passed` | `none`: **missed** |

**What these three runs do and do not show.** On all three, the differential saw nearly the same inputs: `sensor` admitted, NS failed on one channel, and the hold-out passed. It answered `none` (`holdout_passed`) on two runs and `sensor` on one. On these three runs the live model and the differential's coded fallback (`first_in_p0_order`) **each get two of three right**: the model is right on S0-01 r1 and S2-01 r1, the fallback on S2-01 r1 and S8-01 r0. **The one changed outcome (S2-01 r1) is therefore not evidence that the differential tells a fault from a clean run.** On near-identical inputs its answers differ, and the evidence does not show what separates them.

- **S0-01 r1, the known design limitation.** As predicted, a live `coupled_inside` reading on the clean S0-01 r1 makes code admit `sensor`: the null fails on `ph` alone and the S1 table holds. That is a known design limitation of the admission rule, stated before the pilot. Here the false alarm did not reach the outcome only because the model's differential declined the admitted label. The differential's coded fallback, on the same inputs, would have labelled it `sensor` (wrong). The run's `none` is the absence of a false alarm, **not a detection**: nothing on the run's inputs marks it as clean.
- **S8-01 r0.** The same mechanism cost a correct label: the differential's coded fallback would have chosen the admitted `sensor` (correct); the model declined it.
- **What the model did, read plainly.** On two of the three runs it set `sensor` aside citing `holdout_passed`. On the third, S2-01 r1, the hold-out also passed, and it chose `sensor`. So it did not consistently treat a passed hold-out as evidence against a sensor fault, and the records do not show what tipped it either way. Design §7 gives the hold-out bit to S6 (`structural`) only, while §2.7 lets the differential cite `holdout_passed` for any label. That inconsistency is with the lead (the coordinator's D-1); nothing is changed here.

## The go/no-go of ruling (b)

**UNABLE TO FIRE.** The rule stops the pilot only if **both** seeds of S0-01 B/B label something other than `none`. S0-01 r0's null stands, so at most one seed could ever label. As it happened, both seeds are `none` (`stop = False`).

## Every decision, against the coded fallback on the same inputs

"Refused" means a code constraint (a schema or code check) refused the model's proposal. After two refusals the point takes its fallback. The last column is the point's coded fallback on the same inputs, which is what the offline decider does. For `dq.trust` that is QC's flagged windows shown, minus any spike inside the first HRT; for `verify.differential` it is `first_in_p0_order`. The two S2-01 r0 differential rows are the verifier's round 1 and its REVISE round 2.

| run | point (sensor) | what the model chose (each attempt) | status | the coded fallback on the same inputs |
|---|---|---|---|---|
| S0-01 B/B r0 | `dq.trust` (gas_flow) | `{"quarantine": [[44.0, 44.0], [46.0, 46.0]], "reason": "spike_run", "sensor": "gas_flow"}` | accepted | quarantine [[44.0, 44.0], [46.0, 46.0]] |
| S0-01 B/B r0 | `dq.trust` (ph) | `{"quarantine": [], "reason": "flatline", "sensor": "ph"}` | accepted | quarantine [] |
| S0-01 B/B r0 | `cal.split` | `{"channels": ["cod_total", "tan"], "common_step_day": 105}` → `{"channels": ["cod_total", "tan"], "common_step_day": 105}` | refused ×2 → fallback | R4's earliest common step: day 15.0, ['gas_flow', 'ph'] |
| S0-01 B/B r0 | `verify.differential` | `{"label": "none", "rejected": []}` | accepted | `first_in_p0_order`: `none` (admitted: none) |
| S0-01 B/B r1 | `dq.trust` (gas_flow) | `{"quarantine": [[59.0, 59.0]], "reason": "spike_run", "sensor": "gas_flow"}` | accepted | quarantine [[59.0, 59.0]] |
| S0-01 B/B r1 | `dq.trust` (ph) | `{"quarantine": [[149, 149]], "reason": "spike_run", "sensor": "ph"}` | accepted | quarantine [[149.0, 149.0]] |
| S0-01 B/B r1 | `dq.coupled` (ph) | `{"code": "coupled_inside", "sensor": "ph"}` | accepted | `insufficient`: no sensor finding |
| S0-01 B/B r1 | `cal.split` | `{"channels": [], "common_step_day": null}` | accepted | R4's earliest common step: day 10.0, ['gas_flow', 'ph'] |
| S0-01 B/B r1 | `verify.differential` | `{"label": "none", "rejected": [{"code": "holdout_passed", "label": "sensor"}]}` | accepted | `first_in_p0_order`: `sensor` (admitted: ['sensor']) |
| S2-01 B/B r0 | `dq.trust` (gas_flow) | `{"quarantine": [[92, 92]], "reason": "spike_run", "sensor": "gas_flow"}` | accepted | quarantine [[92.0, 92.0]] |
| S2-01 B/B r0 | `dq.trust` (ph) | `{"quarantine": [[90, 90]], "reason": "spike_run", "sensor": "ph"}` | accepted | quarantine [[90.0, 90.0]] |
| S2-01 B/B r0 | `cal.split` | `{"channels": [], "common_step_day": null}` | accepted | R4's earliest common step: day 112.0, ['alkalinity', 'gas_flow'] |
| S2-01 B/B r0 | `verify.differential` round 1 | `{"label": "none", "rejected": [{"code": "signature_absent", "label": "s1"}]}` | accepted | `first_in_p0_order`: `none` (admitted: none) |
| S2-01 B/B r0 | `verify.differential` round 2 (REVISE) | `{"label": "none", "rejected": [{"code": "signature_absent", "label": "s1"}]}` | accepted | `first_in_p0_order`: `none` (admitted: none) |
| S2-01 B/B r1 | `dq.trust` (ch4_fraction) | `{"quarantine": [[22.0, 22.0]], "reason": "spike_run", "sensor": "ch4_fraction"}` | accepted | quarantine [[22.0, 22.0]] |
| S2-01 B/B r1 | `dq.trust` (gas_flow) | `{"quarantine": [[0, 0], [23, 23], [89, 89], [109, 109], [131, 131]], "reason": "spike_run", "sensor": "gas_flow"}` → `{"quarantine": [[0, 0], [23, 23], [89, 89], [109, 109], [131, 131]], "reason": "spike_run", "sensor": "gas_flow"}` | refused ×2 → fallback | quarantine [[23.0, 23.0], [89.0, 89.0], [109.0, 109.0], [131.0, 131.0]] (drops [[0.0, 0.0]]: a spike inside the first HRT, day ≤ 17.2) |
| S2-01 B/B r1 | `dq.trust` (ph) | `{"quarantine": [], "reason": "flatline", "sensor": "ph"}` | accepted | quarantine [] |
| S2-01 B/B r1 | `dq.coupled` (ph) | `{"code": "coupled_inside", "sensor": "ph"}` | accepted | `insufficient`: no sensor finding |
| S2-01 B/B r1 | `cal.split` | `{"channels": ["tan", "vfa_total"], "common_step_day": 84}` → `{"channels": ["tan", "vfa_total"], "common_step_day": 84}` | refused ×2 → fallback | R4's earliest common step: day 55.0, ['cod_total', 'ph', 'tan'] |
| S2-01 B/B r1 | `verify.differential` | `{"label": "sensor", "rejected": []}` | accepted | `first_in_p0_order`: `sensor` (admitted: ['sensor']) |
| S8-01 B/B r0 | `dq.trust` (gas_flow) | `{"quarantine": [[68.0, 68.0], [89.0, 89.0]], "reason": "spike_run", "sensor": "gas_flow"}` | accepted | quarantine [[68.0, 68.0], [89.0, 89.0]] |
| S8-01 B/B r0 | `cal.bound` (Y_ac) | `{"code": "identifiability_limit"}` | accepted | `identifiability_limit` |
| S8-01 B/B r0 | `cal.bound` (k_m_h2) | `{"code": "identifiability_limit"}` | accepted | `identifiability_limit` |
| S8-01 B/B r0 | `dq.coupled` (gas_flow) | `{"code": "coupled_inside", "sensor": "gas_flow"}` | accepted | `insufficient`: no sensor finding |
| S8-01 B/B r0 | `cal.split` | `{"channels": [], "common_step_day": null}` | accepted | R4's earliest common step: day 10.0, ['gas_flow', 'ph'] |
| S8-01 B/B r0 | `verify.differential` | `{"label": "none", "rejected": [{"code": "holdout_passed", "label": "sensor"}]}` | accepted | `first_in_p0_order`: `sensor` (admitted: ['sensor']) |
| S8-01 B/B r1 | `dq.trust` (alkalinity) | `{"quarantine": [], "reason": "outage", "sensor": "alkalinity"}` | accepted | quarantine [] |
| S8-01 B/B r1 | `dq.trust` (gas_flow) | `{"quarantine": [], "reason": "flatline", "sensor": "gas_flow"}` | accepted | quarantine [] |
| S8-01 B/B r1 | `dq.trust` (ph) | `{"quarantine": [[89, 89]], "reason": "spike_run", "sensor": "ph"}` | accepted | quarantine [[89.0, 89.0]] |
| S8-01 B/B r1 | `cal.bound` (Y_ac) | `{"code": "identifiability_limit"}` | accepted | `identifiability_limit` |
| S8-01 B/B r1 | `cal.split` | `{"channels": ["alkalinity", "gas_flow", "ph"], "common_step_day": 62}` → `{"channels": ["gas_flow", "ph"], "common_step_day": 62}` | accepted on attempt 2 (attempt 1 refused) | R4's earliest common step: day 61.0, ['gas_flow', 'ph'] |
| S8-01 B/B r1 | `verify.differential` | `{"label": "none", "rejected": []}` | accepted | `first_in_p0_order`: `none` (admitted: none) |

## Findings, reported and not fixed (no code changes in this commit)

1. **`verify.differential`'s `rejected[].label` is a free string.** In S2-01 r0 the model set aside `"s1"`, which is not a label. The verdict uses code's own `rejected` list, so nothing reaches the outcome. Still, an enum of the labels code set aside would close the slot, as fix (a) did for `label`.
2. **The hold-out bit reaches the differential without a stated use**, and the model used it against `sensor` (above). Either the template states that the bit is for `structural` only, or the bit is withheld from the differential when `structural` is not admitted. That is a design question for the lead.
3. **`cal.split` proposals.** The model proposed `cod_total` + `tan` again on S0-01 r0, and `tan` + `vfa_total` on S2-01 r1. Both were refused correctly (a channel below R4's threshold). On S8-01 r1 a three-channel proposal was refused, then a two-channel one accepted, as fix (c) intends.

## Files

For each run, `<run id>/` holds the gateway's `llm_calls.jsonl`, the decision records `decisions.jsonl` and the registry's `calls.jsonl`, copied unchanged by `scripts.p2_pilot report --attempt attempt2`. The same command wrote `cells.json` and `summary.md`. None of these files contains a key or an Authorization header.
