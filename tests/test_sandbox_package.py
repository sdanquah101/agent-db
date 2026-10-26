"""Package staging in the jail (docs/decisions.md, 2026-10-26, the lead's option A).

``tools.sandbox.launch`` stages the entry script's package into the box only when the
opt-in marker ``.jail-package`` sits beside the script; the staged directory goes on
``sys.path`` before the bootstrap's forbidden-module probe. Each property has its negative
control:

* without the marker the box holds exactly what it held before (P0's and P1's entries:
  the stub and ``workflow.py``); with it, the package appears;
* a staged package imports by its host name and sees its own files; without the marker
  the same import fails;
* a package carrying a forbidden module name (``state.py``, a ``scenarios/`` directory,
  or ``sim`` as its own name) is refused before the jail is built, a clean one runs, and a
  forbidden module planted after staging is refused by the bootstrap's probe;
* the staged copy sees nothing of the host tree: not the package's host path, not a
  truth planted beside it, not the repository, while its own staged sibling is readable;
* every module of the staged P2 package is one the truth-isolation scanner checks, and the
  scanner catches a violation planted in a staged module;
* ``_python_chain`` keeps the real binary's path (the one-hop venv that dangled before,
  the review of 2026-10-26), and a one-hop venv runs in the jail where the old chain
  exited 127.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import tools.sandbox as sandbox_module
from tests.conftest import REPO_ROOT
from tests.test_truth_isolation import find_truth_references, workflow_modules
from tools import Budget, make_registry
from tools.sandbox import (
    FORBIDDEN_MODULES,
    JAIL_MARKER,
    JAIL_PACKAGE_MARKER,
    SandboxError,
    _python_chain,
    launch,
    stage,
    stage_workflow,
)

P0_ENTRY = REPO_ROOT / "workflows" / "p0_scripted" / "pipeline.py"
P1_ENTRY = REPO_ROOT / "workflows" / "p1_single_agent" / "agent.py"
P2_ENTRY = REPO_ROOT / "workflows" / "p2_multi_agent" / "workflow.py"


def _registry():
    return make_registry(budget=Budget(5, 60.0, 0), seed=1)


def _package(root: Path, name: str = "pkg", *, marker: bool = True) -> Path:
    """A package ``root/<name>/`` with a helper module, a data file and an entry script."""
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    (pkg / "data.txt").write_text("sibling\n", encoding="utf-8")
    if marker:
        (pkg / JAIL_PACKAGE_MARKER).write_text("staged into the jail\n", encoding="utf-8")
    (pkg / "entry.py").write_text(
        textwrap.dedent(
            f"""
            import json, os, sys
            import tools
            from {name} import helper
            here = os.path.dirname(helper.__file__)
            print(json.dumps({{
                "value": helper.VALUE,
                "sibling": open(os.path.join(here, "data.txt")).read().strip(),
                "helper_file": helper.__file__,
                "tools_origin": tools.__file__,
                "path": sys.path,
            }}))
            """
        ),
        encoding="utf-8",
    )
    return pkg


# ------------------------------------------------------------------ the opt-in


def test_without_the_marker_the_box_is_what_it_was_and_p0_and_p1_carry_no_marker(tmp_path):
    for entry in (P0_ENTRY, P1_ENTRY):
        assert not (entry.parent / JAIL_PACKAGE_MARKER).exists(), entry
        assert (entry.parent / "__init__.py").is_file()  # an __init__ alone opts nothing in
        box = tmp_path / entry.parent.name
        box.mkdir()
        stage(box)
        staged, package = stage_workflow(entry, box)
        assert package is None
        assert sorted(p.name for p in box.iterdir()) == ["site", "workflow.py"]
        assert staged.read_bytes() == entry.read_bytes()
    # the negative control: the same P1 directory with the marker added stages its package
    copy = tmp_path / "copy" / "p1_single_agent"
    shutil.copytree(P1_ENTRY.parent, copy, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / JAIL_PACKAGE_MARKER).write_text("", encoding="utf-8")
    box = tmp_path / "box_marked"
    box.mkdir()
    stage(box)
    staged, package = stage_workflow(copy / "agent.py", box)
    assert package == box / "package"
    assert sorted(p.name for p in box.iterdir()) == ["package", "site", "workflow.py"]
    assert (package / "p1_single_agent" / "agent.py").read_bytes() == P1_ENTRY.read_bytes()
    assert not (package / "p1_single_agent" / "__pycache__").exists()
    # the P2 package opts in, at its dotted path, with the ancestor package's __init__
    assert (P2_ENTRY.parent / JAIL_PACKAGE_MARKER).is_file()
    box = tmp_path / "box_p2"
    box.mkdir()
    _, package = stage_workflow(P2_ENTRY, box)
    assert package is not None
    assert (package / "workflows" / "__init__.py").is_file()
    assert (package / "workflows" / "p2_multi_agent" / "workflow.py").is_file()
    assert sorted(p.name for p in package.iterdir()) == ["workflows"]


def test_a_staged_package_imports_by_its_host_name_and_the_marker_is_the_only_opt_in(tmp_path):
    pkg = _package(tmp_path / "with", marker=True)
    box = tmp_path / "box"
    box.mkdir()
    result = launch(pkg / "entry.py", _registry(), sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["value"] == 42 and report["sibling"] == "sibling"
    assert report["helper_file"] == "/box/package/pkg/helper.py"
    assert report["tools_origin"] == "/box/site/tools/__init__.py"  # the stub comes first
    assert report["path"][:2] == ["/box/site", "/box/package"]
    # the negative control: the same package without the marker is not there
    bare = _package(tmp_path / "without", marker=False)
    box2 = tmp_path / "box2"
    box2.mkdir()
    result = launch(bare / "entry.py", _registry(), sandbox=box2, timeout_s=120.0)
    assert result.returncode != 0
    assert "No module named 'pkg'" in result.stderr
    assert not (box2 / "package").exists()


# ------------------------------------------------------------------ forbidden names


def test_a_package_with_a_forbidden_module_name_is_refused_and_a_clean_one_runs(
    tmp_path, monkeypatch
):
    registry = _registry()
    # a forbidden module inside the package, a forbidden directory, the package's own name
    planted = _package(tmp_path / "module")
    (planted / "state.py").write_text("SECRET = 1\n", encoding="utf-8")
    directory = _package(tmp_path / "directory")
    (directory / "scenarios").mkdir()
    own_name = _package(tmp_path / "own", name="sim")
    for pkg, name in ((planted, "state"), (directory, "scenarios"), (own_name, "sim")):
        box = tmp_path / f"box_{name}"
        box.mkdir()
        with pytest.raises(SandboxError, match=f"forbidden module name \\['{name}'\\]"):
            launch(pkg / "entry.py", registry, sandbox=box, timeout_s=120.0)
        assert not (box / "package").exists()
        assert not (box / JAIL_MARKER).exists()  # refused before any jail was built
    # the negative control: the clean package runs
    clean = _package(tmp_path / "clean")
    box = tmp_path / "box_clean"
    box.mkdir()
    result = launch(clean / "entry.py", registry, sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    # past the launcher's check, the bootstrap's probe refuses a forbidden module planted
    # into the staged tree (the staged directory is on the path before the probe)
    original = sandbox_module.stage_workflow

    def plant_after_staging(script, sandbox):
        staged, package = original(script, sandbox)
        (package / "state.py").write_text("SECRET = 1\n", encoding="utf-8")
        return staged, package

    monkeypatch.setattr(sandbox_module, "stage_workflow", plant_after_staging)
    box = tmp_path / "box_planted"
    box.mkdir()
    result = launch(clean / "entry.py", registry, sandbox=box, timeout_s=120.0)
    assert result.returncode == 3
    assert "sandbox refused to start: forbidden modules resolve ['state']" in result.stderr
    assert "42" not in result.stdout


# ------------------------------------------------------------------ no path escape


def test_the_staged_copy_sees_nothing_of_the_host_tree(tmp_path):
    host_root = tmp_path / "host"
    pkg = _package(host_root)
    # a truth planted beside the package on the host, and the hidden tree's spelling
    (host_root / "planted_truth.json").write_text('{"truth": 1}', encoding="utf-8")
    (host_root / "truth_store").mkdir()
    (host_root / "truth_store" / "index.jsonl").write_text("{}\n", encoding="utf-8")
    (pkg / "probe.py").write_text(
        textwrap.dedent(
            f"""
            import json, os, sys
            from pkg import helper
            here = os.path.dirname(os.path.abspath(helper.__file__))
            opens = {{}}
            for label, path in (
                ("host_package", {str(pkg / "helper.py")!r}),
                ("planted_beside", {str(host_root / "planted_truth.json")!r}),
                ("planted_relative", os.path.join(here, "..", "planted_truth.json")),
                ("truth_store_relative", os.path.join(here, "..", "truth_store", "index.jsonl")),
                ("truth_store_host", {str(host_root / "truth_store" / "index.jsonl")!r}),
                ("repository", {str(REPO_ROOT / "CLAUDE.md")!r}),
                ("sibling", os.path.join(here, "data.txt")),
            ):
                try:
                    with open(path, encoding="utf-8") as fh:
                        fh.read(10)
                    opens[label] = "OPENED"
                except OSError as exc:
                    opens[label] = type(exc).__name__
            found = []
            walk = here
            for _ in range(8):
                for name in ("truth_store", "scenarios", "sim", "planted_truth.json"):
                    if os.path.exists(os.path.join(walk, name)):
                        found.append(os.path.join(walk, name))
                walk = os.path.dirname(walk)
            print(json.dumps({{
                "opens": opens,
                "walk": found,
                "here": here,
                "staged": sorted(os.listdir(here)),
                "host_paths_on_sys_path": [p for p in sys.path if {str(tmp_path)!r} in p],
            }}))
            """
        ),
        encoding="utf-8",
    )
    box = tmp_path / "box"
    box.mkdir()
    result = launch(pkg / "probe.py", _registry(), sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["here"] == "/box/package/pkg"
    for label, outcome in report["opens"].items():
        if label == "sibling":
            assert outcome == "OPENED"  # the negative control: its own staged file
        else:
            assert outcome != "OPENED", (label, outcome)
    assert report["walk"] == []
    assert report["host_paths_on_sys_path"] == []
    assert set(report["staged"]) - {"__pycache__"} == {  # the jail's own bytecode aside
        "__init__.py", "helper.py", "data.txt", "entry.py", "probe.py", JAIL_PACKAGE_MARKER
    }  # fmt: skip


# ------------------------------------------------------------------ the scanner


def test_the_scanner_covers_every_module_of_the_staged_p2_package(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    _, package = stage_workflow(P2_ENTRY, box)
    assert package is not None
    staged = sorted(p.relative_to(package) for p in package.rglob("*.py"))
    assert staged, "nothing staged"
    scanned = {p.relative_to(REPO_ROOT) for p in workflow_modules()}
    assert set(staged) <= scanned, sorted(set(staged) - scanned)
    assert not [v for p in staged for v in find_truth_references(package / p)]
    # the negative control: a violation planted in a staged module is a finding
    bad = package / "workflows" / "p2_multi_agent" / "planted.py"
    bad.write_text("import sim\n", encoding="utf-8")
    assert [v.kind for v in find_truth_references(bad)] == ["import"]
    assert bad.relative_to(package) not in scanned  # and only because it is not on the host


# ------------------------------------------------------------------ the python chain


def _link(path: Path, target: Path | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def test_the_python_chain_keeps_the_real_binary_one_hop_and_multi_hop(tmp_path):
    real = tmp_path / "real" / "bin" / "python3.11"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"#!binary\n")
    # one hop out of the venv: bin/python -> python3.11 -> the real binary
    one = tmp_path / "one"
    _link(one / "bin" / "python3.11", real)
    _link(one / "bin" / "python", "python3.11")
    assert _python_chain(one / "bin" / "python") == (real, [str(real)])
    # the control: a chain through a host link still names every hop, the real one last
    hop = tmp_path / "hop" / "python3.11"
    _link(hop, real)
    multi = tmp_path / "multi"
    _link(multi / "bin" / "python3.11", hop)
    _link(multi / "bin" / "python", "python3.11")
    assert _python_chain(multi / "bin" / "python") == (real, [str(hop), str(real)])
    # a venv made with copies needs no link at all
    copies = tmp_path / "copies"
    (copies / "bin").mkdir(parents=True)
    shutil.copy2(real, copies / "bin" / "python")
    assert _python_chain(copies / "bin" / "python") == (copies / "bin" / "python", [])


def test_a_one_hop_venv_runs_in_the_jail_where_the_old_chain_dangled(tmp_path, monkeypatch):
    real = Path(sys.executable).resolve()
    venv = tmp_path / "venv"
    subprocess.run(
        [str(real), "-m", "venv", "--without-pip", str(venv)],
        check=True, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    python = venv / "bin" / "python"
    link = venv / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    assert Path(os.readlink(link)) == real  # one hop: the venv links the binary itself
    monkeypatch.setattr(sandbox_module, "sandbox_interpreter", lambda **kw: python)
    script = tmp_path / "workflow.py"
    script.write_text("print('RAN')\n", encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    result = launch(script, _registry(), sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "RAN"
    # the control: the chain as it was (the real binary's path dropped) leaves
    # /venv/bin/python dangling in the jail; the jail starts, the interpreter is not found
    fixed = sandbox_module._python_chain

    def old_chain(interpreter):
        real_binary, names = fixed(interpreter)
        return real_binary, [n for n in names if n != str(real_binary)]

    monkeypatch.setattr(sandbox_module, "_python_chain", old_chain)
    box2 = tmp_path / "box2"
    box2.mkdir()
    result = launch(script, _registry(), sandbox=box2, timeout_s=120.0)
    assert (box2 / JAIL_MARKER).exists()
    assert result.returncode == 127 and "RAN" not in result.stdout
    assert FORBIDDEN_MODULES  # the probe never ran: nothing started
