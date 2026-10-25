# P2 as agents: a design note (proposal §6.5)

Status: **DRAFT for the coordinator's review and the lead's approval. No code, no live call
until it is approved.** It was written by the P2 component session after the lead's ruling of
2026-10-25 (`docs/decisions.md`). That ruling supersedes the 2026-09-30 reading "P2 should not
be agents with prompts", which produced the procedural design of `docs/p2_launch_brief.md`
(draft 2) and `docs/p2_design.md`.

The aim is the P2 the proposal describes. Several specialist agents look at the same logged
evidence, write expert assessments, and argue for a label. Then an independent verifier argues
against it before anything is concluded. It is built **on top of** what exists: the registry,
the budgets, the null rule, the logs and the rerun machinery all stay.

---

## 1. What changes and why

**The procedural P2 adds no judgement.** In it, code runs seven procedures and asks a model
only at twelve typed decision points. Each point's answer is an enum or a window, checked by
code, with a coded fallback. Three pilots show what that buys.

- **Attempt 3** (`reports/p2_pilot/attempt3/`, six runs, 19 requests, USD 0.004146). Every
  answer the workflow **applied** equalled the coded fallback, except three `dq.coupled`
  readings. Those three restated `"coupled_inside": true`, a field code had computed and shown
  the model. Attempt 3's outcomes therefore equal a pure-code rule: admit `sensor` when NS fails
  on one channel and the S1 table holds. The differential's label equalled its coded fallback on
  all seven calls. Four of those seven calls offered only `none`, so the answer was forced.
- **Attempt 2** (`reports/p2_pilot/attempt2/`). On the three runs where the model's choice
  mattered, it and the coded fallback each got two of three right. The model's one changed
  outcome rested on a hold-out argument it applied inconsistently: it set `sensor` aside as
  `holdout_passed` on two near-identical runs and chose it on the third. D-1 and D-3 then
  closed that route.
- **Both attempts score 3 of 6.** Offline (no model) scores 2 of 6. At these counts the
  attempts are indistinguishable from each other and from code.

The cause is the design, not the model. A decision point shown a code-computed table, and
offered two labels code already admitted, can only agree with code or contradict it without
evidence. Nothing in the procedural P2 lets a model:
- choose what to look at;
- ask for a test;
- weigh competing causes;
- be challenged.

Yet these are what proposal §6.5 and RQ3 are about: "communicating through typed messages and
shared state … the verifier … returns pass / fail / abstain." A P2 without them cannot answer
RQ3. Its only comparison with P1 would be "code with a few multiple-choice questions" against
"one free agent".

**The change.** Replace the top layer (the twelve decision points and the procedural steps that
feed them) with role agents. Each agent reasons over evidence and calls registry tools in its
own lane, and there is an adversarial verification loop. **Everything below the top layer is
kept** (§2).

## 2. What is kept as code (not up for debate)

| kept | as what | module(s), reused unchanged unless noted |
|---|---|---|
| The registry, its tools, versions and budgets (simulator evaluations, assay units; no wall-clock limit for P2) | the only numerical code; budgets enforced in the registry (rules 2, 3) | `tools/impl/`, `tools/registry.py`, `tools/runner.py` |
| Logging and provenance | `calls.jsonl` and the model log, both written on the privileged side | `tools/runner.py`, `tools/llm.py` (frozen, used as is) |
| Truth isolation, and the jail | workflows run inside the jail and see `runs/<id>/` only; the truth-isolation scanner applies to the new code | `tools/sandbox.py`, `tests/test_truth_isolation.py` |
| The QC gate | `data_qc` runs first; a flagged sensor cannot enter an objective; P0's §3.1 exclusions | the existing P2 step, moved to code-before-agents |
| The declared background, and the null rule | **evidence shown to every agent**: the null table (NB, NM, NS, the failed channels and the placement against the band). The hard rule stays: **a label other than `none` needs a failed null case of the kind the label requires** (admission, §4.4). Code refuses a finding that breaks it, as it refuses an uncited one. The null table no longer pre-decides the label: agents argue which cause explains the failed case. | `tools/impl/` (`declared_background`), the null-table and signature functions of `workflows/p2_multi_agent/workflow.py`, moved to an evidence module |
| The code signatures (S1 table, onset test, early/late, change point, R3, inhibition) | evidence: computed by code, shown as numbers with their thresholds, never as verdicts | the same functions, moved with the null table |
| The rerun rule and the in-flight journal; the approval record; the freeze check | unchanged | `scripts/p2_rerun.py`, `scripts/p2_pilot.py`, `scripts/p2_power.py`, `tools/p2_live.py` (approval and freeze) |
| The task state and the evaluator | the eval reads `state.json` only; free text never enters a field it reads | `state/task_state.py`, `eval/` (frozen) |
| The gateway caps | per run: requests, tokens, USD; refusals stop and abstain | `tools/p2_live.py`, **extended** (§6): an agent turn is a multi-message, tool-using request, as P1's is; the current gateway accepts only one-message decision requests |

