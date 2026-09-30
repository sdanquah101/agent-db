# P2 launch brief — the task-specialised multi-agent workflow (proposal §6.5)

Status: **DRAFT for the lead's approval, 2026-09-30.** Written by the coordinator
(`docs/coordinator.md`) after the lead's rulings of 2026-09-30 ("Freeze P1 and prepare
the P2 launch brief"). Nothing here launches anything: a P2 session starts only when the
lead sends `launch: p2-multi-agent` to the coordinating session (CLAUDE.md, "Who starts a
component session"), and only after PR #26 and PR #27 have merged on the lead's word.

## 1. Where the project stands

- **P0** is built, frozen and characterised: 17/78 exact on the Level 0–5 sweep, a
  one-sided failure (`none` on 43 of 61 faulted cells), no unsupported claims; the
  positive-control ladder (PR #23) rules the harness out as the cause of its misses; the
  distinguishability analysis (PR #25) gives the admissible set of every cell.
- **P1** is frozen on the lead's word of 2026-09-30: revision 2 of the prompts
  (`prompt_sha256 c80a3752…`) with `gpt-5.6-luna`, no expert brief
  (`configs/workflows/p1.yaml`; the freeze commit lands on PR #27). Six development arms
  were run on the ten development cells, one run per cell:

  | arm | concluded | exact | primary = truth | `none` on the 4 clean cells | extra abstentions | cost, USD |
  |---|---|---|---|---|---|---|
  | old prompt / GPT | 10 | 0 | 1 | 0 | 166 | 0.35 |
  | revision 1a / GPT | 10 | 0 | 1 | 0 | 101 | 0.43 |
  | revision 1b / GPT | 8 | 1 | 2 | 0 | 71 | 0.31 |
  | **revision 2 / GPT (frozen P1)** | 10 | 1 | 4 | 0 | 92 | 0.42 |
  | revision 2 + brief / GPT | 10 | 0 | 3 | 0 | 61 | 0.47 |
  | revision 2 / claude-opus-5-5 | 10 | 2 | 2 | 0 | 31 | 9.86 |

  Failed runs are misses. The Claude arm gave one label per cell, nine of them
  `influent`; its two exact hits are the two cells whose truth matched that answer.

- **The finding P2 is launched against.** Across three prompt revisions, a scoring
  statement, a 45-citation domain brief and a second model, no single-agent arm ever
  concluded `none` on a clean cell. P1 always names a cause; P0 has the opposite failure.
  The pattern is stable across everything varied, so it is not a wording problem and not
  a model problem. Nothing in a single-agent loop argues the null case.

## 2. What the proposal says P2 is (§6.5, §6.6, §6.7, §10)

- Seven roles from the review: **data quality, influent, identifiability, calibration,
  experimental design, verification, coordination**, communicating through typed messages
  and the shared §6.6 task state.
- **The coordinator routes; it cannot approve its own output.**
- **The verifier receives the proposed result, the full action log and the frozen
  validation data and returns pass / fail / abstain.** Week 26–30 row: "role separation
  enforced; verifier cannot see proposer's reasoning."
- Common constraints (P1 and P2): no fabricated values, no editing raw data, no
  parameter-bound change without a logged justification, no bypass of a failed QC gate,
  no function outside the registry. Prompts, model version, temperature and retry policy
  frozen before the final run.
- Research question RQ3 and hypothesis H4: multi-agent decomposition adds reliability or
  efficiency beyond a single agent only in scenarios with two or more simultaneous fault
  types; in single-fault scenarios it incurs overhead without gain.
- Ablations (§6.7 E, P1 and P2): remove persistent state, the verifier, the coordinator,
  individual specialist roles, self-correction; report deltas on families A–D.
- Descope clause (§10 risks): if week 26 is missed, P2 is three roles — QC, calibration,
  verifier — and the paper is still viable. Gate G4 (week 30): P1 and P2 run inside
  budget with frozen prompts; fail → publish P0 + P1, P2 becomes Phase 2.

## 3. Design requirements the coordinator adds from the P1 evidence

These are for the lead to approve or strike. Each follows from something P1 showed.

1. **The null case is a role's job, and it is scored first.** The verifier's mandate
   includes the null hypothesis: before any label passes, the verifier must state,
   with evidence from the log and the frozen validation data, whether the record shows any
   pattern beyond the declared instrument noise and the background misfit of the fitted
   model. A label passes only over an explicit `none` case that failed. `none` reached on
   the clean development cells is the first number in every P2 report, before exact
   attribution.
2. **Role separation is enforced by the harness, not the prompt.** Each role runs in its
   own gateway context with its own hashed system prompt and its own tool allow-list taken
   from the one registry. A first cut, to be fixed in the design document:
   data quality → `data_qc`, record inspection; influent → `mass_balance`, the feed
   tools; identifiability → `gsa_morris`, `gsa_sobol`, `profile_likelihood`,
   `fisher_info`; calibration → `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc`;
   experimental design → `voi_assay` and assay requests; verification → `validate`,
   read-only state and log; coordination → no numerical tool at all, routing and the
   stopping actions only. The verifier is given the state, the log and the frozen
   validation data, and nothing the proposing roles wrote in free text.
3. **One run, one budget.** The registry's evaluation meter, the wall-clock allowance, the
   assay units, the token cap (`loop.max_total_tokens`, 6 M per run in P1) and the
   duration guard are per run, summed over roles, not per role. Equal budgets is the
   point of RQ3; a P2 that spends seven P1 budgets has answered a different question.
4. **Typed messages, no free-text summaries in place of results (§6.6).** Message schemas
   in Pydantic beside the task state; every message logged to
   `runs/<id>/workflows/p2/messages.jsonl` with sender, recipient, schema, digest and the
   call indices it cites, beside `llm_calls.jsonl`. The evaluator reads logs only.
5. **Same jail, same gateway, same provider settings.** P2 reuses `tools/llm.py`
   (the gateway, the request checker, the verbatim log, the replay) and the P1 sandbox.
   The frozen P1 model (`gpt-5.6-luna`, effort high, no temperature) is the default for
   every role; a Claude comparison arm is a later, separate decision. The live-client
   hash lesson of PR #26 (hash the text actually sent) applies to every role's prompt.
6. **Ablations are configuration switches from day one.** Verifier off, coordinator off,
   each specialist off, persistent state off, self-correction off: each a flag in
   `configs/workflows/p2.yaml`, each with a test, so that §6.7 E costs runs, not code.
   The three-role minimum (QC, calibration, verifier) is the first thing that runs live.
7. **The P1 prompt rule applies to all seven prompts.** Content from the proposal, the
   benchmark card, the tool documentation and the published vocabularies only; no scenario
   ids, no label frequencies, no per-cell P0 or P1 outcomes. The guard of PR #26 runs on
   every role prompt. The expert brief is not carried into P2.
8. **Same records.** `reports/p2_pilot.csv` with the P1 columns plus `workflow`, `role
   count` and the verifier verdict; summaries carry every role's token and turn counts;
   verifier rejections are counted (family D). Failed runs stay in the denominator and
   are never credited with a placeholder label.
9. **Two runs per cell for P2 development runs.** P1's one-run-per-cell tables left every
   difference inside the noise. P2's development runs use two seeds per cell from the
   start, on the same ten development cells, so its comparison with the frozen P1 and
   with its own ablations has a variance estimate.

## 4. What the P2 session is asked to deliver, in order

1. `docs/p2_design.md`: the roles, the message schemas, the tool allow-lists, the
   routing rules, the verifier protocol including the null case, the budget accounting,
   the ablation switches, the record schema. Reviewed by the coordinator before any live
   call. No live call in this step.
2. The three-role minimum (QC, calibration, verifier) running offline on the scripted and
   recorded doubles, with tests: role separation (a role cannot call a tool outside its
   list, tested with a negative control), the verifier's blindness to free text, the
   budget summed across roles, the message log, the null case in the verifier's output.
3. The three-role minimum live on three development cells (one clean, two faulted), two
   seeds each. Report: `none` on the clean cell, labels on the faulted ones, the verifier's
   verdicts, cost. This is the first go / no-go point.
4. The seven roles, offline then live on the ten development cells, two seeds each. The
   P2 development report against the frozen P1 rows, with the same totals and the
   verifier's counts.
5. The ablations of §6.7 E on the ten cells (verifier off first, then coordinator off,
   then each specialist), two seeds each where budget allows.
6. Then, on the lead's word only: the P2 freeze, and the held-out variants of §7 for both
   P1 and P2.

## 5. Success criteria for the development phase

- `none` reached on at least two of the four clean development cells, with no loss of
  primary-label hits on the faulted cells against the frozen P1 (4/10).
- No unsupported claim, no false kinetic update, no kinetic drift on faulted cells.
- Budget parity shown from the logs: evaluations, wall clock, tokens and assay units per
  run within the P1 caps.
- Every ablation switch tested and at least the verifier-off ablation run.
- The verifier's abstentions have precision: an `abstain` verdict on a cell whose truth
  is representable is a miss, counted.

If the three-role minimum reaches `none` on no clean cell in step 3, the P2 session stops
and reports before building the other four roles: that result would say the null case is
not reachable with these tools and this task framing, which is a benchmark finding, not
a P2 engineering task.

## 6. Cost and time

- P1 revision 2 on GPT: about USD 0.42 and about 14 runner-hours per ten cells at
  three lanes. P2 with seven roles under the same per-run token cap should cost no more
  than two to three times that per cell in practice; two seeds per cell doubles it.
  Order of magnitude for the whole development phase including ablations: tens of USD,
  a few runner-days.
- Wall clock per cell is bounded by the same allowance as P1 (90–150 min by tier);
  message passing adds model turns, not simulator evaluations.
- Elapsed time, from the P1 record (one session, one machine): the design document and
  the offline three-role minimum in the first two or three days, the live minimum by
  day four, the seven roles and the ten-cell run within the second week, ablations in the
  third. The proposal's week 26–30 window is the outer bound.

## 7. Risks and their mitigations

- **The verifier abstains on everything.** Scored: abstention precision is a metric;
  `abstain` on a representable cell is a miss.
- **The coordinator smuggles its own conclusion through the verifier.** The verifier sees
  no free text from any proposing role; the coordinator holds no numerical tool and
  cannot conclude; a test plants a free-text claim and asserts the verifier never
  receives it.
- **Message overhead eats the token budget.** Per-run cap, with the guard's conclude
  notice and grace turns as in P1; the message log makes the spend attributable per role.
- **Seven roles built as seven single agents.** Step 3's go / no-go on the three-role
  minimum, before the other four exist.
- **P2 built twice.** The launch protocol: one launch word, one session, the open-PR
  check first, questions through the coordinator.
- **Machine-instance effects.** The evaluation rate changes with the container instance
  (P1 record, 2026-09-29): P2's comparisons with P1 are on counts and labels, not on
  wall clock across instances.

## 8. What the coordinator needs from the lead

1. Approval of this brief, or edits to §3–§5.
2. The merge word for PR #26, then PR #27 (the Claude arm and the P1 freeze).
3. `launch: p2-multi-agent`, after the merges. The coordinator then starts one P2
   session with this brief, the proposal, `docs/p1_design.md`, `docs/coordinator.md` and
   the standing constraints, and reviews its design document before any live call.
