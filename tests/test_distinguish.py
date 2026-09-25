"""The distinguishability analysis (docs/distinguishability.md, method version 4).

- The admissibility rule: a score of -2 log-likelihood plus a penalty (the critical value
  of the alternative's knobs at alpha / alternatives, plus 2 ln N for a search), and a
  margin read from ``configs/eval.yaml``. The null pays nothing; a fixed alternative
  (k = 0) pays the simple-hypothesis critical value.
- The likelihood is the observation model's own: the drift covariance matches the drift
  the model draws, and the flatline flags follow its episode model (an injected window
  must be flagged throughout).
- The joint noise calibration (second re-review of PR #25): on records drawn by the
  observation model itself, drift and all, with every class competing at once, ``none``
  stays admissible at least the declared rate. Correlated noise beyond the model's
  (AR(1) white noise) is the stated limit, measured here.
- The sensor class recovers a planted scale step; its ramp is ``observe``'s ramp.
- Flatlined samples stay visible (their flags), and the hold-out is never read.
- The second score only ever adds credit, and no workflow may import the package.
- One short cell end to end: the rebuilt truth reproduces the stored channels exactly,
  and ``none`` is admissible on the clean cell.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.stats import chi2 as chi2_dist
from scipy.stats import norm

from distinguish.analysis import (
    Candidate,
    SensorData,
    _ramp,
    admissible,
    analyse_pair,
    calibration_end,
    chance_rate,
    class_limited,
    class_penalty,
    drift_covariance,
    flag_deviance,
    load_record,
    prepare,
    sensor_candidates,
    truth_representable,
)
from eval.config import load_eval_config
from eval.records import load_records
from eval.score import score_records
from tests.distinguish_noise import none_admissible_rate
from tests.eval_support import build_run, minimal_state
from tests.test_truth_isolation import find_truth_references

CFG = load_eval_config().distinguishability


def _fits(**dev_k: tuple[float, int]) -> dict[str, Candidate]:
    return {lab: Candidate(lab, d, k) for lab, (d, k) in dev_k.items()}


def test_admissibility_is_a_penalised_margin():
    p1, p2 = class_penalty(1, 1), class_penalty(2, 1)
    assert p1 == pytest.approx(chi2_dist.ppf(1 - 0.05 / 5, 1))  # 6.63
    fits = _fits(none=(100.0, 0), state=(100.0 - p1 + 2.5, 1), sensor=(100.0 - p2 - 1.0, 2))
    # scores: none 100, state 102.5, sensor 99
    assert admissible(fits, 2.0) == ["none", "sensor"]
    assert admissible(fits, 10.0) == ["none", "sensor", "state"]
    # a failed class is never admissible, and all-failed admits nothing
    assert admissible(_fits(none=(float("inf"), 0), state=(10.0, 1)), 2.0) == ["state"]
    assert admissible(_fits(none=(float("inf"), 0)), 2.0) == []


def test_a_search_pays_two_ln_n():
    searched = Candidate("sensor", 90.0, 2, n_candidates=300)
    assert searched.penalty == pytest.approx(class_penalty(2, 1) + 2.0 * np.log(300))
    # a 10-unit gain found among 300 candidates does not beat the null
    fits = {"none": Candidate("none", 100.0, 0), "sensor": searched}
    assert admissible(fits, 2.0) == ["none"]


def test_a_fixed_alternative_pays_the_simple_critical_value():
    """An extension left out has no knob, but it is still an alternative to the null."""
    c = norm.ppf(1 - 0.05 / 5) ** 2  # 5.41
    assert class_penalty(0, 1) == pytest.approx(c)
    assert Candidate("structural", 0.0, 0, n_candidates=4).penalty == pytest.approx(
        c + 2 * math.log(4)
    )
    assert Candidate("none", 0.0, 0).penalty == 0.0
    # the bound it rests on: for any fixed shift, P(2 d z - d^2 > c) <= P(Z > sqrt(c))
    for d in (0.5, math.sqrt(c), 5.0):
        assert norm.sf((c + d * d) / (2 * d)) <= norm.sf(math.sqrt(c)) + 1e-15


def test_the_rule_comes_from_the_configuration():
    assert CFG.method_version == 4 and CFG.margin == 2.0 and CFG.sensitivity_margin == 10.0
    assert CFG.lr_alpha == 0.05 and CFG.n_alternatives == 5 and CFG.look_elsewhere
    assert min(CFG.flatline_durations_d) >= 2.0  # a one-sample hold is the sensor's own


def test_the_chance_rate_counts_a_or_the_truth():
    """Re-review item 8: a uniform guess lands in A or the truth with |A or T| / 6."""
    assert chance_rate(["none", "sensor"], ["sensor"]) == pytest.approx(2 / 6)
    assert chance_rate(["none"], ["state", "sensor"]) == pytest.approx(3 / 6)


def _quiet(spec: Any, **update: Any) -> Any:
    return spec.model_copy(update={"noise": spec.noise.model_copy(update={"cv": 0.0,
                                   "sd_abs": 0.0}), "fouling": None, "flatline": None,
                                   "saturation": None, **update})  # fmt: skip


class _Flat:
    def __init__(self, channel: str, value: float, horizon: float) -> None:
        self.t = np.arange(0.0, horizon + 1e-9, 0.25)
        self._c, self._v = channel, np.full(self.t.size, value)

    def __getitem__(self, name: str) -> np.ndarray:
        return self._v


def test_the_drift_covariance_is_the_observation_models():
    """The drift the model draws (pH at Tier B: 30-d recalibration) has this covariance."""
    from sim.faults.plan import ObservationFaults
    from sim.observation import load_observation_config
    from sim.observation.model import _sensor_series
    from sim.observation.schema import MissingnessModel

    obs = load_observation_config()
    spec = _quiet(obs.sensors["ph"])
    recal = obs.tiers["B"].recalibration_interval_d
    horizon = 70.0
    ch = _Flat(spec.channel, 7.0, horizon)
    flags = np.zeros(ch.t.size, dtype=bool)
    draws = []
    for seed in range(3000):
        s = _sensor_series(
            spec, ch, horizon, flags, flags,
            lambda b, _s=seed: np.random.default_rng([_s, b]), ObservationFaults(),
            MissingnessModel(base_rate=0.0), 0.0, recal,
        )  # fmt: skip
        draws.append(s.value - 7.0)
    t = s.sample_t
    emp = np.cov(np.array(draws).T)
    model = drift_covariance(t, spec.sampling_interval_d, spec.drift.sd_per_sqrt_d, recal, True)
    scale = spec.drift.sd_per_sqrt_d**2 * 30.0
    assert np.max(np.abs(emp - model)) < 0.12 * scale
    # the walk restarts at recalibration: nothing is shared across an interval boundary
    i, j = int(np.searchsorted(t, 29.0)), int(np.searchsorted(t, 31.0))
    assert model[i, j] == 0.0 and abs(emp[i, j]) < 0.05 * scale


def _flags(flag: list[bool], seen: list[bool] | None = None, hazard: float = 0.01) -> SensorData:
    n = len(flag)
    return SensorData(
        sensor="ch4_fraction", channel="ch4_fraction", kind="online", t=np.arange(float(n)),
        y=np.zeros(n), keep=np.ones(n, bool), flag=np.array(flag), flag_seen=np.array(
            seen if seen is not None else [True] * n), dt=1.0, cv=0.0, sd_abs=0.01,
        drift_sd=0.0, recalibrated=False, recal_d=30.0, hazard_per_d=hazard, episode_d=1.0,
    )  # fmt: skip


def test_the_flatline_flags_follow_the_episode_model():
    p = 0.01
    flag = [False] * 20
    flag[5] = flag[6] = flag[7] = True
    s = _flags(flag, hazard=p)
    # one-sample episodes: the flags are Bernoulli(p)
    assert flag_deviance(s) == pytest.approx(-2 * (3 * math.log(p) + 17 * math.log(1 - p)))
    # an injected window over the run explains it; one that also covers an unflagged
    # sample is (all but) impossible, since observe flags every sample of the window
    assert flag_deviance(s, (5.0, 8.0)) == pytest.approx(-2 * 17 * math.log(1 - p))
    assert flag_deviance(s, (5.0, 9.0)) > flag_deviance(s, (5.0, 8.0)) + 40
    # a missing sample's flag constrains nothing
    seen = [True] * 20
    seen[6] = False
    assert flag_deviance(_flags(flag, seen, p)) == pytest.approx(
        -2 * (2 * math.log(p) + 17 * math.log(1 - p))
    )


def test_on_the_models_own_noise_none_stays_admissible(tmp_path: Path):
    """Second re-review of PR #25: the declared joint rate, drift and all."""
    rate = none_admissible_rate(300, tmp_path, CFG)
    assert rate >= CFG.none_admissible_rate_min, rate


