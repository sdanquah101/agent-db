# AD-AgentBench — standing instructions for Claude Code

## What this repository is
An open, reproducible benchmark for agent-supported calibration and discrepancy
diagnosis of anaerobic-digestion (AD) process models. Full design in
`docs/proposal.md` — read it before any non-trivial task. Section numbers
below refer to that document.

## Non-negotiable rules
1. **Hidden truth is never readable by workflows.** Simulator ground truth
   (true parameters, true influent fractions, fault labels) is written only
   to `runs/<id>/truth/`. Nothing under `workflows/` may import from or read
   that path. Enforce with a test.
2. **All workflows use the same tool registry.** No workflow may call
   numerical code outside `tools/`. Budgets (simulator evals, wall-clock,
   assay units) are enforced in the registry, not in workflows.
3. **Every tool call is logged** (name, version, args hash, runtime, outcome)
   to `runs/<id>/calls.jsonl`. Evaluation reads logs only.
4. **Determinism.** Every stochastic component takes an explicit seed. No
   unseeded randomness anywhere.
5. **P0 is built and frozen before any agent code.** Do not weaken P0 to make
   agents look better. If P0 could reasonably do something, it does.
6. **No silent unit choices.** Gas volumes carry standard-condition metadata;
   solids carry wet/dry basis; every quantity has an explicit unit in schemas.

## Repository layout (§9.2)
```
sim/        truth models, plants, influent generator, observation model, fault injection
scenarios/  YAML scenario definitions + ground-truth labels
tools/      registry: pure, versioned, schema-typed functions
workflows/  p0_scripted/ p1_single_agent/ p2_multi_agent/
state/      shared task-state schema (Pydantic) and provenance logger
eval/       metrics, statistical analysis, report generation
anchor/     open real-data ingestion and comparison
configs/    frozen budgets, prompts, model versions
docs/       proposal, benchmark card, design notes, decisions log
tests/
```

## Conventions
- Python 3.11+, `pyproject.toml`, `ruff` for lint/format, `pytest` for tests.
- Pydantic models for every schema (scenarios, task state, tool I/O).
- Type hints everywhere; docstrings on public functions.
- Small, focused commits with descriptive messages. One concern per PR.
- Run `pytest -q` and `ruff check .` before every push. Fix failures; do not skip tests.
- New design decisions go in `docs/decisions.md` (date, decision, reason, alternatives).
- **Follow-on sessions start from their predecessor.** Before starting work that
  continues a previous session's task, confirm that the predecessor's PR is merged
  (`gh`/GitHub: list open PRs and check `docs/milestones.md` on `main` against the
  open PR list). If it is not merged, branch from the predecessor's branch, not from
  `main`, and say so in the PR description. Never re-implement a component that an
  open PR already contains (decision of 2026-09-02, "Duplicate ADM1 core").
- Prefer boring, well-tested libraries (SciPy, NumPy, Pydantic) over clever ones.
- Numerical tolerances and solver settings live in `configs/`, never hard-coded.

## Domain reminders
- ADM1 is stiff. Use implicit solvers (Radau / BDF); test for step-size collapse.
- Sensitivity ≠ identifiability. Screening is Morris → Sobol → profiles/FIM (§13 of the review, §6.2 here).
- A residual is evidence about *where* error entered (sensor / influent / state / parameter / structural), not an instruction to refit kinetics.
- Structural-mismatch scenarios (Level 6) must never be scored on parameter recovery.

## When unsure
Ask in the session rather than guess. If a proposal section is ambiguous,
propose an interpretation, record it in `docs/decisions.md`, and proceed.

## Current milestone
Track progress in `docs/milestones.md`. Update it at the end of every session
with: what was done, what is blocked, what the next session should start on.
