# AD-AgentBench

An open, reproducible benchmark for **agent-supported calibration and discrepancy
diagnosis of anaerobic-digestion (AD) process models**.

Anaerobic-digestion models such as ADM1 are routinely calibrated to sparse industrial
data in which influent composition, latent states, sensor bias, kinetic parameters and
structural error all compensate for one another. A better fit can mean worse parameters.
The first question a good engineer asks of a model–data mismatch — *where did this error
enter?* — is rarely asked by automated workflows and never scored. Real plant data cannot
settle whether AI agents help with this task, because on a real plant the true parameters
and the true cause of any discrepancy are unknown.

AD-AgentBench is the environment in which that claim, or its negation, can be tested. It
provides a simulated industrial plant with a **hidden truth model** (an extended ADM1
with syntrophic acetate oxidation, ionic-strength correction and a precipitation sink),
realistic stochastic influent, an explicit observation model with three instrumentation
tiers, and a declarative library of injected faults — sensor drift, mislabelled feed,
mis-initialised biomass, true parameter shifts, omitted mechanisms, and compounds of
these — each with a labelled ground-truth cause and a correct conclusion. A frozen,
versioned registry of conventional tools (data QC, mass balance, Morris/Sobol screening,
profile likelihood, least squares, differential evolution, MCMC, ensemble Kalman
filtering, residual diagnostics, value-of-information for assays) is exposed identically
to three workflows: a **scripted pipeline (P0)**, a **single constrained LLM agent
(P1)** and a **task-specialised multi-agent system with an independent verifier (P2)**.
All three run under identical data, tools, simulator-evaluation, wall-clock and assay
budgets. Evaluation measures not only fit and interval coverage but attribution accuracy,
false kinetic drift, correct abstention, unsupported claims, and cost.

Full design: [`docs/proposal.md`](docs/proposal.md). Standing engineering rules:
[`CLAUDE.md`](CLAUDE.md). Decisions: [`docs/decisions.md`](docs/decisions.md). Progress:
[`docs/milestones.md`](docs/milestones.md).

## Status

Milestone 1 (proposal §9.3, weeks 1–2): repository scaffold and selection of the base
ADM1 implementation ([`docs/adm1_comparison.md`](docs/adm1_comparison.md); accepted with
conditions, see the decisions log) and open-dataset identification (see below). Done.

Milestone 2 (weeks 3–6), in progress: `sim/adm1/` implements standard ADM1 as a
Petersen-matrix model (matrix and BSM2 parameters as data under `configs/adm1/`,
algebraic pH, BSM2 gas phase, SciPy BDF/Radau) and is ring-tested against bsm2-python on
Probes 1–2 and the 280-day BSM2 dynamic influent (`tests/test_adm1_ring.py`). The §6.1
extensions — syntrophic acetate oxidation, Davies ionic-strength correction, the
carbonate second dissociation and calcite precipitation — are declared as additional
rows and switches in `configs/adm1/extensions.yaml` and compiled onto the base matrix by
`sim/adm1/extensions.py` (`tests/test_adm1_extensions.py`). The three plants and the
influent generator are not started.

Real-data anchor (proposal §8): open datasets identified, characterised and, where
openly licensed, fetched into `anchor/raw/` by `python -m anchor.fetch` from
`anchor/MANIFEST.json`. See [`docs/anchor_datasets.md`](docs/anchor_datasets.md) for the
comparison table and the anchoring recommendation, which needs domain sign-off.

## Layout

```
sim/        truth models, plants, influent generator, observation model, fault injection
scenarios/  YAML scenario definitions + ground-truth labels, and their Pydantic schema
tools/      registry: pure, versioned, schema-typed functions; budgets enforced here
workflows/  p0_scripted/ p1_single_agent/ p2_multi_agent/
state/      shared task-state schema (Pydantic) and provenance logger
eval/       metrics, statistical analysis, report generation (reads logs only)
anchor/     open real-data ingestion and comparison
configs/    frozen budgets, solver settings, prompts, model versions
scripts/    disposable harnesses (e.g. the ADM1 candidate probes)
docs/       proposal, benchmark card, design notes, decisions log, milestones
tests/
```

Two rules are enforced by tests rather than convention: nothing under `workflows/` may
import from, or open a path containing, `truth/` (`tests/test_truth_isolation.py`), and
every committed scenario must satisfy the Appendix-B schema
(`tests/test_scenario_schema.py`).

## Development

Python ≥ 3.11.

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest -q
```

CI runs the same three commands on every push and pull request.

## Licence

Code is released under the Apache License 2.0 (`LICENSE`). Scenario definitions
(`scenarios/`), benchmark results and figures are released under
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) (`NOTICE`).
