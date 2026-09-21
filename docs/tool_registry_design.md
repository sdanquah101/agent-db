# Tool registry v1.0 — design (milestone 4, proposal §6.2)

Status: **proposed 2026-09-21** by the tool-registry session. The lead delegated the
part-B decision to the coordinator (2026-09-21): the coordinator accepts it on the lead's
behalf if it (i) meets the recorded requirement (decisions 2026-09-12), (ii) carries the
demonstrating test with a negative control, (iii) touches nothing under `sim/`,
`scenarios/` or the frozen configs. Parts A, C and D are what CLAUDE.md rules 2–6 already
require and are built regardless. All four parts are built and tested on
`claude/tool-registry` as described here; part B is built *as proposed* and changes if the
coordinator's acceptance asks for it.

## 1. What the registry is

One object, `tools.Registry`, through which a workflow calls every tool. A call is

```
tools.call(name, **args) -> Output          # or, over the wire, tools.client.call(...)
```

and does, in this order:

1. **Validate** `args` against the tool's Pydantic input model; every numeric field states
   its unit in its description (rule 6). A validation failure is logged as `error` and
   raised as `ToolArgumentError`.
2. **Check the budget** (rule 2): every tool declares `cost(args)`, an upper bound on the
   simulator evaluations it will make. If `remaining.simulator_evals < cost`, or the
   wall-clock allowance is spent, or a requested assay costs more units than remain, the
   call is refused with outcome `budget_exceeded` and **nothing runs**. During the call a
   meter counts the evaluations actually made; a tool that would overrun mid-way is
   stopped at the limit (the meter raises inside the model call), the partial result is
   discarded, and the outcome is `budget_exceeded`.
3. **Apply the Level-8 directive**: if the run's `WorkflowFaults.tool_failure` names this
   tool, a keyed stream decides (with the row's probability, 1.0 in S8-01) whether the call
   returns the tool's **realistic failure payload** with outcome `injected_failure`. For
   `bayes_mcmc` that is a set of chains that has not converged: R-hat > 1.1 on every
   parameter, ESS below the floor, `converged=False`, quantiles present but marked
   unreliable. It is a normal return value, not an exception. The directive is held in
   memory; nothing under `runs/<id>/` mentions it.
4. **Run** the tool as a pure function of its validated input, the resolved model and an
   explicit seed.
5. **Log** exactly one `CallRecord` to `runs/<id>/calls.jsonl` through
   `state.provenance.CallLog(projection=True)` (rule 3), continuing the harness's
   sequence. The projection carries name, version, args hash, outcome and detail — no
   timestamp and no runtime, as the harness's visible records do. The registry also keeps
   a **truth-side** log at `truth_store/<id>/calls.jsonl` with timestamps and runtimes,
   which is the one rule 3's evaluator reads.
6. **Return** the Pydantic output; `tools.remaining()` reports the budget left for the
   task state (§6.6).

Every numerical setting a tool has (trajectories, samples, multistarts, tolerances, chain
lengths, thresholds) lives in `configs/tools/<tool>.yaml` and is loaded through a Pydantic
schema. A workflow may pass a *smaller* number than the config's ceiling (that is how a
budget is spent wisely) but never a larger one.

### The evaluation-counting rule

**One call of a registered model on one parameter vector is one simulator evaluation**,
whatever the model. The fitted ADM1's evaluation includes its own burn-in. A Morris screen
of `r` trajectories over `k` parameters costs `r (k + 1)`; a Saltelli/Jansen Sobol design
of base size `N` costs `N (2k + 2)` with second-order indices; a profile of `m` points with
`s` starts costs at most `m · s · maxfev`; a fit costs at most `starts · maxfev`. The cost
is charged as the evaluations actually made, never more than the declared bound.

### Models

A tool that needs a simulator takes `model: str`, resolved by the registry to a
`tools.models.Model`: a callable `theta -> {output: array on the model's time grid}`
with declared parameter names, defaults, bounds and output units. The run's registry
registers `adm1_fitted` (§4). Tests register analytic models (Ishigami, a linear-Gaussian
model with a non-identifiable direction, a linear state-space system) **only through the
privileged side**; a workflow cannot register a model.

