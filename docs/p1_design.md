# P1 — the single constrained agent (milestone 7, proposal §6.5)

Status: **DEVELOPMENT, 2026-09-25.** The P1 session builds this on
`claude/p1-single-agent`, launched by the lead ("launch: p1-single-agent") through the
coordinator. The prompts and `configs/workflows/p1.yaml` are **not frozen and not hashed**.
They are frozen, and their hash committed, on the lead's word, before the held-out
variants of §7 are generated (the P1 prompt rule of 2026-09-24). Until then P1 runs on
development (pilot) cells only. It is not scored on the Level 0–5 sweep and not compared
with P0 in any table; that waits for PRs #23 and #25 and the lead's word.

## 1. What P1 is

§6.5: "One LLM-based agent with access to the same registry, a structured task state,
and the same stopping actions. It chooses which tool to call next, with what arguments,
and when to conclude or abstain. It may request assays from the budget." It shares
everything with P0 except the decisions:

| | P0 | P1 |
|---|---|---|
| Registry, tools, budgets (evaluations, wall clock, assay units) | the run's | the same, enforced in the same registry |
| Where it runs | the jail (`tools.sandbox.launch`) | the same jail, the same stub, the same checks |
| What it sees | the visible record, the declared noise and geometry, the vocabularies | the same, plus the assays' public price list |
| Who decides the next call | a fixed script | the model |
| Output | the §6.6 task state, `report.json` | the same state schema, `report.json`, and the model log |

The two state-space filters (`filter_enkf`, `filter_mhe`) take a registered state-space
model, and a run registers none. Neither P0 nor P1 can use them, so P1's tool list leaves
them out (tested).

## 2. Where the model is called: the gateway (`tools/llm.py`)

The agent runs in the jail and never holds a key. It sends each model turn over the
registry socket as a new op, `llm`, with only `system`, `messages` and `tools`. On the
privileged side, a `ModelGateway` does five things:

- **sends** the request with the frozen settings of the `model` block: the model id, the
  response cap, the effort and prompt caching. A request carrying anything else is refused.
- **refuses** a turn once the run has used its model turns or its tokens (`loop.max_turns`,
  `loop.max_total_tokens`), the way the registry refuses a tool call over budget.
- **retries** per the declared policy: 429, ≥ 500, connection errors and timeouts only,
  with doubling backoff. The SDK's own retries are off, so every attempt passes the log.
- **refuses any form an agent may not send** (`check_agent_request`; the review of
  PR #26, 5). It accepts only custom tools (a name, a description and an input schema;
  no `type`, so no server tool that runs code or reaches the network); only user and
  assistant turns made of text, tool_use, tool_result and thinking blocks; and exactly
  the committed system prompt (its sha256, handed over by the runner).
- **logs every attempt verbatim** to `runs/<id>/workflows/p1/llm_calls.jsonl` (§13). The
  line holds the request as sent (its messages from the first one the previous request did
  not hold, the fixed parts whenever they change), the response as received or the error,
  the request's sha256, and its replay digest (the same with every wall-clock reading
  masked). `rebuild_requests` reassembles every request exactly (tested).
  The workflow cannot write this file (a reserved name in `OutputSink`, tested).
- **meters** the tokens every response reports. The runner writes them into `summary.json`:
  `tokens_used` (input + cache writes + cache reads + output), the breakdown, the turns,
  the attempts and the cost at the declared prices. The meter is the privileged side's
  count, like the registry's evaluation meter, never the agent's self-report.

**Clients.** The live client is chosen by the `model` block's `provider`.
- `OpenAIResponsesClient` (the provider chosen by the lead on 2026-09-25) calls OpenAI's
  Responses API through the `openai` SDK. It translates the agent's Messages-shaped request
  and the reply both ways (`to_responses_request`, `from_responses_output`, tested), so the
  agent, the gateway checks, the log and the replay are the same for every provider. The
  model's reasoning items are carried across turns encrypted (`store=False`), inside a
  thinking block's `signature`. The raw provider response is logged verbatim beside the
  translated one. The GPT-5.6 models refuse function tools with reasoning on Chat
  Completions, hence the Responses API.
- `AnthropicClient` calls the Messages API through the `anthropic` SDK.

Each SDK is imported only when its client is built. Two deterministic doubles run the whole loop in
CI with no network and no key:
- `ScriptedClient(policy)` answers with a pure function of the request (the test policies
  are in `tests/p1_support.py`);
