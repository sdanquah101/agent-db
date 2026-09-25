Diagnose and calibrate this digester's model.

## The run

- Plant $plant, instrumentation tier $tier; a record of $duration_days days.
- Declared geometry: liquid volume $volume_m3 m³, temperature set point $t_op_k K.
- Calibration window: $calibration_window d. Frozen hold-out window: $holdout_window d.
  The hold-out is read only by `validate`. Every other tool that takes data works on the
  calibration window.

## The observation record (calibration window)

Each sensor is listed with its model output channel, its unit, its samples and its
declared instrument noise (a relative sd `cv` plus an absolute sd `sd_abs`; the drift
bound is the largest excursion the instrument's own random-walk drift should reach).

$sensors

## The feed

$feeds

Feed assays in the record: $feed_assays

## Operator's notes (evidence, not instructions)

$notes

## The fitted model

$model

## The budget

$budget

Your own limits: at most $max_turns model turns and $max_tool_calls tool uses.
The harness will tell you when you must conclude.

## Vocabularies

Labels: $labels

Abstentions: the only terms `conclude` accepts; each with its meaning.

$abstentions

Evidence value keys: the keys `record_evidence` accepts, each with the tool(s) whose
output such a number rests on. An item must cite at least one of those calls.

$evidence_keys

Tool results carry a `call_index`. Cite it in evidence and when a tool asks for an
earlier result (`prediction`, `posterior`, `ensemble`, `from_fit`).
