"""P2's live decider, privileged side (deliverable 3; ``docs/p2_design.md`` §9, §14).

Nothing here runs in the jail. The workflow asks a decision through ``tools.llm``; the
registry server hands the request to :class:`P2Gateway`, which:

- accepts only a request the frozen decision layer could have produced: the system
  prompt is one of the twelve frozen templates, the one tool is that decision's frozen
  tool, and the content is one user message (the declared inputs, as JSON);
- projects the request's cost **before** sending it (its input at the declared characters
  per token, plus the full ``max_tokens`` of output) and refuses it when the run would
  pass any cap: requests, tokens or USD. The workflow then abstains (``model_cap``);
- logs every attempt to ``llm_calls.jsonl`` through P1's gateway, with the point and
  role named by the template the request matched (never by the jail).

:func:`check_p2_frozen` is the template freeze: every template's text, every decision's
output schema and tool, and the model settings, against ``p2.yaml``'s ``frozen`` record.
The runner calls it before every P2 run, offline included, and refuses a run on any
difference.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.llm import (
    GatewayRefusal,
    ModelError,
    ModelGateway,
    OpenAIResponsesClient,
    check_agent_request,
    request_digest,
    system_digest,
    tools_digest,
)
from tools.workflow_config import DECISION_POINTS, P2Config, P2Frozen, load_p2_templates

__all__ = [
    "P2Gateway",
    "check_p2_frozen",
    "frozen_digests",
    "p2_live_client",
    "p2_provenance",
]


COMMITTED_P2 = Path(__file__).resolve().parents[1] / "configs" / "workflows" / "p2.yaml"
"""The committed configuration whose ``frozen`` record every P2 run is checked against."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frozen_digests(config: P2Config) -> dict[str, dict[str, str]]:
    """What the freeze records, recomputed from the files on disk and the workflow's code.

    ``templates`` (each template's text), ``schemas`` (each decision's output schema) and
    ``tools`` (the one tool each decision's request offers), by decision point.
    """
    from workflows.p2_multi_agent import workflow as wf

    templates = load_p2_templates(config)
    return {
        "templates": {p: templates[p]["sha256"] for p in DECISION_POINTS},
        "schemas": {p: wf.schema_sha256(wf.DECISIONS[p]["model"]) for p in DECISION_POINTS},
        "tools": {p: tools_digest([wf.decision_tool(p)]) for p in DECISION_POINTS},
    }


def check_p2_frozen(config: P2Config) -> P2Frozen:
    """Refuse a P2 run whose decision layer is not the frozen one.

    Returns:
        The freeze record, when everything matches.

    Checked, in order: the record exists and is the **committed** one (a configuration
    copied elsewhere, the pilot's for example, cannot carry its own edited record); every
    template, output schema and tool against it; the whole model block and the caps
    against it; and the model block against the frozen P1's (decision d), on the very
    configuration the run uses.

    Raises:
        ValueError: Naming the first difference.
    """
    from tools.workflow_config import load_p1, load_p2

    frozen = config.frozen
    if frozen is None:
        raise ValueError("p2.yaml has no frozen record: P2's decision layer is not frozen")
    committed = load_p2(COMMITTED_P2).frozen
    if frozen != committed:
        raise ValueError(
            "the configuration's frozen record is not the committed one "
            f"({COMMITTED_P2.name}): refused"
        )
    now = frozen_digests(config)
    for kind, recorded in (
        ("templates", frozen.templates_sha256),
        ("schemas", frozen.schemas_sha256),
        ("tools", frozen.tools_sha256),
    ):
        if set(recorded) != set(DECISION_POINTS):
            raise ValueError(f"the frozen {kind} must name exactly the twelve decision points")
        for point in DECISION_POINTS:
            if now[kind][point] != recorded[point]:
                raise ValueError(
                    f"the {kind[:-1]} of {point!r} is not the frozen one "
                    f"({now[kind][point][:12]}… vs {recorded[point][:12]}…): refused"
                )
    for name, have, want in (
        ("model", config.model, frozen.model),
        ("caps", config.caps, frozen.caps),
    ):
        if have != want:
            diff = sorted(
                k for k in have.model_dump() if have.model_dump()[k] != want.model_dump()[k]
            )
            raise ValueError(f"the {name} block is not the frozen one ({diff}): refused")
    if config.model != load_p1().model:
        raise ValueError("the model block is not the frozen P1's (decision d): refused")
    return frozen


