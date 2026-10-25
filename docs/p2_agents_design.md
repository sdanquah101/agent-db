# P2 as agents: a design note (proposal §6.5)

Status: **DRAFT for the coordinator's review and the lead's approval. No code and no live call
until it is approved.** Written by the P2 component session after the lead's ruling of
2026-10-25 (`docs/decisions.md`). That ruling supersedes the 2026-09-30 reading "P2 should not
be agents with prompts", which produced the procedural design of `docs/p2_launch_brief.md`
(draft 2) and `docs/p2_design.md`. Revised after the coordinator's review of `447f4c2`.

The aim is the P2 the proposal describes. Several specialist agents look at the same logged
evidence, write expert assessments and argue for a label. Then an independent verifier argues
against it before anything is concluded. It is built **on top of** what exists: the registry,
the budgets, the null rule, the logs and the rerun machinery stay.

**§9 is the single list of the decisions this note asks of the lead.**

---

## 1. What changes and why

**The procedural P2 adds no judgement.** In the procedural P2, code runs seven procedures and
asks a model at only twelve typed decision points. Each answer is an enum or a window, checked
by code, with a coded fallback. Three pilots show what that buys.

- **Attempt 3** (`reports/p2_pilot/attempt3/`, six runs, 19 requests, USD 0.004146).
  - The only answers whose **applied** value differed from the coded fallback were three
    `dq.coupled` readings. Each restated `"coupled_inside": true`, a field code computed and
    showed the model. Attempt 3's outcomes therefore equal a pure-code rule: admit `sensor`
    when NS fails on one channel and the S1 table holds.
  - The differential's label equalled its coded fallback on all seven calls. Its `rejected`
    list differed on all seven, but it is recorded and never applied. Four of the seven calls
    offered only `none`, so their answer was forced.
- **Attempt 2** (`reports/p2_pilot/attempt2/`). On the three runs where the model's choice
  mattered, the model and the coded fallback each got two of three right. The one outcome the
  model changed rested on a hold-out argument it applied inconsistently. D-1 and D-3 then closed
  that route.
- **Both attempts score 3 of 6, against 2 of 6 offline.** At these counts the attempts are
  indistinguishable from each other and from code.

**The cause is the design, not the model.** A decision point is shown a table code computed
and offered labels code already admitted. It can only agree with code, or contradict it without
evidence. Nothing in the procedural P2 lets a model:
- choose what to look at;
- ask for a test;
- weigh competing causes;
- be challenged.

Yet these are what proposal §6.5 and RQ3 are about. A P2 without them cannot answer RQ3.

**The change.** The top layer is replaced: the twelve decision points and the procedural steps
that feed them. In their place come role agents, each reasoning over evidence and calling
registry tools in its own lane, and an adversarial verification loop. **Everything below the
top layer is kept** (§2).

## 2. What is kept as code (not up for debate)

| kept | as what | module(s), reused unchanged unless noted |
|---|---|---|
| The registry, its tools, versions and budgets (simulator evaluations, assay units; no wall-clock limit for P2) | the only numerical code; budgets enforced in the registry (rules 2, 3); quantities carry the registry's units (rule 6) | `tools/impl/`, `tools/registry.py`, `tools/runner.py` |
| Logging and provenance | `calls.jsonl` and the model log, written on the privileged side | `tools/runner.py`, `tools/llm.py` (frozen, used as is) |
| Truth isolation and the jail | workflows run in the jail and see `runs/<id>/` only; the truth-isolation scanner applies to the new code | `tools/sandbox.py`, `tests/test_truth_isolation.py` |
| The QC gate | `data_qc` runs first. A QC-flagged sensor never enters an objective: the `set_sensor_status` view refuses putting one back (no QC bypass). P0's §3.1 exclusions apply. | the existing P2 step, run as code before the agents |
| The declared background and the null rule | **Evidence shown to every agent:** the null table (NB, NM, NS, the failed channels, the placement against the band). The hard rule stays: **a label other than `none` needs a failed null case of the kind the label requires** (admission, §4.4). Code refuses a finding that breaks it. The null table no longer pre-decides the label; how `none` is reached over a failed null is §4 and Q3. | `tools/impl/` (`declared_background`); the null-table and signature functions of `workflows/p2_multi_agent/workflow.py`, moved to an evidence module |
| The code signatures (S1 table, onset test, early/late, change point, R3, inhibition) | evidence: numbers with their thresholds, never verdicts | the same functions, moved with the null table |
| The rerun rule, the in-flight journal, the approval record, the freeze check | unchanged | `scripts/p2_rerun.py`, `scripts/p2_pilot.py`, `scripts/p2_power.py`, `tools/p2_live.py` |
| The task state and the evaluator | the eval reads only `calls`, `values` and `rule` from evidence items, plus the typed labels and parameters (§5) | `state/task_state.py`, `eval/` (frozen) |
| The gateway caps | requests, tokens and USD per run; a refusal stops the run, which abstains | `tools/p2_live.py`, **extended** (§6) to accept a multi-message, tool-using agent turn, as P1's does |

