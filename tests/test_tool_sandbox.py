"""The structural defence (decisions 2026-09-12, rounds two and three; design §4).

A workflow process must not have ``sim``, ``scenarios/`` or ``truth_store/`` importable
or readable. The static checker of ``test_truth_isolation.py`` names routes; this file
drives the *process*: a workflow-side script launched by :func:`tools.sandbox.launch`
attempts every route the requirement names --

* ``import sim`` (and ``scenarios``, ``anchor``, ``eval``, ``state``, ``sim.run.harness``,
  ``importlib.import_module``, ``__import__``);
* ``open("truth_store/...")`` and ``open("scenarios/...")``, the repository-relative
  spellings, and the run's own truth file by its relative path;
* walking upwards from the working directory to find a ``truth_store`` or ``scenarios``;
* **a plain child interpreter** (``subprocess.run([sys.executable, "-c", ...])``, no
  flags, site processing on) attempting ``import sim`` and, through ``sim.__file__``, the
  repository's ``truth_store/index.jsonl`` -- the coordinator's acceptance finding of
  2026-09-21;
* **the host interpreters by name** -- ``/usr/bin/python3``, ``/usr/local/bin/python3``,
  ``/usr/bin/python3.11``, ``shutil.which("python3")`` -- each absent or, run plain,
  unable to resolve ``sim`` (review finding B1 of 2026-09-21, closed by the jail);
* **the privileged process** through ``/proc/<ppid>/cwd`` and ``/proc/<ppid>/environ``,
  and the repository root, the run store and its parent **by their absolute paths**;

-- and reports each as failed. The **negative control** in the same process calls a tool
through ``import tools``, reads the run's sensors through ``tools.run``, and gets a budget
refusal as the right exception, so the test cannot pass by a sandbox that runs nothing.

The stub is also checked to be a copy of the source (no drift), the bootstrap to refuse
to run when a forbidden module resolves (fail closed), the launcher to raise rather than
run unjailed when the jail cannot be built, the launcher to refuse a sandbox inside the
repository or the run store, the jail to leave no mount behind, and the transport to
carry arrays bit for bit.
"""

from __future__ import annotations

import json
import socket
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import pytest

from scenarios.schema import load_scenario
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from state.provenance import read_calls
from tests.conftest import REPO_ROOT
from tools import AnalyticModel, Budget, make_registry, open_registry
from tools.sandbox import (
    FORBIDDEN_MODULES,
    SandboxError,
    _library_directories,
    launch,
    sandbox_interpreter,
    stage,
)
from tools.server import RegistryServer
from tools.transport import decode_arrays, encode_arrays, read_message, write_message

SHORT_DAYS = 30.0


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("store") / "runs"
    scenario = load_scenario(REPO_ROOT / "scenarios" / "S0-01.yaml").model_copy(
        update={"duration_days": SHORT_DAYS}
    )
    run = generate_run(scenario, "B", plant=load_plant_config("C"), runs_root=root)
    return run, scenario, root


