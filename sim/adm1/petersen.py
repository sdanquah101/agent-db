"""Petersen (stoichiometric) matrix loaded from data and compiled against a parameter set.

The matrix lives in ``configs/adm1/petersen_matrix.yaml`` as expressions over parameter
names. :func:`load_petersen` parses the file; :func:`compile_stoichiometry` evaluates every
expression for a concrete :class:`~sim.adm1.schema.ADM1Parameters` and returns a dense
``(n_components, n_processes)`` array. Expressions are evaluated by walking a restricted
AST (numbers, names, ``+ - * /`` and unary minus, parentheses) so no code is ever
executed from a data file.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim.adm1.schema import GAS_STATE_NAMES, LIQUID_STATE_NAMES, ADM1Parameters

_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def evaluate_expression(expr: str, namespace: Mapping[str, float]) -> float:
    """Evaluate an arithmetic expression over named parameters without ``eval``.

    Args:
        expr: Arithmetic expression such as ``"(1 - Y_su)*f_bu_su"``.
        namespace: Parameter values by name.

    Returns:
        The numeric value.

    Raises:
        ValueError: on any construct outside numbers, names, ``+ - * /`` and unary ``-``/``+``,
            or on an unknown name.
    """
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"cannot parse expression {expr!r}: {exc}") from exc

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in namespace:
                raise ValueError(f"unknown parameter {node.id!r} in expression {expr!r}")
            return float(namespace[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(f"unsupported construct {type(node).__name__} in expression {expr!r}")

    return walk(tree)


class Component(BaseModel):
    """One liquid-phase component with its conserved-quantity contents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unit: str
    description: str
    cod: float = Field(description="kg COD per unit of the component")
    carbon: str | float = Field(description="kmol C per kg COD: a parameter name or a number")
    nitrogen: str | float = Field(description="kmol N per kg COD: a parameter name or a number")
    charge: float = Field(description="kmol charge per kmol of the component")


class Process(BaseModel):
    """One biochemical process: its documented rate and its stoichiometric column."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    rate: str = Field(description="Rate expression, documentation only; code is in rates.py")
    stoichiometry: dict[str, str] = Field(description="component -> expression; missing = 0")


class GasTransfer(BaseModel):
    """A liquid-gas transfer pairing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    liquid: str
    gas: str
    henry: str = Field(description="Name of the temperature-corrected Henry constant")
    cod_per_kmol: float = Field(description="kg COD per kmol of the transferred species")
    liquid_species: Literal["total", "free_co2"] = "total"


class GasComponent(BaseModel):
    """A headspace state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unit: str
    description: str


class PetersenMatrix(BaseModel):
    """The parsed matrix file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    components: tuple[Component, ...]
    processes: tuple[Process, ...]
    gas_transfer: tuple[GasTransfer, ...]
    gas_components: tuple[GasComponent, ...]

    @model_validator(mode="after")
    def _consistent_with_state_order(self) -> PetersenMatrix:
        names = tuple(c.name for c in self.components)
        if names != LIQUID_STATE_NAMES:
            raise ValueError(
                "component order in petersen_matrix.yaml must equal LIQUID_STATE_NAMES; "
                f"got {names}"
            )
        gas = tuple(g.name for g in self.gas_components)
        if gas != GAS_STATE_NAMES:
            raise ValueError(f"gas component order must equal GAS_STATE_NAMES; got {gas}")
        known = set(names)
        for p in self.processes:
            unknown = set(p.stoichiometry) - known
            if unknown:
                raise ValueError(f"process {p.name!r} references unknown components {unknown}")
        for g in self.gas_transfer:
            if g.liquid not in known or g.gas not in gas:
                raise ValueError(f"gas transfer {g.name!r} references unknown states")
        if len({p.name for p in self.processes}) != len(self.processes):
            raise ValueError("process names must be unique")
        return self

    @property
    def process_names(self) -> tuple[str, ...]:
        """Process names in matrix (column) order."""
        return tuple(p.name for p in self.processes)


def load_petersen(path: Path) -> PetersenMatrix:
    """Parse a Petersen-matrix YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return PetersenMatrix.model_validate(raw)


def compile_stoichiometry(matrix: PetersenMatrix, params: ADM1Parameters) -> np.ndarray:
    """Evaluate every stoichiometric expression; returns ``(n_components, n_processes)``."""
    ns = params.namespace()
    index = {c.name: i for i, c in enumerate(matrix.components)}
    out = np.zeros((len(matrix.components), len(matrix.processes)))
    for j, proc in enumerate(matrix.processes):
        for comp, expr in proc.stoichiometry.items():
            out[index[comp], j] = evaluate_expression(expr, ns)
    return out


def _content(value: str | float, ns: Mapping[str, float]) -> float:
    return float(ns[value]) if isinstance(value, str) else float(value)


def conservation_residuals(matrix: PetersenMatrix, params: ADM1Parameters) -> dict[str, np.ndarray]:
    """Per-process balance residuals for COD, carbon, nitrogen and charge.

    Each residual is ``sum_i nu_ij * content_i``; every entry should be zero (to rounding)
    for a correctly transcribed ADM1 matrix.
    """
    ns = params.namespace()
    nu = compile_stoichiometry(matrix, params)
    # Contents are per unit of the component: kmol C (or N) per kg COD for COD-bearing
    # components, and 1 for S_IC / S_IN whose unit already is kmol C / kmol N.
    cod = np.array([c.cod for c in matrix.components])
    carbon = np.array([_content(c.carbon, ns) for c in matrix.components])
    nitrogen = np.array([_content(c.nitrogen, ns) for c in matrix.components])
    charge = np.array([c.charge for c in matrix.components])
    return {
        "COD": cod @ nu,
        "C": carbon @ nu,
        "N": nitrogen @ nu,
        "charge": charge @ nu,
    }
