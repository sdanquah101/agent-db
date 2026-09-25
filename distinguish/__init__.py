"""Distinguishability: the labels a cell's visible record admits (docs/distinguishability.md).

Evaluation side only. It rebuilds the truth simulation and reads the truth store for the
seeds and the answer key, so no workflow may import it; the rule-1 checker forbids it
(``tests/test_truth_isolation.py``). ``eval/`` does not import it either: it reads the
``admissible.json`` this package writes.
"""