**What goes.** The twelve decision points as the only place a model speaks, and the procedural
ordering. The offline decider stays only as a test double and as the "no model" ablation.

## 3. The roles as real agents

Each role is a **bounded tool-using agent**, built on P1's agent loop
(`workflows/p1_single_agent/agent.py`). It has its own frozen system prompt, its own
allow-list (below), its own turn budget, the shared registry and the shared typed state.

A role reasons in free text and writes an **expert assessment**. The assessment goes into
`messages.jsonl` only, never to the verifier (§4) and never into `state.json`. A role emits
**one typed finding**, whose every evidence item cites one logged call (one label per cited
call, as P1 does now). Code refuses:
- an uncited item, or a call that did not return;
- a number that is not in the cited output, with its registry unit (no fabricated values;
  rule 6);
- a finding that breaks the null rule.

### 3.1 The one allow-list (this replaces `p2_design.md` §6.1 for the agent P2)

| tool | DQ | Influent | Ident | Calib | Design | Verifier | Coord |
|---|---|---|---|---|---|---|---|
| `data_qc`, `set_sensor_status` (the view refuses reinstating a QC-flagged sensor) | ✓ | | | | | | |
| `inspect_record` | ✓ | ✓ | | | | ✓ | |
| `mass_balance`, `feed_loads` | | ✓ | | | | | |
| `describe_model`, `gsa_morris`, `gsa_sobol`, `fisher_info`, `profile_likelihood` | | | ✓ | | | | |
| `residual_diag` | ✓ | | ✓ | ✓ | | ✓ | |
| `simulate` | ✓ | ✓ | | ✓ | | ✓ | |
| `fit_lsq`, `fit_de`, `fit_cmaes`, `bayes_mcmc` | | | | ✓ | | | |
| `voi_assay` | | | | | ✓ | | |
| `request_assay` (only under a coordinator grant) | | | | | ✓ | | |
| `declared_background` | ✓ | ✓ | | ✓ | | ✓ | |
| `validate` (the hold-out) | | | | | | ✓ | |
| `stored` (a harness action, as in P1, not a registry tool: fetch a logged output by call index) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `conclude` / `abstain` | | | | | | | code only |

Three settled points:
- **Assays are requested by the design role only**, under the coordinator's grant. Data
  quality asks for one through the design role, and does not hold `request_assay` itself.
- **The verifier's `simulate` and `residual_diag` calls are charged to the run's budget** and
  bounded by its turn budget.
- **Parameter bounds (proposal §6.5).** The calibration agent may **narrow** a parameter's
  declared bounds, as P1 does: logged, with a `bounds_justification`, and never widened. A
  bound hit is never a kinetic update. The justification is free text, so it is redacted
  from the verifier's view (§4).

### 3.2 The roles

