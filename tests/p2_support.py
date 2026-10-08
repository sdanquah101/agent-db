"""A fake ``tools`` module for running P2's workflow in-process, with no simulator.

The jail's ``tools`` stub is replaced by :class:`FakeTools`, which answers every tool P2
calls with small deterministic outputs of the shape the workflow reads, charges a declared
number of evaluations per call against a budget, and keeps what the workflow writes. The
band is the real one (``configs/background.yaml`` through ``tools.background``), so the
null table is computed against the published envelope. This exercises the workflow's
control flow (roles, allow-lists, decisions, ablations, the record) in seconds; one
sandboxed end-to-end run (``tests/test_p2_workflow.py``) exercises the real tools.
"""

from __future__ import annotations

import types
from typing import Any

import numpy as np

from tools.config import load_background
from tools.schemas import DeclaredBackgroundOutput

T_DAYS = 200
CHANNELS = {
    "gas_flow": ("q_gas_stp_dry", "m3/d", 2000.0, 60.0),
    "ph": ("pH", "-", 7.2, 0.05),
    "tan": ("S_IN_mgN", "mg/L", 900.0, 30.0),
    "vfa_total": ("vfa_total", "mg/L", 300.0, 20.0),
    "alkalinity": ("alkalinity_total", "mg/L", 4000.0, 100.0),
    "ch4_fraction": ("ch4_fraction", "-", 0.62, 0.01),
    "cod_total": ("cod_total", "g/L", 30.0, 1.0),
    "temperature": ("temperature", "K", 308.0, 0.2),
}
PARAMS = ["k_dis", "k_hyd_ch", "k_m_ac", "K_S_ac", "K_I_nh3", "Y_ac"]


class ToolError(Exception):
    """The stub's tool error."""


class BudgetExceededError(ToolError):
    """The stub's budget error."""


def ns(**kw: Any) -> types.SimpleNamespace:
    """A plain object with attributes."""
    return types.SimpleNamespace(**kw)


class FakeRun:
    """``tools.run``: the record, the manifest, and the output sink."""

    def __init__(self, plant: str, tier: str, sensors: dict[str, Any]) -> None:
        """Set up with the record."""
        self._plant, self._tier, self._sensors = plant, tier, sensors
        self.outputs: dict[str, str] = {}

    def manifest(self) -> dict[str, Any]:
        return {"run_id": "run_fake", "plant": self._plant, "tier": self._tier,
                "duration_days": float(T_DAYS)}  # fmt: skip

    def sensors(self) -> dict[str, Any]:
        return {"sensors": self._sensors}

    def feed_log(self) -> dict[str, np.ndarray]:
        t = np.arange(T_DAYS, dtype=float)
        return {"maize": 20.0 + 0.0 * t, "manure": 30.0 + 0.0 * t}

    def operator_notes(self) -> list[dict[str, Any]]:
        return [{"day": 40, "author": "operator", "text": "a note"}]

    def write_output(self, relative: str, content: str) -> dict[str, Any]:
        self.outputs[relative] = content
        return {"ok": True}