- `RecordedClient(transcript)` replays a logged run turn by turn and refuses a request
  whose **replay digest** differs from the recorded one. The digest masks the wall-clock
  readings the agent is shown, which no replay can reproduce, and nothing else. A harness
  notice that the clock triggered in one run and not the other still differs, and the
  replay is refused. **A limit, stated:** a run whose clock crossed the conclude-notice
  threshold at a different turn from its replay cannot be replayed. The transcript is read once and never written. A replay writes to
  its own output directory, and a gateway asked to log over the transcript it replays
  refuses to start. `python -m tools.runner --workflow p1 --run <id> --replay
  <llm_calls.jsonl>` re-runs a cell into `runs/<id>/workflows/p1_replay/` (tested with a
  double that sleeps).

## 3. The harness (`workflows/p1_single_agent/agent.py`)

The model decides; the harness does what a JSON argument cannot.

- **Data plumbing.** A sensor name becomes the `ObservedSeries` a tool takes: the sample
  times, the values with quarantines applied, and weights from the **declared** noise
  (`sd = sqrt((cv·|v|)² + sd_abs²)`, floored), which is P0's convention. A call index
  becomes the prediction, the fit or the posterior that call returned. The feed loads are
  fetched once, when a tool first needs them, and that call is logged like any other.
- **Windows.** Every tool that takes the record works on the calibration window
  `[0, 0.75 T]`, and so does everything the agent is shown: the task prompt's record, the
  notes, `data_qc` with its event windows, `mass_balance`, record inspection, fits,
  screening, Fisher, profiles, the sampler, residuals and assays (the coordinator's
  ruling of 2026-09-25). **The hold-out is not the agent's to read, edit or score:**
  - `validate` is not among its tools;
  - `conclude` names the final prediction or an ensemble, and after the conclusion the
    harness validates it **once** on the frozen hold-out `[0.75 T, T]` (the evaluator's
    own, tested equal), as recorded;
  - the score goes into the state only;
  - a quarantine window may not reach into the hold-out.

  P0 also validates once, so neither workflow can choose a prediction by its hold-out
  score. P0's QC and balance do read the whole record, so P1 sees less than P0: a known
  asymmetry that favours P0 (rule 5).
- **Seeds** (rule 4). A stochastic call's seed is `seeds.base` plus its registry call index,
  so the same sequence of calls gives the same seeds.
- **Readable results.** An array longer than `loop.array_preview` is summarised (n, missing,
  min, max, mean, first and last values), and floats are rounded to five significant
  digits. Every result carries its `call_index` and the budget left.
- **The residual summary.** `residual_diag`'s result adds `bias_z`, `rmse_z`, `step_z`,
  `step_day`, `early_bias_z` and `late_bias_z`, computed by P0's arithmetic on the
  standardised residual. Under ruling D3 these numbers rest on that `residual_diag` call and
  the `simulate` it was taken against.
