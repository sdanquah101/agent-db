"""The one write a workflow may make: ``run.write_output`` into ``runs/<id>/workflows/<name>/``.

The P0 session's registry addition (2026-09-21; ``docs/p0_design.md`` §5, §6 point 3). A
jailed workflow cannot open the run directory, so its task state and report reach
``runs/<id>/workflows/<workflow>/`` through the registry server's :class:`OutputSink`.
This file drives the sink directly and over the wire: a plain name lands in the right
place; every other spelling -- absolute, traversal, the run's own files by ``..``, a
symlink planted in the output directory, a directory, an empty name -- is refused with the
rule-1 error; the observations, the manifest and the call log are untouched afterwards;
a server opened without a workflow name has no sink at all. The negative control is the
write that succeeds and reads back, and the listing that shows it.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from scenarios.schema import load_scenario
from sim.plants import load_plant_config
from sim.run.harness import generate_run
from state.run_view import TruthAccessError
from tests.conftest import REPO_ROOT
from tools import Budget, make_registry
from tools.sandbox import launch
from tools.server import OUTPUTS_DIR, OutputSink, RegistryServer


@pytest.fixture(scope="module")
def short_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("store") / "runs"
    scenario = load_scenario(REPO_ROOT / "scenarios" / "S0-01.yaml").model_copy(
        update={"duration_days": 20.0}
    )
    return generate_run(scenario, "A", plant=load_plant_config("C"), runs_root=root)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and OUTPUTS_DIR not in p.relative_to(root).parts
    }


def test_the_sink_writes_one_directory_and_refuses_every_other_spelling(short_run):
    root = short_run.paths.root
    before = _snapshot(root)
    sink = OutputSink(root, "p0")
    out_dir = root / OUTPUTS_DIR / "p0"
    assert out_dir.is_dir()

    # the negative control: a plain name is written, read back, and listed
    result = sink.write("state.json", json.dumps({"label": "none"}))
    assert result == {"relative": "state.json", "bytes": len(b'{"label": "none"}')}
    assert json.loads((out_dir / "state.json").read_text()) == {"label": "none"}
    assert sink.write("sub/report.json", "{}")["relative"] == "sub/report.json"
    assert sink.files() == ["state.json", "sub/report.json"]
    assert not (out_dir / "state.json.tmp").exists()

    for bad in (
        "",
        "   ",
        ".",
        "/etc/passwd",
        "/tmp/x.json",
        "../manifest.json",
        "../../manifest.json",
        "../../observations/sensors.json",
        "../../calls.jsonl",
        "sub/../../escape.json",
        "../p1/state.json",
        "..\\x.json",
        "sub",
    ):
        with pytest.raises(TruthAccessError):
            sink.write(bad, "x")
    # a planted symlink out of the directory is refused, even under a plain name
    link = out_dir / "link.json"
    link.symlink_to(short_run.paths.manifest)
    try:
        with pytest.raises(TruthAccessError):
            sink.write("link.json", "x")
        assert json.loads(short_run.paths.manifest.read_text())["run_id"] == short_run.run_id
    finally:
        link.unlink()
    with pytest.raises(ValueError):
        sink.write("bytes.bin", b"binary")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OutputSink(root, "../p0")
    # nothing else under the run changed
    assert _snapshot(root) == before


def test_the_write_reaches_the_run_through_the_jail_and_nowhere_else(short_run, tmp_path):
    """Over the wire: ``tools.run.write_output`` from a sandboxed workflow."""
    root = short_run.paths.root
    before = _snapshot(root)
    registry = make_registry(budget=Budget(2, 60.0, 0), seed=1, run_dir=root)
    script = tmp_path / "workflow.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import tools
            out = {}
            out["write"] = tools.run.write_output("state.json", json.dumps({"ok": True}))
            out["files"] = list(tools.run.output_files())
            for bad in ("../manifest.json", "/etc/x", "../../calls.jsonl", ""):
                try:
                    tools.run.write_output(bad, "x")
                    out[bad] = "WROTE"
                except tools.ToolError as exc:
                    out[bad] = type(exc).__name__ + ": " + str(exc)
            print(json.dumps(out))
            """
        ),
        encoding="utf-8",
    )
    box = tmp_path / "box"
    box.mkdir()
    result = launch(script, registry, sandbox=box, run_dir=root, timeout_s=120.0, workflow="p1")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["write"] == {"relative": "state.json", "bytes": 12}
    assert report["files"] == ["state.json"]  # p1's directory, not p0's from the test above
    for bad in ("../manifest.json", "/etc/x", "../../calls.jsonl", ""):
        assert report[bad].startswith("ToolError: TruthAccessError"), (bad, report[bad])
        assert "/" + "tmp" not in report[bad]  # no path in the message
    assert json.loads((root / OUTPUTS_DIR / "p1" / "state.json").read_text()) == {"ok": True}
    # nothing else under the run changed but the call log, which the registry appends to
    after = _snapshot(root)
    assert after.pop("calls.jsonl").startswith(before.pop("calls.jsonl"))
    assert after == before
    # the run tree now has exactly one more top-level entry, the workflows directory
    assert {p.name for p in root.iterdir()} == {
        "observations",
        "manifest.json",
        "calls.jsonl",
        OUTPUTS_DIR,
    }


def test_a_server_without_a_workflow_name_has_no_sink(short_run, tmp_path):
    registry = make_registry(budget=Budget(2, 60.0, 0), seed=1)
    with RegistryServer(registry, tmp_path / "s.sock", run_dir=short_run.paths.root) as server:
        reply = server._handle({"op": "run", "method": "write_output", "args": {}})
    assert reply == {
        "ok": False,
        "error": "this registry serves no workflow output directory",
        "kind": "RunError",
    }
    assert not (short_run.paths.root / OUTPUTS_DIR / "q").exists()
    assert os.listdir(tmp_path) == []
