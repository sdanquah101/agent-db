"""P0 — the scripted pipeline baseline (§6.5).

Built and frozen before any agent code. QC -> balance -> Morris -> Sobol -> profiles
-> screened fit -> MCMC -> validate, with thresholds declared in advance.
"""
