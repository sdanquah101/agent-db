# configs/

Frozen configuration: budgets per (scenario, tier) cell, solver settings and numerical
tolerances, agent prompts, LLM model versions, temperature and retry policy.

Nothing numerical is hard-coded in `sim/`, `tools/` or `workflows/` — it lives here and
is versioned, so that a run can be reproduced from a tag (proposal §7, §13).
