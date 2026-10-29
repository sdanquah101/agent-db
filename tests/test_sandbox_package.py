"""Package staging in the jail (docs/decisions.md, 2026-10-26, the lead's option A).

``tools.sandbox.launch`` stages the entry script's package into the box only when the
opt-in marker ``.jail-package`` sits beside the script; the staged directory goes on
``sys.path`` before the bootstrap's forbidden-module probe. Each property has its negative
control:

* without the marker the box holds exactly what it held before (P0's and P1's entries:
  the stub and ``workflow.py``); with it, the package appears;
* a staged package imports by its host name and sees its own modules; without the marker
  the same import fails; the launch reports the staged tree's digest;
* a package carrying a denied name (``state.py``, a ``scenarios/`` directory, ``sim`` as
  its own name, and the scanner's ``truth``/``truth_store``/``distinguish`` and the stub's
  ``tools``) is refused before the jail is built, a clean one runs, and a forbidden module
  planted after staging is refused by the bootstrap's probe;
* a symlink anywhere in the package (a file, or a directory that would carry ``state.py``
  past the name scan) and a file that is not a module are refused before the jail is built;
  a plain module beside them is staged and readable (the review of 2026-10-27, F1);
* the staged copy sees nothing of the host tree: not the package's host path, not a
  truth planted beside it, not the repository, while its own staged sibling is readable;
* every module of the staged P2 package is one the truth-isolation scanner checks, and the
  scanner catches a violation planted in a staged module;
* the staged tree's digest is stable and moves with any module;
* ``_python_chain`` keeps the real binary's path (the one-hop venv that dangled before,
  the review of 2026-10-26), and a one-hop venv runs in the jail where the old chain
  exited 127.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import tools.sandbox as sandbox_module
from tests.conftest import REPO_ROOT
from tests.test_truth_isolation import _TRUTH_MODULES, find_truth_references, workflow_modules
from tools import Budget, make_registry
from tools.sandbox import (
    FORBIDDEN_MODULES,
    JAIL_MARKER,
    JAIL_PACKAGE_MARKER,
    LAUNCH_RECORD,
    STAGED_NAME_DENY,
    SandboxError,
    _python_chain,
    launch,
    launch_record,
    stage,
    stage_workflow,
)
from tools.server import OUTPUTS_DIR

P0_ENTRY = REPO_ROOT / "workflows" / "p0_scripted" / "pipeline.py"
P1_ENTRY = REPO_ROOT / "workflows" / "p1_single_agent" / "agent.py"
P2_ENTRY = REPO_ROOT / "workflows" / "p2_multi_agent" / "workflow.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _registry():
    return make_registry(budget=Budget(5, 60.0, 0), seed=1)


def _package(root: Path, name: str = "pkg", *, marker: bool = True) -> Path:
    """A package ``root/<name>/`` with a helper module and an entry script."""
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    if marker:
        (pkg / JAIL_PACKAGE_MARKER).write_text("staged into the jail\n", encoding="utf-8")
    (pkg / "entry.py").write_text(
        textwrap.dedent(
            f"""
            import json, os, sys
            import tools
            from {name} import helper
            print(json.dumps({{
                "value": helper.VALUE,
                "sibling": open(helper.__file__).read().strip(),
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
    # "what it was" is a manifest by assertion: before this change `launch` put the stub
    # (`stage`) and the entry copy in the box and nothing else, and that is what is checked
    for entry in (P0_ENTRY, P1_ENTRY):
        assert not (entry.parent / JAIL_PACKAGE_MARKER).exists(), entry
        assert (entry.parent / "__init__.py").is_file()  # an __init__ alone opts nothing in
        box = tmp_path / entry.parent.name
        box.mkdir()
        stage(box)
        staged = stage_workflow(entry, box)
        assert staged.package is None and staged.package_sha256 is None
        assert sorted(p.name for p in box.iterdir()) == ["site", "workflow.py"]
        assert staged.script.read_bytes() == entry.read_bytes()
    # the negative control: the same P1 directory with the marker added stages its package
    copy = tmp_path / "copy" / "p1_single_agent"
    shutil.copytree(P1_ENTRY.parent, copy, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / JAIL_PACKAGE_MARKER).write_text("", encoding="utf-8")
    box = tmp_path / "box_marked"
    box.mkdir()
    stage(box)
    staged = stage_workflow(copy / "agent.py", box)
    assert staged.package == box / "package"
    assert sorted(p.name for p in box.iterdir()) == ["package", "site", "workflow.py"]
    assert (staged.package / "p1_single_agent" / "agent.py").read_bytes() == P1_ENTRY.read_bytes()
    assert not (staged.package / "p1_single_agent" / "__pycache__").exists()
    # the P2 package opts in, at its dotted path, with the ancestor package's __init__
    assert (P2_ENTRY.parent / JAIL_PACKAGE_MARKER).is_file()
    box = tmp_path / "box_p2"
    box.mkdir()
    staged = stage_workflow(P2_ENTRY, box)
    assert staged.package is not None
    assert (staged.package / "workflows" / "__init__.py").is_file()
    assert (staged.package / "workflows" / "p2_multi_agent" / "workflow.py").is_file()
    assert sorted(p.name for p in staged.package.iterdir()) == ["workflows"]
    assert SHA256.match(staged.package_sha256)


def test_a_staged_package_imports_by_its_host_name_and_the_marker_is_the_only_opt_in(tmp_path):
    pkg = _package(tmp_path / "with", marker=True)
    box = tmp_path / "box"
    box.mkdir()
    result = launch(pkg / "entry.py", _registry(), sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["value"] == 42 and report["sibling"] == "VALUE = 42"
    assert report["helper_file"] == "/box/package/pkg/helper.py"
    assert report["tools_origin"] == "/box/site/tools/__init__.py"  # the stub comes first
    assert report["path"][:2] == ["/box/site", "/box/package"]
    # the launch reports the staged tree's digest, the same `stage_workflow` computes
    again = tmp_path / "again"
    again.mkdir()
    assert result.package_sha256 == stage_workflow(pkg / "entry.py", again).package_sha256
    assert SHA256.match(result.package_sha256)
    # the negative control: the same package without the marker is not there
    bare = _package(tmp_path / "without", marker=False)
    box2 = tmp_path / "box2"
    box2.mkdir()
    result = launch(bare / "entry.py", _registry(), sandbox=box2, timeout_s=120.0)
    assert result.returncode != 0
    assert "No module named 'pkg'" in result.stderr
    assert not (box2 / "package").exists()
    assert result.package_sha256 is None


# ------------------------------------------------------------------ denied names


def test_a_package_with_a_denied_module_name_is_refused_and_a_clean_one_runs(tmp_path, monkeypatch):
    registry = _registry()
    # the deny list is exactly the forbidden modules, the scanner's truth modules and the
    # stub's name: an equality, so neither list can drift from the other (G4)
    assert set(STAGED_NAME_DENY) == set(FORBIDDEN_MODULES) | set(_TRUTH_MODULES) | {"tools"}
    assert len(STAGED_NAME_DENY) == len(set(STAGED_NAME_DENY))
    cases = []
    for name in STAGED_NAME_DENY:  # each denied name as a module inside the package ...
        pkg = _package(tmp_path / f"module_{name}")
        (pkg / f"{name}.py").write_text("SECRET = 1\n", encoding="utf-8")
        cases.append((pkg, name))
    directory = _package(tmp_path / "directory")  # ... as a directory ...
    (directory / "scenarios").mkdir()
    cases.append((directory, "scenarios"))
    for name in ("sim", "truth_store", "tools"):  # ... and as the package's own name
        cases.append((_package(tmp_path / f"own_{name}", name=name), name))
    for pkg, name in cases:
        box = tmp_path / f"box_{pkg.parent.name}"
        box.mkdir()
        with pytest.raises(SandboxError, match=f"forbidden module name \\['{name}'\\]"):
            launch(pkg / "entry.py", registry, sandbox=box, timeout_s=120.0)
        assert not (box / "package").exists()
        assert not (box / "workflow.py").exists()  # nothing was copied, the entry included (G2)
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
        staged = original(script, sandbox)
        (staged.package / "state.py").write_text("SECRET = 1\n", encoding="utf-8")
        return staged

    monkeypatch.setattr(sandbox_module, "stage_workflow", plant_after_staging)
    box = tmp_path / "box_planted"
    box.mkdir()
    result = launch(clean / "entry.py", registry, sandbox=box, timeout_s=120.0)
    assert result.returncode == 3
    assert "sandbox refused to start: forbidden modules resolve ['state']" in result.stderr
    assert "42" not in result.stdout


# ------------------------------------------------------------------ symlinks, non-modules


def test_a_symlink_or_a_non_module_anywhere_in_the_package_is_refused(tmp_path):
    registry = _registry()
    host = tmp_path / "host"
    host.mkdir()
    (host / "secret.json").write_text('{"truth": 1}', encoding="utf-8")
    (host / "dir").mkdir()
    (host / "dir" / "state.py").write_text("SECRET = 1\n", encoding="utf-8")
    (host / "dir" / "note.py").write_text("NOTE = 1\n", encoding="utf-8")

    # a file link, a directory link (which rglob would not descend, so its state.py would
    # pass a name scan), a link inside a subpackage, and a dangling link
    def linked(name: str, where: str, target: Path) -> Path:
        pkg = _package(tmp_path / name)
        path = pkg / where
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent != pkg:
            (path.parent / "__init__.py").write_text("", encoding="utf-8")
        path.symlink_to(target)
        return pkg

    # ... and a symlinked __init__.py of an ancestor package (staged with the package)
    outer = tmp_path / "ancestor" / "outer"
    inner = _package(outer, name="inner")
    (outer / "__init__.py").symlink_to(host / "dir" / "note.py")
    for pkg in (
        linked("file_link", "link_file.py", host / "secret.json"),
        linked("dir_link", "link_dir", host / "dir"),
        linked("nested_link", "sub/link.py", host / "dir" / "note.py"),
        linked("dangling", "gone.py", host / "missing.py"),
        # a link named like bytecode or its cache is refused, not skipped (G1)
        linked("pyc_link", "x.pyc", host / "secret.json"),
        linked("cache_link", "__pycache__", host / "dir"),
        inner,
    ):
        box = tmp_path / f"box_{pkg.parent.name}"
        box.mkdir()
        with pytest.raises(SandboxError, match="symlink"):
            launch(pkg / "entry.py", registry, sandbox=box, timeout_s=120.0)
        assert not (box / "package").exists()
        assert not (box / "workflow.py").exists()  # (G2)
        assert not (box / JAIL_MARKER).exists()
    # a file that is not a module enters no jail unscanned
    data = _package(tmp_path / "data")
    (data / "data.txt").write_text("sibling\n", encoding="utf-8")
    box = tmp_path / "box_data"
    box.mkdir()
    with pytest.raises(SandboxError, match="not a module"):
        launch(data / "entry.py", registry, sandbox=box, timeout_s=120.0)
    assert not (box / "package").exists()
    # the negative control: the plain modules beside them are staged and readable
    plain = _package(tmp_path / "plain")
    (plain / "sub").mkdir()
    (plain / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (plain / "sub" / "note.py").write_text("NOTE = 1\n", encoding="utf-8")
    box = tmp_path / "box_plain"
    box.mkdir()
    result = launch(plain / "entry.py", registry, sandbox=box, timeout_s=120.0)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["sibling"] == "VALUE = 42"
    assert (box / "package" / "pkg" / "sub" / "note.py").read_text() == "NOTE = 1\n"
    assert not any(p.is_symlink() for p in (box / "package").rglob("*"))


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
                ("sibling", os.path.join(here, "helper.py")),
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
            assert outcome == "OPENED"  # the negative control: its own staged module
        else:
            assert outcome != "OPENED", (label, outcome)
    assert report["walk"] == []
    assert report["host_paths_on_sys_path"] == []
    assert set(report["staged"]) - {"__pycache__"} == {  # the jail's own bytecode aside
        "__init__.py", "helper.py", "entry.py", "probe.py", JAIL_PACKAGE_MARKER
    }  # fmt: skip


# ------------------------------------------------------------------ the scanner


def test_the_scanner_covers_every_module_of_the_staged_p2_package(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    package = stage_workflow(P2_ENTRY, box).package
    assert package is not None
    staged = sorted(p.relative_to(package) for p in package.rglob("*.py"))
    assert staged, "nothing staged"
    scanned = {p.relative_to(REPO_ROOT) for p in workflow_modules()}
    assert set(staged) <= scanned, sorted(set(staged) - scanned)
    assert not [v for p in staged for v in find_truth_references(package / p)]
    # the staged tree holds modules and the marker, nothing else
    files = {p.name for p in package.rglob("*") if p.is_file()}
    assert all(name.endswith(".py") or name == JAIL_PACKAGE_MARKER for name in files), files
    # the negative control: a violation planted in a staged module is a finding
    bad = package / "workflows" / "p2_multi_agent" / "planted.py"
    bad.write_text("import sim\n", encoding="utf-8")
    assert [v.kind for v in find_truth_references(bad)] == ["import"]
    assert bad.relative_to(package) not in scanned  # and only because it is not on the host


# ------------------------------------------------------------------ the digest


def test_the_staged_trees_digest_is_stable_and_moves_with_any_module(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    one = stage_workflow(P2_ENTRY, first).package_sha256
    assert one == stage_workflow(P2_ENTRY, second).package_sha256
    assert SHA256.match(one)
    # a copy of the package with one byte changed in a module, or a module added, differs
    copy = tmp_path / "copy" / "p2_multi_agent"
    shutil.copytree(P2_ENTRY.parent, copy, ignore=shutil.ignore_patterns("__pycache__"))
    box = tmp_path / "box_copy"
    box.mkdir()
    same_layout = stage_workflow(copy / "workflow.py", box).package_sha256
    assert same_layout != one  # the dotted path differs (no `workflows/` ancestor): recorded
    (copy / "workflow.py").write_text(
        (copy / "workflow.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8"
    )
    box = tmp_path / "box_changed"
    box.mkdir()
    changed = stage_workflow(copy / "workflow.py", box).package_sha256
    assert changed != same_layout
    (copy / "extra.py").write_text("X = 1\n", encoding="utf-8")
    box = tmp_path / "box_added"
    box.mkdir()
    added = stage_workflow(copy / "workflow.py", box).package_sha256
    assert added not in {one, same_layout, changed}
    # a rename alone, same bytes, moves the digest too (a bytes-only hash would not; G6)
    (copy / "extra.py").rename(copy / "extra_renamed.py")
    box = tmp_path / "box_renamed"
    box.mkdir()
    renamed = stage_workflow(copy / "workflow.py", box)
    assert renamed.package_sha256 not in {one, same_layout, changed, added}
    assert "p2_multi_agent/extra_renamed.py" in renamed.modules
    assert "p2_multi_agent/extra.py" not in renamed.modules


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


# ------------------------------------------------------------------ every module, in the jail


def test_every_module_of_the_staged_p2_package_imports_in_the_jail(tmp_path):
    """The jail reaches every staged module by its dotted name.

    ``messages.py`` and ``agents.py`` included (the review of #40, H1: the arm's jailed run
    imports them only through the entry's dispatch). A copy of the package carries the
    probe as its entry.
    """
    host = tmp_path / "host" / "workflows"
    host.mkdir(parents=True)
    shutil.copy2(P2_ENTRY.parents[1] / "__init__.py", host / "__init__.py")
    copy = host / "p2_multi_agent"
    shutil.copytree(P2_ENTRY.parent, copy, ignore=shutil.ignore_patterns("__pycache__"))
    names = sorted(p.stem for p in P2_ENTRY.parent.glob("*.py") if p.stem != "__init__")
    assert {"workflow", "evidence", "messages", "agents"} <= set(names)
    probe = textwrap.dedent(
        f"""
        import importlib, json
        files = {{}}
        for name in {names!r}:
            try:
                files[name] = importlib.import_module("workflows.p2_multi_agent." + name).__file__
            except ImportError as exc:
                files[name] = type(exc).__name__ + ": " + str(exc)
        print(json.dumps(files))
        """
    )
    (copy / "probe.py").write_text(probe, encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    result = launch(copy / "probe.py", _registry(), sandbox=box, timeout_s=300.0)
    assert result.returncode == 0, result.stderr
    files = json.loads(result.stdout.strip().splitlines()[-1])
    assert files == {n: f"/box/package/workflows/p2_multi_agent/{n}.py" for n in names}
    # the negative control: a module removed from the copy is reached by nothing else (the
    # host tree is not on the path), and what imports it fails with it
    (copy / "messages.py").unlink()
    box2 = tmp_path / "box2"
    box2.mkdir()
    result = launch(copy / "probe.py", _registry(), sandbox=box2, timeout_s=300.0)
    assert result.returncode == 0, result.stderr
    files = json.loads(result.stdout.strip().splitlines()[-1])
    assert files["messages"].startswith("ModuleNotFoundError")
    # agents.py imports messages by `from workflows.p2_multi_agent import … messages`:
    # an ImportError naming it
    assert files["agents"].startswith("ImportError") and "'messages'" in files["agents"]
    assert files["evidence"] == "/box/package/workflows/p2_multi_agent/evidence.py"


# ------------------------------------------------------------------ the launch record


@pytest.fixture(scope="module")
def short_run(tmp_path_factory):
    from scenarios.schema import load_scenario
    from sim.plants import load_plant_config
    from sim.run.harness import generate_run

    root = tmp_path_factory.mktemp("store") / "runs"
    scenario = load_scenario(REPO_ROOT / "scenarios" / "S0-01.yaml").model_copy(
        update={"duration_days": 20.0}
    )
    return generate_run(scenario, "A", plant=load_plant_config("C"), runs_root=root)


def test_a_launch_with_a_staged_package_records_it_and_the_workflow_cannot_rewrite_the_record(
    short_run, tmp_path
):
    """``launch.json`` beside the workflow's outputs is the launcher's record of the jail.

    The privileged side's record of the entry and the staged tree (the review of
    2026-10-27, F3; of #40, H2), written before the workflow starts under a reserved name;
    the runner, which is frozen, is not involved.
    """
    root = short_run.paths.root
    pkg = _package(tmp_path / "with")
    (pkg / "probe.py").write_text(
        textwrap.dedent(
            f"""
            import json
            import tools
            out = {{"before": list(tools.run.output_files())}}
            out["other"] = tools.run.write_output("other.json", "{{}}")
            try:
                tools.run.write_output({LAUNCH_RECORD!r}, '{{"package_sha256": "forged"}}')
                out["forged"] = "WROTE"
            except tools.ToolError as exc:
                out["forged"] = type(exc).__name__ + ": " + str(exc)
            out["after"] = list(tools.run.output_files())
            print(json.dumps(out))
            """
        ),
        encoding="utf-8",
    )
    box = tmp_path / "box"
    box.mkdir()
    registry = make_registry(budget=Budget(2, 60.0, 0), seed=1, run_dir=root)
    result = launch(
        pkg / "probe.py", registry, sandbox=box, run_dir=root, timeout_s=120.0, workflow="probe"
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    out_dir = root / OUTPUTS_DIR / "probe"
    record = json.loads((out_dir / LAUNCH_RECORD).read_text(encoding="utf-8"))
    again = tmp_path / "again"
    again.mkdir()
    assert record == launch_record(stage_workflow(pkg / "probe.py", again))
    assert record["package_sha256"] == result.package_sha256
    assert SHA256.match(record["package_sha256"])
    assert record["entry"] == "probe.py"  # outside the repository: the name, never a path
    assert record["entry_sha256"] == hashlib.sha256((pkg / "probe.py").read_bytes()).hexdigest()
    assert record["modules"] == ["pkg/__init__.py", "pkg/entry.py", "pkg/helper.py", "pkg/probe.py"]
    # written before the workflow started; the workflow's forgery is refused by name, and
    # the record afterwards is the one the launcher wrote
    assert out["before"] == [LAUNCH_RECORD]
    assert out["forged"].startswith("ToolError: TruthAccessError"), out["forged"]
    assert "nothing else (CLAUDE.md rule 1)" in out["forged"]  # the server's one message
    assert out["after"] == [LAUNCH_RECORD, "other.json"]
    assert json.loads((out_dir / LAUNCH_RECORD).read_text(encoding="utf-8")) == record
    assert not (out_dir / (LAUNCH_RECORD + ".tmp")).exists()
    # the negative control: an entry without a package records nothing, and its output
    # directory holds only what it wrote (the frozen P0 and P1 records stay what they were)
    script = tmp_path / "plain.py"
    script.write_text(
        'import tools\ntools.run.write_output("state.json", "{}")\nprint("RAN")\n',
        encoding="utf-8",
    )
    box2 = tmp_path / "box2"
    box2.mkdir()
    registry = make_registry(budget=Budget(2, 60.0, 0), seed=1, run_dir=root)
    result = launch(script, registry, sandbox=box2, run_dir=root, timeout_s=120.0, workflow="plain")
    assert result.returncode == 0 and "RAN" in result.stdout, result.stderr
    assert result.package_sha256 is None
    assert sorted(p.name for p in (root / OUTPUTS_DIR / "plain").iterdir()) == ["state.json"]
