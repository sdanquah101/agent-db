"""The controlled abstention vocabulary (ruling A3 of 2026-09-24).

One spelling for every quantity an answer key asks a workflow to decline and a workflow
declines: ``configs/abstentions.yaml``, loaded by :mod:`state.abstentions`, validated
against every scenario's ``abstain_on`` and handed to the workflow's sandbox. Changing an
answer key's spelling moves nothing a workflow can see: the regeneration test below
rewrites S2-02's key and checks the visible run tree and the run id are byte-identical.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scenarios.schema import CorrectConclusion, load_scenario
from state.abstentions import ABSTENTIONS_CONFIG, abstention_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "workflows" / "p0_scripted" / "pipeline.py"


def test_every_term_has_a_one_line_meaning():
    vocabulary = abstention_vocabulary()
    assert len(vocabulary) > 15
    for term, meaning in vocabulary.items():
        assert term.isidentifier(), term
        assert meaning and "\n" not in meaning, term


def test_templates_expand_over_the_declared_sensors_and_channels():
    vocabulary = abstention_vocabulary()
    assert "ch4_fraction_claims" in vocabulary
    assert "ph_claims" in vocabulary
    assert "alkalinity_total_budget" in vocabulary


def test_every_scenario_abstains_only_on_vocabulary_terms():
    vocabulary = abstention_vocabulary()
    seen = set()
    for path in sorted((REPO_ROOT / "scenarios").glob("S*.yaml")):
        scenario = load_scenario(path)
        for term in scenario.correct_conclusion.abstain_on:
            assert term in vocabulary, (path.name, term)
            seen.add(term)
    # the two terms the ruling respelled, in their new spelling
    assert {"ch4_fraction_claims", "alkalinity_total_budget"} <= seen


def test_the_schema_rejects_a_term_outside_the_vocabulary():
    # negative control: the validator refuses the pre-ruling spellings and a repeat ...
    for bad in (("ch4_fraction",), ("alkalinity_budget",), ("ch4_yield", "ch4_yield")):
        with pytest.raises(ValidationError):
            CorrectConclusion(kinetic_update_allowed=False, abstain_on=bad)
    # ... and accepts the vocabulary's own
    ok = CorrectConclusion(
        kinetic_update_allowed=False, abstain_on=("ch4_fraction_claims", "ch4_yield")
    )
    assert ok.abstain_on == ("ch4_fraction_claims", "ch4_yield")


def test_every_spelling_p0_emits_is_a_vocabulary_term():
    """P0's literal abstentions and its two templates are all in the vocabulary."""
    vocabulary = abstention_vocabulary()
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    literals: set[str] = set()
    templates: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend", "insert")
            and "abstentions" in ast.unparse(node.func.value)
        ) and not (isinstance(node, ast.AugAssign) and "abstentions" in ast.unparse(node.target)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                literals.add(sub.value)
            if isinstance(sub, ast.JoinedStr):
                templates.add(
                    "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in sub.values)
                )
    literals -= {v for t in templates for v in t.split("{}") if v}
    assert literals, "found no literal abstentions in the pipeline"
    assert literals <= set(vocabulary), literals - set(vocabulary)
    assert templates == {"{}_claims", "{}_budget"}
    # P0 fills {}_claims with a declared sensor and {}_budget with a fitted output
    # channel: every one of them must be a term, whichever the run flags
    from sim.observation import load_observation_config
    from tools.config import load_fitted_model

    sensors = set(load_observation_config().sensors)
    channels = set(load_fitted_model().outputs)
    assert sensors and channels
    assert {f"{s}_claims" for s in sensors} <= set(vocabulary)
    assert {f"{c}_budget" for c in channels} <= set(vocabulary)
    # and the templates range over nothing else
    assert {t[: -len("_claims")] for t in vocabulary if t.endswith("_claims")} <= sensors
    assert {t[: -len("_budget")] for t in vocabulary if t.endswith("_budget")} <= channels


def test_the_sandbox_carries_the_vocabulary():
    from tools.workflow_config import load_p0, sandbox_config

    assert sandbox_config(load_p0())["abstentions"] == abstention_vocabulary()


def test_the_vocabulary_lives_outside_the_truth_store_and_imports_no_simulator():
    assert ABSTENTIONS_CONFIG.parent == REPO_ROOT / "configs"
    source = (REPO_ROOT / "state" / "abstentions.py").read_text(encoding="utf-8")
    imported = {
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not any(m.split(".")[0] in {"sim", "scenarios", "eval"} for m in imported), imported


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _truth_contents(root: Path) -> dict[str, object]:
    """Every truth file by content, keyed by its name.

    npz members as arrays (the zip container stamps the time), JSON parsed with the
    manifest's creation time dropped, the generation log without its clock fields
    (``t_utc``, ``runtime_s``), anything else as bytes.
    """
    import numpy as np

    out: dict[str, object] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        name = str(p.relative_to(root))
        if p.suffix == ".npz":
            with np.load(p) as z:
                for key in sorted(z.files):
                    arr = np.ascontiguousarray(z[key])
                    out[f"{name}:{key}"] = (arr.dtype.str, arr.shape, arr.tobytes())
        elif p.suffix == ".json":
            doc = json.loads(p.read_text(encoding="utf-8"))
            if name == "manifest.json":
                doc.pop("created_utc")
            out[name] = doc
        elif p.suffix == ".jsonl":
            # the truth-side generation log stamps each call's time and runtime
            lines = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
            out[name] = [
                {k: v for k, v in line.items() if k not in ("t_utc", "runtime_s")} for line in lines
            ]
        else:
            out[name] = p.read_bytes()
    return out


def test_respelling_an_answer_key_moves_nothing_a_workflow_sees(tmp_path, monkeypatch):
    """Regenerating S2-02 under the old and then the new key, at a fixed commit.

    The run id, the visible tree and the truth are the same.
    Only ``truth_store/<id>/faults.json`` differs, and only in
    ``correct_conclusion.abstain_on``. ``manifest.json`` may differ only in
    ``created_utc``, and the truth-side ``calls.jsonl`` only in its clock fields.
    """
    from sim.run.harness import generate_run
    from tests.conftest import _short

    new = _short("S2-02", evals=40, wall_min=20.0, assays=2)
    assert new.correct_conclusion.abstain_on == ("ch4_fraction_claims", "ch4_yield")
    # the pre-ruling key, as it was generated into the store (model_copy skips validation)
    old = new.model_copy(
        update={
            "correct_conclusion": new.correct_conclusion.model_copy(
                update={"abstain_on": ("ch4_fraction", "ch4_yield")}
            )
        }
    )
    runs = tmp_path / "runs"
    # the manifest records the checkout's commit; pin it so a commit landing between the
    # two generations cannot pass for a difference the answer key made
    import sim.run.harness as harness

    monkeypatch.setattr(harness, "git_sha", lambda *a, **k: "pinned-for-this-test")

    first = generate_run(old, "B", runs_root=runs)
    visible_before = _tree_hashes(first.paths.root)
    truth_before = _truth_contents(first.paths.truth)
    faults_before = json.loads(first.paths.truth_faults.read_text(encoding="utf-8"))

    second = generate_run(new, "B", runs_root=runs)
    visible_after = _tree_hashes(second.paths.root)
    truth_after = _truth_contents(second.paths.truth)
    faults_after = json.loads(second.paths.truth_faults.read_text(encoding="utf-8"))

    assert second.run_id == first.run_id
    assert "observations" in " ".join(visible_before)
    assert visible_after == visible_before
    assert faults_before["correct_conclusion"]["abstain_on"] == ["ch4_fraction", "ch4_yield"]
    assert faults_after["correct_conclusion"]["abstain_on"] == ["ch4_fraction_claims", "ch4_yield"]
    faults_before["correct_conclusion"]["abstain_on"] = faults_after["correct_conclusion"][
        "abstain_on"
    ]
    assert faults_after == faults_before
    # every other truth file is the same, content for content
    assert set(truth_after) == set(truth_before)
    assert "manifest.json" in truth_before and any(k.endswith(".npz:y") for k in truth_before)
    for name in truth_before:
        if name != "faults.json":
            assert truth_after[name] == truth_before[name], name