class FakeTools:
    """The stub's API: ``call``, ``remaining``, ``last_call``, ``run``, the errors."""

    ToolError = ToolError
    BudgetExceededError = BudgetExceededError

    def __init__(
        self,
        plant: str = "B",
        tier: str = "B",
        *,
        evals: int = 450,
        wall_min: float = 90.0,
        assays: int = 2,
        offsets: dict[str, float] | None = None,
        closures: list[float] | None = None,
        mcmc_converged: bool = False,
    ) -> None:
        """A run of ``plant`` at ``tier`` with a budget, channel offsets and closures."""
        sensors = {}
        rng = np.random.default_rng(7)
        names = ["gas_flow", "ph", "temperature"] if tier == "A" else list(CHANNELS)
        self.base = {}
        t = np.arange(0.0, T_DAYS, 1.0)
        for name in names:
            channel, unit, level, sd = CHANNELS[name]
            self.base[channel] = level + 0.0 * t
            off = (offsets or {}).get(name, 0.0)
            value = level + off * sd + rng.normal(0.0, sd, t.size)
            sensors[name] = {"channel": channel, "unit": unit, "sample_t_d": t.tolist(),
                             "value": value.tolist()}  # fmt: skip
        self.run = FakeRun(plant, tier, sensors)
        self.plant, self.tier = plant, tier
        self.closures = closures if closures is not None else [-0.05, -0.04, -0.06, -0.05]
        self.mcmc_converged = mcmc_converged
        self.totals = {"evals": evals, "wall": wall_min, "assays": assays}
        self.used = {"evals": 0, "assays": 0, "calls": 0}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._last: dict[str, Any] | None = None

    # -- the budget --------------------------------------------------------------------
    def remaining(self) -> Any:
        u, tot = self.used, self.totals
        return ns(
            simulator_evals=tot["evals"] - u["evals"], simulator_evals_total=tot["evals"],
            wall_clock_min=tot["wall"] - 0.01 * u["calls"], wall_clock_min_total=tot["wall"],
            assay_units=tot["assays"] - u["assays"], assay_units_total=tot["assays"],
            n_calls=u["calls"],
        )  # fmt: skip

    def last_call(self) -> dict[str, Any] | None:
        return self._last

    def _charge(self, evals: int = 0, assays: int = 0) -> None:
        if self.used["evals"] + evals > self.totals["evals"]:
            raise BudgetExceededError(f"{evals} evaluations do not fit")
        if self.used["assays"] + assays > self.totals["assays"]:
            raise BudgetExceededError(f"{assays} assay units do not fit")
        self.used["evals"] += evals
        self.used["assays"] += assays

    # -- the tools ---------------------------------------------------------------------
    def call(self, name: str, **args: Any) -> Any:
        self.calls.append((name, args))
        seq = self.used["calls"]
        self.used["calls"] += 1
        self._last = {"seq": seq, "args_hash": f"h{seq}", "version": "1.0", "outcome": "ok"}
        try:
            return getattr(self, f"_{name}")(**args)
        except BudgetExceededError:
            self._last["outcome"] = "budget_exceeded"
            raise

    def _describe_model(self, model: str) -> Any:
        return ns(parameter_names=PARAMS, lower=[0.25] * len(PARAMS), upper=[4.0] * len(PARAMS),
                  parameter_units={p: "-" for p in PARAMS}, output_names=list(self.base),
                  t=np.arange(T_DAYS + 1.0))  # fmt: skip

    def _feed_loads(self, model: str) -> Any:
        t = np.arange(T_DAYS, dtype=float)
        return ns(t=t, q_m3_d=60.0 + 0 * t, cod_kg_d=5000.0 + 100 * np.sin(t / 9),
                  tkn_kg_n_d=200.0 + 0 * t, charge_keq_d=1.0 + 0 * t)  # fmt: skip

    def _simulate(self, model: str, parameters: dict | None = None, **kw: Any) -> Any:
        self._charge(1)
        t = np.arange(T_DAYS + 1.0)
        shift = sum((parameters or {}).values()) * 0.0
        scale = kw.get("biomass_scale") or 1.0
        out = {ch: v.mean() + shift + 0.0 * t + (scale - 1.0) * 0.0 for ch, v in self.base.items()}
        return ns(t=t, outputs=out)

    def _data_qc(self, series: Any, event_windows: Any, **kw: Any) -> Any:
        res = [ns(name=s["name"], flags=[], missing_fraction=0.0, flatlines=[], spikes=[5.0],
                  drift_flag=False, drift_slope_per_d=0.0, drift_signal_to_noise=0.0,
                  informative_missingness=False, event_missing_ratio=None)
               for s in series]  # fmt: skip
        return ns(results=res)

    def _declared_background(self, plant: str, tier: str) -> Any:
        config = load_background()
        band = config.band(plant, tier)
        return DeclaredBackgroundOutput(
            plant=plant, tier=tier, status=config.provenance.status,
            band_seeds=config.provenance.seeds, procedure=config.procedure, units={},
            **band.model_dump(),
        )  # fmt: skip

    def _mass_balance(self, windows: Any, **kw: Any) -> Any:
        out = []
        for i, w in enumerate(windows):
            c = self.closures[i] if i < len(self.closures) else self.closures[-1]
            out.append(ns(window=ns(start=w["start"], end=w["end"]), cod_closure=c,
                          cod_admissible=abs(c) < 0.15))  # fmt: skip
        return ns(windows=out, charge_drift=0.3, charge_consistent=False, admissible=True)

    def _gsa_morris(self, parameters: Any, outputs: Any, n_trajectories: int, **kw: Any) -> Any:
        self._charge(n_trajectories * (len(parameters) + 1))
        mu = [1.0 / (i + 1) for i in range(len(parameters))]
        return ns(parameters=list(parameters), results=[ns(mu_star=mu) for _ in outputs])

    def _fisher_info(self, parameters: Any, **kw: Any) -> Any:
        self._charge(2 * len(parameters))
        return ns(parameters=list(parameters), crlb_sd=[0.1] * len(parameters))

    def _fit_lsq(self, parameters: Any, max_nfev_per_start: int = 40, **kw: Any) -> Any:
        self._charge(max_nfev_per_start)
        k = len(parameters)
        return ns(parameters=list(parameters), theta=np.ones(k), chi2=100.0, at_bound=[],
                  converged=True, sd=np.full(k, 0.1), n_data=100, message="",
                  n_evaluations=max_nfev_per_start, covariance=None)  # fmt: skip

    def _residual_diag(self, **kw: Any) -> Any:
        return ns(serially_structured=False, lag1_autocorrelation=0.0, trend_slope_per_d=0.0,
                  most_explanatory=None, covariates=[])  # fmt: skip

    def _bayes_mcmc(self, parameters: Any, n_walkers: int, n_steps: int, **kw: Any) -> Any:
        self._charge(n_walkers * (n_steps + 1))
        k = len(parameters)
        return ns(parameters=list(parameters), converged=self.mcmc_converged,
                  rhat=np.full(k, 1.01 if self.mcmc_converged else 3.0), ess=np.full(k, 50.0),
                  warning="",
                  quantiles={"q05": np.full(k, 0.8), "q95": np.full(k, 1.2)})  # fmt: skip

    def _request_assay(self, assay: str, day: float) -> Any:
        self._charge(assays=1)
        return ns(report_day=day + 3.0,
                  results=[ns(channel="vfa_total", value=300.0, sd=20.0, unit="mg/L")])  # fmt: skip

    def _validate(self, observed: Any, t: Any, predicted: Any, holdout: Any = None,
                  **kw: Any) -> Any:  # fmt: skip
        """The real tool's point metrics over the hold-out (``rmse`` is what P2 reads)."""
        results = []
        for o in observed:
            tt, y = np.asarray(o["t"], dtype=float), np.asarray(o["value"], dtype=float)
            keep = np.isfinite(y)
            if holdout is not None:
                keep &= (tt >= holdout["start"]) & (tt <= holdout["end"])
            err = np.interp(tt[keep], np.asarray(t, dtype=float),
                            np.asarray(predicted[o["output"]], dtype=float)) - y[keep]  # fmt: skip
            results.append(ns(output=o["output"], n=int(err.size), mae=float(np.mean(np.abs(err))),
                              rmse=float(np.sqrt(np.mean(err**2))), nrmse=0.1,
                              bias=float(np.mean(err)), coverage={}, interval_score={},
                              crps=None, constraint_violations=0))  # fmt: skip
        return ns(ensemble=False, results=results)