## 2. The fitted model (`adm1_fitted`)

`sim.adm1` base ADM1 plus the extensions the plant contract declares **as fitted for this
run**: the plant's `truth_model.extensions` less the ones a Level-6 row removes
(`truth_store/<id>/parameters.json: fitted_extensions`, written by the harness). The
registry reads that field on its privileged side and applies it silently.

- **Influent**: the operator's feed log (`observations/feed_log.csv`) mapped through the
  declared catalogue (`configs/influent/feed_fractionation.yaml`) at catalogue solids, day by
  day, sample-and-hold; the declared blend tank of Plant B applied to its declared feeds;
  dissolved calcium as the catalogue's flow-weighted mean. Nothing hidden enters.
- **Geometry**: the declared volume and set point (`sim.plants.declared_geometry`).
- **Initial state**: a burn-in on the feed log's first-window mean recipe at the
  parameters being evaluated (the harness's own staging, on declared quantities), unless
  the caller passes `initial_state` or a `biomass_scale` (the Level-4 unknown).
- **Calibratable parameters**: the base ADM1 kinetic and stoichiometric parameters, by
  name, as multipliers of the BSM2 defaults, within bounds from
  `configs/tools/model.yaml`. Extension parameters are **not** calibratable, and the
  parameter list is the same on every run, so a workflow cannot read the rung off the
  model's interface — the only difference between a Level-6 fitted model and a Level-0
  one is what it predicts, which is the diagnostic task. **Flagged for the lead** (§6):
  `fitted_extensions` in the truth store is the right place, and the registry never
  reports the set, but the model's *behaviour* is necessarily different.
- **Outputs**: the observation channels of `sim.observation.channel_series` on the daily
  grid, in the channel units, so a residual is observed-minus-predicted in one unit.

## 3. Requested assays (§6.4)

`request_assay(assay, day)` spends `assay_units`. The price list and turnaround are
`configs/tools/assays.yaml`. The registry's privileged side reads
`truth_store/<id>/channels.npz` at the sample day, applies the **same noise model** the
observation layer applies to the corresponding lab sensor (`configs/observation/sensors.yaml`:
`cv`, `sd_abs`, drawn from `SeedSequence([assay seed, assay key, day])` so a repeated
request on the same day returns the same value and does not average noise away), and
returns the value with `report_day = day + turnaround`. A request for a day beyond the
record, or an assay with no channel in this run, is an `error`.

## 4. Part B — the process boundary (the question for the lead)

**Requirement** (decisions 2026-09-12, rounds two and three): a workflow process must not
have `sim`, `scenarios/` or `truth_store/` importable or readable. The tools must import
`sim` (the fitted model is `sim.adm1`), so the boundary is between the workflow process and
the registry.

**Proposed design: a registry server and a sandboxed workflow subprocess.**

```
 privileged process (the workflow harness, later P0 driver)          sandbox process
 ┌──────────────────────────────────────────────────┐   unix socket   ┌──────────────────────┐
 │ tools.Registry: sim + budgets + logs + truth-side │ <────────────> │ import tools (client) │
 │   channel for assays; RunView of runs/<id>/       │  JSON frames,  │ tools.call(...)       │
 │ tools.server.serve(registry, socket_path)         │  arrays base64 │ tools.run.sensors()   │
 │ tools.sandbox.launch(script, registry)            │                │ python -I -S, sys.path │
 └──────────────────────────────────────────────────┘                │  = [stub, site-pkgs]   │
                                                                     └──────────────────────┘
```

- The **server** is a thread in the privileged process listening on a Unix-domain socket,
  handling one request at a time (the registry is sequential by design: budgets are a
  serial resource). The protocol is newline-delimited JSON frames; numpy arrays travel as
  `{"__ndarray__": {dtype, shape, base64}}`.
- The **client stub** is a small package copied into a staging directory as `tools/`
  (so `import tools` in a workflow is the allow-listed spelling). It contains only the
  I/O schemas (`tools.schemas`, Pydantic + numpy, no `sim`), the frame encoder and the
  proxy `call`, `remaining`, `describe` and `run` (the run view served over the wire:
  `sensors()`, `feed_log()`, `feed_assays()`, `operator_notes()`, `manifest()`).
- The **sandbox** runs the workflow in a **user + mount + pid namespace with a private
  root** (`tools.sandbox.launch`: `unshare --user --map-root-user --mount --pid --fork
  --kill-child`, then a shell script that mounts a tmpfs root, bind-mounts into it only
  what the sandbox interpreter needs, and `pivot_root`s into it, unmounting the old root).
  Inside the root: `/usr/lib` read-only (the C library and, on Debian, the standard
  library) and the interpreter's own library directory where it lies elsewhere, with
  every `site-packages` and `dist-packages` inside them hidden under an empty tmpfs; the
  interpreter **binary alone** at `/usr/bin/python-jail` plus the symlinks the venv's
  `bin/python` chain needs; the **sandbox environment** at `/venv` — a virtual
  environment holding numpy, scipy and pydantic pinned to the host's versions and *not*
  the project install (`tools.sandbox.sandbox_interpreter`, built once per host
  interpreter and package set, cached under `AD_AGENTBENCH_SANDBOX_HOME`, re-checked in
  a scrubbed environment on every use); the sandbox directory at `/box` (the stub, the
  workflow, its cwd, the socket); `/dev/{null,zero,random,urandom}`; `/etc/ld.so.cache`;
  a fresh `/proc` of the pid namespace. Nothing else: no `/home`, no host `/tmp`, no
  repository, no run store, no `/usr/bin/python3`. The workflow runs on `/venv/bin/python
  -I -S` with `PATH=/venv/bin`, `sys.path` set by a bootstrap to the stub, the standard
  library and the venv's package directory. The bootstrap **fails closed** before the
  script runs: if a forbidden module resolves in its own process, or in a plain child of
  the sandbox interpreter, or in a plain child of any other interpreter name it can find
  (`/usr/bin/python3`, `/usr/local/bin/python3`, `shutil.which("python3")`), it exits
  without running the workflow. `launch` raises `SandboxError` — never runs unjailed — if
  `unshare` is missing or the jail cannot be built, and refuses a sandbox directory under
  the repository root, the run store or the run store's parent.
- The **test** launches a workflow-side script that attempts `import sim` by every
  spelling, `open("truth_store/…")`, `open("scenarios/…")` and the repository-relative
  equivalents, a plain child interpreter, the host interpreters by name, `/proc/<ppid>`
  of the privileged process, and the repository root, the run store and its parent by
  their absolute paths, and asserts each fails; a **negative control** in the same
  process calls a tool, reads the run's sensors and gets a budget refusal as the right
  exception.

**What it costs.**

- *Serialisation.* Every array crosses the socket twice (base64 JSON: ~1.33× the bytes).
  A 200-day daily record is kilobytes; a Sobol design never crosses (it is generated
  server-side); the largest payload is a fitter's trajectory output (~30 series × 200
  points ≈ 50 kB). Measured cost per call: well under a millisecond of encoding against
  seconds of ADM1 integration. The registry stays sequential, so nothing is lost to
  contention.