| role | shown (evidence) | may conclude | emits | budget (proposed) |
|---|---|---|---|---|
| **Data quality** | QC output, the raw records on the calibration window, the S1 table, the coupled channels' after-fit statistics, the band | each sensor's status; whether a `sensor` cause explains a failed NS; a refutation of `sensor`; that the failed case is background (`none`, §4) | `SensorFinding` | 12 turns |
| **Influent** | the feed log and operator notes (as data), `mass_balance` windows, the COD band, the onset test, the feed covariate | whether an `influent` cause explains NB, and its onset; the mechanism, as a report only | `InfluentFinding` | 12 turns |
| **Identifiability** | Morris, Sobol, Fisher and profile outputs; the CRLB table | the identifiable subset here; a no-go for kinetic updates when nothing is identifiable | `IdentFinding` | 8 turns |
| **Calibration** | the reference fit, residuals, change point, inhibition, the early/late split, the biomass pair | whether `parameter` or `state` explains NM or NS; fitted values only on an identified subset | `CalFinding` | 14 turns |
| **Experimental design** | the open disagreement, the price list, the assay budget left | which assay separates two named causes, with the predicted outcome under each | `AssayPlan` | 6 turns |
| **Verification** | §4 | `pass`, `fail` or `abstain` | `Verdict` | 14 turns per round |
| **Coordination** | the typed state and the typed findings | whom to route to next and which grants to make; never a label | routing entries | (code) |

### 3.3 The typed messages (fields)

Every evidence item is `{label, rule, calls: [call index], values: {name: number}}`, with
`statement` **templated by code** from those fields, never written by the model. So
`state.json` holds no model free text. The guarantee the eval relies on is the same as now: it
reads `calls`, `values` and `rule`, plus the typed labels and parameters.

