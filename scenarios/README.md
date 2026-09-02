# scenarios/

YAML scenario definitions (proposal §6.3, Appendix B) and the Pydantic schema that
validates them (`schema.py`). Load with `scenarios.load_scenario(path)`.

Each file carries both the injection recipe and the answer key (`truth_label`,
`correct_conclusion`). **Workflows never read these files**; the simulator reads the
recipe and the evaluator reads the key. Scenario IDs are randomised before they reach
any agent (proposal §10).

Scenario definitions are released under CC-BY-4.0 (see `NOTICE`).