def test_correlation_beyond_the_model_is_a_stated_limit(tmp_path: Path):
    """AR(1) white noise, which the observation model does not have, costs the rate.

    The measured rates are stated in docs/distinguishability.md (§3); this test pins
    that the method's guarantee is for the model's own noise, not for any correlation.
    """
    own = none_admissible_rate(150, tmp_path, CFG, seed0=1000)
    strong = none_admissible_rate(150, tmp_path, CFG, rho=0.6, seed0=1000)
    assert strong < own


def _series(t: np.ndarray, y: np.ndarray, sd: float, **kw: Any) -> SensorData:
    base = dict(
        sensor="gas_flow", channel="q_gas_stp_dry", kind="online", t=t, y=y,
        keep=np.ones(t.size, bool), flag=np.zeros(t.size, bool),
        flag_seen=np.ones(t.size, bool), dt=1.0, cv=0.0, sd_abs=sd, drift_sd=0.0,
        recalibrated=False, recal_d=30.0, hazard_per_d=0.0, episode_d=1.0,
    )  # fmt: skip
    base.update(kw)
    return SensorData(**base)


def test_the_sensor_class_recovers_a_planted_scale_step():
    t = np.arange(0.0, 100.0)
    mu = np.full(t.size, 10.0)
    y = mu.copy()
    y[t >= 40.0] *= 1.3
    s = _series(t, y, 0.1)
    prepare([s], {"gas_flow": mu})
    fit = sensor_candidates([s], {"gas_flow": mu}, {"gas_flow": 0.0}, [0.0, 20.0, 40.0], [])
    assert fit.knobs["form"] == "scale" and fit.knobs["onset_d"] == 40.0
    assert fit.knobs["value"] == pytest.approx(1.3) and fit.deviance < 1e-12