WORKFLOW = textwrap.dedent(
    '''
    """A workflow that tries every forbidden route, then does legitimate work."""
    import importlib
    import json
    import os
    import sys

    report = {"imports": {}, "opens": {}, "walk": None, "control": {}}

    for name in ("sim", "scenarios", "anchor", "eval", "state", "sim.run.harness",
                 "sim.run.layout", "state.run_view"):
        try:
            importlib.import_module(name)
            report["imports"][name] = "IMPORTED"
        except ImportError as exc:
            report["imports"][name] = "ImportError: " + str(exc)[:60]
    try:
        __import__("sim")
        report["imports"]["__import__ sim"] = "IMPORTED"
    except ImportError:
        report["imports"]["__import__ sim"] = "ImportError"

    for path in ("truth_store/index.jsonl", "truth_store/salt", "scenarios/S0-01.yaml",
                 "../truth_store/index.jsonl", "../../truth_store/index.jsonl",
                 "../scenarios/S0-01.yaml", "../../scenarios/S0-01.yaml",
                 "faults.json", "../faults.json", "manifest.json", "observations/sensors.json"):
        try:
            with open(path, encoding="utf-8") as fh:
                fh.read(10)
            report["opens"][path] = "OPENED"
        except OSError as exc:
            report["opens"][path] = type(exc).__name__

    found = []
    here = os.getcwd()
    for _ in range(8):
        for name in ("truth_store", "scenarios", "sim"):
            if os.path.exists(os.path.join(here, name)):
                found.append(os.path.join(here, name))
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    report["walk"] = found
    report["sys_path_has_repo"] = any(
        os.path.exists(os.path.join(p, "sim", "__init__.py")) for p in sys.path if p
    )

    # the child-interpreter route: a plain interpreter, no flags, site processing on
    import subprocess

    probe = (
        "import json, os\\n"
        "out = {}\\n"
        "try:\\n"
        "    import sim\\n"
        "    out['import'] = 'IMPORTED ' + sim.__file__\\n"
        "    root = os.path.dirname(os.path.dirname(sim.__file__))\\n"
        "    try:\\n"
        "        open(os.path.join(root, 'truth_store', 'index.jsonl')).read(10)\\n"
        "        out['index'] = 'OPENED'\\n"
        "    except OSError as exc:\\n"
        "        out['index'] = type(exc).__name__\\n"
        "except ImportError as exc:\\n"
        "    out['import'] = 'ImportError: ' + str(exc)[:40]\\n"
        "    out['index'] = 'no root to derive'\\n"
        "print(json.dumps(out))\\n"
    )
    child = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    report["child"] = json.loads(child.stdout) if child.returncode == 0 else {"error": child.stderr}
    report["child_executable"] = sys.executable

    # the host-interpreter route (review finding B1): every name a workflow could run
    import shutil

    report["hosts"] = {}
    for name in ("/usr/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3.11",
                 "/usr/local/bin/python", shutil.which("python3"), shutil.which("python")):
        if not name or not os.path.exists(name):
            report["hosts"][str(name)] = "absent"
            continue
        r = subprocess.run([name, "-c", probe], capture_output=True, text=True)
        ok = r.returncode == 0
        report["hosts"][name] = json.loads(r.stdout) if ok else {"error": r.stderr[-80:]}
    report["path_env"] = os.environ.get("PATH")

    # the privileged process, and the hidden trees by their absolute paths
    report["ppid"] = os.getppid()
    report["absolute"] = {}
    for label, path in (("ppid_cwd", "/proc/%d/cwd" % os.getppid()),
                        ("ppid_environ", "/proc/%d/environ" % os.getppid()),
                        ("repo", "REPO_ROOT_PLACEHOLDER"),
                        ("store_parent", "STORE_PARENT_PLACEHOLDER"),
                        ("truth_index", "STORE_PARENT_PLACEHOLDER/truth_store/index.jsonl"),
                        ("run_dir", "RUN_DIR_PLACEHOLDER"),
                        ("home", "/home")):
        try:
            if os.path.isdir(path):
                os.listdir(path)
            else:
                open(path, "rb").read(10)
            report["absolute"][label] = "READ"
        except OSError as exc:
            report["absolute"][label] = type(exc).__name__
    report["root"] = sorted(os.listdir("/"))
    report["tmp_listing"] = os.listdir("/tmp")  # the jail's own, not the host's

    # the negative control: legitimate work through the registry
    import tools

    report["control"]["tools_origin"] = tools.__file__
    desc = tools.call("describe_model", model="linear")
    report["control"]["parameters"] = list(desc.parameter_names)
    out = tools.call("simulate", model="linear", parameters={"a": 2.0})
    report["control"]["y_last"] = float(out.outputs["y"][-1])
    report["control"]["units"] = dict(out.units)
    sensors = tools.run.sensors()
    report["control"]["sensor_names"] = sorted(sensors["sensors"])
    report["control"]["files"] = list(tools.run.files())
    report["control"]["manifest_keys"] = sorted(tools.run.manifest())
    log = tools.run.feed_log()
    report["control"]["feed_log_days"] = int(next(iter(log.values())).size)
    report["control"]["remaining_before"] = tools.remaining().simulator_evals
    try:
        tools.call("gsa_morris", model="linear", parameters=("a", "b"), outputs=("y",),
                   n_trajectories=50, seed=1)
        report["control"]["budget"] = "RAN"
    except tools.BudgetExceededError as exc:
        report["control"]["budget"] = "BudgetExceededError: " + str(exc)[:40]
    try:
        tools.call("simulate", model="linear", bogus=1)
        report["control"]["bad_arg"] = "RAN"
    except tools.ToolArgumentError:
        report["control"]["bad_arg"] = "ToolArgumentError"
    try:
        tools.run.read_text("../manifest.json")
        report["control"]["traversal"] = "READ"
    except tools.ToolError as exc:
        report["control"]["traversal"] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(report))
    '''
)

T = np.linspace(0.0, 10.0, 11)


