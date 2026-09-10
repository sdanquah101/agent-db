"""The truth-side plant record: what a plant's declared baselines *are*, numerically.

The plant contract (``configs/plants/plant_<id>.yaml``, :mod:`sim.plants.schema`) is
**visible** to workflows. Since the lead's ruling B5 of 2026-09-10 it declares a plant's
baselines only *qualitatively* — that Plant A has an acclimated community state and an
unacclimated one, and what kind of digester each is — and nothing numeric about either.
The numbers that used to sit beside those declarations (the adapted inhibition constant,
the measured biomass, acetate and ammonia of each state) are the answer to the question
the Level-6 rows ask: with them in a visible file, redacting ``baseline`` from the manifest
hid nothing, because the run's own acetate read off against a published table said which
state the digester was in (whole-branch review, finding B5).

So they live **here**, in a record the harness reads and a workflow cannot: the module is
``sim.plants.truth`` and the file is ``sim/plants/truth/plant_<id>.yaml``, and both spell
``truth`` as a segment, which is exactly what the static checker in
``tests/test_truth_isolation.py`` flags. The record is not under ``configs/`` on purpose —
``configs/`` is the declared, visible contract — and it is not under ``truth_store/``
either, because it is a property of the *plant*, not of a run; the run's realised
parameters (which carry the adapted constant once applied) are written to the truth store
as before.

Plants B and C have no record: they declare no baselines and keep the ADM1 defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim.plants.schema import PlantConfig, PositiveStatistic

TRUTH_RECORD_DIR = Path(__file__).resolve().parent
"""Where the per-plant truth records live (``sim/plants/truth/plant_<id>.yaml``)."""

_Pos = Annotated[float, Field(gt=0)]

__all__ = [
    "TRUTH_RECORD_DIR",
    "Adaptation",
    "BaselineTruth",
    "PlantTruthRecord",
    "load_plant_truth",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Adaptation(_Frozen):
    """Truth-model constants this plant's community has adapted to (lead's ruling 2, 2026-09-03).

    ADM1's kinetic defaults describe a mesophilic sewage-sludge community. A digester that
    has run for years at high ammonia does not have that community: acetoclastic
    methanogens acclimate, and their free-ammonia inhibition constant rises by an order of
    magnitude. Treating that as a **plant property** rather than as a fault is what lets
    Plant A hold a genuine steady state with both acetoclastic and syntrophic pathways
    present — the state the Level-5/6/7 ammonia rows are supposed to start from.

    Before this existed, Plant A at the ADM1 default washed its acetoclasts out entirely
    within ~800 d, and the harness had to stop the burn-in early to keep a mixed community.
    That workaround is gone (gate G1, 2026-09-03).

    Until 2026-09-10 this block was *declared* in the visible plant contract. It is now
    truth-side (ruling B5): a workflow is told the plant has an acclimated community state,
    not what constant that community carries.
    """

    K_I_nh3: _Pos | None = Field(
        default=None,
        description="Adapted free-ammonia inhibition constant of the acetoclastic "
        "methanogens, kmol N/m3. None keeps the ADM1 default.",
    )
    source: str = Field(default="", description="Evidence for the adapted value")
    note: str = ""


class BaselineTruth(_Frozen):
    """What one declared baseline is, numerically: its adaptation and what it measures as."""

    name: str = Field(description="The declared baseline this record describes")
    adaptation: Adaptation | None = Field(
        default=None,
        description="The community adaptation of this baseline; None keeps ADM1's defaults",
    )
    expected_digestate_tan: PositiveStatistic | None = Field(
        default=None,
        description="Measured digestate total ammonia of this baseline, kg N/m3",
    )
    measured: dict[str, float] = Field(
        default_factory=dict,
        description="Measured steady-state figures of this baseline (biomass, acetate, pH, "
        "CH4 ...), as recorded when the baseline was declared; documentation, not inputs",
    )
    note: str = ""


class PlantTruthRecord(_Frozen):
    """The truth-side record of one plant's baselines."""

    plant: Literal["A", "B", "C"]
    version: Annotated[int, Field(ge=1)]
    baselines: tuple[BaselineTruth, ...] = Field(min_length=1)
    note: str = ""

    @model_validator(mode="after")
    def _unique(self) -> PlantTruthRecord:
        names = [b.name for b in self.baselines]
        if len(set(names)) != len(names):
            raise ValueError("baseline names must be unique")
        return self

    def baseline(self, name: str) -> BaselineTruth:
        """The record of the named baseline.

        Raises:
            ValueError: If the record has no baseline of that name.
        """
        for candidate in self.baselines:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"plant {self.plant} truth record has no baseline {name!r}; "
            f"it has {sorted(b.name for b in self.baselines)}"
        )


def load_plant_truth(
    plant: PlantConfig, record_dir: Path = TRUTH_RECORD_DIR
) -> PlantTruthRecord | None:
    """The truth record of a plant, checked against its declared contract.

    Args:
        plant: The plant's visible configuration.
        record_dir: Where the records live (a test can point this elsewhere).

    Returns:
        The record, or None for a plant that declares no baselines and has no record
        (Plants B and C: the ADM1 defaults throughout).

    Raises:
        ValueError: If the record is for another plant, or if the set of baselines it
            describes is not exactly the set the contract declares — the contract and the
            record are two halves of one declaration and must not disagree; or if the
            plant declares baselines and no record exists to say what they are.
    """
    path = record_dir / f"plant_{plant.id}.yaml"
    declared = {b.name for b in plant.baselines}
    if not path.is_file():
        if declared:
            raise ValueError(
                f"plant {plant.id} declares baselines {sorted(declared)} but has no truth "
                f"record at {path}"
            )
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    record = PlantTruthRecord.model_validate(raw)
    if record.plant != plant.id:
        raise ValueError(f"{path}: record is for plant {record.plant!r}, config is {plant.id!r}")
    described = {b.name for b in record.baselines}
    if described != declared:
        raise ValueError(
            f"plant {plant.id}: the contract declares baselines {sorted(declared)} and the "
            f"truth record describes {sorted(described)}; they must agree"
        )
    return record