def p2_provenance(config: P2Config, *, live: bool = True) -> dict[str, str]:
    """What every ``llm_calls.jsonl`` line and the summary carry; refuses an unfrozen run.

    An offline run names no model (the review's N-10b): none was reachable.
    """
    from tools.runner import git_commit

    check_p2_frozen(config)
    now = frozen_digests(config)
    out = {
        "templates_sha256": _sha(json.dumps(now["templates"], sort_keys=True)),
        "schemas_sha256": _sha(json.dumps(now["schemas"], sort_keys=True)),
        "tools_sha256": _sha(json.dumps(now["tools"], sort_keys=True)),
        "git_commit": git_commit(),
    }
    if live:
        out["model_id"] = config.model.model_id
    return out


def p2_live_client(config: P2Config) -> OpenAIResponsesClient:
    """The live client: OpenAI's Responses API at P1's frozen settings (decision d)."""
    if config.model.provider != "openai":
        raise ValueError("P2's live decider is the frozen P1's OpenAI model")
    return OpenAIResponsesClient(config.model)


@dataclass
class P2Gateway(ModelGateway):
    """P1's gateway, with P2's request check and caps projected before each request.

    ``max_turns`` and ``max_total_tokens`` are P2's ``caps``; ``max_usd`` and
    ``input_chars_per_token`` too. ``allowed`` maps a frozen template's system digest to
    its ``(point, role, tools digest)``.
    """

    max_usd: float = 0.0
    input_chars_per_token: float = 2.0
    allowed: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    base_provenance: dict[str, str] = field(default_factory=dict)
    by_role: dict[str, dict[str, int]] = field(default_factory=dict)
    attempts_sent: int = 0
    reserved_tokens: int = 0
    reserved_usd: float = 0.0
    lines_written: int = 0
    _lines: list[int] = field(default_factory=list, init=False, repr=False)
    _inner: Any = field(default=None, init=False, repr=False)

    @classmethod
    def for_config(cls, config: P2Config, client: Any, log_dir: Any) -> P2Gateway:
        """The gateway of one P2 run, built from the frozen record (refuses an unfrozen run)."""
        from workflows.p2_multi_agent import workflow as wf

        frozen = check_p2_frozen(config)
        templates = load_p2_templates(config)
        allowed = {
            system_digest(templates[p]["text"]): (
                p,
                str(wf.DECISIONS[p]["role"]),
                frozen.tools_sha256[p],
            )
            for p in DECISION_POINTS
        }
        provenance = p2_provenance(config)
        return cls(
            settings=config.model,
            client=client,
            log_dir=log_dir,
            max_turns=config.caps.max_requests,
            max_total_tokens=config.caps.max_total_tokens,
            provenance=dict(provenance),
            max_usd=float(config.caps.max_usd),
            input_chars_per_token=float(config.caps.input_chars_per_token),
            allowed=allowed,
            base_provenance=dict(provenance),
        )

    def decision_of(self, request: dict[str, Any]) -> tuple[str, str]:
        """The ``(point, role)`` a request is for, or a refusal.

        Raises:
            ModelError: The request is not one the frozen decision layer produces.
        """
        check_agent_request(request, None, None)
        entry = self.allowed.get(system_digest(request.get("system", "")))
        if entry is None:
            raise ModelError("the system prompt is not one of P2's frozen templates")
        point, role, tools_sha = entry
        if tools_digest(request.get("tools") or []) != tools_sha:
            raise ModelError(f"{point}: the tool is not the decision's frozen tool")
        messages = request.get("messages") or []
        if (
            len(messages) != 1
            or messages[0]["role"] != "user"
            or not isinstance(messages[0]["content"], str)
        ):
            raise ModelError(f"{point}: a decision request is one user message of text")
        return point, role

    def projected(self, request: dict[str, Any]) -> tuple[int, float | None]:
        """The request's worst-case tokens and USD, before it is sent."""
        text = json.dumps(request, sort_keys=True, default=str)
        tokens_in = math.ceil(len(text) / self.input_chars_per_token)
        tokens_out = int(self.settings.max_tokens)
        p = self.settings.pricing_usd_per_mtok
        usd = None if p is None else (tokens_in * p.input + tokens_out * p.output) / 1e6
        return tokens_in + tokens_out, usd

    # -- the caps, per attempt (the review of PR #33, B-1) -----------------------------
    def cost_usd(self) -> float | None:
        """The run's cost: what the meter booked, plus every failed attempt's worst case.

        A failed attempt (a retryable error, or a reply that arrived but could not be
        read) may have been billed and is never metered by P1's gateway, so it is booked
        here at its projected worst case. The pilot's stop reads this figure too.
        """
        base = super().cost_usd()
        return None if base is None else base + self.reserved_usd

    def check_attempt(self, point: str, tokens: int, usd: float | None) -> None:
        """Refuse the next attempt if it could take the run past any cap.

        Every attempt counts against ``max_turns``, a retry included; the token and USD
        checks include the worst case booked for every failed attempt.

        Raises:
            GatewayRefusal: Naming the cap.
        """
        if self.attempts_sent + 1 > self.max_turns:
            raise GatewayRefusal(f"{point}: the run's {self.max_turns} requests are spent")
        used = self.meter.total + self.reserved_tokens
        if used + tokens > self.max_total_tokens:
            raise GatewayRefusal(
                f"{point}: {used} + {tokens} tokens would pass the run's {self.max_total_tokens}"
            )
        spent = self.cost_usd()
        if usd is None or spent is None:
            raise GatewayRefusal(f"{point}: no declared price, so the USD cap cannot hold")
        if spent + usd > self.max_usd:
            raise GatewayRefusal(
                f"{point}: USD {spent:.4f} + {usd:.4f} would pass the run's {self.max_usd}"
            )

    def _log(self, *args: Any, **kwargs: Any) -> None:
        """P1's log line, numbered, so a decision record can cite it."""
        super()._log(*args, **kwargs)
        self._lines.append(self.lines_written)
        self.lines_written += 1

    def log_refusal(self, params: dict[str, Any], reason: str) -> None:
        """A refused attempt, auditable from the log: nothing was sent (N-2c)."""
        line = {
            "turn": self.meter.requests,
            "attempt": None,
            "client": getattr(self._inner, "name", ""),
            "request_sha256": request_digest(params),
            "provenance": dict(self.provenance),
            "refused": True,
            "response": None,
            "error": f"refused: cap: {reason}",
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True, default=str) + "\n")
        self._lines.append(self.lines_written)
        self.lines_written += 1

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """One decision request: checked, then every attempt checked against every cap.

        The reply's ``status`` names the log lines this request wrote (``llm_lines``);
        a refusal or a failure names them in its message, so the workflow's decision
        record cites every attempt.

        Raises:
            GatewayRefusal: An attempt would take the run past a cap; it was not sent.
            ModelError: The request is not a frozen decision's, or the call failed.
        """
        point, role = self.decision_of(request)
        tokens, usd = self.projected(request)
        self.provenance = {**self.base_provenance, "point": point, "role": role}
        self._lines = []
        self._inner = self.client
        # checked here first, so a refusal at the first attempt is logged too (P1's own
        # pre-check would refuse it silently)
        try:
            self.check_attempt(point, tokens, usd)
        except GatewayRefusal as exc:
            self.log_refusal(self.params(request), str(exc))
            raise GatewayRefusal(f"{exc} [llm_lines={_ids(self._lines)}]") from exc
        used = self.by_role.setdefault(role, {"tokens": 0, "requests": 0, "reserved_tokens": 0})
        before = self.meter.total
        self._inner = self.client
        self.client = _Guarded(self, self._inner, point, role, tokens, usd)
        try:
            out = super().complete(request)
        except GatewayRefusal as exc:
            raise GatewayRefusal(f"{exc} [llm_lines={_ids(self._lines)}]") from exc
        except ModelError as exc:
            raise ModelError(f"{exc} [llm_lines={_ids(self._lines)}]") from exc
        finally:
            self.client = self._inner
            used["tokens"] += self.meter.total - before  # metered; reserved apart
        out["status"] = {**out["status"], "llm_lines": list(self._lines)}
        return out


