"""The Petersen matrix as data: loading, safe evaluation and conservation."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest

from sim.adm1 import compile_stoichiometry, conservation_residuals
from sim.adm1.petersen import evaluate_expression
from sim.adm1.rates import PROCESS_NAMES
from sim.adm1.schema import LIQUID_STATE_NAMES

CONSERVATION_TOL = 1e-12


def test_matrix_shape_and_order(adm1_matrix, adm1_params):
    nu = compile_stoichiometry(adm1_matrix, adm1_params)
    assert nu.shape == (len(LIQUID_STATE_NAMES), 19)
    assert adm1_matrix.process_names == PROCESS_NAMES
    assert tuple(c.name for c in adm1_matrix.components) == LIQUID_STATE_NAMES


@pytest.mark.parametrize("quantity", ["COD", "C", "N", "charge"])
def test_every_process_conserves(adm1_matrix, adm1_params, quantity):
    residuals = conservation_residuals(adm1_matrix, adm1_params)[quantity]
    worst = int(np.argmax(np.abs(residuals)))
    assert np.all(np.abs(residuals) < CONSERVATION_TOL), (
        f"{quantity} not conserved; worst process {adm1_matrix.process_names[worst]!r} "
        f"residual {residuals[worst]:.3e}"
    )


def test_strong_ions_are_inert(adm1_matrix, adm1_params):
    nu = compile_stoichiometry(adm1_matrix, adm1_params)
    for name in ("S_cat", "S_an"):
        assert np.all(nu[LIQUID_STATE_NAMES.index(name)] == 0.0)


def test_spot_values_match_bsm2(adm1_matrix, adm1_params):
    """A few entries checked against the hand-expanded BSM2 arithmetic."""
    nu = compile_stoichiometry(adm1_matrix, adm1_params)
    row = {n: i for i, n in enumerate(LIQUID_STATE_NAMES)}
    col = {n: j for j, n in enumerate(adm1_matrix.process_names)}
    s = adm1_params.stoichiometry
    # sugar uptake: (1 - Y_su) * f_bu_su butyrate, Y_su biomass
    assert nu[row["S_bu"], col["uptake_sugars"]] == pytest.approx((1 - 0.1) * 0.13)
    assert nu[row["X_su"], col["uptake_sugars"]] == pytest.approx(0.1)
    # BSM2 stoich5 (carbon balance of sugar uptake), sign flipped into the S_IC column
    stoich5 = (
        -s.C_su + (1 - s.Y_su) * (0.13 * s.C_bu + 0.27 * s.C_pro + 0.41 * s.C_ac) + s.Y_su * s.C_bac
    )
    assert nu[row["S_IC"], col["uptake_sugars"]] == pytest.approx(-stoich5)
    # amino-acid uptake releases N_aa and fixes Y_aa * N_bac
    assert nu[row["S_IN"], col["uptake_amino_acids"]] == pytest.approx(0.007 - 0.08 * 0.08 / 14)
    # decay returns biomass to composites
    assert nu[row["X_xc"], col["decay_X_ac"]] == 1.0
    assert nu[row["X_ac"], col["decay_X_ac"]] == -1.0


def test_gas_transfer_block(adm1_matrix):
    names = [g.name for g in adm1_matrix.gas_transfer]
    assert names == ["transfer_h2", "transfer_ch4", "transfer_co2"]
    co2 = adm1_matrix.gas_transfer[2]
    assert co2.liquid_species == "free_co2" and co2.cod_per_kmol == 1.0
    assert [g.cod_per_kmol for g in adm1_matrix.gas_transfer[:2]] == [16.0, 64.0]


EVAL_NS = {"a": 2.0, "b": 0.5}


class TestExpressionEvaluator:
    NS: ClassVar[dict[str, float]] = EVAL_NS

    def test_arithmetic(self):
        assert evaluate_expression("(1 - b)*a + 3/2 - -1", self.NS) == pytest.approx(3.5)

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os')",
            "a.real",
            "a ** 2",
            "max(a, b)",
            "a if b else 1",
            "[a]",
            "a; b",
            "lambda: 1",
        ],
    )
    def test_rejects_anything_but_arithmetic(self, expr):
        with pytest.raises(ValueError):
            evaluate_expression(expr, self.NS)

    def test_unknown_name(self):
        with pytest.raises(ValueError, match="unknown parameter 'c'"):
            evaluate_expression("a*c", self.NS)


def test_unknown_component_in_matrix_is_rejected(adm1_matrix):
    from pydantic import ValidationError

    raw = adm1_matrix.model_dump()
    raw["processes"][0]["stoichiometry"]["S_xyz"] = "1"
    with pytest.raises(ValidationError, match="unknown components"):
        type(adm1_matrix).model_validate(raw)


def test_parameter_namespace_has_no_duplicates(adm1_params):
    ns = adm1_params.namespace()
    total = sum(
        len(type(g).model_fields)
        for g in (adm1_params.stoichiometry, adm1_params.kinetics, adm1_params.physchem)
    )
    assert len(ns) == total
