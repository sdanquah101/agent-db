"""The registry's reserves: the agent P2's verifier draws on its own budget (Q9).

``docs/p2_agents_design.md`` §3.1 and Q9: the verifier's ``simulate``, ``residual_diag``,
``validate`` calls and its named separating test draw on its own budget, enforced in the
registry (CLAUDE.md rule 2: budgets are enforced in the registry, not in workflows). The
reserve is carved out of the cell's envelope (the same for every workflow, §7), set on the
privileged side by the launcher from the jail document the runner wrote
(:func:`tools.sandbox.apply_reserves`), and reached through a role tag on the stub's
``call`` (``_role``). Four layers, each with its negative control:

1. :class:`tools.registry.Registry`: a tagged call draws on its reserve and is refused past
   it; an untagged call is refused past what the envelope holds outside the reserves; the
   refusal is logged as ``budget_exceeded``; the charge record carries the role.
2. :class:`tools.server.RegistryServer`: the ``call`` op's ``role`` and the ``reserves`` op.
3. :func:`tools.sandbox.apply_reserves`: the box document sets the reserve; no block, no
   reserve.
4. The jail: a probe script sees the reserve through ``tools.reserves()`` and spends it
   through ``tools.call(..., _role=...)``.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from state.provenance import read_calls
from tests.test_tool_registry import registry
from tools import Budget, BudgetExceededError, make_registry
from tools.sandbox import apply_reserves, launch
from tools.server import RegistryServer

MORRIS = {"model": "linear", "parameters": ("a", "b"), "outputs": ("y",), "seed": 1}


def _morris(n: int) -> dict:
    return {**MORRIS, "n_trajectories": n}  # cost n x (k + 1) = 3 n


def test_a_tagged_call_draws_on_its_reserve_and_an_untagged_one_cannot_touch_it(tmp_path):
    reg, run_dir, _ = registry(tmp_path, budget=Budget(20, 60.0, 0))
    reg.reserve("verification", simulator_evals=10, assay_units=0)
    assert reg.reserves_remaining() == {
        "verification": {
            "simulator_evals": 10,
            "simulator_evals_total": 10,
            "assay_units": 0,
            "assay_units_total": 0,
        }
    }
    # an untagged call fits the envelope (12 <= 20) but not the envelope outside the
    # reserve (10): refused before running, logged
    with pytest.raises(BudgetExceededError, match="outside the reserves"):
        reg.call("gsa_morris", **_morris(4))
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    assert reg.remaining().simulator_evals == 20
    # a tagged call past its reserve is refused too (12 > 10), whatever the envelope holds
    with pytest.raises(BudgetExceededError, match="verification reserve has 10"):
        reg.call("gsa_morris", role="verification", **_morris(4))
    # the negative controls: a tagged call inside the reserve runs and the reserve pays
    out = reg.call("gsa_morris", role="verification", **_morris(3))
    assert out.n_evaluations == 9
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 1
    assert reg.remaining().simulator_evals == 11
    assert reg.charged_calls[-1]["role"] == "verification"
    assert reg.charged_calls[-1]["n_evaluations"] == 9
    # ... and an untagged call inside the shared part runs (9 <= 11 - 1)
    out = reg.call("gsa_morris", **_morris(3))
    assert out.n_evaluations == 9 and reg.charged_calls[-1]["role"] is None
    assert reg.remaining().simulator_evals == 2
    # the shared part is now 1: an untagged single evaluation runs, a second is refused
    reg.call("simulate", model="linear")
    with pytest.raises(BudgetExceededError, match="outside the reserves"):
        reg.call("simulate", model="linear")
    # the reserve's last evaluation is the verifier's alone
    reg.call("simulate", model="linear", role="verification")
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 0
    # (the envelope is spent too, so the registry's own refusal may name it first)
    with pytest.raises(BudgetExceededError, match=r"reserve has 0|0 of 20 remain"):
        reg.call("simulate", model="linear", role="verification")
    # a reserve in use cannot be reset; a reserve past the envelope is refused
    with pytest.raises(ValueError, match="in use"):
        reg.reserve("verification", simulator_evals=5, assay_units=0)
    fresh = make_registry(budget=Budget(20, 60.0, 1), seed=1)
    with pytest.raises(ValueError, match="exceed the envelope"):
        fresh.reserve("verification", simulator_evals=21, assay_units=0)
    with pytest.raises(ValueError, match="exceed the envelope"):
        fresh.reserve("verification", simulator_evals=1, assay_units=2)
    assert fresh.cost_bound("simulate", model="linear") == (1, 0)
    assert fresh.cost_bound("gsa_morris", **_morris(4)) == (12, 0)


def test_the_server_tags_a_call_and_serves_the_reserves(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(20, 60.0, 0))
    reg.reserve("verification", simulator_evals=10, assay_units=0)
    with RegistryServer(reg, tmp_path / "s.sock") as server:
        assert server._handle({"op": "reserves"})["result"] == reg.reserves_remaining()
        reply = server._handle(
            {"op": "call", "name": "gsa_morris", "args": _morris(2), "role": "verification"}
        )
        assert reply["ok"] and reply["result"]["outcome"] == "ok"
        assert reg.charged_calls[-1]["role"] == "verification"
        assert reg.reserves_remaining()["verification"]["simulator_evals"] == 4
        # the negative control: no tag, no reserve: the untagged refusal (12 fits the 14
        # left in the envelope, not the 10 outside the reserve)
        reply = server._handle({"op": "call", "name": "gsa_morris", "args": _morris(4)})
        assert reply["result"]["outcome"] == "budget_exceeded"
        assert "outside the reserves" in reply["result"]["error"]
        assert reg.charged_calls[-1]["role"] is None


def test_the_launcher_sets_the_reserve_from_the_jail_document(tmp_path):
    reg = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box = tmp_path / "box"
    (box / "cwd").mkdir(parents=True)
    doc = {"agents": {"verifier_budget": {"simulator_evals": 80, "assay_units": 1}}}
    (box / "cwd" / "p2_config.json").write_text(json.dumps(doc), encoding="utf-8")
    assert apply_reserves(box, reg) == {"verification": {"simulator_evals": 80, "assay_units": 1}}
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 80
    # the negative controls: a document without the block, and no document
    plain = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box2 = tmp_path / "box2"
    (box2 / "cwd").mkdir(parents=True)
    (box2 / "cwd" / "p2_config.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    assert apply_reserves(box2, plain) == {} and plain.reserves_remaining() == {}
    box3 = tmp_path / "box3"
    box3.mkdir()
    assert apply_reserves(box3, plain) == {}


def test_the_jail_sees_the_reserve_and_spends_it_through_the_stubs_role_tag(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(20, 60.0, 0))
    script = tmp_path / "workflow.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import tools
            out = {"before": tools.reserves()}
            try:
                tools.call("gsa_morris", model="linear", parameters=["a", "b"],
                           outputs=["y"], n_trajectories=4, seed=1)
                out["untagged_big"] = "RAN"
            except tools.BudgetExceededError as exc:
                out["untagged_big"] = str(exc)
            r = tools.call("gsa_morris", _role="verification", model="linear",
                           parameters=["a", "b"], outputs=["y"], n_trajectories=3, seed=1)
            out["tagged"] = r.n_evaluations
            out["after"] = tools.reserves()
            try:
                tools.call("gsa_morris", _role="verification", model="linear",
                           parameters=["a", "b"], outputs=["y"], n_trajectories=3, seed=1)
                out["tagged_again"] = "RAN"
            except tools.BudgetExceededError as exc:
                out["tagged_again"] = str(exc)
            print(json.dumps(out))
            """
        ),
        encoding="utf-8",
    )
    box = tmp_path / "box"
    (box / "cwd").mkdir(parents=True)
    doc = {"agents": {"verifier_budget": {"simulator_evals": 10, "assay_units": 0}}}
    (box / "cwd" / "p2_config.json").write_text(json.dumps(doc), encoding="utf-8")
    result = launch(script, reg, sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["before"]["verification"]["simulator_evals"] == 10
    assert "outside the reserves" in out["untagged_big"]
    assert out["tagged"] == 9
    assert out["after"]["verification"]["simulator_evals"] == 1
    assert "reserve has 1" in out["tagged_again"]
    assert [c["role"] for c in reg.charged_calls if c["name"] == "gsa_morris"] == [
        None,
        "verification",
        "verification",
    ]