def test_the_sensor_ramp_is_the_observation_models():
    """An injected pH electrode drift, as observe applies it (reset at recalibration)."""
    from sim.faults.plan import ObservationFaults
    from sim.observation import load_observation_config
    from sim.observation.model import _sensor_series
    from sim.observation.schema import MissingnessModel

    obs = load_observation_config()
    spec = _quiet(obs.sensors["ph"])
    spec = spec.model_copy(update={"drift": spec.drift.model_copy(update={"sd_per_sqrt_d": 1e-12})})
    ch = _Flat(spec.channel, 7.0, 100.0)
    flags = np.zeros(ch.t.size, dtype=bool)
    faults = ObservationFaults(ramps={"ph": (45.0, -0.01)})
    s = _sensor_series(spec, ch, 100.0, flags, flags, lambda b: np.random.default_rng(b), faults,
                       MissingnessModel(base_rate=0.0), 0.0, 30.0)  # fmt: skip
    d = _series(s.sample_t, s.value, 0.02, drift_sd=1e-12, recalibrated=True, recal_d=30.0)
    np.testing.assert_allclose(s.value - 7.0, -0.01 * _ramp(d, 45.0), atol=1e-9)


def test_class_limits_are_declared_per_fault_type():
    assert truth_representable([{"type": "hydrolysis_regime_change"}]) == (True, [])
    # every influent fault is now a candidate of its class (method version 4)
    assert truth_representable([{"type": "moisture_drift"}]) == (True, [])
    assert truth_representable([{"type": "feed_mislabelled"}]) == (True, [])
    ok, limits = truth_representable([{"type": "informative_missingness"}])
    assert not ok and "missingness" in limits[0]
    assert class_limited([{"type": "unrecorded_delivery"}, {"type": "ph_electrode_drift"}]) == []


