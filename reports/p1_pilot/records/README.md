# The run records of the two revision-2 arms (for the knowledge audit)

`<prompt_version>/<run_id>/` holds each run's own visible record, copied from
`runs/<run_id>/` of the pilot store: the redacted manifest, `calls.jsonl`,
`workflows/p1/state.json`, `report.json` where present and the model log
(`llm_calls.jsonl`, or `llm_calls.jsonl.gz` where the file exceeded 5 MB). Nothing here
comes from `truth_store/` and nothing is derived from it (rule 1).

`index.csv` sits at this root, outside every run directory, and is the only file that
names a truth label: its `truth_label` column is the **public scenario label** from
`scenarios/<id>.yaml` (the same column `reports/p1_pilot.csv` carries), added so that
the records can be read beside the cell's answer. It is not truth-store content, and no
run directory contains it.
