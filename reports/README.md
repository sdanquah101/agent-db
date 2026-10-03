# reports/

Committed outputs of the scored and development runs. Every number here is read from
run logs and summaries, never from a workflow's self-report (rule 3).

## P1 development pilot (`p1_pilot*.csv`, `p1_pilot/`)

Development diagnostics only: never a sweep score, never set beside P0 (P1 is frozen
since 2026-09-30; the sweep scoring waits for the lead's word).

- `p1_pilot/results/<prompt_version>.jsonl`: the pilot driver's results files
  (`scripts/p1_pilot.py`), one line per cell with the runner's summary and the evaluator's
  row, for every arm: old, 1a, 1b, rev2_contended, rev2, rev2_brief, rev2_claude. These
  are the committed inputs of the CSVs; `p1_pilot/results/spec.json` names each arm's
  results file, store, prompt (and brief) hash and CSV for the report writer.
- `p1_pilot/summaries/<prompt_version>_<cell>.json`: each run's `summary.json`.
- `p1_pilot/records/`: the full visible records of the two revision-2 arms (its README).
- `p1_pilot.csv`, `p1_pilot_c1e5829.csv`, `p1_pilot_rev2_contended.csv`: the per-cell
  rows, written by `scripts/p1_pilot_report.py` from the results files and the run
  stores.

**What regenerates.** Only the rev2 and rev2_claude rows regenerate byte for byte: their
run stores are committed (`p1_pilot/records/`). The other five arms (old, 1a, 1b,
rev2_contended, rev2_brief) do not: their stores are not committed, so the three
columns read from a store's `llm_calls.jsonl` and `state.json` (`harness_refusals`,
`evidence_by_label`, `labels_without_localised_evidence`) cannot be rebuilt, and for
rev2_contended's two model-transport failures (S5-01 A/A, S6-02 B/B) `failure_reason`
`connection` is carried explicitly in the results file's summaries, copied from the
committed CSV, because the classifier reads it from the model log. For those five arms
the committed CSVs are the record; every other column of theirs comes from the results
files alone.

To regenerate, from the repository root (the stores are local and ignored):

```
python - <<'PY'
import os
from pathlib import Path
records, stores = Path("reports/p1_pilot/records"), Path("reports/p1_pilot/stores")
for ver in ("rev2", "rev2_claude"):
    for run in (records / ver).iterdir():
        if run.is_dir():
            dst = stores / ver / "runs" / run.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.exists() or os.symlink(run.resolve(), dst)
PY
python -m scripts.p1_pilot_report . reports/p1_pilot/results/spec.json --csv-only
```

The records keep each run under `<prompt_version>/<run_id>/` where a store has
`runs/<run_id>/`, hence the links; the two logs committed as `llm_calls.jsonl.gz` need no
unpacking (`tools.llm.read_transcript` reads the packed file when the plain one is
absent). The command rewrites all three CSVs: the rev2 and rev2_claude rows come back
identical, the other arms' rows with the three store-read columns empty, so check the
diff and keep the committed rows for those.
