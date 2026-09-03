# scenarios/

YAML scenario definitions (proposal §6.3, Appendix B) and the Pydantic schema that
validates them (`schema.py`). Load one with `scenarios.load_scenario(path)`, or the whole
library with `sim.run.matrix.load_library()`.

Each file carries both the injection recipe and the answer key (`truth_label`,
`correct_conclusion`). **Workflows never read these files**; the simulator reads the
recipe and the evaluator reads the key. Scenario IDs are randomised before they reach
any agent (proposal §10) — which is also why a run directory is named by an opaque hash
rather than by its scenario.

Scenario definitions are released under CC-BY-4.0 (see `NOTICE`).

## The ladder

Nineteen rows, one per line of the §6.3 table. The id is `S<level>-<index>`; the index is
an identifier, not a position in that table (`S2-03` is the Appendix-B example and keeps
its number).

| Id | Level | Injection | Truth label | Runs on |
|---|---|---|---|---|
| `S0-01` | 0 | none | none | B, C |
| `S1-01` | 1 | sensor noise ×2, random gaps ×2 | none | B, C |
| `S2-01` | 2 | pH electrode drift −0.01 pH/d from d45 | sensor | B, C, A |
| `S2-02` | 2 | CH₄ analyser flatlined for 6 d from d90 | sensor | B, C, A |
| `S2-03` | 2 | gas-meter scale ×1.08 from d60 | sensor | B, C, A |
| `S3-01` | 3 | feed mislabelled (Dirichlet κ 5) d60–120 | influent | B, C, A |
| `S3-02` | 3 | unrecorded delivery of 3 medians at d90 | influent | B, C, A |
| `S3-03` | 3 | moisture drift −30 % over d30–180 | influent | B, C, A |
| `S4-01` | 4 | biomass mis-initialised ×0.25 | state | B, C, A |
| `S4-02` | 4 | informative missingness ×3 | state + sensor | B, C, A |
| `S5-01` | 5 | loss of adaptation: `K_I_nh3` ×0.1 at d120 | parameter | **A only** |
| `S5-02` | 5 | hydrolysis constants ×0.6 at d120 | parameter | B, C, A |
| `S6-01` | 6 | SAO omitted from the fitted model | structural | **A only** |
| `S6-02` | 6 | precipitation omitted from the fitted model | structural | B, C |
| `S6-03` | 6 | imperfect mixing, stagnant fraction 0.30 | structural | B, C |
| `S7-01` | 7 | pH drift **and** feed mislabelled | sensor + influent | B, C |
| `S7-02` | 7 | SAO omitted **and** loss of adaptation | structural + parameter | **A only** |
| `S8-01` | 8 | `bayes_mcmc` always fails, over a gas-meter fault | sensor | B, C |
| `S8-02` | 8 | false operator note, over a gas-meter fault | sensor | B, C |

Plant A runs the Level 2–5 rows at **Tier A only**; the three ammonia rows run at all
three tiers and nowhere but Plant A (`sim/run/matrix.py`, and the decisions entry of
2026-09-03). Plants B and C run the sixteen non-ammonia rows at all three tiers.

## Conventions

* **Magnitudes are not free.** `sim/faults/schema.py` declares the unit, the admissible
  range and the target of every fault type, and `build_plan` validates against it. Each
  file's header comment says *why* its magnitude is the value it is, inside that range;
  the judgement calls are collected in `docs/decisions.md` (2026-09-03).
* **Seeds are `1000 + 10 × level + index`.** Explicit and unique — CLAUDE.md rule 4
  forbids an implicit one and `sim.run.matrix` refuses a scenario without one.
* **`notes` says what a workflow should notice**, and what the characteristic failure is.
  It is for maintainers and reviewers and is never shown to a workflow.
* **Level 8 rows carry an underlying fault.** The §6.3 table gives them no truth label,
  but the frozen schema requires one and forbids `none` above Level 1 — and a tool-failure
  row needs a diagnostic task to fall back *to*, and a false-cause note needs a true cause
  to be false about. Both carry the Appendix-B gas-meter fault (decisions log,
  2026-09-03).

## Known gaps, recorded rather than worked around

* **There is one answer key per scenario, not one per tier.** `S2-02` flatlines a Tier-B
  instrument, so at Tier A there is nothing to observe and its `correct_conclusion` is
  the Tier-B/C answer. Flagged for the lead in `docs/decisions.md`.
* **`S4-02` is currently weak on a healthy digester.** The overload flag it scales fires
  on no day at all in most sound Plant B runs and on 3.3 % in the worst, against the
  plant's ~8 %. Measured in `docs/g1_anchor_report.md` §5.
* **`S6-01` is inert.** Plant A declares an adapted acetoclastic inhibition constant and is
  acetoclastic at baseline, so omitting the syntrophic pathway from the fitted model omits
  one that carries no flux. Acetoclasts and syntrophs cannot coexist at a steady state —
  they compete for one substrate — so the other two ammonia rows are staged as
  *transitions* instead. Three ways out are written into `S6-01.yaml`, awaiting the lead.
