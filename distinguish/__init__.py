"""Distinguishability: the labels a cell's visible record admits (docs/distinguishability.md).

Evaluation side only. It builds the fitted model on the privileged side and reads the
truth store for labels, so no workflow may import it; the rule-1 checker forbids it
(``tests/test_truth_isolation.py``). ``eval/`` does not import it either: it reads the
``admissible.json`` this package writes.
"""
