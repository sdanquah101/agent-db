"""The registry's reserves: the agent P2's verifier draws on its own budget (Q9).

``docs/p2_agents_design.md`` §3.1 and Q9: the verifier's ``simulate``, ``residual_diag``,
``validate`` calls and its named separating test draw on its own budget, enforced in the
registry (CLAUDE.md rule 2: budgets are enforced in the registry, not in workflows). The
reserve is **on top of** the cell's envelope (the lead's ruling B of 2026-10-29): the
untagged calls keep the whole envelope, exactly what P0 and P1 get, and a tagged call draws
on the reserve and is refused past it. It is set on the privileged side by the launcher from
the jail document the runner wrote (:func:`tools.sandbox.apply_reserves`), and reached
through a role tag on the stub's ``call`` (``_role``). Four layers, each with its negative
control:

1. :class:`tools.registry.Registry`: a tagged call draws on its reserve and is refused past
   it; an untagged call keeps the whole envelope and is refused past it, as before; the
   refusal is logged as ``budget_exceeded``; the charge record carries the role; with no
   reserve nothing changes.
2. :class:`tools.server.RegistryServer`: the ``call`` op's ``role`` and the ``reserves`` op.
3. :func:`tools.sandbox.apply_reserves`: the box document sets the reserve; no block, no
   reserve; none under the verifier-off ablation.
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
from tools.sandbox import SandboxError, apply_reserves, launch
from tools.server import RegistryServer

MORRIS = {"model": "linear", "parameters": ("a", "b"), "outputs": ("y",), "seed": 1}


def _morris(n: int) -> dict:
    return {**MORRIS, "n_trajectories": n}  # cost n x (k + 1) = 3 n


def test_a_tagged_call_draws_on_its_reserve_on_top_of_the_envelope(tmp_path):
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
    # an untagged call keeps the whole envelope: 12 of the 20 run, the reserve untouched
    out = reg.call("gsa_morris", **_morris(4))
    assert out.n_evaluations == 12 and reg.charged_calls[-1]["role"] is None
    assert reg.remaining().simulator_evals == 8
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 10
    # a tagged call past its reserve is refused (12 > 10), logged, whatever the envelope holds
    with pytest.raises(BudgetExceededError, match="verification reserve has 10 of 10"):
        reg.call("gsa_morris", role="verification", **_morris(4))
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    # a tagged call inside the reserve runs and the reserve pays: the envelope does not move
    out = reg.call("gsa_morris", role="verification", **_morris(3))
    assert out.n_evaluations == 9
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 1
    assert reg.remaining().simulator_evals == 8
    assert reg.evaluations_used == 21  # the run spent past the envelope, by the reserve
    assert reg.charged_calls[-1]["role"] == "verification"
    assert reg.charged_calls[-1]["n_evaluations"] == 9
    # the untagged refusal is the envelope's own, worded as it always was (9 > 8)
    with pytest.raises(BudgetExceededError, match="8 of 20 remain"):
        reg.call("gsa_morris", **_morris(3))
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    # the envelope's last evaluations are the untagged calls' alone
    reg.call("gsa_morris", **_morris(2))
    reg.call("simulate", model="linear")
    reg.call("simulate", model="linear")
    assert reg.remaining().simulator_evals == 0
    with pytest.raises(BudgetExceededError, match="0 of 20 remain"):
        reg.call("simulate", model="linear")
    # the reserve's last evaluation is the verifier's alone, and the envelope being spent
    # does not refuse it
    reg.call("simulate", model="linear", role="verification")
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 0
    with pytest.raises(BudgetExceededError, match="reserve has 0 of 10"):
        reg.call("simulate", model="linear", role="verification")
    assert reg.evaluations_used == 30
    # a tag naming no reserve is an untagged call for the budget (a proposer's own tag)
    with pytest.raises(BudgetExceededError, match="0 of 20 remain"):
        reg.call("simulate", model="linear", role="calibration")
    # a reserve in use cannot be reset; a negative one is refused; a reserve larger than
    # the envelope is accepted (it is on top of it) and the envelope is unchanged
    with pytest.raises(ValueError, match="in use"):
        reg.reserve("verification", simulator_evals=5, assay_units=0)
    fresh = make_registry(budget=Budget(20, 60.0, 1), seed=1)
    with pytest.raises(ValueError, match="not negative"):
        fresh.reserve("verification", simulator_evals=-1, assay_units=0)
    fresh.reserve("verification", simulator_evals=21, assay_units=2)
    assert fresh.reserves_remaining()["verification"]["simulator_evals_total"] == 21
    assert fresh.reserves_remaining()["verification"]["assay_units_total"] == 2
    assert fresh.remaining().simulator_evals == 20 and fresh.remaining().assay_units == 1


def test_an_overrunning_tool_is_stopped_at_the_callers_share_not_the_envelope(tmp_path):
    """M3: the meter's limit is the caller's share while a call runs.

    An untagged tool that lies about its bound is stopped at the envelope and cannot eat a
    reserve; a tagged one is stopped at its reserve, past the envelope by that much and
    no further.
    """
    from tools.registry import ToolSpec
    from tools.schemas import SimulateInput, SimulateOutput

    def greedy(inp, ctx):
        model = ctx.model(inp.model)
        for _ in range(100):
            model.evaluate(model.defaults)
        raise AssertionError("unreachable")

    reg, run_dir, _ = registry(tmp_path, budget=Budget(20, 60.0, 0))
    reg._specs["greedy"] = ToolSpec(
        name="greedy", input_model=SimulateInput, output_model=SimulateOutput, run=greedy,
        cost=lambda inp, ctx: 1,
    )  # fmt: skip
    reg.reserve("verification", simulator_evals=10, assay_units=0)
    # untagged: stopped after the envelope's 20; the reserve is untouched
    with pytest.raises(BudgetExceededError):
        reg.call("greedy", model="linear")
    assert reg.remaining().simulator_evals == 0
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 10
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    # tagged: stopped after its 10, on top of the spent envelope; nothing else is left to it
    with pytest.raises(BudgetExceededError):
        reg.call("greedy", model="linear", role="verification")
    assert reg.evaluations_used == 30
    assert reg.remaining().simulator_evals == 0
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 0
    assert reg._meter.limit == 20  # the limit is restored on every path
    # the negative control: with no reserve the envelope is the only stop (the old rule)
    plain, _, _ = registry(tmp_path / "plain", budget=Budget(20, 60.0, 0))
    plain._specs["greedy"] = reg._specs["greedy"]
    with pytest.raises(BudgetExceededError):
        plain.call("greedy", model="linear")
    assert plain.remaining().simulator_evals == 0 and plain._meter.limit == 20


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
        assert server._handle({"op": "remaining"})["result"]["simulator_evals"] == 20
        # the negative control: no tag, no reserve: the whole envelope (12 of the 20 run,
        # the reserve's 4 untouched), then the envelope's own refusal
        reply = server._handle({"op": "call", "name": "gsa_morris", "args": _morris(4)})
        assert reply["ok"] and reply["result"]["outcome"] == "ok"
        assert reg.charged_calls[-1]["role"] is None
        assert reg.reserves_remaining()["verification"]["simulator_evals"] == 4
        reply = server._handle({"op": "call", "name": "gsa_morris", "args": _morris(3)})
        assert reply["result"]["outcome"] == "budget_exceeded"
        assert "8 of 20 remain" in reply["result"]["error"]


def test_the_launcher_sets_the_reserve_from_the_jail_document(tmp_path):
    reg = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box = tmp_path / "box"
    (box / "cwd").mkdir(parents=True)
    doc = {"agents": {"verifier_budget": {"simulator_evals": 80, "assay_units": 1}}}
    (box / "cwd" / "p2_config.json").write_text(json.dumps(doc), encoding="utf-8")
    assert apply_reserves(box, reg) == {"verification": {"simulator_evals": 80, "assay_units": 1}}
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 80
    assert reg.remaining().simulator_evals == 100  # the envelope is unchanged (ruling B)
    # the negative controls: a document without the block, and no document
    plain = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box2 = tmp_path / "box2"
    (box2 / "cwd").mkdir(parents=True)
    (box2 / "cwd" / "p2_config.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    assert apply_reserves(box2, plain) == {} and plain.reserves_remaining() == {}
    box3 = tmp_path / "box3"
    box3.mkdir()
    assert apply_reserves(box3, plain) == {}
    # the verifier-off ablation sets no reserve: that arm has P1's budget exactly (M2)
    off = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box4 = tmp_path / "box4"
    (box4 / "cwd").mkdir(parents=True)
    (box4 / "cwd" / "p2_config.json").write_text(
        json.dumps({**doc, "ablation": {"verifier": False, "roles": {}}}), encoding="utf-8"
    )
    assert apply_reserves(box4, off) == {} and off.reserves_remaining() == {}
    # ... and the control: the ablation block with the verifier on sets it
    on = make_registry(budget=Budget(100, 60.0, 2), seed=1)
    box4b = tmp_path / "box4b"
    (box4b / "cwd").mkdir(parents=True)
    (box4b / "cwd" / "p2_config.json").write_text(
        json.dumps({**doc, "ablation": {"verifier": True, "roles": {}}}), encoding="utf-8"
    )
    assert apply_reserves(box4b, on)["verification"]["simulator_evals"] == 80
    assert on.reserves_remaining()["verification"]["simulator_evals_total"] == 80
    # a cell whose envelope is smaller than the reserve takes it: the reserve is on top
    small = make_registry(budget=Budget(50, 60.0, 0), seed=1)
    box5 = tmp_path / "box5"
    (box5 / "cwd").mkdir(parents=True)
    (box5 / "cwd" / "p2_config.json").write_text(json.dumps(doc), encoding="utf-8")
    assert apply_reserves(box5, small)["verification"] == {"simulator_evals": 80, "assay_units": 1}
    assert small.remaining().simulator_evals == 50 and small.remaining().assay_units == 0
    # a document missing a key, or naming a negative number, is refused before any jail
    # exists, with a clear error (N9)
    for bad, match in (
        ({"agents": {"verifier_budget": {"simulator_evals": 80}}}, "lacks"),
        ({"agents": {"verifier_budget": {"simulator_evals": -1, "assay_units": 0}}}, "refused"),
    ):
        fresh = make_registry(budget=Budget(100, 60.0, 2), seed=1)
        box6 = tmp_path / f"box_{match}"
        (box6 / "cwd").mkdir(parents=True)
        (box6 / "cwd" / "p2_config.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(SandboxError, match=match):
            apply_reserves(box6, fresh)
        assert fresh.reserves_remaining() == {}


def test_the_jail_sees_the_reserve_and_spends_it_through_the_stubs_role_tag(tmp_path):
    reg, _, _ = registry(tmp_path, budget=Budget(20, 60.0, 0))
    script = tmp_path / "workflow.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import tools
            out = {"before": tools.reserves()}
            r = tools.call("gsa_morris", model="linear", parameters=["a", "b"],
                           outputs=["y"], n_trajectories=4, seed=1)
            out["untagged"] = r.n_evaluations
            r = tools.call("gsa_morris", _role="verification", model="linear",
                           parameters=["a", "b"], outputs=["y"], n_trajectories=3, seed=1)
            out["tagged"] = r.n_evaluations
            out["after"] = tools.reserves()
            out["left"] = tools.remaining().simulator_evals
            try:
                tools.call("gsa_morris", _role="verification", model="linear",
                           parameters=["a", "b"], outputs=["y"], n_trajectories=3, seed=1)
                out["tagged_again"] = "RAN"
            except tools.BudgetExceededError as exc:
                out["tagged_again"] = str(exc)
            try:
                tools.call("gsa_morris", model="linear", parameters=["a", "b"],
                           outputs=["y"], n_trajectories=3, seed=1)
                out["untagged_again"] = "RAN"
            except tools.BudgetExceededError as exc:
                out["untagged_again"] = str(exc)
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
    assert out["untagged"] == 12  # the whole envelope is the untagged calls'
    assert out["tagged"] == 9
    assert out["after"]["verification"]["simulator_evals"] == 1
    assert out["left"] == 8  # the envelope does not pay the tagged call
    assert "reserve has 1" in out["tagged_again"]
    assert "8 of 20 remain" in out["untagged_again"]
    assert [c["role"] for c in reg.charged_calls if c["name"] == "gsa_morris"] == [
        None,
        "verification",
        "verification",
        None,
    ]
    assert reg.evaluations_used == 21


# ---------------------------------------------- the lead's Q9 ruling B (2026-10-29)


def test_a_proposer_spends_the_whole_p1_envelope_while_the_verifier_holds_its_reserve(tmp_path):
    """Ruling B: the untagged calls keep the cell's full envelope, exactly as P1 does.

    The same untagged sequence on a registry carrying the verifier's reserve (§8: 80
    evaluations, 1 assay unit, larger than this cell's envelope) and on one without (P1's
    registry) spends the same 20 evaluations and is refused the same way; the reserve is
    untouched throughout. The control: once the envelope is spent, the reserve still pays
    a tagged call, and P1's registry has nothing more.
    """
    agent, _, _ = registry(tmp_path / "agent", budget=Budget(20, 60.0, 0))
    agent.reserve("verification", simulator_evals=80, assay_units=1)
    p1, _, _ = registry(tmp_path / "p1", budget=Budget(20, 60.0, 0))
    for reg in (agent, p1):
        assert reg.call("gsa_morris", **_morris(4)).n_evaluations == 12
        assert reg.call("gsa_morris", **_morris(2)).n_evaluations == 6
        reg.call("simulate", model="linear")
        reg.call("simulate", model="linear")
        assert reg.remaining().simulator_evals == 0 and reg.evaluations_used == 20
        with pytest.raises(BudgetExceededError, match="0 of 20 remain"):
            reg.call("simulate", model="linear")
    assert agent.reserves_remaining()["verification"] == {
        "simulator_evals": 80,
        "simulator_evals_total": 80,
        "assay_units": 1,
        "assay_units_total": 1,
    }
    # the control
    assert agent.call("simulate", model="linear", role="verification").n_evaluations == 1
    assert agent.reserves_remaining()["verification"]["simulator_evals"] == 79
    assert agent.evaluations_used == 21 and agent.remaining().simulator_evals == 0
    with pytest.raises(BudgetExceededError, match="0 of 20 remain"):
        p1.call("simulate", model="linear", role="verification")  # no reserve: the envelope


def test_the_verifier_is_refused_past_80_evaluations_and_past_1_assay_unit(tmp_path):
    """Ruling B: the reserve is the verifier's whole budget; the envelope lends it nothing."""
    from tools import ToolArgumentError

    reg, run_dir, _ = registry(tmp_path, budget=Budget(100, 60.0, 0))
    reg.reserve("verification", simulator_evals=80, assay_units=1)
    for _ in range(6):  # 6 x 12 = 72
        assert reg.call("gsa_morris", role="verification", **_morris(4)).n_evaluations == 12
    assert reg.call("gsa_morris", role="verification", **_morris(2)).n_evaluations == 6
    reg.call("simulate", model="linear", role="verification")
    reg.call("simulate", model="linear", role="verification")
    assert reg.reserves_remaining()["verification"]["simulator_evals"] == 0
    assert reg.remaining().simulator_evals == 100  # the envelope is untouched
    with pytest.raises(BudgetExceededError, match="reserve has 0 of 80"):
        reg.call("simulate", model="linear", role="verification")
    assert read_calls(run_dir)[-1].outcome == "budget_exceeded"
    # the control: the envelope's 100 are still the untagged calls' to spend
    assert reg.call("simulate", model="linear").n_evaluations == 1
    assert reg.remaining().simulator_evals == 99 and reg.evaluations_used == 81
    # the assay unit: a 2-unit assay is refused by the 1-unit reserve; a 1-unit assay passes
    # the budget gate (and fails on this registry's missing truth channel, which charges
    # nothing); the envelope holds no unit, so an untagged 1-unit assay is refused (control)
    with pytest.raises(BudgetExceededError, match="costs 2 units, the verification reserve has 1"):
        reg.call("request_assay", assay="cod_total", day=10.0, role="verification")
    with pytest.raises(ToolArgumentError):
        reg.call("request_assay", assay="alkalinity", day=10.0, role="verification")
    assert reg.reserves_remaining()["verification"]["assay_units"] == 1
    with pytest.raises(BudgetExceededError, match="costs 1 units, 0 of 0 remain"):
        reg.call("request_assay", assay="alkalinity", day=10.0)
    assert reg.remaining().assay_units == 0


