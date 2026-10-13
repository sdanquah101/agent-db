# P2 live pilot, attempt 1: STOPPED

**Status: stopped. The wall-clock budget fired on S0-01 r1, and this attempt is superseded by the lead's ruling of 2026-10-13 ("P2 runs have NO wall-clock limit").**

This directory records the attempt. It is not a pilot result: no cell completed except S0-01 r0, and it is not scored.

## The launch

- **Command:** `python -m scripts.p2_pilot run --store /home/user/p2_pilot_store --live`.
- **When:** started once at 2026-10-13T14:24:47Z.
- **Code and record:** commit `679f327`, with the approval record of 2026-10-11 (digest `27e59f6a…948aa8`).
- **Checks:** the approval and freeze checks passed. The first live requests succeeded (no 401 or 403), and every logged attempt has an empty `error`.
- **Model and caps:** model `gpt-5.6-luna`, effort high, under the committed caps (60 requests, 6M tokens, USD 0.25 per run). No model cap fired: there were no refusals and no `abstain:model_cap`.

## The runs

| run | run id | outcome | live attempts | tokens in / out | USD |
|---|---|---|---|---|---|
| S0-01 B/B r0 | `run_c2509d5aec41` | `none` (`null_stands`), completed | 7: dq.trust ×3, cal.split ×2, verify.differential ×2 | 1915 / 1419 | 0.002086 |
| S0-01 B/B r1 | `run_9ecc445b609b` | `pending`: crashed (see below) | 2: dq.trust ×2 | 525 / 168 | 0.000307 |
| S2-01 B/B r0 | `run_a15fca9f2e9a` | ended by SIGTERM mid-run; no summary | 2: dq.trust ×2 | 535 / 1009 | about 0.0013, not metered |
| S2-01 r1, S8-01 r0, S8-01 r1 | — | not started | 0 | — | — |

The pilot ledger shows **USD 0.002393** over the two runs that wrote a summary. S2-01 r0's two calls are not in the ledger. At the frozen prices (USD 0.20 per million tokens in, 1.20 per million out) they come to about USD 0.0013, computed here rather than metered. That puts the attempt at about **USD 0.0037** in all.

## The budget refusal

The refusal happened on S0-01 B/B r1 (`run_9ecc445b609b/calls.jsonl`):

- **seq 15:** `simulate` returned `budget_exceeded`, with "wall-clock allowance of 90 min spent (91.21 min elapsed)".
- **seq 16:** `declared_background` returned `budget_exceeded`, with the same message.

By then calibration had taken 1970 s and identifiability 3498 s. The run had used 147 of 450 simulator evaluations.

The workflow did not catch `BudgetExceededError` at `step_null` (`workflow.py:1560`), so the jail exited with status 1. The runner recorded `failure_reason: other`, and the outcome was `pending`. That is a defect: a budget refusal should end the run as an abstention. It is fixed in the next commit.

For comparison, S0-01 r0 completed in about 81 min (1391 s calibration, 3491 s identifiability).

## The stop

The relay's rule was to stop when a cap fires. At **2026-10-13T18:28:37Z** the P2 session sent SIGTERM to the pilot's process group:

- S2-01 B/B r0 was 68 min in, after its two `dq.trust` calls.
- The last three runs never started.
- Nothing was retried, and no code, configuration, cap, cell or seed changed.

## Files

For each started run, `<run id>/llm_calls.jsonl` is the gateway's live call log and `<run id>/calls.jsonl` is the registry's tool-call log. These are copied unchanged from the run store. They contain no key and no Authorization header: the proxy attaches the key, and the logs never record headers.
