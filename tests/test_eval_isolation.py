"""Rule 1 for the evaluation suite: no workflow reaches ``eval/``, ``eval/`` reaches no workflow.

1. The rule-1 checker (``tests/test_truth_isolation.py``) flags a workflow module that
   imports ``eval`` by any spelling or opens a path under ``eval/`` -- and leaves a module
   that merely evaluates a model or spells ``evaluations`` alone (the negative control).
2. No module under ``eval/`` imports ``workflows``, and every import of the suite is on
   its own allow-list (records, schemas, declared configs; never a workflow, a scenario
   file, the harness or a plant), with the same checker shown to catch a module that does
   import a workflow (the negative control).
3. Every module actually under ``workflows/`` passes the extended checker.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from tests.conftest import REPO_ROOT
from tests.test_truth_isolation import find_truth_references, workflow_modules

EVAL_DIR = REPO_ROOT / "eval"

_WORKFLOW_REACHING_EVAL = '''
"""A workflow that reaches for the scorer."""
import eval
from eval import score_records
from eval.score import Scorer
import eval.aggregate as agg
a = open("eval/config.py")
b = open("../eval/records.py")
c = Path(root) / "eval"
d = open("/repo/EVAL/tables.py")
e = open("configs/eval.yaml")
'''

_WORKFLOW_EVALUATING_A_MODEL = '''
"""A workflow that evaluates the fitted model and counts its evaluations."""
import tools

def run(model):
    n_evaluations = 0
    out = tools.call("simulate", model=model, parameters={"k_dis": 1.0})
    n_evaluations += out.n_evaluations
    label = "eval_seconds_assumed"
    note = "the evaluation of the fitted model costs 12 s"
    return out, n_evaluations, label, note, "evaluations"
'''

_ALLOWED_EVAL_IMPORTS = {
    "eval",
    "numpy",
    "scipy",
    "pydantic",
    "yaml",
    "state.provenance",
    "state.task_state",
    "tools.config",
    "sim.run.layout",
    "sim.adm1",
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


def _allowed(module: str) -> bool:
    top = module.split(".", 1)[0]
    if top in sys.stdlib_module_names:
        return True
    return any(module == a or module.startswith(a + ".") for a in _ALLOWED_EVAL_IMPORTS)


def test_the_checker_flags_a_workflow_that_reaches_eval(tmp_path: Path):
    path = tmp_path / "reaching.py"
    path.write_text(_WORKFLOW_REACHING_EVAL)
    found = find_truth_references(path)
    lines = {v.line for v in found}
    # one finding per route: four imports, five path spellings
    assert {3, 4, 5, 6, 7, 8, 9, 10, 11} <= lines, [str(v) for v in found]
    assert any(v.kind == "path literal" and "eval/config.py" in v.detail for v in found)
    assert any(v.kind == "path literal" and v.detail == "'eval'" for v in found)
    # the scorer's own thresholds, by the PATH rule (not only by the dotted-module regex)
    assert any(v.kind == "path literal" and "configs/eval.yaml" in v.detail for v in found)


def test_the_checker_leaves_a_workflow_that_evaluates_a_model_alone(tmp_path: Path):
    path = tmp_path / "evaluating.py"
    path.write_text(_WORKFLOW_EVALUATING_A_MODEL)
    assert find_truth_references(path) == []


def test_every_workflow_module_passes_the_extended_checker():
    modules = workflow_modules()
    assert modules
    for module in modules:
        assert find_truth_references(module) == [], module


def test_no_eval_module_imports_a_workflow_or_anything_off_its_allow_list():
    modules = sorted(EVAL_DIR.rglob("*.py"))
    assert len(modules) >= 8
    for module in modules:
        for name in _imports(module):
            assert not name.startswith("workflows"), (module, name)
            assert _allowed(name), (module, name)


def test_the_eval_import_check_catches_a_module_that_imports_a_workflow(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("from workflows.p0_scripted import pipeline\nimport scenarios\n")
    names = _imports(bad)
    assert any(n.startswith("workflows") for n in names)
    assert not all(_allowed(n) for n in names)
    good = tmp_path / "good.py"
    good.write_text("import json\nfrom state.task_state import TaskState\nimport numpy as np\n")
    assert all(_allowed(n) for n in _imports(good))


def test_eval_and_workflows_are_disjoint_packages():
    assert (EVAL_DIR / "__init__.py").is_file()
    assert not (EVAL_DIR / "workflows").exists()
    assert not (REPO_ROOT / "workflows" / "eval").exists()
