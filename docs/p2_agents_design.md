# P2 as agents: a design note (proposal §6.5)

Status: **DRAFT for the coordinator's review and the lead's approval. No code and no live call
until it is approved.** Written by the P2 component session after the lead's ruling of
2026-10-25 (`docs/decisions.md`). That ruling supersedes the 2026-09-30 reading "P2 should not
be agents with prompts", which produced the procedural design of `docs/p2_launch_brief.md`
(draft 2) and `docs/p2_design.md`. Revised after the coordinator's review of `447f4c2` and the check of `588187b`. The lead decided Q1–Q12 on 2026-10-25 (§9). Q13 is open.

The aim is the P2 the proposal describes. Several specialist agents look at the same logged
evidence, write expert assessments and argue for a label. Then an independent verifier argues
against it before anything is concluded. It is built **on top of** what exists: the registry,
the budgets, the null rule, the logs and the rerun machinery stay.

**§9 is the single list of the lead's decisions: Q1–Q12 decided 2026-10-25, Q13 open.**

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
- **The verifier has its own budget** (the lead's ruling on Q9). Its `simulate`,
  `residual_diag` and `validate` calls, and its one named separating test per round, draw on
  its budget, not the proposers'. The budget is set apart from, and in addition to, the run's
  caps (§8).
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
`statement` **templated by code** from those fields, never written by the model. P1's
workspace also writes model text into `state.json` in two places. A bounds justification and
the agent's summary go into `annotations`. A sensor's `set_sensor_status.reason` goes into its
`notes`. **The P2 harness drops both**: that text goes to `messages.jsonl` only, `notes` is
templated from the typed status, and `annotations` holds code-written lines only.

So `state.json` holds no model free text. The narrower guarantee the eval relies on also holds:
it reads `calls`, `values` and `rule`, plus the typed labels and parameters
(`eval/attribution.py`), and no field it reads carries model text.

| message | fields |
|---|---|
| `SensorFinding` | `role`; `statuses: {sensor: ok\|quarantined\|excluded\|flagged}`; `quarantines: {sensor: [[t0, t1]]}`; `claim: sensor\|none\|refute_sensor\|no_claim`; `channel`; `confidence: low\|medium\|high`; `evidence: [item]` |
| `InfluentFinding` | `role`; `claim: influent\|none\|refute_influent\|no_claim`; `onset_day`; `feed_id`; `mechanism: fractionation\|moisture\|unrecorded_delivery\|mislabel\|none` (as `influent.mechanism`, `p2_design.md` §2.3; report only); `confidence`; `evidence` |
| `IdentFinding` | `role`; `subset: [parameter]`; `kinetic_update_allowed: bool`; `evidence` |
| `CalFinding` | `role`; `claim: parameter\|state\|none\|refute_parameter\|refute_state\|no_claim`; `parameters: {name: {estimate, lower, upper, unit, method}}`; `bounds_narrowed: {name: [lo, hi]}` (its justification kept out of the verifier's view); `confidence`; `evidence` |
| `AssayPlan` | `role`; `assay`; `day`; `separates: [label, label]`; `predicted: {label: number}`; `evidence` |
| `Verdict` | `round`; `verdict: pass\|fail\|abstain`; `alternative: an admissible label or none` (checked by code: it must be admitted by the null rule, or `none`); `separating_test: {tool, args}` or null (`args` validated against the tool's schema with the redacted free-text fields excluded, so no prose passes through a named test); `evidence` |
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
     **one** separating test per round (a tool call or an assay), charged to the
     verifier's own budget.
3. **Response.** The coordinator routes the named test to the role whose allow-list holds the
   tool. The test is run on the verifier's budget; the role's own budget is untouched. The role answers **with evidence**: new cited calls.
4. **Verdict.**
   - `pass`: the proposal survives.
   - `fail`: with the alternative and the evidence for it.
   - `abstain`: the data cannot separate the two.
5. **Round semantics.**
   - At most **2 rounds**, each with its own verifier turn budget, all inside the run's caps.
   - An `abstain` in round 1 ends the loop: the run abstains.
   - A named test outside every allow-list, or beyond the verifier's budget, counts as `abstain`,
     and is logged.
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
   hold-out and the structural signature, and the hold-out result is recorded.
   - **Under the frozen null rule** (2026-10-07(a)), `structural` is admitted only over a
     **failed** NM, with R3 and a failed hold-out. So on a standing null, a `Verdict` whose
     alternative is `structural` is refused by code (§3.3).
   - The reachable outcomes are then only `pass` (`none`) or `abstain`.
   - S6-02 at tier B, whose null stands, therefore stays admissible-`none`: the branch decision
     3 of 2026-09-30 already allowed. The hold-out test is run and recorded, but cannot admit
     `structural`.
   - Whether a **failed hold-out** should become an admitting case for `structural` when NM
     stands is a change to the frozen null rule. It is a separate question for the lead
     (Q13).

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
- **No model free text in `state.json`.** Statements and sensor notes are templated by code,
  annotations are code-written (§3.3), and assessments go to `messages.jsonl`.
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
same cells, two seeds per cell. **Four asymmetries are not removed by that, and are stated
beside every comparison:**

| asymmetry | what isolates it |
|---|---|
| **(a)** P2's roles call `declared_background`; the frozen P1 does not (decision 1 of 2026-09-30) | **nothing in P2.** Only a matched P1 arm (P1 with the band tool, unfrozen, development only) would remove it (Q5) |
| **(b)** P2's verifier holds `validate` and sees the full hold-out inside the loop, over up to two rounds; P1's hold-out is scored once by the harness | the **verifier-off** ablation |
| **(c)** P2 has no wall-clock limit; P1 had a 90–150 min allowance | not removable afterwards. No frozen revision-2 run hit the allowance; the two killed P1 runs (S0-01 B/C, S3-01 C/B) are in arm 1b, not in the comparison |
| **(d)** P2's verifier has its own budget on top of the run's caps (the lead's ruling on Q9); P1 had one budget | the **verifier-off** ablation |

**H4** predicts a gain only with two or more simultaneous faults (Level 7). **No current
development cell has two faults.** The proposal is to add **S7-01** (`sensor` + `influent`;
defined at B/B) at B/A, B/B and B/C, and **S7-02** (omitted SAO, `structural`, plus an ammonia inhibition shift, `parameter`) at
**A/C, its defined tier**, with two seeds each, as **new development cells**. Not A/A: tier A
has no TAN or VFA (proposal §6.4), and `p2_design.md` §4.4 already records that a smooth
parameter fault can be missed at tier A. A/C is also the tier the scenario was written for. The brief's standing rule is
development cells only, and new cells need the lead's word (Q6).

**The ablations of §6.7 E**, each a configuration switch:
1. verifier off;
2. coordinator off (a fixed route);
3. one specialist off at a time: each of the five specialists (data quality, influent, identifiability, calibration, design), its tools run by code as P0 does, all available from the first build under the Q1 ruling;
4. self-correction off (one round, no response step);
5. persistent state off (each role sees only its own calls).

The procedural P2 is an extra arm: "decision points only".

| stage | cells | seeds | runs | what it can detect |
|---|---|---|---|---|
| development | the ten development cells | 2 | 20 | only differences of 3–4 hits or more |
| H4 (Q6) | S7-01 at B/A, B/B, B/C; S7-02 at A/C | 2 | 8 | descriptive only |
| ablations | the four S7 cells and two clean cells, S0-01 B/B (null stands) and S1-01 B/B (null fails) | 2 | 12 per configuration; 9 configurations (verifier, coordinator, the five specialists, self-correction, persistent state): **108** | only differences of 3–4 hits or more |
| final | the factorial share of §7 | 5 | 480 | the pre-registered analysis |

The code-only floor for each development cell is `reports/p2_power/`: the procedural P2 with
every decision at its fallback. Any agent result is read against it.

## 8. Cost and time

**Per run (an estimate, before any measurement), from one sizing.**

- **P1 for comparison.** P1 costs USD 0.02–0.06 a run with `gpt-5.6-luna`: 10–27 turns and
  0.3–1.4 M tokens, mostly cached input (`reports/p1_pilot.csv`, revision 2). Its blended rate
  is about USD 0.05–0.065 per M tokens (0.08 on its smallest run).
- **The five specialists.** Each is a bounded conversation of roughly half a P1 run: 0.15–0.7 M
  tokens. That is 0.75–3.5 M tokens for all five.
- **The verifier.** The projection is capped at 200 points per output (§4). At about 100 k
  tokens per turn, 14 turns and 2 rounds come to about **2.8 M input tokens per run**.
- **A run in all: about 3.6–6.3 M tokens.**
  - **Cached** (as P1's were), at P1's blended rate: **about USD 0.2–0.4 per run**. The honest
    upper end is about USD 0.40.
  - **Uncached**, at USD 0.20 per M input: about **USD 0.8–1.3 per run**. The verifier alone
    would be USD 0.56.
- **Two budgets (the lead's ruling on Q9).**
  - **The proposers** (the five specialists, and coordination as code) are bound by the run's
    caps (Q8): USD 0.50, 200 requests and 10 M tokens for the pilot. Their 0.75–3.5 M tokens
    hold under those caps, at about USD 0.04–0.23 cached.
  - **The verifier** has its own caps, separate from and in addition to the run's. Proposed:

    | | per round | per run (2 rounds) |
    |---|---|---|
    | requests | 20 | 40 |
    | tokens | 2 M | 4 M |
    | USD | 0.25 | 0.50 |
    | simulator evaluations (its `simulate`, `validate` and the named test) | 40 | 80 |
    | assay units (a named test that is an assay) | 1 | 1 |

    Its expected 2.8 M tokens (about USD 0.14–0.18 cached, 0.56 uncached) fit inside them.
  - **What is reported.** A run's total cost is the proposers' spend plus the verifier's. The
    two are logged separately (`calls.jsonl` attributes each call to its role, and the report
    gives both and their sum).
  - **Against the current caps.** The 6 M-token cap of `p2.yaml` would have been hit at the
    upper end, and USD 0.25 would have bound.

**Per stage (model cost, cached, at USD 0.2–0.4 a run).**

| stage | runs | model cost |
|---|---|---|
| the six-cell pilot (all seven roles, the Q1 ruling; proposers + verifier) | 6 | about USD 1.2–2.4 |
| development | 20 | USD 4–8 |
| H4 cells (Q6) | 8 | USD 1.6–3.2 |
| ablations (9 configurations × 12) | 108 | USD 22–43 |
| the final share | 480 | USD 96–192 |

**A Claude Opus 5.5 arm** (Q2): P1 on Claude cost USD 9.86 for 10 runs, so about USD 3–6 per P2
run and **about USD 1.5–3 k for the final share**.

**Runner time.** The simulator, not the model, sets the wall clock: about 45–60 min a run now,
more if agents call more fits. The live driver runs **serially** (one process). At that rate:

| stage | runner time (serial) |
|---|---|
| the six-cell pilot | about 5–6 h |
| development (20 runs) | about 15–20 h |
| H4 cells (8 runs) | about 6–8 h |
| ablations (108 runs) | about 81–108 h (≈ 90 h) |
| final share (480 runs) | **360–480 runner-hours, 15–20 days** |

Offline parts already run in parallel. Running live parts in parallel, two or three on four
cores, would need the lead's word and a check that the per-run caps stay per run.

**Weeks of work (one session), with all seven roles from the start: 5–7 in all, before
development runs.**
1. The evidence module and the typed schemas, moved and tested offline: 1 week.
2. The agent harness on P1's loop, the allow-list views, the projection and the gateway
   extension: 1–2 weeks.
3. All seven roles, the verifier loop, and the scripted-model tests (every guard rail with a
   negative control and a mutation): 2–3 weeks.
4. The freeze, an offline dry run with scripted models, and the six-cell pilot: 1 week.

**The G4 gate and the descope clause.** By calendar this is about week 11 of the 36-week plan.
The lead decided on 2026-10-25 that all seven roles are built from the start (Q1). The
proposal's week-26 descope clause (P2 with three roles: data quality, calibration and verifier)
is not triggered. It stays the fallback if the build slips toward G4. The ablation switches
make that descope a configuration, not a rewrite.

## 9. The lead's decisions

**Ruled on 2026-10-25.** The lead's words, relayed by the coordinator:
- on Q1: "FOr the first, let's have all the agents";
- on the rest: "Yes to all except that the coordinator should be code. Let the verifier get
  its own budget outside of what you have set."

Every recommendation below therefore stands as decided, with the lead's two points stated in
Q7 and Q9. Q13 was written after the ruling and is **open**.

1. **DECIDED: all seven roles from the start.** Data quality, influent, identifiability,
   calibration, experimental design and verification are built as agents from the first build;
   coordination is code (Q7).
2. **DECIDED: P1's frozen `gpt-5.6-luna` for every arm** of the RQ3 comparison. A Claude arm
   (about USD 3–6 a run, USD 1.5–3 k for the final share) is not part of the plan.
3. **DECIDED: `none` over a failed null, and the verifier when the null stands** (§4, steps
   6–8):
   - a specialist may emit a cited `none` finding, and the verifier challenges it like any
     label;
   - a last-round `fail` whose alternative is `none` concludes `none`, not abstain;
   - the verifier runs when the null stands too, and its hold-out result is recorded. What it
     can conclude there **depends on Q13 (open)**: under the frozen null rule, `pass`
     (`none`) or `abstain` only.
4. **DECIDED: D-1 under a free verifier** (§5). The full hold-out goes to the verifier only. A
   passed hold-out never counts against a non-structural label, stated in the prompt and
   enforced on the `Verdict`.
5. **DECIDED: the `declared_background` asymmetry with P1** (§7 a) is disclosed now. Whether
   to run a matched P1 arm (P1 plus the band tool, unfrozen, development only) is decided after
   the pilot.
6. **DECIDED: new development cells for H4** (§7): S7-01 at B/A, B/B and B/C, and S7-02 at
   **A/C, pending the lead's confirmation of the tier**, two seeds each.
   - The lead approved the four cells on text that said A/A.
   - The check of `588187b` corrected the tier to S7-02's defined A/C: tier A has no TAN or
     VFA.
   - The coordinator has told the lead of the correction, which stands unless the lead
     objects.
7. **DECIDED: the coordinator is code.** The lead stated this explicitly. A model coordinator
   is at most an optional ablation.
8. **DECIDED: the caps** for the run's proposers are USD 0.50, 200 requests and 10 M tokens
   per run for the pilot. After the pilot they are frozen at about twice the measured median.
9. **DECIDED, the lead's variant: the verifier has its own budget**, separate from and in
   addition to the run's caps (§8 gives the proposed per-round and per-run caps).
   - It names one separating test per round.
   - Its `simulate`, `residual_diag` and `validate` calls, and its named test, draw on its own
     budget.
   - The run's reported cost is the proposers' spend plus the verifier's, both logged
     separately.
   - This is an asymmetry with P1, which had one budget (§7 d). The verifier-off ablation
     removes it.
10. **DECIDED: parameter bounds.** Calibration may narrow bounds, logged with a justification
    (redacted from the verifier), and never widen them. A bound hit is never a kinetic
    update.
11. **DECIDED: two rounds.**
12. **DECIDED: the procedural P2 is reported** as the "decision points only" arm, with attempts
    1–3 as its record.

**Also decided with Q1–Q12: assays.** Data quality requests assays only through the design
role's grant (§3.1).

13. **OPEN: a failed hold-out as an admitting case for `structural` when NM stands.** This would
    **change the null rule frozen on 2026-10-07 (a)**: today `structural` is admitted only over
    a failed NM, with R3 and a failed hold-out.
    - *Option (i), keep the rule.* On a standing null the verifier can conclude only `none` or
      `abstain`. S6-02 at tier B stays admissible-`none`, as decision 3 of 2026-09-30
      allowed.
    - *Option (ii), change it.* A failed hold-out, with R3, admits `structural` over a standing
      null. S6 becomes reachable at tier B, but a hold-out that fails by chance on a clean
      cell would then become a structural false alarm.

    *Recommend (i) for the first build.* Record the verifier's hold-out result on every
    standing-null run in the pilot and development, to measure how often the hold-out fails
    on clean cells. Then decide (ii) with that rate in hand.
