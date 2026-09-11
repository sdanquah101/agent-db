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

Twenty rows. Nineteen are one per line of the §6.3 table; `S6-04` was added by the lead's
ruling 1 of 2026-09-09 and is the second staging of the omitted-SAO row (below). The id is
`S<level>-<index>`; the index is an identifier, not a position in that table (`S2-03` is the
Appendix-B example and keeps its number).

| Id | Level | Injection | Truth label | Runs on |
|---|---|---|---|---|
| `S0-01` | 0 | none | none | B, C |
| `S1-01` | 1 | sensor noise ×2, random gaps ×2 | none | B, C |
| `S2-01` | 2 | pH electrode drift −0.01 pH/d from d45 | sensor | B, C, A |
| `S2-02` | 2 | CH₄ analyser flatlined for 6 d from d90 | sensor | B, C, A |
| `S2-03` | 2 | gas-meter scale ×1.08 from d60 | sensor | B, C, A |
| `S3-01` | 3 | feed mislabelled (Dirichlet κ 5) d60–120 | influent | B, C, A |
| `S3-02` | 3 | unrecorded delivery of 3 medians at d90 | influent | B, C, A |
| `S3-03` | 3 | moisture drift −30 % over d30–180, then held | influent | B, C, A |
| `S4-01` | 4 | biomass mis-initialised ×0.25 | state | B, C, A |
| `S4-02` | 4 | informative missingness ×3 | state + sensor | B, C, A |
| `S5-01` | 5 | loss of adaptation: `K_I_nh3` ×0.1 at d120 | parameter | **A only** |
| `S5-02` | 5 | hydrolysis constants ×0.6 at d120 | parameter | B, C, A |
| `S6-01` | 6 | SAO omitted from the fitted model, on the **unadapted** baseline (it bites) | structural | **A only** |
| `S6-02` | 6 | precipitation omitted from the fitted model | structural | B, C |
| `S6-03` | 6 | imperfect mixing, stagnant fraction 0.30 | structural | B, C |
| `S6-04` | 6 | the same SAO omission on the **adapted** baseline, where it carries no flux — the **abstention** row | structural | **A only** |
| `S7-01` | 7 | pH drift **and** feed mislabelled | sensor + influent | B, C |
| `S7-02` | 7 | SAO omitted **and** loss of adaptation | structural + parameter | **A only** |
| `S8-01` | 8 | `bayes_mcmc` always fails, over a gas-meter fault | sensor | B, C |
| `S8-02` | 8 | false operator note, over a gas-meter fault | sensor | B, C |

**The horizon is the plant's, not the row's** (the lead's ruling 3, 2026-09-11): every cell
on Plants B and C runs for **200 days** and every cell on Plant A for **365**, whichever row
it is (`horizon_days` in `configs/plants/`). A row's own `duration_days` is its horizon on
its own plant and is checked to equal it; a Plant B row that also runs on Plant A at Tier A
is re-timed to a year by the matrix (`sim.run.matrix.at_plant_horizon`). Until this ruling
the horizon was the row's — 180 d for Levels 0–4 and 8, 240 d for Levels 5–7 — and, the
field being public, the two values partitioned the ladder: a Plant B/C run at 240 d was
exactly one of the four parameter or structural rows, a strong prior for free (review
finding F2). Uniform per plant, the field says nothing the plant id does not. A year on
Plant A because its transition rows need it: the SAO takeover S5-01 and S7-02 inject
reaches the recorded shares only by day ~300 / ~350 (`docs/f2_horizon_report.md` §17).
The rows that grew from 180 d run their faults further from the same onsets; the four
B/C rows that shrank from 240 d lose their last forty days, which changes no fault window
(the latest ends at d180).

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

* **`S6-01b` is filed as `S6-04`, and the lead has confirmed it** (2026-09-09). The frozen
  id pattern `^S\d+-\d{2}$` admits no letter suffix and the id feeds the opaque run-id
  hash, so the row took the next free Level-6 index. **The pattern stays frozen and the row
  keeps this name.** Settled, not open.
* **There is one answer key per scenario, not one per tier.** `S2-02` flatlines a Tier-B
  instrument, so at Tier A there is nothing to observe and its `correct_conclusion` is
  the Tier-B/C answer. Flagged for the lead in `docs/decisions.md`.
* **`S4-02` has something to scale** (settled 2026-09-09/10; this entry once said the
  opposite). Both flags its fault scales fire on the **hidden state**: overload on true VFA
  above 2.00× its 30-day trailing median (lead's ruling B), foaming on a gas surge above
  1.80× its 30-day trailing median while true VFA is above its own (ruling B3). Measured on
  24 sound Plant B runs at the 200-d matrix horizon they fire on 7.38 % and
  6.34 % of days, in every run (7.12 % and 6.63 % before the lead's ruling 5 of
  2026-09-11 corrected the HSW and FOG degradability centres), against the
  plant's own 7.78–9.18 % FOS/TAC exceedance; the titrimetric sensor convention is
  implemented (ruling A, `sim.observation.channels.titrimetric_fos`, no fitted parameter).
  `docs/g1_anchor_report.md` §5.4 has the four-row tables. What remains thin is the single
  Plant A Tier-A cell, where both triggers fire on well under 1 % of days — recorded, not
  tuned.
* **`S6-01` was inert and is not any more** (lead's ruling 1, 2026-09-09). Acetoclasts and
  syntrophs cannot coexist at a steady state — they compete for one substrate — so Plant A
  is one or the other, and at its adapted constant it is acetoclastic, which left the
  omitted pathway carrying no flux. Plant A now declares **two baselines** and each row
  names the one its answer key assumes:

  | baseline | community | acetate flux carried by | rows |
  |---|---|---|---|
  | `adapted` | acclimated to its ammonia | the acetoclastic methanogens; the syntrophic pathway is present and idle | S5-01, S7-02 (they inject a *loss* of adaptation), and S6-04 |
  | `unadapted` | not acclimated | syntrophic acetate oxidation; the acetoclasts have washed out | S6-01 |

  The numbers — the adapted inhibition constant and what each state measures at — are in
  the **truth-side plant record** `sim/plants/truth/plant_A.yaml` (lead's ruling B5,
  2026-09-10), not in the visible contract and not here: this file is under `scenarios/`,
  which a workflow is barred from, but a table it could be quoted from belongs in one place.
  Both are sound digesters; they are two different ones. **S6-01 and S6-04 are the same
  fault on the two baselines** — on the first the omitted pathway carries the whole acetate
  flux and the correct conclusion is a structural revision; on the second it carries nothing
  and the correct conclusion is that no structural residual is detectable. The pair is what
  lets §6.7 B tell a diagnosis from a workflow that always answers "structural".
