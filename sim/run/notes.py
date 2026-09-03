"""Operator log notes, and the Level-8 note that asserts a false cause (§6.3).

The `adversarial_log_note` fault is one of the two Level-8 rows: "an operator note asserts
a false cause", and the correct conclusion is to "treat note as evidence, not instruction;
verify against data". :mod:`sim.faults.plan` routes it to the ``workflow`` layer and says
it is *applied by the run harness*; this module is that application.

**Every run carries notes.** If a notes file existed only in the adversarial run, its
presence would be the answer and the scenario would test nothing. So each run gets a few
true, mundane notes from ``configs/faults/log_notes.yaml`` at seeded random days, and the
adversarial run gets one more — a plausible misdiagnosis of the fault that was actually
injected, pointing at the kinetic parameters that §6.7 B counts as a false kinetic drift.

The notes are **observations**, not truth: they are written to
``runs/<id>/observations/operator_notes.json``. Nothing here reads a truth trajectory, and
a benign note never mentions the run's state, so a note cannot leak what the record does
not already show.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LOG_NOTES_CONFIG", "LogNote", "LogNotesConfig", "load_log_notes", "operator_notes"]

LOG_NOTES_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "faults" / "log_notes.yaml"


class LogNotesConfig(BaseModel):
    """``configs/faults/log_notes.yaml``: the note catalogue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    benign_per_100_d: Annotated[float, Field(ge=0.0)] = Field(
        description="Expected number of benign notes per 100 d of run, 1/100 d"
    )
    benign: tuple[str, ...] = Field(min_length=1, description="True, uninformative notes")
    adversarial: dict[str, str | dict[str, str]] = Field(
        description="``default`` plus ``by_scenario``: the false-cause note per scenario"
    )

    def adversarial_for(self, scenario_id: str) -> str:
        """The false-cause note for one scenario, falling back to the default.

        Raises:
            ValueError: If the config declares neither a per-scenario note nor a default.
        """
        by_scenario = self.adversarial.get("by_scenario", {})
        if isinstance(by_scenario, dict) and scenario_id in by_scenario:
            return str(by_scenario[scenario_id]).strip()
        default = self.adversarial.get("default")
        if not isinstance(default, str):
            raise ValueError(f"no adversarial note for {scenario_id!r} and no default declared")
        return default.strip()


def load_log_notes(path: Path = LOG_NOTES_CONFIG) -> LogNotesConfig:
    """Parse the note catalogue.

    Raises:
        ValueError: If the file is not a YAML mapping.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return LogNotesConfig.model_validate(raw)


@dataclass(frozen=True)
class LogNote:
    """One note in the operator's log, as a workflow sees it."""

    day: int
    """Day of the run the note was written, d from t = 0."""
    author: str
    """Who wrote it: ``"operator"`` for the routine notes, ``"process_engineer"`` for the
    Level-8 note, because a workflow may reasonably weigh those differently."""
    text: str

    def as_dict(self) -> dict[str, object]:
        """The note as a JSON-safe mapping."""
        return dict(asdict(self))


def operator_notes(
    n_days: int,
    seed: int,
    *,
    adversarial: bool,
    scenario_id: str,
    adversarial_day: int = 0,
    config: LogNotesConfig | None = None,
) -> tuple[LogNote, ...]:
    """The notes in one run's log, ordered by day.

    Args:
        n_days: Length of the run, d.
        seed: Seed of the notes stream (stream 4 of :mod:`sim.run.seeds`).
        adversarial: Whether the scenario injects ``adversarial_log_note``.
        scenario_id: Which scenario's false-cause note to use.
        adversarial_day: Day the false-cause note is written. The harness passes the
            fault's onset day, so the note appears once there is something to misdiagnose.
        config: The catalogue (default: ``configs/faults/log_notes.yaml``).

    Returns:
        The notes, sorted by day and then by author.

    Raises:
        ValueError: If the horizon is empty.
    """
    if n_days < 1:
        raise ValueError("n_days must be positive")
    cfg = config or load_log_notes()
    rng = np.random.default_rng(seed)
    expected = cfg.benign_per_100_d * n_days / 100.0
    # Poisson count, then days without replacement: two notes on one day would read as a
    # duplicated entry rather than as two events.
    count = int(min(rng.poisson(expected), n_days, len(cfg.benign)))
    days = np.sort(rng.choice(n_days, size=count, replace=False)) if count else np.empty(0, int)
    texts = rng.choice(len(cfg.benign), size=count, replace=False) if count else np.empty(0, int)
    notes = [
        LogNote(day=int(d), author="operator", text=cfg.benign[int(i)])
        for d, i in zip(days, texts, strict=True)
    ]
    if adversarial:
        day = int(np.clip(adversarial_day, 0, n_days - 1))
        notes.append(
            LogNote(day=day, author="process_engineer", text=cfg.adversarial_for(scenario_id))
        )
    return tuple(sorted(notes, key=lambda n: (n.day, n.author)))
