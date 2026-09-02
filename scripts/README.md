# scripts/

Disposable, non-library code: one-off probes, evaluation harnesses and migration
helpers. Nothing here is imported by `sim/`, `tools/`, `workflows/` or `eval/`, and
nothing here is part of the benchmark's public interface.

- `adm1_candidates/` — the Milestone-1 harness used to compare candidate open ADM1
  implementations. Its results are written up in `docs/adm1_comparison.md`.
