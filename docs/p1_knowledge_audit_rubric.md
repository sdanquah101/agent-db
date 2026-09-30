# Knowledge audit of the P1 revision-2 transcripts — rubric (coordinator, 2026-09-30)

Purpose: decide whether P1's wrong labels came from process-literate reasoning misapplied,
or from reasoning that does not use the AD process signatures at all. Reads logs only:
reports/p1_pilot/records/<arm>/<run_id>/{state.json, calls.jsonl, llm_calls.jsonl(.gz)}
on claude/p1-anthropic-arm, plus the scenario YAMLs for the truth label and the fault
description (scenarios/), the benchmark card and docs/proposal.md §6.3 for the class
definitions. Never read truth_store/.

## A. The diagnostic signatures (what a process-literate reader would use)

Grade each recorded evidence statement and each reasoning passage against these; cite
which signature it used, misused or ignored.

S1 Sensor fault vs process change: a step or drift in ONE measured channel while the
   channels it is physically coupled to stay consistent (gas volume vs CH4 fraction vs
   VFA/pH/alkalinity; pH vs alkalinity vs VFA; TAN vs feed N) points to the instrument.
   A change that appears coherently across coupled channels points to the process.
S2 Feed under/over-recording: a persistent gap between the COD (or VS) fed and the
   COD accounted for in gas plus effluent, with the gas deficit tracking the feed record
   discrepancy over time, and no change in VFA/pH (the process is stable, the books are
   wrong). Onset coincides with a feed-log change, not with a process transient.
S3 Overload / inhibition (a process upset, which P1 may still have to attribute to its
   upstream cause): gradual gas decline with VFA rise and pH/alkalinity fall (organic
   overload); VFA rise with elevated TAN and pH held high (ammonia inhibition); CH4
   fraction falling with total gas (acidification). Time constants of days to weeks, not
   steps.
S4 Initial-state error: an early transient in residuals that decays with the hydraulic
   or solids retention time and vanishes later in the record; late-window residuals
   clean. Early_bias_z large, late_bias_z small.
S5 Parameter (kinetic) error: a persistent, smooth mismatch across the whole record that
   the calibration reduces without pushing estimates outside their prior boxes, coherent
   across coupled channels, no step, no early-only transient.
S6 Structural mismatch: a residual pattern the fitted model cannot reproduce at any
   parameter value (e.g. two-zone mixing, a missing inhibition term): fits improve only
   by parameters leaving their boxes; residuals remain serially structured; validation on
   the hold-out fails while calibration looks acceptable.
S7 The null case: residuals within the declared instrument noise once the background
   misfit of the model is accounted for; no time-localised, channel-coherent pattern; the
   calibration's intervals cover; the hold-out validates. `none` is the correct label.
S8 Mass and charge balance as arbiter: a closed balance rules out feed error; an open
   balance with clean sensors points to the feed record; the balance cannot by itself
   decide kinetics vs structure.

## B. What to grade, per run

For each of the twenty runs (ten rev2/luna, ten rev2/claude):
1. List every evidence item recorded in state.json (rule, label, statement, values,
   calls) and every reasoning passage in llm_calls.jsonl where the model argues toward
   or away from a label (quote briefly; cite turn numbers).
2. For each: which signature(s) S1–S8 it invokes, explicitly or implicitly; whether the
   invocation is correct in principle (would a process engineer accept the inference
   form?); whether the record supports it (check the cited tool outputs in calls.jsonl /
   the tool_result blocks); grade: LITERATE-CORRECT / LITERATE-MISAPPLIED /
   NOT-PROCESS-BASED (e.g. a label chosen from vocabulary, prior frequency, or a single
   number without a mechanism) / UNSUPPORTED (no cited evidence).
3. The null case: did the model ever test S7 (state the background misfit, compare
   residuals to the declared noise, look for a time-localised pattern) before choosing a
   label? If it did and still labelled, why? If it never did, note where in the loop it
   would have been natural.
4. Coupled-channel reasoning: did it ever compare coupled channels (S1) before calling a
   sensor fault, or compare balance closure (S8) before calling influent?
5. Where its final label was wrong, name the signature that would have given the truth
   and whether the model had the tool output it needed (it ran the tool but did not read
   it that way) or never ran the tool.

## C. Output

- A per-run table (arm, cell, truth, label, number of evidence items, grades count,
  null-case tested Y/N, coupled-channel check Y/N, missing signature, tool run but
  misread / never run).
- Totals per arm: fraction of evidence items in each grade; runs where the null case
  was tested; runs where the deciding signature's tool output was available but not used.
- The one-paragraph answer to the audit question: process-literate-but-misapplied, or
  not process-based, or mixed, with the three most telling quotations.
- Differences between the two models in kind of reasoning (not in score).
- Implications for P2 procedural roles: which signatures must be encoded as steps, and
  which decisions can be left to the model.