**What goes.**
- The twelve decision points as the only place a model speaks.
- The procedural ordering that fixes which tool runs when.
- The offline decider as the P2 workflow: it remains as a test double and as the ablation "no
  model". The dead `cal.split` / `cal.bound` points go with it.

## 3. The roles as real agents

Each role is a **bounded tool-using agent**, built on P1's agent loop (`workflows/p1_single_agent/agent.py`):
- its own frozen system prompt;
- its own tool allow-list (the existing §6.1 allow-lists);
- its own turn and token budget;
- the shared registry and the shared typed state.

A role reasons in free text and writes an **expert assessment** (free text, into
`messages.jsonl` only). It emits **one typed finding**: a label or a refutation, its confidence,
and the evidence items. Each evidence item cites one logged call, with one label per cited call,
as P1 and P2 do now. Code refuses an uncited item, a call that did not return, or a finding
that breaks the null rule.

| role | shown (evidence) | may conclude | emits | tools / assays | budget (proposed) |
|---|---|---|---|---|---|
| **Data quality** | QC output, the raw records on the calibration window, the S1 table, the coupled channels' after-fit statistics | each sensor's status (ok, quarantined, excluded); whether a `sensor` cause explains a failed NS; may refute `sensor` | `SensorFinding` (statuses, quarantines, a `sensor` claim or its refutation, citations) | `data_qc`, `residual_diag`, `simulate`, `request_assay` (assays from the shared budget) | 12 turns |
| **Influent** | the feed log and operator notes (as data), `mass_balance` windows, the declared COD band, the onset test, the feed covariate | whether an `influent` cause explains NB, and its onset; the mechanism as a report only | `InfluentFinding` | `mass_balance`, `feed_loads`, `simulate`, `declared_background` | 12 turns |
| **Identifiability** | Morris and Fisher outputs, the CRLB table | the parameter subset that is identifiable here; a no-go for kinetic updates when nothing is | `IdentFinding` (subset, reasons) | `gsa_morris`, `fisher_info` | 8 turns |
| **Calibration** | the reference fit, residuals, the change point and inhibition evidence, the early/late split, the biomass pair | whether a `parameter` or `state` cause explains NM/NS; the fitted values only on an identified subset | `CalFinding` | `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc`, `simulate`, `residual_diag` | 14 turns |
| **Experimental design** | the open disagreement (§4), the price list, the assay budget left | which assay would best separate two named causes, and its predicted outcome under each | `AssayPlan` (assay, day, the two predictions) | `request_assay` only through the coordinator's grant | 6 turns |
| **Verification** | §4: the findings (typed only), the full action log, the hold-out | pass / fail / abstain, with the alternative cause and the separating test | `Verdict` | `validate` (hold-out), `residual_diag`, `simulate`, read access to every logged call | 14 turns per round |
| **Coordination** | the typed state and the typed findings | which role speaks next, which grants (budget, assays) it makes; never a label | routing messages | none | — |

**Coordination: recommended as code.** It routes on the typed state: QC first; then the
specialists whose null case failed; then the design role if two findings conflict; then the
verifier. It grants budgets and enforces the round limit. It cannot write a finding or a
verdict. The reasons:
- §6.5 says it "routes; it cannot approve its own output", and code makes that unbreakable;
- it costs nothing and is deterministic, so a difference between P2 and P1 is the specialists'
  and the verifier's, not a routing model's;
- the proposal's ablation "remove coordinator" becomes a fixed route (every specialist once, in
  P0's order), which is cleanly defined.

**The alternative**, a model coordinator choosing whom to consult next, is a second ablation if
the lead wants it.

**Who concludes.** The typed state's final label comes from code, applying fixed rules:
- the label of the one finding the verifier passed;
- `none` if the null stands and no finding claims otherwise;
- `abstain` otherwise.

No model writes the final label directly.

## 4. The adversarial step

1. **Proposal.** The specialists' typed findings are collected. If more than one claims a
   cause, the conflict goes to the design role, which may spend assay budget on a separating
   test granted by the coordinator.
