"""Simulator layer: truth models, plants, influent generator, observation model, faults.

This package owns the *hidden truth* of the benchmark (proposal §6.1). Ground truth
produced here is written only to ``runs/<id>/truth/`` and must never be reachable from
:mod:`workflows`.
"""