- **Workspace actions.** `set_sensor_status`, `record_evidence` and `conclude` fill the task
  state. The harness refuses what the common constraints of §6.5 forbid:
  - an evidence item with no published value key, or citing a call that did not return;
  - **a value no cited call produced** (§6.5: no fabricated values; the review of PR #26,
    3). The harness keeps the evidence values each call produced, under the evaluator's
    keys. Numbers must match to the five significant digits the agent is shown, strings
    exactly, and a word for a number is refused;
  - an abstention outside the published vocabulary;
  - an interval whose method has no successful call behind it for that parameter (the
    review of PR #26, 4): a converged sampler for `posterior`, its profile for
    `profile`, and for `fisher` a Fisher-information call or a fit's covariance (the
    Fisher information at the optimum, as P0's intervals);
  - `none` beside another label (the review of PR #26, 7);
  - any tool use after `conclude` in the same turn (the review of PR #26, 7);
  - a bounds change without a justification;
  - a flagged or excluded sensor in the objective;
  - an estimate outside the declared bounds;
  - **an estimate or interval that no call produced** (the re-review of PR #26, 1):
    - a Fisher interval must be a fit's optimum ± z sd, or a Fisher call's point ± z
      CRLB sd, clipped to the bounds, with a finite sd (z = 1.645, P0's);
    - a profile interval must be a closed profile's;
    - a posterior must be a converged sampler's mean or median with its q05 to q95;
    - an estimate without an interval must be one some call used or returned.

    Matches are to `uncertainty.rel_tolerance`, and the harness shows each interval in
    the tool result;
  - an evidence value that the cited call did not produce for the sensor the item's tag
    names (the re-review, 3);
  - a quarantine window that reaches into the hold-out (found on the first live cell).
    Validation scores the hold-out as recorded.

  A refusal goes back to the model as an error. It is recorded under `tool_failures` (name
  `p1.<action>`) and counted in `plan.sizes.refused_actions`. The harness does **not**
  check that an evidence item cites the *right* tool for its keys; that is the evaluator's
  unsupported-claim check. The produced-value check refuses a value no cited call
  produced, which in practice also refuses citing the wrong tool for a key.
- **Limits.** The tool-use cap (`loop.max_tool_calls`) is counted in the harness. When the
  wall clock left falls below `loop.wall_clock_reserve_min`, or a cap is close, the harness
  tells the model to conclude, and after `loop.conclude_grace_turns` more turns it stops.
  A run that never concludes is written with `completed` false and rule `unconcluded`, and
  it stays in every denominator (§6.7 D).
- **State.** The shared schema (`state/task_state.py`), written after every turn:
  - actions named by their log lines;
  - evidence items with the calls they rest on (`rule` = `p1`: P1 has no rule table, and its
    items are traced by their value keys);
  - the final label set, the flag, the scale factors, `kinetic_update` and the estimates
    with intervals and method;
  - the abstentions;
  - the validation block;
  - the residual summaries;
  - the notes seen as day, author and length.

  The runner fills `tokens_used`.
- **The history is append-only.** The assistant's blocks go back exactly as received:
  thinking blocks unchanged, only the fields the API reads kept. This keeps each request a
  prefix-extension of the last, which the prompt cache and the model's preserved-thinking
  check both require.

## 4. The prompts

`configs/workflows/p1_prompts/system.md` (role, task, labels, method, rules, budget,
conclusion) and `task.md` (a template the harness fills from the visible record). They are
written from the proposal (§2, §4, §6.3–§6.7, Appendix A), the benchmark card (§1–§4, §7),
`docs/tool_registry_design.md` (the evaluation-counting rule) and the published
vocabularies (`configs/abstentions.yaml`, the labels, `evidence_keys`). They name no
scenario and no P0 rule, give no label frequency and encode no per-cell P0 outcome.
`tests/test_p1_agent.py` fails on `S\d-\d\d` or `R[1-6]` in any committed prompt.
Under the lead's ruling of 2026-09-25 the label definitions carry **generic** examples
only. Nothing tracks the scenario library or its correct-action column, and a test scans
every prompt surface for the library-shaped phrases (decisions, 2026-09-25). Operator
notes enter the task prompt as quoted data, under a heading that says they are evidence,
not instructions.

## 5. The frozen settings (to be frozen)

`configs/workflows/p1.yaml`, `model` block:
- **OpenAI `gpt-5.6-luna`**, by the lead's instruction in the P1 session on 2026-09-25
  ("use ChatGPT, GPT 5.6"). The account serves three GPT-5.6 variants and no plain
  `gpt-5.6`; the lead chose luna. It is the least expensive of the three:
  - luna: $0.20 input, $0.02 cached input, $1.20 output per million tokens;
  - sol: $4, $0.80 and $30;
  - terra: $4, $0.40 and $18.

  These are OpenAI's published Standard, short-context rates, read 2026-09-25, and are
  recorded in `p1.yaml` for cost reporting only;
- `max_tokens` (`max_output_tokens`) 16000, reasoning included;
- reasoning effort `high`;
- prompt caching: automatic at OpenAI (the history is append-only, so every turn reuses
  the last one's prefix), nothing sent for it;
- `temperature` **null, not sent**: reasoning models take no sampling parameters, so
  §10's "temperature 0 where possible" is not possible here, and LLM variance is measured
  across seeds;
- no fallback model: a refusal ends the run unconcluded;
- the key reaches the runner's environment as `OPENAI_API_KEY` and is never written to
  the repository, a run directory or a log.

Loop: 60 turns, 90 tool uses, 6 M tokens, a 6-minute wall-clock reserve, 3 grace turns.

## 6. A known asymmetry: model latency is on the registry's clock

The scenario's wall-clock allowance is measured by the registry from its opening, and a
model turn takes wall-clock time. So P1 gets less simulator time than P0 within the same
allowance: every second the model spends is a second the tools do not get. This is by
design of "the same budgets" (§7: identical T per cell) and is reported, not compensated.
The evaluator reports `tool_runtime_s` (from the truth-side log) beside `wall_clock_s`, so
the model's share can be read per cell.

## 7. Open points (in the PR for the coordinator)

1. The model: `gpt-5.6-luna` is the lead's choice. Whether a larger GPT-5.6 variant
   should be frozen instead is the lead's call.
2. Invalid actions the harness refuses never reach the registry, so the evaluator's
   `invalid_actions` (read from logs) does not count them. They are in `tool_failures` and
   `plan.sizes.refused_actions`.
3. The live pilot: cost and wall time per development cell, once the key is present.