2. **Challenge.** The verifier receives:
   - the leading proposal (its label and evidence items, typed only);
   - **every** other finding (typed only);
   - the full action log (every call, its arguments and outputs);
   - the hold-out (through `validate`).

   It is instructed to **argue against the proposal**: to find the alternative cause that
   explains the same evidence, and to name the test (a tool call or an assay) that would
   separate them. It does **not** see any proposer's free-text assessment ("verifier cannot see
   proposer's reasoning", §9.3). It can only call read and validation tools: it cannot fit a
   new model or change data.
3. **Response.** The coordinator routes the named test to the role that owns the tool, within
   budget. That role runs it and answers **with evidence** (new cited calls), not argument.
4. **Verdict.** The verifier returns one of:
   - `pass`: the proposal survives;
   - `fail`, with the alternative and the evidence that favours it;
   - `abstain`: the data cannot separate the two.
5. **Bounds.** At most **2 rounds** (propose 2; a round is steps 2–4). Each verifier round has
   its own turn budget, and the run's model caps (§8) bind the total. After the last round
   without a `pass`, the run abstains.
6. **How a disagreement ends.** The verifier's verdict is **final**. The coordinator cannot
   overrule it, and no proposer can appeal past the round limit.
   - A `fail` does not make the verifier's alternative the label: the verifier cannot propose.
   - The alternative goes back to the specialists for the next round, if one is left.
   - Otherwise the run abstains.

## 5. Guard rails kept, and D-1 revisited

- **No fabricated values:** every number in a finding comes from a cited call that returned.
  Code checks this, as P1's workspace does now.
- **Registry-only tools, with no QC bypass:** a flagged sensor cannot enter an objective, and
  role allow-lists are enforced by code.
- **Every claim cites a logged call.** The unsupported-claim metric (§6.7 B) reads the evidence
  items.
- **No free text in the evaluated state.** Assessments go to `messages.jsonl`. The eval reads
  `state.json`, which holds only typed fields.
- **Abstain is a real option** at every role and for the run, and it is scored as abstention,
  never as `none`.
- **D-1 (the hold-out bit only beside `structural`).** D-1 existed because the procedural
  differential, shown one bit, used a passed hold-out to reject `sensor`. A sensor fault can
  pass a hold-out, so that inference is wrong. With a free-reasoning verifier:
  - **the hold-out is shown in full, to the verifier only** (§6.5);
  - its prompt states that a **passed** hold-out is not evidence against `sensor` or
    `influent`, and that a **failed** one is evidence for `structural` or for an unmodelled
    state;
  - proposers still never see it.

  D-1 thus becomes an instruction to the verifier and a check on its `Verdict`. The check: a
  `fail` that cites only a passed hold-out against a non-structural label is refused by code,
  as D-3 refuses such a code now. **A question for the lead (§9, Q3).**

## 6. What is frozen and what moves

