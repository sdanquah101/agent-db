"""Enforce CLAUDE.md rule 1: hidden truth is never readable by workflows.

Ground truth is written only to ``runs/<id>/truth/``. Nothing under ``workflows/`` may
import a ``truth`` module or reference a path with a ``truth`` segment. The check is
static (AST-based) so it covers code that is never executed in tests.

The checker is exercised against synthetic violating and clean files first, so the
test cannot pass simply because ``workflows/`` is still mostly empty.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / "workflows"

# A path-like string literal with "truth" as a segment: "runs/x/truth/", "/truth",
# "truth/params.json", or the bare segment "truth" (as in Path(run) / "truth").
_TRUTH_PATH = re.compile(r"(?i)(^|[/\\])truth([/\\]|$)")


@dataclass(frozen=True)
class Violation:
    """One forbidden reference to hidden truth."""

    path: Path
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        """Format as file:line: kind: detail."""
        return f"{self.path}:{self.line}: {self.kind}: {self.detail}"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Return ids of string constants that are docstrings, which are exempt."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                exempt.add(id(body[0].value))
    return exempt


def find_truth_references(path: Path) -> list[Violation]:
    """Statically find imports of, or path references to, hidden truth in one module.

    Args:
        path: A Python source file.

    Returns:
        Every violation found, in source order.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    exempt = _docstring_nodes(tree)
    found: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "truth" in alias.name.lower().split("."):
                    found.append(Violation(path, node.lineno, "import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            segments = module.split(".") if module else []
            names = [alias.name.lower() for alias in node.names]
            if "truth" in segments or "truth" in names:
                names_str = ", ".join(alias.name for alias in node.names)
                found.append(
                    Violation(path, node.lineno, "import", f"from {node.module} import {names_str}")
                )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in exempt
            and _TRUTH_PATH.search(node.value)
        ):
            found.append(Violation(path, node.lineno, "path literal", repr(node.value)))

    return found


def workflow_modules() -> list[Path]:
    """Every Python module under workflows/, recursively."""
    return sorted(WORKFLOWS_DIR.rglob("*.py"))


# --- self-check: the checker must catch each forbidden pattern -----------------------

_VIOLATING_SOURCE = '''
"""Docstring mentioning runs/<id>/truth/ is allowed."""
import sim.truth
from sim import truth
from sim.truth.model import TruthModel
from pathlib import Path

def load(run: Path):
    a = open(run / "truth" / "params.json")
    b = open(f"{run}/truth/labels.json")
    c = open("/data/runs/abc/TRUTH/x.yaml")
    d = run.joinpath("truth")
    return a, b, c, d
'''

_CLEAN_SOURCE = '''
"""Ground truth is discussed here in a docstring only; that is fine."""
from pathlib import Path

from tools import registry

def load(run: Path):
    # "truthful" and "untruth" are not path segments and must not be flagged.
    label = "truthful"
    obs = open(run / "observations.csv")
    return registry, label, obs, "untruth"
'''


def test_checker_catches_every_forbidden_pattern(tmp_path: Path):
    bad = tmp_path / "bad_workflow.py"
    bad.write_text(_VIOLATING_SOURCE, encoding="utf-8")
    kinds = [v.kind for v in find_truth_references(bad)]
    assert kinds.count("import") == 3, kinds
    # "truth" (joined), "/truth/" (f-string part), "/TRUTH/", "truth" (joinpath)
    assert kinds.count("path literal") == 4, kinds


def test_checker_ignores_docstrings_and_near_misses(tmp_path: Path):
    good = tmp_path / "good_workflow.py"
    good.write_text(_CLEAN_SOURCE, encoding="utf-8")
    assert find_truth_references(good) == []


# --- the rule itself -------------------------------------------------------------


def test_workflows_layout_exists():
    assert WORKFLOWS_DIR.is_dir()
    for sub in ("p0_scripted", "p1_single_agent", "p2_multi_agent"):
        assert (WORKFLOWS_DIR / sub / "__init__.py").is_file(), sub


def test_no_workflow_module_references_hidden_truth():
    modules = workflow_modules()
    assert modules, "workflows/ contains no Python modules to check"
    violations = [v for path in modules for v in find_truth_references(path)]
    assert not violations, "workflows/ must not touch hidden truth:\n" + "\n".join(
        str(v) for v in violations
    )