def test_flatlined_samples_stay_visible_and_the_holdout_is_never_read(tiny_cell):
    run, scenario = tiny_cell
    end = calibration_end(scenario.duration_days)
    assert end == pytest.approx(0.75 * scenario.duration_days)
    path = run.paths.root / "observations" / "sensors.json"
    record = load_record(path, "B", end)
    assert record and all(float(s.t.max()) <= end for s in record)
    assert max(float(s.t.max()) for s in load_record(path, "B", 1e9)) > end
    # a flatlined sample's value is dropped, its flag is kept
    raw = json.loads(path.read_text())
    raw["sensors"]["ch4_fraction"]["flatlined"][3] = True
    changed = path.parent / "sensors_flat.json"
    changed.write_text(json.dumps(raw))
    ch4 = next(s for s in load_record(changed, "B", end) if s.sensor == "ch4_fraction")
    changed.unlink()
    assert ch4.flag[3] and not ch4.keep[3] and ch4.t.size > 3


def _score(tmp_path: Path, admissible_doc: dict | None, label: str) -> dict:
    state = minimal_state("run_000000000001")
    state["final"]["label"] = label
    runs, store = build_run(tmp_path, truth_label=("sensor",), state=state)
    if admissible_doc is not None:
        (store / "run_000000000001" / "admissible.json").write_text(json.dumps(admissible_doc))
    return score_records(load_records("run_000000000001", "p0", runs_root=runs, truth_store=store))


def _others(row: dict) -> dict:
    return {k: v for k, v in row.items() if "admissible" not in k and "representable" not in k}


def test_the_second_score_only_adds_credit(tmp_path: Path):
    doc = {"method_version": 4, "admissible_set": ["none", "state"], "truth_admissible": False,
           "truth_representable": True, "chance_rate": 3 / 6}  # fmt: skip
    # the truth itself is never marked wrong, even when the record does not admit it
    truth = _score(tmp_path / "a", doc, "sensor")
    assert truth["attribution_exact"] is True and truth["attribution_admissible"] is True
    # an admissible non-truth answer earns the second score, not the first
    other = _score(tmp_path / "b", doc, "none")
    assert other["attribution_exact"] is False and other["attribution_admissible"] is True
    assert other["n_admissible"] == 2 and other["admissible_chance_rate"] == 0.5
    # an analysis of another method version is not read
    stale = _score(tmp_path / "f", {**doc, "method_version": 3}, "none")
    assert stale["attribution_admissible"] is None and stale["admissible_set"] is None
    wrong = _score(tmp_path / "c", doc, "parameter")
    assert wrong["attribution_admissible"] is False
    # an unrepresentable truth gives a null score, never a credit
    limited = _score(tmp_path / "d", {**doc, "truth_representable": False}, "none")
    assert limited["attribution_admissible"] is None and limited["truth_representable"] is False
    # without the analysis the columns are None, and nothing else moves
    absent = _score(tmp_path / "e", None, "none")
    assert absent["attribution_admissible"] is None and absent["admissible_set"] is None
    assert _others(other) == _others(absent)


def test_no_workflow_may_import_the_analysis(tmp_path: Path):
    for text in (
        "import distinguish\n",
        "from distinguish.analysis import admissible\n",
        "import importlib\nm = importlib.import_module('distinguish.analysis')\n",
    ):
        bad = tmp_path / "wf.py"
        bad.write_text(text)
        assert find_truth_references(bad), text  # negative control: it is caught
    for module in (Path(__file__).resolve().parents[1] / "workflows").rglob("*.py"):
        assert find_truth_references(module) == [], module


