# tests/

Run with `pytest -q` from the repository root.

Two tests encode non-negotiable rules from `CLAUDE.md` rather than ordinary behaviour:

- `test_truth_isolation.py` — no module under `workflows/` may import from, or reference
  a path containing, `truth/` (rule 1). It self-checks against a synthetic violating
  file so it cannot pass vacuously while `workflows/` is still mostly empty.
- `test_scenario_schema.py` — the scenario YAML contract (proposal Appendix B) loads,
  round-trips and rejects malformed input.