def test_with_no_tagged_call_the_logs_are_byte_identical_with_and_without_a_reserve(tmp_path):
    """P0, P1 and the procedural P2 set no reserve and tag no call: their logs cannot change.

    The same untagged sequence (two calls, then a refusal) under one injected clock, on a
    registry carrying the verifier's reserve and on one without: the visible
    ``calls.jsonl`` is byte-identical, and the truth-side log is identical but for its
    wall-clock timestamps (``t_utc``, the real clock). The control: the same sequence
    with its last call tagged, and both logs differ (the reserve runs it).
    """
    from tests.test_tool_registry import Clock

    def logs(name: str, *, reserve: bool, tag_last: bool) -> tuple[bytes, list[dict]]:
        clock = Clock()
        reg, run_dir, truth_dir = registry(tmp_path / name, budget=Budget(20, 60.0, 0), clock=clock)
        if reserve:
            reg.reserve("verification", simulator_evals=80, assay_units=1)
        reg.call("gsa_morris", **_morris(4))
        clock.now += 1.0
        reg.call("gsa_morris", **_morris(2))
        clock.now += 1.0
        role = "verification" if tag_last else None
        if tag_last:
            reg.call("gsa_morris", role=role, **_morris(1))  # 3 > 2 left: the reserve pays
        else:
            with pytest.raises(BudgetExceededError, match="2 of 20 remain"):
                reg.call("gsa_morris", **_morris(1))
        visible = (run_dir / "calls.jsonl").read_bytes()
        truth = [
            {k: v for k, v in json.loads(line).items() if k != "t_utc"}
            for line in (truth_dir / "calls.jsonl").read_text("utf-8").splitlines()
        ]
        assert visible and truth and all("n_evaluations" in c for c in truth)
        return visible, truth

    p1 = logs("p1", reserve=False, tag_last=False)
    agent = logs("agent", reserve=True, tag_last=False)
    assert p1 == agent
    assert logs("control", reserve=True, tag_last=True) != p1