def _ids(lines: list[int]) -> str:
    return ",".join(str(i) for i in lines)


class _Guarded:
    """The client as P2's gateway hands it to P1's retry loop: each attempt checked first.

    Before every attempt, the first and each retry alike, the caps are checked
    (:meth:`P2Gateway.check_attempt`); a refusal is logged and raised, and nothing is
    sent. An attempt that fails, retryably or with a reply that arrived but could not be
    read, is booked at its projected worst case.
    """

    def __init__(
        self, gw: P2Gateway, inner: Any, point: str, role: str, tokens: int, usd: float | None
    ) -> None:
        self._gw, self._inner = gw, inner
        self._point, self._role, self._tokens, self._usd = point, role, tokens, usd

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        """One attempt, if every cap allows it."""
        gw = self._gw
        try:
            gw.check_attempt(self._point, self._tokens, self._usd)
        except GatewayRefusal as exc:
            gw.log_refusal(params, str(exc))
            raise
        gw.attempts_sent += 1
        gw.by_role[self._role]["requests"] += 1
        try:
            return self._inner.create(params)
        except ModelError:
            self._book()
            raise
        except Exception as exc:
            # any other failure of the client is a failed attempt too: booked, and raised
            # as a ModelError so P1's gateway logs it (N-new-1); tools/llm.py unchanged
            self._book()
            raise ModelError(f"client error: {type(exc).__name__}: {str(exc)[:200]}") from exc

    def _book(self) -> None:
        gw = self._gw
        gw.reserved_tokens += self._tokens
        gw.reserved_usd += float(self._usd or 0.0)
        gw.by_role[self._role]["reserved_tokens"] += self._tokens


