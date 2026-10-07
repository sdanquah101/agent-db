# P2 offline power run: findings (deliverable 2)

**Run.** 2026-10-07, 17:06 to 22:47 UTC, at commit `e5d4926`. Eight development
cells at their library seeds, horizons and budgets, two at a time on one machine. **No
model call:** every decision point at its declared code fallback. The tables are
`summary.md` and `cells.json` (`python -m scripts.p2_power report`).

**Headline.**
- Offline, P2 labels **none of the six faulted cells correctly**.
- The null is rejected on three of the six faulted cells.
- Three cells end on a **wrong non-`none` label** (`parameter`): S2-01 B/B, S3-01 C/B
  and the clean S0-01 B/C. A `parameter` label carries `kinetic_update`, so these are
  **false kinetic updates**, the failure the benchmark scores hardest.
- The pre-registered §4.5 predictions:
  - **S1-01 B/B holds**: NB failed, gas failed alone, the label is `none`.
  - **S0-01 B/C fails**: the label is `parameter`, where `none` was predicted.

## Per cell

| cell | truth | P2 offline | why |
|---|---|---|---|
| S2-01 B/B | sensor (pH drift) | `parameter` (wrong) | NM failed on gas and pH, so NS cannot fire and no `sensor` finding is possible. A change point on alkalinity and gas admitted `parameter`. |
| S3-01 C/B | influent | `parameter` (wrong) | Only the worst window is outside; the mean closure is inside, so NB stands and `influent` cannot be admitted. NM failed on six channels. A change point on COD, gas and VFA admitted `parameter`; `structural` was also admitted (R3 plus a failed hold-out). |
| S4-01 B/B | state | `none` | The null stands (`null_partial` on COD). The early/late test did not fire. |
| S5-01 A/A | parameter | `none` | The null stands: 3 of 12 statistics outside, no channel failed. Tier A has no TAN or VFA, so the inhibition check is unavailable: the smooth-parameter limit stated in design §4.4. |
| S6-02 B/B | structural | `none` | The null stands: 2 of 35 statistics outside. |
| S8-01 B/B | sensor (gas scale) | `none` (`null_failed_unexplained`) | NS failed on gas alone, and the S1 table holds (CH₄ fraction inside). **The label is blocked only by the offline S1 reading** (`insufficient`, the declared fallback). With a model's `coupled_inside` reading, `sensor` would be admitted: the one cell where the decision point is the whole difference. |
| S0-01 B/C | none | `parameter` (wrong) | NM failed on digestate TS and VS, as predicted. A change point on **gas and pH** (day 15) admitted `parameter`. |
| S1-01 B/B | none | `none` (`null_failed_unexplained`) | NB failed and gas failed alone with VFA partly outside (`null_partial` with NB, the review's R3). No onset passed: there are no candidate onset days, because a uniform offset cannot be dated. |

**A reporting correction.** S8-01's record names the sensor rejection
`coupled_outside`. The S1 table in fact holds, and the label was blocked by the reading
`insufficient`. The code is corrected after the run (`signature_absent` when the table
holds), with a test. No label changes.

## Findings for the coordinator (not acted on)

1. **Admission does not tie the change point to the failed channels.**
   - §4.4 admits `parameter` on NM plus a common change point anywhere. On S0-01 B/C the
     null failed on TS and VS, and the step was on gas and pH. On S2-01 the step was on
     alkalinity and gas, while the failed channels were gas and pH.
   - **Proposal:** a signature must lie on the channels whose null case failed, for
     `parameter` (the change point), `structural` (R3) and `state` (the early/late
     test; `state` already requires it).
   - This proposal is motivated by development cells, so it is the lead's to rule, not
     this session's.
2. **Early change points.** The admitting steps on S0-01 B/C (day 15) and in the smoke
   run (day 13) lie inside the first HRT, where the start-up transient is. P0's R4
   arithmetic has no exclusion window. A step test that ignores the first
   `transient_d` is an option, again for the lead.
3. **`influent` is unreachable when only the worst window is outside.** S3-01's mean
   closure stays inside the band; only `cod_closure_worst` is outside. NB requires both
   on the same side. This is the frozen rule working as written. It is recorded so that
   the influent role's live runs are read with it in mind.
4. **NM on a single fault.** S2-01's pH drift also moved gas outside its envelope.
   Coupled processes put a single-channel fault into NM, where `sensor` cannot be
   admitted. The S1 table already exists to tell a coupled change from an isolated one,
   but NS gates it first.
5. **Cost.** The reference procedure plus the rest used 132–259 evaluations, against
   budgets of 300–750. Wall clock ran 63–111 minutes with two cells sharing the machine;
   S5-01 used 111 of its 120 minutes. Wall clock, not evaluations, binds.