- *One extra process per run*, plus one thread, plus the namespace and mount setup
  (~50 ms) and two probe interpreter starts. Startup ~0.5 s. The sandbox venv is built
  once per environment (~8 s from a warm pip cache).
- *Two copies of the schemas*: the stub's copy is made from `tools/schemas` at launch, so
  it cannot drift, and a test asserts the staged package equals the source.
- *What it does not buy, and the routes it had to close.* Two findings on the way here,
  both reproduced. **The child-interpreter route** (the coordinator's acceptance finding,
  2026-09-21): on the host interpreter, a plain child the workflow spawned ran `site`, the
  editable install's `.pth` hook installed its finder, and the child resolved `sim` at the
  repository root and derived `<root>/truth_store/index.jsonl` from `sim.__file__`. A
  dedicated venv closed `sys.executable` only. **The host-interpreter route** (the
  fresh-context review's finding B1, 2026-09-21): `subprocess.run(["/usr/bin/python3",
  …])` or `shutil.which("python3")` reached the host interpreter and its hook anyway, and
  `/proc/<ppid>/cwd` and `/proc/<ppid>/environ` gave the privileged process's working
  directory and environment — paths *discovered*, not told. Both are closed by the jail
  above, structurally rather than by enumeration: no host interpreter, no hook, no
  repository, no run store and no parent process exist inside it, so the "told an
  absolute path" limit closes too. What the jail is not: a boundary against a kernel
  exploit, or a limit on CPU, memory or wall clock beyond the registry's budget. It needs
  `unshare(1)` and unprivileged user namespaces (or root); CI enables them on the Ubuntu
  24.04 runner with one `sysctl` (`.github/workflows/ci.yml`).

**Alternatives considered.**

- *A `sys.meta_path` import blocker in the workflow process.* Removable by the code it
  guards (`sys.meta_path.remove`); it is the runtime form of the static checker whose
  limit was recorded. Rejected as the defence, kept as nothing.
- *A separate virtual environment per run.* Same guarantee as `-S` with a manual
  `sys.path`, much more setup; rejected.
- *A container.* Strictly stronger (stops filesystem reads too); costs a runtime the
  benchmark's reproducibility (§7, Docker image) already assumes at release. Proposed as
  the release-time hardening on top of this design, not instead of it.
- *In-process registry with the workflow importing `tools` directly.* Cheapest; gives the
  workflow `sim` by transitive import. Rejected: it is exactly what the requirement forbids.

**Decided by the coordinator on the lead's delegation (2026-09-21): ACCEPTED** at ~02:05
UTC with the child-interpreter hardening as a required condition; the fresh-context review
at `b9ca487` (~02:50 UTC) returned DO NOT MERGE on the host-interpreter route and required
the namespace jail above, built in the one fix round. A container stays a release-time
option; the jail is the boundary now.

## 5. Layout

```
tools/
  __init__.py       Registry, open_registry, call, ToolError, ...
  schemas/          Pydantic I/O of every tool (shared with the client stub; no sim import)
  registry.py       dispatch, budgets, logging, the Level-8 directive
  models.py         the Model protocol; the analytic test models
  fitted.py         adm1_fitted (imports sim)
  assays.py         request_assay (privileged side)
  impl/             one module per tool: pure functions of (input, model, seed)
  transport.py      frames and array encoding (shared)
  server.py         the socket server
  sandbox.py        the workflow launcher and its bootstrap
  client/           the stub package staged as `tools` in the sandbox
configs/tools/      one YAML per tool; assays.yaml; model.yaml; budget.yaml
```

## 6. Decided under delegation (the coordinator, 2026-09-21; the lead may overrule at the gate)

1. Part B (§4): the socket server and the jailed subprocess — **accepted**, with the
   child-interpreter hardening and then, after review finding B1, the namespace jail
   required and built; a container stays a release-time option.
2. The fitted model's visible contract — **accepted**: the same parameter list and output
   list on every run, extension parameters fixed and not calibratable. It is what §6.7 A
   implies (structural rows are never scored on parameter recovery) and it stops the
   interface leaking the rung. Recorded in the benchmark card §4.1.
3. `WorkflowFaults.tool_failure` as `(tool, probability)` — **accepted**; the launch note's
   `(tool, onset)` was wrong, the frozen fault plan is right. A per-call Bernoulli from a
   keyed stream (S8-01 is 1.0, so every call fails).
4. Wall clock as time **since the registry was opened** — **accepted**, with the
   requirement that the clock start is written to the truth-side log: the registry's
   first record, `registry.open`, carries the budget as its arguments and the opening
   timestamp in the truth-side copy, so the evaluator can reconstruct the allowance.
