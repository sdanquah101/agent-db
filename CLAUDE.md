# AD-AgentBench — standing instructions for Claude Code

## FIRST ACTION, before anything else

**Read `docs/coordinator.md` and confirm you are not the coordinator.** It names the one
session that coordinates this project, by ID. Compare it with your own session ID and say
which you are, in your first message, before you read another file or run another command.

If you are **not** the coordinator — you almost certainly are not — then: do not spawn
sessions, do not create scheduled routines beyond a check-in on your own PR, do not merge
anything including your own PR, and route every question through the coordinator rather
than sideways to another session. Then list the open PRs before you write any code: if one
already covers your component, stop and say so.

Three of the first six components here were built twice by sessions that did not know
about each other. `docs/coordinator.md` says what that cost and why this check is the
first line of this file.

## What this repository is
An open, reproducible benchmark for agent-supported calibration and discrepancy
diagnosis of anaerobic-digestion (AD) process models. Full design in
`docs/proposal.md` — read it before any non-trivial task. Section numbers
below refer to that document.

## Who starts a component session (read this before starting work)

**The daily routine never launches a component session.** It reviews, subscribes,
reports and salvages, and nothing else. A component session is started **only** when the
lead sends `launch: <component>` to the coordinating session, and the lead sends it after
the previous component's PR has merged.

Everything the lead writes as a "reply to paste" goes to the coordinating session; if a
child session has a question, the coordinator relays it. A child session never spawns
another session.

**Why (2026-09-03).** Three of the first six components were built twice — the ADM1 core
(PR #2 vs #4), the plant layer (#6 vs #7) and the observation model with fault injection
(#11 vs #12). Every collision had the same shape: the routine launched a component
because its plan said so, while a session was already building it because a decision had
reached that session directly. Adding "check the open PRs" to this file did not stop it,
because the duplicate work had usually already started by the time anyone looked.
Removing the routine's launch authority removes the failure mode; it costs the lead one
message per component.

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
  open PR already contains (decision of 2026-09-02, "Duplicate ADM1 core"). This check
  is a backstop, not the defence: the defence is that only the lead launches a component
  session (see "Who starts a component session" above). Listing the open PRs is still
  the first thing a session does, and it lists *all* of them — checking only that the
  named predecessor merged is what let PR #12 duplicate PR #11.
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
