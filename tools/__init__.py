"""Frozen tool registry (§6.2): pure, versioned, schema-typed numerical functions.

Every workflow reaches numerical code only through this package. Budgets (simulator
evaluations, wall-clock, assay units) and call logging are enforced here, not in
workflows.
"""
