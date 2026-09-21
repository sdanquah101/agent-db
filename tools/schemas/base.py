"""Base types of the tool schemas: arrays that cross a process boundary, series, windows."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

__all__ = ["Array", "ObservedSeries", "ToolInput", "ToolOutput", "Window"]


def _to_array(value: Any) -> np.ndarray:
    """Coerce a list (JSON) or array to a float array; ``None`` entries become NaN."""
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=float)
    if isinstance(value, list | tuple):
        return np.array([np.nan if v is None else v for v in value], dtype=float)
    if isinstance(value, int | float | np.generic):
        return np.array([float(value)])
    raise TypeError(f"expected an array or a list of numbers, got {type(value).__name__}")


def _from_array(value: np.ndarray) -> list:
    """An array as a nested list; NaN stays NaN (both ends are Python)."""
    return np.asarray(value, dtype=float).tolist()


Array = Annotated[
    np.ndarray,
    BeforeValidator(_to_array),
    PlainSerializer(_from_array, return_type=list, when_used="json"),
    WithJsonSchema(
        {
            "type": "array",
            "description": "A float array (nested lists for more than one dimension); "
            "null entries are missing values",
        }
    ),
]
"""A float array field: numpy in memory, a (nested) list in JSON."""


class ToolInput(BaseModel):
    """Base of every tool's input: unknown fields are an error, arrays are allowed."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)


class ToolOutput(BaseModel):
    """Base of every tool's output."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)


class ObservedSeries(ToolInput):
    """One observed series a tool compares a model output with.

    ``sd`` is the measurement standard deviation used to weight residuals; a scalar applies
    to every point, an array is per point. ``value`` may contain NaN for missing samples,
    which are dropped.
    """

    output: str = Field(description="Model output (observation channel) this series observes")
    t: Array = Field(description="Sample times, d")
    value: Array = Field(description="Observed values, in the output's unit")
    sd: Array = Field(description="Measurement sd, same unit as value; scalar or per point")
    unit: str = Field(default="", description="Unit of `value`, for the record (rule 6)")

    @model_validator(mode="after")
    def _shapes(self) -> ObservedSeries:
        if self.t.ndim != 1 or self.value.shape != self.t.shape:
            raise ValueError("t and value must be 1-D arrays of the same length")
        if self.sd.shape not in ((1,), self.t.shape):
            raise ValueError("sd must be a scalar or one value per sample")
        if np.any(self.sd <= 0.0):
            raise ValueError("sd must be positive")
        if np.any(np.diff(self.t) < 0):
            raise ValueError("t must be non-decreasing")
        return self

    @property
    def observed(self) -> np.ndarray:
        """Indices of the samples that carry a value."""
        return np.flatnonzero(np.isfinite(self.value))

    @property
    def sd_per_point(self) -> np.ndarray:
        """The sd broadcast to every sample."""
        return np.broadcast_to(self.sd, self.t.shape)


class Window(ToolInput):
    """A closed time window ``[start, end]`` in days."""

    start: float = Field(description="Window start, d")
    end: float = Field(description="Window end, d")

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.end <= self.start:
            raise ValueError(f"window end {self.end} must be after start {self.start}")
        return self