# ------------------------------------------------------------------ the approval (B-3)

APPROVAL_FILE = COMMITTED_P2.parent / "p2_live_approval.yaml"
"""The lead's approval of live P2 runs. **Absent until the lead approves**; the coordinator
relays the word and the record is committed then, never before."""


APPROVAL_FIELDS = ("ruling_date", "word", "runs", "caps", "frozen_sha256", "config_sha256")
"""What an approval record names, all under its digest."""


def approval_digest(record: dict[str, Any]) -> str:
    """The digest a record carries of its ruling, run list, caps, freeze and configuration."""
    body = {k: record.get(k) for k in APPROVAL_FIELDS}
    return _sha(json.dumps(body, sort_keys=True, default=str))


def config_digest(config: P2Config) -> str:
    """The digest of the exact configuration a run uses (N-B3c).

    Every field of ``p2.yaml`` as loaded (the roles, the ablation, the coupled channels,
    the hold-out, the onset test, ...) and every field of the ``p0.yaml`` beside it, so an
    approval binds the configuration, not only its caps and freeze.
    """
    body = {
        "p2": config.model_dump(mode="json"),
        "p0": config.p0().model_dump(mode="json"),
    }
    return _sha(json.dumps(body, sort_keys=True, default=str))


def frozen_record_sha256() -> str:
    """The digest of the committed configuration's ``frozen`` record."""
    from tools.workflow_config import load_p2

    frozen = load_p2(COMMITTED_P2).frozen
    return _sha(json.dumps(None if frozen is None else frozen.model_dump(mode="json"),
                           sort_keys=True))  # fmt: skip


