"""The tool table (§6.2): one :class:`~tools.registry.ToolSpec` per tool.

Every tool is a pure function of its validated input, a metered model and an explicit
seed; the registry does the validation, the budget, the logging and the Level-8
directive. Adding a tool is adding one spec here and one YAML in ``configs/tools/``.
"""

from __future__ import annotations

from tools.registry import ToolSpec
from tools.schemas import TOOL_INPUTS, TOOL_OUTPUTS

from . import (
    data_qc,
    filters,
    fitters,
    gsa,
    identifiability,
    mass_balance,
    mcmc,
    model_tools,
    residual_diag,
    validate,
    voi,
)

__all__ = ["SPECS"]


def _spec(name: str, run, cost, failure=None, assay_cost=None) -> ToolSpec:  # noqa: ANN001
    return ToolSpec(
        name=name,
        input_model=TOOL_INPUTS[name],
        output_model=TOOL_OUTPUTS[name],
        run=run,
        cost=cost,
        failure=failure,
        assay_cost=assay_cost,
    )


SPECS: dict[str, ToolSpec] = {
    "describe_model": _spec("describe_model", model_tools.run_describe, model_tools.describe_cost),
    "simulate": _spec("simulate", model_tools.run_simulate, model_tools.simulate_cost),
    "feed_loads": _spec("feed_loads", model_tools.run_feed_loads, model_tools.feed_loads_cost),
    "data_qc": _spec("data_qc", data_qc.run_data_qc, data_qc.data_qc_cost),
    "mass_balance": _spec(
        "mass_balance", mass_balance.run_mass_balance, mass_balance.mass_balance_cost
    ),
    "gsa_morris": _spec("gsa_morris", gsa.run_morris, gsa.morris_cost),
    "gsa_sobol": _spec("gsa_sobol", gsa.run_sobol, gsa.sobol_cost),
    "profile_likelihood": _spec(
        "profile_likelihood", identifiability.run_profile, identifiability.profile_cost
    ),
    "fisher_info": _spec("fisher_info", identifiability.run_fisher, identifiability.fisher_cost),
    "fit_lsq": _spec("fit_lsq", fitters.run_lsq, fitters.lsq_cost),
    "fit_de": _spec("fit_de", fitters.run_de, fitters.de_cost),
    "fit_cmaes": _spec("fit_cmaes", fitters.run_cmaes, fitters.cmaes_cost),
    "bayes_mcmc": _spec("bayes_mcmc", mcmc.run_mcmc, mcmc.mcmc_cost, failure=mcmc.failure_payload),
    "filter_enkf": _spec("filter_enkf", filters.run_enkf, filters.enkf_cost),
    "filter_mhe": _spec("filter_mhe", filters.run_mhe, filters.mhe_cost),
    "residual_diag": _spec(
        "residual_diag", residual_diag.run_residual_diag, residual_diag.residual_diag_cost
    ),
    "voi_assay": _spec("voi_assay", voi.run_voi, voi.voi_cost),
    "validate": _spec("validate", validate.run_validate, validate.validate_cost),
    "request_assay": _spec(
        "request_assay",
        model_tools.run_assay,
        model_tools.assay_cost,
        assay_cost=model_tools.assay_units,
    ),
}
"""Every tool of §6.2, by name."""
