# P2 live pilot, attempt 3: COMPLETE (cost-and-wiring check)

**What this is.** The third run of the lead's pilot: the three-role P2 (data quality, calibration and verification, with coordination in code) on six runs, S0-01, S2-01 and S8-01 B/B, replicates 0 and 1, with the live decider. It checks cost and wiring. **Six runs are not evidence of skill**; nothing here is a scored result.

- **Launched once**, at 2026-10-20T23:12:16Z from `e1d6bcd`, under the approval record of 2026-10-20 (digest `ea14d0ee…`). The store was `/home/user/p2_pilot_store_3`. The last run ended 2026-10-21T04:06Z.
- **In force:**
  - the tidy-up (PR #35, freeze `c58306b4…`, pilot configuration `cf59bcbb…`): `cal.split` and `cal.bound` are not asked, nor is a `dq.trust` shown nothing;
  - D-1: the hold-out bit is shown only beside an admitted `structural`;
  - D-3, kept by the lead on 2026-10-20: one invalid `rejected` entry voids the answer, and the coded fallback is taken;
  - no wall-clock limit for P2.
- **Model and caps:** `gpt-5.6-luna` at effort high; 60 requests, 6 M tokens and USD 0.25 per run.
- **Every run completed, and none abstained.** There was no client or transport error, no gateway refusal, and no cap or budget refusal. Nothing was unfinished, and nothing was rerun.
- **Every model answer was valid on its first attempt.** Code refused nothing, no decision fell back after a failed attempt, and **no D-3 fallback fired**: every `rejected` entry the model gave was one of the five classes with an allowed code.

## Cost and outcome per run

| run | run id | truth | outcome | rule | requests | tokens in / out | USD | wall min |
|---|---|---|---|---|---|---|---|---|
| S0-01 B/B r0 | `run_a7e17e933fc1` | none | **none** | `null_stands` | 2 | 898 / 237 | 0.000464 | 46.0 |
| S0-01 B/B r1 | `run_0da30fa3e9af` | none | **sensor** | `NS+sensor` | 4 | 1639 / 495 | 0.000922 | 49.9 |
| S2-01 B/B r0 | `run_16bbaf47c5a5` | sensor | **none** | `null_failed_unexplained` | 4 | 1787 / 337 | 0.000762 | 57.2 |
| S2-01 B/B r1 | `run_e0f0a1482202` | sensor | **sensor** | `NS+sensor` | 4 | 1681 / 545 | 0.000990 | 46.8 |
| S8-01 B/B r0 | `run_ddbe54fd1259` | sensor | **sensor** | `NS+sensor` | 3 | 1225 / 343 | 0.000657 | 36.8 |
| S8-01 B/B r1 | `run_166870b8012b` | sensor | **none** | `null_stands` | 2 | 887 / 145 | 0.000351 | 55.5 |
| **total** | | | | | 19 | 8117 / 2102 | **0.004146** | 292.2 |

**Reconciled to the token.** Each run's USD is its `llm_calls.jsonl` usage at the frozen prices (USD 0.20 per M input tokens, 1.20 per M output tokens; no cache tokens were billed). That equals the runner's `llm_cost_usd` on every run. The pilot ledger (`spent_usd.json`) holds USD 0.004146, the same as the total.

| role | requests | tokens in / out | USD | simulator evaluations | wall min (registry-measured) |
|---|---|---|---|---|---|
| calibration | 0 | 0 / 0 | 0.000000 | 800 | 167.1 |
| data_quality | 12 | 3859 / 1214 | 0.002229 | 0 | 0.0 |
| identifiability | 0 | 0 / 0 | 0.000000 | 552 | 124.2 |
| influent | 0 | 0 / 0 | 0.000000 | 0 | 0.0 |
| verification | 7 | 4258 / 888 | 0.001917 | 0 | 0.0 |

**Wall min is the runner's `wall_s`: a cost, not compliance with an allowance** (P2 has no wall-clock limit). The role table's wall minutes are the registry's per-call runtimes.

**Against the estimate.** The approval PR expected about 22 requests and about USD 0.008. The pilot made 19 requests for USD 0.004146. Attempt 2 made 36 requests for USD 0.012263; the 12 `cal.split` and `cal.bound` requests it made are not asked now.

## Outcomes against P0, P1, offline and attempt 2

P0 and the frozen P1 (revision 2, `gpt-5.6-luna`, no brief) were run on replicate 0 only (`reports/p0_pilot_scored.csv`, `reports/p1_pilot.csv`). Offline is the six runs re-run at the tidy-up, with every point at its code fallback (`reports/p2_pilot/tidy/`).

| run | truth | P0 | P1 (frozen) | P2 offline | P2 attempt 2 | **P2 attempt 3** |
|---|---|---|---|---|---|---|
| S0-01 B/B r0 | none | **none** ✓ | **sensor** ✗ | **none** ✓ | **none** ✓ | **none** ✓ |
| S0-01 B/B r1 | none | — | — | **none** ✓ | **none** ✓ | **sensor** ✗ |
| S2-01 B/B r0 | sensor | **none** ✗ | **sensor** ✓ | **none** ✗ | **none** ✗ | **none** ✗ |
| S2-01 B/B r1 | sensor | — | — | **none** ✗ | **sensor** ✓ | **sensor** ✓ |
| S8-01 B/B r0 | sensor | **none** ✗ | **sensor** ✓ | **none** ✗ | **none** ✗ | **sensor** ✓ |
| S8-01 B/B r1 | sensor | — | — | **none** ✗ | **none** ✗ | **none** ✗ |
| **correct** | | 1 of 3 | 2 of 3 | 2 of 6 | 3 of 6 | **3 of 6** |

**Read plainly:**
- Attempt 3 has as many correct as attempt 2 (3 of 6), but not on the same runs.
  - It gains S8-01 r0, a gas-scale fault now labelled `sensor`.
  - It loses S0-01 r1, a **false alarm**: a clean run labelled `sensor`.
- At these counts, neither attempt is distinguishable from the other or from offline.

## Where the model changed an outcome, and where it did not

Code computes the null table from the reference fit on the raw record. It is identical to the offline re-run's on all six runs: the model has no input to it.

The only answers whose **applied** value differs from the coded fallback are the three `dq.coupled` readings. Each is `coupled_inside` where the offline reading is `insufficient`, and each lets code admit `sensor`. The differential's `rejected` list differs from code's own on all seven calls, but it is recorded and never applied: `step_verify` applies only the label.

**These three readings are not independent judgement.** Each restates a field code computed and showed the model: the S1 table's `"coupled_inside": true`. With `s1_holds` taken from that field, and a reading of `coupled_inside` or `assay_implicates` admitting `sensor`, attempt 3's outcomes equal a pure-code rule: admit `sensor` when NS fails on one channel and the S1 table holds. The only offline difference is that the coded fallback reads `insufficient`. The model agreed with what code showed it.

| run | truth | null fails on | `dq.coupled` (live / offline) | admitted | the differential's choice | the coded fallback on the same inputs | outcome |
|---|---|---|---|---|---|---|---|
| S0-01 B/B r1 | none | `ph` alone | `coupled_inside` / `insufficient` | `sensor` | `sensor` | `sensor` (`first_in_p0_order`) | `sensor`: **false alarm** |
| S2-01 B/B r1 | sensor | `ph` alone | `coupled_inside` / `insufficient` | `sensor` | `sensor` | `sensor` (`first_in_p0_order`) | `sensor`: correct |
| S8-01 B/B r0 | sensor | `gas_flow` alone | `coupled_inside` / `insufficient` | `sensor` | `sensor` | `sensor` (`first_in_p0_order`) | `sensor`: correct |

- **The differential's applied answer added nothing on any run.** On all seven `verify.differential` calls, its label equals the coded fallback on the same inputs: `first_in_p0_order` of the admitted labels, or `none` when nothing is admitted. Its `rejected` list differs from code's on every call, and is never applied (the decision table shows both).
  - In attempt 2, on S0-01 r1 and S8-01 r0, the model set the admitted `sensor` aside, citing `holdout_passed`.
  - Since D-1 it is not shown the hold-out bit beside `sensor`, and since D-3 `holdout_passed` is allowed with `structural` only.
  - It took the admitted label each time.
- **S0-01 r1 is the known design limitation, now reaching the outcome.** On the clean S0-01 r1, the null fails on `ph` alone and the S1 table holds. A `coupled_inside` reading then makes code admit `sensor`, and nothing downstream declines it. This limitation was stated before attempt 2 and accepted by the lead with D-1. It is not a new defect, but it is now a false alarm in the record.
- **The `dq.trust` answers changed nothing.** All nine requested quarantines equal QC's flagged windows minus any first-HRT spike: the coded fallback, on every one.

## The go/no-go of ruling (b)

`stop = False`. The rule stops the pilot only if **both** seeds of S0-01 B/B label something other than `none`. S0-01 r0's null stands (`none`), so it cannot fire, even though S0-01 r1 labels `sensor`.

## Every decision, against the coded fallback

Status is one of:
- `decided`: the model's answer was accepted, all on the first attempt;
- `not_asked`: the fallback was taken with no request (the tidy-up's A3), with the reason given;
- `refused` and `fallback`: none occurred.

The last column is the coded fallback on the same inputs: what the offline decider takes.

| run | point (sensor) | status | the model's answer | the coded fallback on the same inputs |
|---|---|---|---|---|
| S0-01 B/B r0 | `dq.trust` (gas_flow) | decided (attempt 1) | `{"quarantine": [[44.0, 44.0], [46.0, 46.0]], "reason": "spike_run", "sensor": "gas_flow"}` | quarantine [[44.0, 44.0], [46.0, 46.0]] (QC's flagged windows; the same) |
| S0-01 B/B r0 | `dq.trust` (ph) | not asked (nothing shown) | — | {"quarantine": [], "reason": "spike_run", "sensor": "ph"} (taken) |
| S0-01 B/B r0 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["gas_flow", "ph"], "common_step_day": 15.0} (taken) |
| S0-01 B/B r0 | `verify.differential` | decided (attempt 1) | `{"label": "none", "rejected": []}` | `first_in_p0_order`: `none` (offered: ['none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}, {"label": "structural", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S0-01 B/B r1 | `dq.trust` (gas_flow) | decided (attempt 1) | `{"quarantine": [[59.0, 59.0]], "reason": "spike_run", "sensor": "gas_flow"}` | quarantine [[59.0, 59.0]] (QC's flagged windows; the same) |
| S0-01 B/B r1 | `dq.trust` (ph) | decided (attempt 1) | `{"quarantine": [[149.0, 149.0]], "reason": "spike_run", "sensor": "ph"}` | quarantine [[149.0, 149.0]] (QC's flagged windows; the same) |
| S0-01 B/B r1 | `dq.coupled` (ph) | decided (attempt 1) | `{"code": "coupled_inside", "sensor": "ph"}` | `insufficient`: no sensor finding |
| S0-01 B/B r1 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["gas_flow", "ph"], "common_step_day": 10.0} (taken) |
| S0-01 B/B r1 | `verify.differential` | decided (attempt 1) | `{"label": "sensor", "rejected": [{"code": "signature_absent", "label": "influent"}, {"code": "signature_absent", "label": "state"}, {"code": "signature_absent", "label": "parameter"}, {"code": "signature_absent", "label": "structural"}]}` | `first_in_p0_order`: `sensor` (offered: ['sensor', 'none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S2-01 B/B r0 | `dq.trust` (gas_flow) | decided (attempt 1) | `{"quarantine": [[92.0, 92.0]], "reason": "spike_run", "sensor": "gas_flow"}` | quarantine [[92.0, 92.0]] (QC's flagged windows; the same) |
| S2-01 B/B r0 | `dq.trust` (ph) | decided (attempt 1) | `{"quarantine": [[90.0, 90.0]], "reason": "spike_run", "sensor": "ph"}` | quarantine [[90.0, 90.0]] (QC's flagged windows; the same) |
| S2-01 B/B r0 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["alkalinity", "gas_flow"], "common_step_day": 112.0} (taken) |
| S2-01 B/B r0 | `verify.differential` | decided (attempt 1) | `{"label": "none", "rejected": []}` | `first_in_p0_order`: `none` (offered: ['none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S2-01 B/B r0 | `verify.differential` | decided (attempt 1) | `{"label": "none", "rejected": []}` | `first_in_p0_order`: `none` (offered: ['none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S2-01 B/B r1 | `dq.trust` (ch4_fraction) | decided (attempt 1) | `{"quarantine": [[22.0, 22.0]], "reason": "spike_run", "sensor": "ch4_fraction"}` | quarantine [[22.0, 22.0]] (QC's flagged windows; the same) |
| S2-01 B/B r1 | `dq.trust` (gas_flow) | decided (attempt 1) | `{"quarantine": [[23.0, 23.0], [89.0, 89.0], [109.0, 109.0], [131.0, 131.0]], "reason": "spike_run", "sensor": "gas_flow"}` | quarantine [[23.0, 23.0], [89.0, 89.0], [109.0, 109.0], [131.0, 131.0]] (QC's flagged windows minus the first-HRT spike at day 0; the same) |
| S2-01 B/B r1 | `dq.trust` (ph) | not asked (nothing shown) | — | {"quarantine": [], "reason": "spike_run", "sensor": "ph"} (taken) |
| S2-01 B/B r1 | `dq.coupled` (ph) | decided (attempt 1) | `{"code": "coupled_inside", "sensor": "ph"}` | `insufficient`: no sensor finding |
| S2-01 B/B r1 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["cod_total", "ph", "tan"], "common_step_day": 55.0} (taken) |
| S2-01 B/B r1 | `verify.differential` | decided (attempt 1) | `{"label": "sensor", "rejected": [{"code": "signature_absent", "label": "influent"}, {"code": "signature_absent", "label": "state"}, {"code": "signature_absent", "label": "parameter"}, {"code": "signature_absent", "label": "structural"}]}` | `first_in_p0_order`: `sensor` (offered: ['sensor', 'none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S8-01 B/B r0 | `dq.trust` (gas_flow) | decided (attempt 1) | `{"quarantine": [[68.0, 68.0], [89.0, 89.0]], "reason": "spike_run", "sensor": "gas_flow"}` | quarantine [[68.0, 68.0], [89.0, 89.0]] (QC's flagged windows; the same) |
| S8-01 B/B r0 | `cal.bound` | not asked (answer unused in deliverable 3) | — | {"code": "identifiability_limit"} (taken) |
| S8-01 B/B r0 | `cal.bound` | not asked (answer unused in deliverable 3) | — | {"code": "identifiability_limit"} (taken) |
| S8-01 B/B r0 | `dq.coupled` (gas_flow) | decided (attempt 1) | `{"code": "coupled_inside", "sensor": "gas_flow"}` | `insufficient`: no sensor finding |
| S8-01 B/B r0 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["gas_flow", "ph"], "common_step_day": 10.0} (taken) |
| S8-01 B/B r0 | `verify.differential` | decided (attempt 1) | `{"label": "sensor", "rejected": []}` | `first_in_p0_order`: `sensor` (offered: ['sensor', 'none']; the same label), rejected [{"label": "state", "code": "signature_absent"}, {"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |
| S8-01 B/B r1 | `dq.trust` (alkalinity) | not asked (nothing shown) | — | {"quarantine": [], "reason": "spike_run", "sensor": "alkalinity"} (taken) |
| S8-01 B/B r1 | `dq.trust` (gas_flow) | not asked (nothing shown) | — | {"quarantine": [], "reason": "spike_run", "sensor": "gas_flow"} (taken) |
| S8-01 B/B r1 | `dq.trust` (ph) | decided (attempt 1) | `{"quarantine": [[89.0, 89.0]], "reason": "spike_run", "sensor": "ph"}` | quarantine [[89.0, 89.0]] (QC's flagged windows; the same) |
| S8-01 B/B r1 | `cal.bound` | not asked (answer unused in deliverable 3) | — | {"code": "identifiability_limit"} (taken) |
| S8-01 B/B r1 | `cal.split` | not asked (answer unused in deliverable 3) | — | {"channels": ["gas_flow", "ph"], "common_step_day": 61.0} (taken) |
| S8-01 B/B r1 | `verify.differential` | decided (attempt 1) | `{"label": "none", "rejected": []}` | `first_in_p0_order`: `none` (offered: ['none']; the same label), rejected [{"label": "parameter", "code": "signature_absent"}] (code's; the model's differs, and is never applied) |

**Totals:**
- `dq.trust`: 9 decided and 4 not asked (nothing shown).
- `dq.coupled`: 3 decided.
- `verify.differential`: 7 decided. S2-01 r0 asked it twice: round 1 and the REVISE round.
- `cal.split`: 6 not asked. `cal.bound`: 3 not asked.
- **Note for deliverable 4 (no change now).** Four of the seven differential calls offered only `none`, so their answer was forced (USD 0.000822 in all), and S2-01 r0's REVISE call repeated round 1's request byte for byte. A3's principle would cover them.
- **D-3 fallbacks: none.** Every `rejected` entry was valid, for example `influent`, `state`, `parameter` and `structural`, each `signature_absent`.

## The records

Each run's visible records are copied beside this file, under `run_<id>/`:
- `llm_calls.jsonl`: every request and response, with usage;
- `decisions.jsonl`: every decision record;
- `calls.jsonl`: the registry's tool log.

`cells.json` and `summary.md` are the driver's own report (`python -m scripts.p2_pilot report --attempt attempt3`). The store itself is outside the repository.
