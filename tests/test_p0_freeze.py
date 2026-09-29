"""The P0 freeze check: one pilot cell reproduces its golden state and summary.

The coordinator's decision of 2026-09-29: the infrastructure changes that followed the
killed P1 runs (the cancel-on-kill path through the meter and the registry, the P1
duration guard, the per-cell batch driver) change no completed run. The check is the
positive-control driver's own normalised comparison (``scripts.positive_control._normalise``:
no wall clock, no log positions, no call lists, the run id masked) of a full P0 pilot cell,
S0-01 plant B tier A, against the golden run made at ``3ea1dee`` before those changes
(``scripts/p0_freeze_golden.py``).

It takes about an hour and must run alone on the machine (P0's plan reads the measured
evaluation rate, so a loaded container can change what it does), so it is deselected by
default: ``pytest -m p0_freeze``, before any live P1 cell.
"""

from __future__ import annotations

import pytest

from scripts.p0_freeze_golden import (
    CELL,
    normalised_state_digest,
    normalised_summary,
    run_cell,
    summary_digest,
)

# The golden run: S0-01 B/A, P0 at 3ea1dee, 2026-09-29, run_8f14dcebe5e2, 61 min:
# label none, 202 evaluations, 23 calls.
GOLDEN = {
    "state_sha256": "156b5c9e86f5742ad55c24681b7bcd53cdfcc1bc8b9c876d8b1ff2bbd2ada457",
    "summary_sha256": "57b705d9aa9795a5bd68cb1fa99551ea98394252b8610a5fe227951c5df5cca6",
    "readable": {"label": "none", "simulator_evals_used": 202, "n_calls": 23},
}


@pytest.mark.p0_freeze
def test_the_p0_pilot_cell_reproduces_its_golden_run(tmp_path):
    assert CELL == ("S0-01", "B", "A")
    run_id, state, summary = run_cell(tmp_path / "store")
    # the readable part first, so a difference names itself before the digests do
    kept = normalised_summary(summary, run_id)
    for key, value in GOLDEN["readable"].items():
        assert kept.get(key) == value, (key, kept.get(key), value)
    assert normalised_state_digest(state, run_id) == GOLDEN["state_sha256"]
    assert summary_digest(summary, run_id) == GOLDEN["summary_sha256"]