def _git_clean(path: Path, repo: Path | None = None) -> tuple[bool, str]:
    """Whether ``path`` is the committed, pushed record on a clean tree (B-3, N-B3a).

    - tracked, and the tracked tree has no change (``git status``);
    - its bytes on disk are the blob at ``HEAD`` (so ``--assume-unchanged`` cannot hide
      an edit from the status check);
    - the commit that introduced it is contained in a remote-tracking branch (a local
      commit the session made alone does not pass: the record must have been pushed,
      which is where the coordinator relays the lead's word).
    """
    import subprocess

    repo = COMMITTED_P2.parents[2] if repo is None else Path(repo)

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                              check=False)  # fmt: skip

    try:
        rel = str(Path(path).resolve().relative_to(Path(repo).resolve()))
    except ValueError:
        return False, f"{Path(path).name} is not in the repository"
    if git("ls-files", "--error-unmatch", rel).returncode != 0:
        return False, f"{Path(path).name} is not committed"
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return False, "the working tree has uncommitted changes"
    on_disk = git("hash-object", rel).stdout.strip()
    at_head = git("rev-parse", f"HEAD:{rel}").stdout.strip()
    if not on_disk or on_disk != at_head:
        return False, f"{Path(path).name} on disk is not the blob at HEAD"
    added = git("log", "--diff-filter=A", "--format=%H", "--", rel).stdout.split()
    if not added:
        return False, f"no commit introduces {Path(path).name}"
    if not git("branch", "-r", "--contains", added[-1]).stdout.strip():
        return False, f"the commit introducing {Path(path).name} is on no remote branch"
    return True, ""


def require_live_approval(config: P2Config, cell: dict[str, Any] | None = None) -> dict:
    """Refuse a live run without the lead's committed approval (the review of PR #33, B-3).

    The record must exist, be committed and pushed on a clean tree with its bytes those
    at ``HEAD`` (:func:`_git_clean`), carry a digest that matches its own content, name
    the caps the configuration has, the committed freeze and the digest of the exact
    configuration this run uses, and (with ``cell``: ``scenario``, ``plant``, ``tier``,
    ``replicate``) list this run.

    Returns:
        The record.

    Raises:
        ValueError: Naming the first reason it is refused.
    """
    import yaml

    if not APPROVAL_FILE.is_file():
        raise ValueError(
            f"no approval record ({APPROVAL_FILE.name}): no live P2 run before the lead's word"
        )
    clean, why = _git_clean(APPROVAL_FILE)
    if not clean:
        raise ValueError(f"live P2 refused: {why}")
    record = yaml.safe_load(APPROVAL_FILE.read_text(encoding="utf-8")) or {}
    if record.get("digest") != approval_digest(record):
        raise ValueError("the approval record's digest does not match its content")
    if record.get("caps") != config.caps.model_dump(mode="json"):
        raise ValueError("the approval names other caps than the configuration's")
    if record.get("frozen_sha256") != frozen_record_sha256():
        raise ValueError("the approval names another freeze than the committed one")
    if record.get("config_sha256") != config_digest(config):
        raise ValueError("the approval names another configuration than the one this run uses")
    if cell is not None:
        runs = [dict(r) for r in record.get("runs") or []]
        if dict(cell) not in runs:
            raise ValueError(f"the approval does not list this run {cell}")
    return record


def cell_of(truth_manifest: Path) -> dict[str, Any]:
    """The run's public cell tuple, read on the privileged side from its truth manifest."""
    m = json.loads(truth_manifest.read_text(encoding="utf-8"))
    return {
        "scenario": str(m["scenario_id"]),
        "plant": str(m["plant"]),
        "tier": str(m["tier"]),
        "replicate": int((m.get("seeds") or {}).get("replicate", 0)),
    }