| message | fields |
|---|---|
| `SensorFinding` | `role`; `statuses: {sensor: ok\|quarantined\|excluded\|flagged}`; `quarantines: {sensor: [[t0, t1]]}`; `claim: sensor\|none\|refute_sensor\|no_claim`; `channel`; `confidence: low\|medium\|high`; `evidence: [item]` |
| `InfluentFinding` | `role`; `claim: influent\|none\|refute_influent\|no_claim`; `onset_day`; `feed_id`; `mechanism` (report only); `confidence`; `evidence` |
| `IdentFinding` | `role`; `subset: [parameter]`; `kinetic_update_allowed: bool`; `evidence` |
| `CalFinding` | `role`; `claim: parameter\|state\|none\|refute_parameter\|refute_state\|no_claim`; `parameters: {name: {estimate, lower, upper, unit, method}}`; `bounds_narrowed: {name: [lo, hi]}` (its justification kept out of the verifier's view); `confidence`; `evidence` |
| `AssayPlan` | `role`; `assay`; `day`; `separates: [label, label]`; `predicted: {label: number}`; `evidence` |
| `Verdict` | `round`; `verdict: pass\|fail\|abstain`; `alternative: an admissible label or none` (checked by code: it must be admitted by the null rule, or `none`); `separating_test: {tool, args}` or null; `evidence` |
| routing entry (coordinator only) | `round`; `to: role`; `grant: {evaluations, assays}`; `reason: an enum` |

The coordinator is the only writer of routing entries in `messages.jsonl`.

**Coordination: recommended as code** (Q7). It routes on the typed state:
1. QC first;
2. the specialists whose null case failed, or all of them when the null stands;
3. the design role when two findings conflict;
4. then the verifier.

It grants budgets and enforces the round limit, and it cannot write a finding or a verdict.
§6.5 says it "routes; it cannot approve its own output". It costs nothing and is deterministic,
and "remove coordinator" becomes a cleanly defined fixed route.

**Who concludes: code, by fixed rules** (§4, step 6). No model writes the final label.

## 4. The adversarial step

1. **Proposal.** The specialists' findings are collected. If more than one claims a cause, the
   design role may spend assay budget on a separating test, under the coordinator's grant.
2. **Challenge.** The verifier receives the leading proposal and every other finding, typed
   fields only. It also receives **the projected action log** and the hold-out, through
   `validate`.
   - **What the projection holds.** Each logged call's index, tool name, version and typed
     arguments, with **every free-text field redacted**: `set_sensor_status.reason`,
     `record_evidence.statement`, `fit_*.bounds_justification`, `conclude.summary`, and any
     other string the schema does not enumerate. It also holds the call's outcome and a
     compact output: arrays cut to at most 200 points, P1's `max_points_shown` and
     `compact()`. A full output is fetched by index with `stored`, as P1 does.
   - **What the verifier never sees:** any proposer's assessment or free-text argument
     ("verifier cannot see proposer's reasoning", §9.3).
   - **The test.** The planted-claim test (`p2_design.md` §10.2) is kept and extended to
     tool-argument strings. A claim planted in a proposer's free-text argument must not appear
     anywhere in the verifier's inputs. The negative control is an unredacted projection, in
     which the scan finds it.
   - **The instruction.** The verifier is told to **argue against the proposal**: find the
     admissible alternative cause, or `none`, that explains the same evidence. It names
     **one** separating test per round (a tool call or an assay), charged to the run.
3. **Response.** The coordinator routes the named test to the role whose allow-list holds the
   tool, within budget. The role answers **with evidence**: new cited calls.
4. **Verdict.**
   - `pass`: the proposal survives.
   - `fail`: with the alternative and the evidence for it.
   - `abstain`: the data cannot separate the two.
5. **Round semantics.**
   - At most **2 rounds**, each with its own verifier turn budget, all inside the run's caps.
   - An `abstain` in round 1 ends the loop: the run abstains.
   - A named test outside every allow-list or budget counts as `abstain`, and is logged.
   - A `fail` sends the alternative back to the specialists for round 2.
6. **How it ends.** The verifier's verdict is **final**. The coordinator cannot overrule it,
   and no proposer appeals past the round limit. Code concludes:
   - **`pass`:** the passed label (`none` included).
   - **`fail` in the last round:**
     - **`none`, when the alternative is `none`** (Q3). The verifier has argued that the
       failed case is background, and it is the role holding the hold-out.
     - **`abstain` for any other alternative.** The verifier cannot propose a cause.
   - **`abstain`:** abstain.
7. **`none` over a failed null (Q3).** A clean cell's null case can fail:
   - S0-01 B/C, NM on TS/VS;
   - S1-01 B/B, NB;
   - attempt 3's S0-01 r1, NS on pH alone.

   Without a route to `none`, such a cell could end only as abstain or wrong, where the
   procedural P2 scored `none`. So a specialist may emit a `none` finding with cited evidence
   ("the failed case is the plant's background: …"). The verifier challenges it like any
   label.
8. **When the null stands, the verifier still runs** (Q3). It challenges `none` by testing the
   hold-out and the structural signature. So S6-02 at tier B gets the hold-out test that
   decision 3 of 2026-09-30 promised.
   - A `fail` whose alternative is `structural` sends that alternative to the calibration role
     for round 2.
   - If calibration then claims `structural` with cited evidence, the verifier challenges it as
     usual.
   - If it does not, the run abstains (step 6).

**Default visibility of shared state before the verifier.** Every role sees:
- the typed state, including the other roles' typed findings as they arrive;
- the projected log.

No role sees another role's assessment. The hold-out is visible only to the verifier.

## 5. Guard rails kept, and D-1 revisited

- **No fabricated values.** Every number in a finding is in a cited output and carries its
  registry unit (rule 6). Code checks this, as P1's workspace does.
- **Registry-only tools; no QC bypass.** Allow-lists are enforced in the view (§3.1), and a
  flagged sensor is never reinstated.
- **Every claim cites a logged call.** The unsupported-claim metric reads the evidence items.
- **No model free text in `state.json`.** Statements are templated by code (§3.3), and
  assessments go to `messages.jsonl`.
- **Abstain is a real option.** It is scored as abstention, never as `none`.
- **Determinism (rule 4).**
  - Every stochastic tool call is seeded with `seeds.base` plus its call index, as P1 does.
  - Roles run sequentially, so call indices are reproducible.
  - The model temperature is null, as in P1's frozen block.
  - The model's own variance is measured across the two run seeds, not hidden.
- **D-1 under a free verifier.** D-1 existed because the procedural differential used a passed
  hold-out to reject `sensor`. A sensor fault can pass a hold-out, so that inference is wrong.
  The proposal (Q4):
  - the full hold-out is shown to the verifier only;
  - its prompt states that a **passed** hold-out is not evidence against a non-structural
    label, and a **failed** one is evidence for `structural` or an unmodelled state;
  - code refuses a `fail` whose only evidence against a non-structural label is a passed
    hold-out, as D-3 refuses such a code now.

## 6. What is frozen and what moves

- **Frozen anew before any live run, in a new frozen record:**
  - each role's prompt and the verifier's;
  - the message and finding schemas (§3.3);
  - the allow-list (§3.1);
  - turn budgets and the round limit;
  - the projection rule and its size bound;
  - P1's frozen model block (decision d), and the caps.

  `check_p2_frozen` checks the record on every run. A new approval record names its digest.
- **The gateway** (`tools/p2_live.py`) is extended to accept an agent turn: multi-message and
  tool-using, with the role's frozen prompt and tools, checked against the freeze.
  `tools/llm.py` is used as is.
- **P0 and P1 stay untouched.** No change to `workflows/p0_*`, `workflows/p1_*`, `p0.yaml`,
  `p1.yaml`, `tools/impl/` or `eval/`. The two-head P0 freeze test and P1's `check_frozen` pass
  on every PR.
- **The procedural P2's records stand as its record:** attempts 1–3 and the offline power run.
  The new P2 is a new `workflow_version`.

## 7. How this tests RQ3 and H4

**The comparison.** P2 against the frozen P1, with the same registry, budgets and model, on the
same cells, two seeds per cell. **Three asymmetries are not removed by that, and are stated
beside every comparison:**

| asymmetry | what isolates it |
|---|---|
| **(a)** P2's roles call `declared_background`; the frozen P1 does not (decision 1 of 2026-09-30) | **nothing in P2.** Only a matched P1 arm (P1 with the band tool, unfrozen, development only) would remove it (Q5) |
| **(b)** P2's verifier holds `validate` and sees the full hold-out inside the loop, over up to two rounds; P1's hold-out is scored once by the harness | the **verifier-off** ablation |
| **(c)** P2 has no wall-clock limit; P1's runs were stopped at 90–150 min | not removable afterwards; reported with P1's wall-clock-stopped runs counted as failures |

**H4** predicts a gain only with two or more simultaneous faults (Level 7). **No current
development cell has two faults.** The proposal is to add **S7-01** (`sensor` + `influent`;
defined at B/B) at B/A, B/B and B/C, and **S7-02** (`structural` + `parameter`; defined at
A/C) at A/A, with two seeds each, as **new development cells**. The brief's standing rule is
development cells only, and new cells need the lead's word (Q6).

**The ablations of §6.7 E**, each a configuration switch:
1. verifier off;
2. coordinator off (a fixed route);
3. one specialist off at a time (its tools run by code, as P0 does);
4. self-correction off (one round, no response step);
5. persistent state off (each role sees only its own calls).

The procedural P2 is an extra arm: "decision points only".

| stage | cells | seeds | runs | what it can detect |
|---|---|---|---|---|
| development | the ten development cells | 2 | 20 | only differences of 3–4 hits or more |
| H4 (Q6) | S7-01 ×3 tiers, S7-02 A/A | 2 | 8 | descriptive only |
| ablations | the four S7 cells and two clean cells | 2 | 12 per ablation, 60 in all | only differences of 3–4 hits or more |
| final | the factorial share of §7 | 5 | 480 | the pre-registered analysis |

The code-only floor for each development cell is `reports/p2_power/`: the procedural P2 with
every decision at its fallback. Any agent result is read against it.

## 8. Cost and time

**Per run (an estimate, before any measurement).**
- **P1 for comparison.** P1 costs USD 0.02–0.06 a run with `gpt-5.6-luna`: 10–27 turns and
  0.3–1.4 M tokens, mostly cached input (`reports/p1_pilot.csv`, revision 2).
- **P2's model calls.** About six bounded role conversations plus one or two verifier rounds,
  each roughly half a P1 run: **about 3–6 × P1, USD 0.10–0.30 per run**.
- **The verifier's input, bounded.** The projection is capped at 200 points per output (§4).
  At about 100 k tokens per verifier turn, 14 turns and 2 rounds come to about **2.8 M input
  tokens per run for the verifier alone**:
  - **USD 0.06 if cached** (USD 0.02 per M);
  - **USD 0.56 if uncached** (USD 0.20 per M).
- **The estimate's assumption.** The USD 0.10–0.30 estimate **assumes prompt caching works for
  agent turns, as it did for P1.** The current cap of USD 0.25 a run would bind uncached, so
  the pilot caps are a lead question (Q8).

**Per stage (model cost).**
- The six-cell pilot: about USD 1–2.
- Development: USD 2–6.
- Ablations: USD 6–18.
- The final share: USD 50–150.
- **A Claude Opus 5.5 arm** (Q2): P1 on Claude cost USD 9.86 for 10 runs, so about USD 3–6 per
  P2 run and **about USD 1.5–3 k for the final share**.

**Runner time.** The simulator, not the model, sets the wall clock: about 45–60 min a run now,
more if agents call more fits. The live driver runs **serially** (one process). At that rate:

| stage | runner time (serial) |
|---|---|
| development (20 runs) | about 17 h |
| ablations (60 runs) | about 50 h |
| final share (480 runs) | **360–480 runner-hours, 15–20 days** |

Offline parts already run in parallel. Running live parts in parallel, two or three on four
cores, would need the lead's word and a check that the per-run caps stay per run.

**Weeks of work (one session), an honest range: 4–6 in all, before development runs.**
1. The evidence module and the typed schemas, moved and tested offline: 1 week.
2. The agent harness on P1's loop, the allow-list views, the projection and the gateway
   extension: 1–2 weeks.
3. The roles, the verifier loop, and the scripted-model tests (every guard rail with a negative
   control and a mutation): 1–2 weeks.
4. The freeze, an offline dry run with scripted models, and the six-cell pilot: 1 week.

**The G4 gate and the descope clause.** By calendar this is about week 11 of the 36-week plan.
The week-26 descope clause (P2 with three roles: data quality, calibration and verifier) is
**not** triggered. Three roles first (Q1) is recommended on build risk alone: it builds and
tests the adversarial loop, the part attempts 1–3 most lacked, before the remaining four roles.

## 9. The decisions asked of the lead (each with a recommendation)

1. **Three roles first, or all seven at once?** *Recommend three first:* data quality,
   calibration and verifier, with coordination in code. It carries the least build risk and
   tests the verifier loop soonest.
2. **The model.** P1's frozen `gpt-5.6-luna`, or a stronger one? *Recommend P1's frozen model*
   for every arm of the RQ3 comparison. A Claude arm is a separate, costed extension: about
   USD 3–6 a run and USD 1.5–3 k for the final share.
3. **`none` over a failed null, and the verifier when the null stands** (§4, steps 6–8).
   *Recommend:*
   - a specialist may emit a cited `none` finding, and the verifier challenges it like any
     label;
   - a last-round `fail` whose alternative is `none` concludes `none`, not abstain;
   - the verifier runs when the null stands too, so S6-02 gets its hold-out test.
4. **D-1 under a free verifier** (§5). *Recommend:* the full hold-out to the verifier only; a
   passed hold-out never counts against a non-structural label, stated in the prompt and
   enforced on the `Verdict`.
5. **The `declared_background` asymmetry with P1** (§7 a). Run a matched P1 arm (P1 plus the
   band tool, unfrozen, development only), or disclose? *Recommend disclosing now, and deciding
   after the pilot* whether the matched arm is worth its cost.
6. **New development cells for H4** (§7). *Recommend adding* S7-01 at B/A, B/B and B/C, and
   S7-02 at A/A, two seeds each. No development cell has two faults now.
7. **The coordinator: code or model?** *Recommend code*, with a model coordinator only as an
   optional ablation.
8. **The caps.** *Recommend* USD 0.50, 200 requests and 10 M tokens per run for the pilot, to
   measure the real cost uncached or cached. Then a frozen cap at about twice the measured
   median.
9. **The verifier's tests.** *Recommend* one named separating test per round, charged to the
   run's budget, with the verifier's own `simulate` and `residual_diag` calls charged the same
   way.
10. **Parameter bounds.** *Recommend* that calibration may narrow bounds, logged with a
    justification (redacted from the verifier), and never widen them. A bound hit is never a
    kinetic update.
11. **The round limit.** *Recommend 2.* A third round only if the pilot shows round 2 leaving
    separable cases unsettled.
12. **The procedural P2's place in the paper.** *Recommend* reporting it as the "decision
    points only" arm: an honest negative result, with attempts 1–3 as its record.