def test_one_short_cell_end_to_end(tiny_cell, monkeypatch, tmp_path: Path):
    """A clean 30-day cell on small grids: the truth is rebuilt exactly, `none` is admissible."""
    from distinguish import analysis

    small = CFG.model_copy(
        update={
            "delivery_multiples": (3.0,),
            "mislabel_durations_d": (10.0,),
            "mislabel_concentrations": (5.0,),
            "moisture_durations_d": (10.0,),
            "moisture_changes": (-0.3,),
            "biomass_multipliers": (0.5,),
            "parameter_multipliers": (2.0,),
        }
    )
    monkeypatch.setattr(analysis, "_cfg", lambda: small)
    run, scenario = tiny_cell
    runs = [(run.run_id, run.paths.root, run.paths.truth)]
    docs = analyse_pair(runs, scenario=scenario, cache_dir=tmp_path / "cache", log=str)
    doc = docs[run.run_id]
    assert doc["method_version"] == 4 and doc["truth_reproduced_max_abs"] == 0.0
    assert doc["truth_label"] == ["none"] and doc["tier"] == "B"
    assert doc["calibration_end_d"] == pytest.approx(0.75 * scenario.duration_days)
    assert set(doc["classes"]) == {"none", "sensor", "influent", "state", "parameter",
                                   "structural"}  # fmt: skip
    # on a clean cell the truth candidate is the null itself
    assert doc["truth_candidate_deviance"] == pytest.approx(doc["classes"]["none"]["deviance"])
    assert doc["none_admissible"]  # the Level-0 requirement (second re-review)
    assert doc["n_admissible"] == len(doc["admissible_set"]) and doc["truth_representable"]
    assert doc["classes"]["sensor"]["n_candidates"] > 1
    # precipitation cannot be switched off without a change under sim/ (declared)
    structural = doc["classes"]["structural"]
    hidden = structural["knobs"].get("not_visible", [])
    assert structural["n_candidates"] + len(hidden) == 3 or structural["score"] is None
    assert all(h["visibility"] < CFG.structural_min_visibility for h in hidden)
    assert set(doc["structural_not_offered"]) == {"precipitation"}
    assert doc["simulation_failures"] == []
    # the simulations are kept: a second analysis integrates nothing
    again = analyse_pair(runs, scenario=scenario, cache_dir=tmp_path / "cache", log=str)
    assert again[run.run_id]["simulations_pair"] == 0
    assert again[run.run_id]["admissible_set"] == doc["admissible_set"]


def test_an_invisible_structural_candidate_is_left_out():
    """An alternative that moves the record by less than the noise is no alternative."""
    from distinguish.analysis import _best_ode

    t = np.arange(0.0, 50.0)
    mu = np.full(t.size, 10.0)
    s = _series(t, mu.copy(), 0.1)
    prepare([s], {"gas_flow": mu})

    class _Ch:
        def __init__(self, shift: float) -> None:
            self.t, self.v = t, mu + shift

        def __getitem__(self, name: str) -> np.ndarray:
            return self.v

    class _Sim:
        def run(self, faults: Any, extensions: Any = None) -> Any:
            return _Ch({"a": 1e-6, "b": 0.5}[extensions[0]])

    options = [
        {"form": "extension off", "group": (x,), "k": 0, "faults": [], "base": [],
         "extensions": (x,), "extension_off": x}
        for x in ("a", "b")
    ]  # fmt: skip
    fit = _best_ode("structural", options, _Sim(), [s], 0.0, mu_ref={"gas_flow": mu},
                    min_visible=1.0)  # fmt: skip
    assert fit.n_candidates == 1 and fit.knobs["extension_off"] == "b"
    assert [h["extension_off"] for h in fit.knobs["not_visible"]] == ["a"]
    assert math.isfinite(fit.deviance)