- **Frozen anew, before any live run:**
  - each role's system prompt, and the verifier's;
  - the typed message and finding schemas;
  - each role's allow-list and turn budget;
  - the round limit;
  - the model block (P1's frozen model, decision d);
  - the caps.

  A new frozen record in `p2.yaml`, checked by `check_p2_frozen` on every run as now. Its
  digest and a new pilot configuration digest go into a new approval record.
- **The gateway** (`tools/p2_live.py`, privileged side) is extended to accept an agent turn:
  multi-message, tool-using, with the role's frozen system prompt and tools, checked against
  the freeze. `tools/llm.py` is reused as is, as P1 uses it.
- **P0 and P1 stay untouched.** No change to `workflows/p0_*`, `workflows/p1_*`,
  `configs/workflows/p0.yaml` or `p1.yaml`, and no change to `tools/impl/` or `eval/`. The
  two-head P0 freeze test and `check_frozen` for P1 must pass on every PR.
- **The procedural P2's records stay as they are**: attempts 1–3 and the offline power run are
  its record. The new P2 is a new workflow version (`workflow_version` bumped), not a
  re-labelling of the old.

## 7. How this tests RQ3 / H4

- **The comparison.** P2 against the frozen P1, under the same tools, budgets and model, on
  the same cells, with two seeds per cell (decision 5 of 2026-09-30).
  - RQ3 asks whether decomposition adds reliability or efficiency once tools and budgets are
    equal.
  - H4 predicts a gain only with two or more simultaneous faults (Level 7), and overhead
    elsewhere.
  - Reported: attribution (exact, partial, primary in truth), false kinetic drift, correct
    abstention, unsupported claims, and cost per run (§6.7 A–D).
- **The ablations of §6.7 E**, each a configuration switch with no code fork:
  1. remove the verifier (the leading finding is concluded unchallenged);
  2. remove the coordinator (a fixed route);
  3. remove one specialist at a time (its tools go to the coordinator's fixed route, run by
     code as P0 does);
  4. remove self-correction (one round, with no response step);
  5. remove persistent state (each role sees only its own calls).

  The procedural P2 of attempts 1–3 is a useful extra arm: "decision points only".
- **Sweep sizes (proposed).**

  | stage | cells | seeds | runs |
  |---|---|---|---|
  | development | the ten development cells | 2 | 20 |
  | ablations | the four multi-fault and two clean cells | 2 | 12 per ablation, 60 in all |
  | final | the factorial share of §7, with no change after the start | 5 | 16 scenarios × 3 tiers × 2 plants × 5 = 480 |

## 8. Cost and time

- **Per run (estimate, before any measurement).**
  - P1 costs USD 0.02–0.06 a run with `gpt-5.6-luna`: 10–27 turns and 0.3–1.4 M tokens, mostly
    cached input (`reports/p1_pilot.csv`, revision 2).
  - A P2 run is about six bounded role conversations plus one or two verifier rounds, each
    roughly half a P1 run: **about 3–6 × P1, USD 0.10–0.30 per run**.
  - The current cap of USD 0.25 per run would bind at the top of that range. A new cap is the
    lead's call (Q4).
  - The simulator, not the model, sets the wall clock: about 45–60 min a run now, and likely
    more if agents call more fits. Evaluations stay capped by the registry budget.
- **The six-cell pilot** (the same six runs): about USD 1–2.
- **Development:** USD 2–6. **Ablations:** USD 6–18. **The final share:** USD 50–150.
- **Weeks of work (one session), honest range:**

  | weeks | work |
  |---|---|
  | 1 | the evidence module and the typed schemas, moved and tested offline |
  | 1–2 | the agent harness on P1's loop, with role allow-lists and the gateway extension |
  | 1–2 | the roles, the verifier loop, and the scripted-model tests (each guard rail with a negative control and a mutation, as now) |
  | 1 | the freeze, an offline dry run with scripted models, and the six-cell pilot |
  | **4–6** | **in all**, before development runs |

- **The G4 gate and the descope clause.** G4 (week 30) asks that P1 and P2 run inside budget
  with frozen prompts. The project is past the proposal's week-26 mark. The risk table's descope
  clause applies: **P2 with three roles** (data quality, calibration, verifier) if the full
  seven do not fit. The design above degrades to that cleanly: the coordinator is code, and the
  other roles are ablation switches. I recommend building **the three-role version first**,
  with the verifier loop complete, piloting it, and then adding influent, identifiability and
  design (Q1).

## 9. Open questions for the lead (each with a recommendation)

1. **Three roles first, or all seven at once?** *Recommend three first* (data quality,
   calibration, verifier, with coordination in code): it is the proposal's descope clause,
   and it tests the adversarial loop, the part attempt 3 most lacked, soonest.
2. **The model: P1's frozen `gpt-5.6-luna`, or a stronger one?** *Recommend P1's frozen model*
   for every arm of the RQ3 comparison: equal model is part of "tools and budgets equal". The
   knowledge audit found the GPT arm less process-literate than Claude Opus 5.5 (29 of 57
   evidence items not process-based), at about 1/20 of the cost. A Claude P2 arm is a separate,
   costed extension if the lead wants it.
3. **D-1 under a free verifier** (§5). *Recommend:* the full hold-out to the verifier only; a
   passed hold-out never counts against a non-structural label, stated in the prompt and
   enforced on the `Verdict`.
4. **The caps.** *Recommend* USD 0.50, 200 requests and 10 M tokens per run for the pilot, to
   measure the real cost. Then a cap at about twice the measured median for development and the
   final runs, frozen.
5. **The round limit.** *Recommend 2*, as proposed; 3 only if the pilot shows a second round
   settling disagreements that a third would also need.
6. **The procedural P2's place in the paper.** *Recommend* reporting it as the "decision points
   only" arm: an honest negative result on constrained model use, with attempts 1–3 as its
   record, not discarded.
7. **The coordinator as a model** (§3). *Recommend code*, with a model coordinator only as an
   optional ablation after the main comparison.
