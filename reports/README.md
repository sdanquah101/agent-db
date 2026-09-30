# reports/

Committed outputs of the scored and development runs. Every number here is read from
run logs and summaries, never from a workflow's self-report (rule 3).

## P1 development pilot (`p1_pilot*.csv`, `p1_pilot/`)

Development diagnostics only: never a sweep score, never set beside P0 (P1 is frozen
since 2026-09-30; the sweep scoring waits for the lead's word).

- `p1_pilot/results/<prompt_version>.jsonl`: the pilot driver's results files
  (`scripts/p1_pilot.py`), one line per cell with the runner's summary and the evaluator's
  row, for every arm: old, 1a, 1b, rev2_contended, rev2, rev2_brief, rev2_claude. These
  are the committed inputs of the CSVs.
- `p1_pilot/summaries/<prompt_version>_<cell>.json`: each run's `summary.json`.
- `p1_pilot/records/`: the full visible records of the two revision-2 arms (its README).
- `p1_pilot.csv`, `p1_pilot_c1e5829.csv`, `p1_pilot_rev2_contended.csv`: the per-cell
  rows, written by `scripts/p1_pilot_report.py` from the results files and the run
  stores (a spec names each arm's results file, store, prompt hash and CSV). Every
  column but three comes from the results files alone; `harness_refusals`,
  `evidence_by_label` and `labels_without_localised_evidence` are read from the store's
  `llm_calls.jsonl` and `state.json`, which are committed for the two revision-2 arms
  only (`p1_pilot/records/`, under `<prompt_version>/<run_id>/` rather than a store's
  `runs/<run_id>/`; two logs there are gzipped). The results files are the record the
  CSVs are checked against.