def linear_model() -> AnalyticModel:
    return AnalyticModel(
        name="linear",
        parameter_names=("a", "b"),
        defaults=np.array([1.0, 0.0]),
        lower=np.array([-5.0, -5.0]),
        upper=np.array([5.0, 5.0]),
        function=lambda th: {"y": th[0] * T + th[1]},
        output_names=("y",),
        t=T,
        output_units={"y": "-"},
    )


def test_a_workflow_in_the_sandbox_cannot_reach_sim_scenarios_or_the_truth_store(
    clean_run, tmp_path
):
    run, _, _ = clean_run
    registry = make_registry(
        budget=Budget(20, 60.0, 0),
        seed=1,
        run_dir=run.paths.root,
        truth_log_dir=run.paths.truth,
        models={"linear": linear_model()},
    )
    script = tmp_path / "workflow.py"
    store_parent = run.paths.root.parent.parent
    script.write_text(
        WORKFLOW.replace("REPO_ROOT_PLACEHOLDER", str(REPO_ROOT))
        .replace("STORE_PARENT_PLACEHOLDER", str(store_parent))
        .replace("RUN_DIR_PLACEHOLDER", str(run.paths.root)),
        encoding="utf-8",
    )
    assert (store_parent / "truth_store" / "index.jsonl").is_file()  # it exists, out here
    box = tmp_path / "box"
    box.mkdir()
    result = launch(script, registry, sandbox=box, run_dir=run.paths.root, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    # every forbidden import fails ...
    for name, outcome in report["imports"].items():
        assert outcome.startswith("ImportError"), (name, outcome)
    # ... every forbidden open fails, the run's own files included ...
    for path, outcome in report["opens"].items():
        assert outcome != "OPENED", (path, outcome)
    # ... nothing hidden is reachable by walking up from the working directory ...
    assert report["walk"] == []
    assert report["sys_path_has_repo"] is False
    # ... a plain child interpreter fails the same way (the acceptance finding) ...
    assert report["child"]["import"].startswith("ImportError"), report["child"]
    assert report["child"]["index"] == "no root to derive"
    assert report["child_executable"] == "/venv/bin/python"  # the jail's view of the venv
    # ... every host interpreter name is absent or resolves nothing (finding B1) ...
    for name, outcome in report["hosts"].items():
        if outcome != "absent":  # the venv's own link is the one interpreter that exists
            assert outcome["import"].startswith("ImportError"), (name, outcome)
            assert outcome["index"] == "no root to derive", (name, outcome)
    assert report["hosts"]["/usr/bin/python3"] == "absent"
    assert report["hosts"]["/usr/local/bin/python3"] == "absent"
    assert report["path_env"] == "/venv/bin"
    # ... the privileged process and the hidden trees are not there by absolute path ...
    assert report["ppid"] == 0  # PID 1 of its own pid namespace
    for label, outcome in report["absolute"].items():
        assert outcome != "READ", (label, outcome)
    assert "home" not in report["root"] and "root" not in report["root"]
    assert report["tmp_listing"] == []
    # the root holds the jail's own directories and, where the host interpreter's library
    # directory lies outside /usr/lib (a runner's /opt/hostedtoolcache), its top component
    libdir_tops = {Path(d).parts[1] for d in _library_directories(sandbox_interpreter())}
    assert set(report["root"]) <= {
        "box", "dev", "etc", "lib", "lib64", "oldroot", "proc", "tmp", "usr", "venv", *libdir_tops
    }  # fmt: skip
    assert not {"home", "root", "run", "runs", "truth_store", "srv", "mnt"} & set(report["root"])

    # ... and the negative control did legitimate work through the stub
    control = report["control"]
    assert control["tools_origin"] == "/box/site/tools/__init__.py"  # the jail's view
    assert control["parameters"] == ["a", "b"]
    assert control["y_last"] == pytest.approx(20.0)
    assert control["units"] == {"y": "-"}
    assert set(control["sensor_names"]) == {
        "temperature",
        "ph",
        "gas_flow",
        "ch4_fraction",
        "alkalinity",
        "vfa_total",
        "tan",
        "cod_total",
    }  # Tier B
    assert set(control["files"]) == {
        "sensors.json", "feed_log.csv", "feed_assays.csv", "operator_notes.json"
    }  # fmt: skip
    assert "run_id" in control["manifest_keys"] and "scenario_id" not in control["manifest_keys"]
    assert control["feed_log_days"] == int(SHORT_DAYS)
    assert control["remaining_before"] == 19
    assert control["budget"].startswith("BudgetExceededError")
    assert control["bad_arg"] == "ToolArgumentError"
    assert control["traversal"].startswith("ToolError: TruthAccessError")
    assert "rule 1" in control["traversal"] and "/tmp" not in control["traversal"]
    # every call is in the run's visible log, projected
    names = [r.name for r in read_calls(run.paths.root)]
    assert (
        names[-4:] == ["simulate", "gsa_morris", "simulate", "describe_model"]
        or names.count("simulate") >= 2
    )
    assert result.n_requests == 10


def test_the_bootstrap_refuses_to_run_when_a_forbidden_module_resolves(tmp_path, monkeypatch):
    """Fail closed: the check is live. With numpy declared forbidden, the venv trips it."""
    import tools.sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module, "FORBIDDEN_MODULES", (*FORBIDDEN_MODULES, "numpy"))
    registry = make_registry(budget=Budget(5, 60.0, 0), seed=1, models={"linear": linear_model()})
    script = tmp_path / "workflow.py"
    script.write_text("print('RAN')\n", encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    # the sandbox interpreter's own clean-check sees numpy as forbidden and refuses first
    with pytest.raises(SandboxError, match="resolves"):
        launch(script, registry, sandbox=box, timeout_s=60.0)
    # ... and, past that check, the bootstrap inside the jail refuses too
    monkeypatch.setattr(sandbox_module, "_forbidden_resolving", lambda python: [])
    result = launch(script, registry, sandbox=box, timeout_s=60.0)
    assert result.returncode == 3
    assert "sandbox refused to start" in result.stderr and "numpy" in result.stderr
    assert "RAN" not in result.stdout
    assert result.n_requests == 0


def test_launch_raises_rather_than_run_unjailed(tmp_path, monkeypatch):
    """No weak mode: without unshare, or with a jail that cannot be built, nothing runs."""
    import tools.sandbox as sandbox_module

    registry = make_registry(budget=Budget(5, 60.0, 0), seed=1, models={"linear": linear_model()})
    script = tmp_path / "workflow.py"
    script.write_text("print('RAN')\n", encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    with pytest.raises(SandboxError, match="unshare"):
        launch(script, registry, sandbox=box, timeout_s=60.0)
    monkeypatch.undo()
    # a jail script that fails before the pivot exits JAIL_EXIT: the launcher raises
    monkeypatch.setattr(
        sandbox_module, "_JAIL_SCRIPT", "#!/bin/sh\necho 'jail: forced failure' >&2\nexit 111\n"
    )
    with pytest.raises(SandboxError, match="could not be built"):
        launch(script, registry, sandbox=box, timeout_s=60.0)
    assert not (box / "cwd" / "RAN").exists()


def test_the_jail_leaves_no_mount_behind(clean_run, tmp_path):
    run, _, _ = clean_run
    registry = make_registry(budget=Budget(5, 60.0, 0), seed=1, models={"linear": linear_model()})
    script = tmp_path / "workflow.py"
    script.write_text("import tools; print(tools.remaining().simulator_evals)\n", encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    result = launch(script, registry, sandbox=box, run_dir=run.paths.root, timeout_s=60.0)
    assert result.returncode == 0 and result.stdout.strip() == "5"
    mounts = Path("/proc/self/mounts").read_text(encoding="utf-8")
    assert str(box) not in mounts
    assert not any((box / "root").iterdir())  # the tmpfs root was private to the namespace


def test_the_sandbox_interpreter_is_clean_and_cached(tmp_path):
    python = sandbox_interpreter()
    assert python.is_file()
    assert str(REPO_ROOT) not in str(python)
    # a plain run of it, from the repository root as cwd, resolves nothing forbidden
    probe = (
        "import importlib.util, json; "
        f"print(json.dumps([n for n in {list(FORBIDDEN_MODULES)!r} "
        "if importlib.util.find_spec(n) is not None]))"
    )
    out = subprocess.run(
        [str(python), "-c", probe], capture_output=True, text=True, check=True, cwd=str(tmp_path)
    )
    assert json.loads(out.stdout) == []
    # and it carries what the stub needs
    out = subprocess.run(
        [str(python), "-c", "import numpy, scipy, pydantic; print('ok')"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert out.stdout.strip() == "ok"
    assert sandbox_interpreter() == python  # cached, not rebuilt


def test_launch_refuses_a_sandbox_inside_the_repository_or_the_run_store(clean_run, tmp_path):
    run, _, root = clean_run
    registry = make_registry(budget=Budget(5, 60.0, 0), seed=1, models={"linear": linear_model()})
    script = tmp_path / "workflow.py"
    script.write_text("print('RAN')\n", encoding="utf-8")
    for box in (
        REPO_ROOT / "runs" / "box",  # under the repository root
        root / "box",  # under the run store
        root.parent / "box",  # under the run store's parent, beside the truth store
        run.paths.root / "box",  # inside the run itself
    ):
        with pytest.raises(SandboxError, match="lies under"):
            launch(script, registry, sandbox=box, run_dir=run.paths.root, timeout_s=60.0)
        assert not box.exists()


def test_the_staged_stub_is_a_copy_of_the_source(tmp_path):
    site = stage(tmp_path)
    source = Path(REPO_ROOT / "tools")
    assert (site / "tools" / "__init__.py").read_bytes() == (
        source / "client" / "__init__.py"
    ).read_bytes()
    assert (site / "tools" / "transport.py").read_bytes() == (source / "transport.py").read_bytes()
    for py in (source / "schemas").glob("*.py"):
        assert (site / "tools" / "schemas" / py.name).read_bytes() == py.read_bytes()
    staged = {p.name for p in (site / "tools").rglob("*.py")}
    assert (
        "registry.py" not in staged and "fitted.py" not in staged and "privileged.py" not in staged
    )
    # the stub imports nothing forbidden
    text = "\n".join(p.read_text() for p in (site / "tools").rglob("*.py"))
    for name in FORBIDDEN_MODULES:
        assert f"import {name}" not in text and f"from {name}" not in text


def test_the_transport_carries_arrays_bit_for_bit_and_frames_messages(tmp_path):
    rng = np.random.default_rng(0)
    arrays = {
        "a": rng.standard_normal((3, 4)),
        "b": np.array([np.nan, 1e-300, np.inf]),
        "nested": [np.arange(5, dtype=np.int64), {"c": np.float32(1.5)}],
    }
    round_trip = decode_arrays(json.loads(json.dumps(encode_arrays(arrays))))
    np.testing.assert_array_equal(round_trip["a"], arrays["a"])
    assert np.array_equal(round_trip["b"], arrays["b"], equal_nan=True)
    assert round_trip["a"].dtype == arrays["a"].dtype
    np.testing.assert_array_equal(round_trip["nested"][0], arrays["nested"][0])
    assert round_trip["nested"][1]["c"] == 1.5

    registry = make_registry(budget=Budget(5, 60.0, 0), seed=1, models={"linear": linear_model()})
    path = tmp_path / "s.sock"
    with RegistryServer(registry, path), socket.socket(socket.AF_UNIX) as client:
        client.connect(str(path))
        write_message(client, {"op": "tools"})
        assert "simulate" in read_message(client)["result"]
        write_message(client, {"op": "call", "name": "simulate", "args": {"model": "linear"}})
        reply = read_message(client)
        assert reply["ok"] and reply["result"]["outcome"] == "ok"
        write_message(client, {"op": "run", "method": "sensors"})
        assert read_message(client)["kind"] == "RunError"
        write_message(client, {"op": "nonsense"})
        assert read_message(client)["kind"] == "ProtocolError"


def test_the_privileged_registry_of_a_run_serves_the_fitted_model_in_the_sandbox(
    clean_run, tmp_path
):
    """End to end: open_registry on a generated run, a sandboxed workflow simulating."""
    run, scenario, root = clean_run
    registry = open_registry(run.run_id, runs_root=root, scenario=scenario)
    script = tmp_path / "workflow.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import tools
            desc = tools.call("describe_model")
            sim = tools.call("simulate", parameters={"k_hyd_ch": 1.2})
            loads = tools.call("feed_loads")
            print(json.dumps({
                "n_params": len(desc.parameter_names),
                "ph_last": float(sim.outputs["pH"][-1]),
                "unit": sim.units["q_gas_stp_dry"],
                "cod": float(loads.cod_kg_d.mean()),
                "left": tools.remaining().simulator_evals,
            }))
            """
        ),
        encoding="utf-8",
    )
    box = tmp_path / "box"
    box.mkdir()
    result = launch(script, registry, sandbox=box, run_dir=run.paths.root, timeout_s=300.0)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["n_params"] == len(registry.configs.model.parameters)
    assert 6.5 < report["ph_last"] < 8.0
    assert report["unit"].startswith("m3/d")
    assert report["cod"] > 0
    assert report["left"] == scenario.budget.simulator_evals - 1
