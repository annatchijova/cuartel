[English overview](README.md) · [Resumen en español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md) · [Roadmap](ROADMAP.md) · [Hoja de ruta en español](ROADMAP_ES.md)

# CUARTEL — technical reference

This document is the audit and extension surface for CUARTEL: the schema it
reads, what each renderer emits, and the reasoning behind every status in the
fleet table. The [README](README.md) is the pitch; this is the thing you read
before touching `registry.yaml`.

## Architecture decision

CUARTEL is a **registry**, not a server. `registry.yaml` is pure metadata —
no forensic logic, no decision authority — describing how to launch each
project's own, independently-owned MCP server, and what capability plane and
authority boundary that server operates under. `render.py` is a dumb
templater over that metadata.

Every entry is a separate MCP capability plane. Entries are never merged
into a single combined server. ZAYNOR's own
[`docs/adr/0001-separate-mcp-capability-planes.md`](https://github.com/annatchijova/zaynor/blob/main/docs/adr/0001-separate-mcp-capability-planes.md)
rejected fusing VIGÍA + CRONOS + MNEME into one server, because that
collapses distinct trust levels — read-only evidence access is not the same
thing as case memory, and neither is the same thing as a gated offensive
action. CUARTEL generalizes that same call across the whole fleet instead of
re-deciding it per project.

If a target runtime someday cannot load more than one MCP server, the
documented fallback is a typed multiplexer that preserves these same
capability-plane boundaries — not a flat proxy. That multiplexer does not
exist yet, and building it is not implied by anything here.

### Invariants, from the first entry on

1. The registry is metadata only — no renderer executes forensic logic or
   makes a decision about any project's output.
2. Every entry declares its capability plane and authority note explicitly
   — never inferred from the command alone.
3. Nothing is ever flattened into one combined server (see above).
4. A blocked or not-ready project is registered as such — never wired in
   silently because its server happens to exist and work.

## `registry.yaml` schema

```yaml
servers:
  <name>:
    display_name: string
    repo: absolute path to the project
    command: absolute path to the executable, or null if status != ready
    args: list of CLI arguments
    cwd: working directory to launch in
    env: {ENV_VAR: value}             # only what this entry needs to set
    plane: short capability-plane label (e.g. read-only-evidence-and-analysis)
    authority: >-
      one or two sentences on what this server can and cannot decide
    status: ready | blocked | planned
    tool_count: integer, from an actual handshake, never guessed
    notes: >-
      what was verified, when, how, and any caveat worth knowing before
      trusting this entry
```

`status: ready` is the only status a renderer ever emits into a runtime
config. `blocked` (exists, has a known open issue) and `planned` (does not
exist yet, or exists but is deliberately not enabled) both show up in
`doctor` output, so the gap is visible rather than silent.

## Renderers

`render.py <target>` reads the registry and emits exactly one of:

| Target | Format | Shape |
|---|---|---|
| `claude` | Claude Code's `.mcp.json` | `{"mcpServers": {name: {command, args, env?, cwd?}}}` |
| `codex` | Codex CLI's `config.toml` | `[mcp_servers.<name>]` blocks with `command`, `args`, `cwd`, `env.*`, `enabled` |
| `opencode` | OpenCode's `opencode.json` | `{"mcp": {name: {type: "local", command: [...], environment?, enabled}}}` |
| `doctor` | — | one line per entry: `OK`/`MISSING` for `ready`, or the status + first 100 chars of `notes` for anything else |
| `doctor --deep` | — | a real stdio handshake per `ready` entry (deliberately without `cwd`, matching the global scope's actual behavior): `OK` (count matches), `DRIFT` (handshake succeeded, tool count changed from the registry), or `FAIL` with a diagnosis from a small library of this project's own past failure signatures when one matches (ROADMAP.md Level 1) |
| `digest` | — | the same deep check, compared against `.doctor_state.json` (gitignored) from the last run — prints only transitions (new fail, resolved fail, tool-count change) or "no changes," the shape a scheduled run should actually print (ROADMAP.md Level 4; the schedule itself is not decided by this repo) |
| `scan` | — | drafts `registry.yaml` changes for drift it finds — a new MCP server file in a known repo not referenced by any entry, or SIBERIAN's own README losing its "NOT READY" banner — and prints them for review. Never writes `registry.yaml` (ROADMAP.md Level 5) |

`daily_digest_hook.sh` wires `digest` into a Claude Code SessionStart
hook (registered in `~/.claude/settings.json`), throttled to once per
calendar day via a gitignored marker file (`.digest_last_run`) — see
ROADMAP.md Level 4 for why a session hook was chosen over cron/systemd/a
cloud agent.

All three formats were confirmed against each tool's own current
documentation at the time this was built (October 2026), not assumed from
memory. `--out <path>` writes to a file instead of stdout.

## Verification methodology used for every `ready` entry

Every server in this registry was brought to `status: ready` the same way,
regardless of who built it or when:

1. A real stdio MCP handshake (`ClientSession.initialize()` +
   `list_tools()`) against the actual launch command — never assumed from
   reading the server's source.
2. At least one real tool call with real or realistic input, checked
   against either the project's own test fixtures (when available) or a
   hand-built equivalent, and the response inspected for correctness — not
   just "it didn't crash."
3. A deliberate check of the error path: an invalid argument or an
   unreachable dependency should degrade to a structured error, not a
   stack trace reaching the MCP client.

`tool_count` in the registry is always the number `list_tools()` actually
returned during that handshake.

## Fleet, in detail

### CUARTEL itself — ready
`mcp_server.py`, 4 tools: `cuartel_list_servers`, `cuartel_describe_server`
(both fast, registry.yaml-only), `cuartel_run_doctor` (shallow or
`deep=True`, reusing `render.py`'s own `doctor_deep_data()` — one
implementation, not two that can drift apart), `cuartel_find_capability`
(a real parallel handshake to every `ready` server, searching live tool
names/descriptions — never a second, stale copy of them). ROADMAP.md
Level 2. Two real bugs surfaced only by calling the deep tools
end-to-end: both originally called `asyncio.run()` from inside FastMCP's
already-running event loop and crashed on the first real call; fixed by
making them `async def` tools that `await` directly. CUARTEL registers
itself here deliberately — the fleet it manages includes itself.

All 4 tools also log their own call as a CRONOS trace (ROADMAP.md
Level 3: `agent_id="cuartel"`, `post_to_slack=False`) — best-effort,
never blocking the real result on it. CUARTEL does not mediate fleet
tool *invocations* (only `list_tools()`), so what's logged is CUARTEL's
own usage, not the whole fleet's — `cronos_list_traces(agent_id=
"cuartel")` is CUARTEL's queryable call history. Verified: all 4 tools
called once each, confirmed in CRONOS with `chain_ok: 1`; degradation
verified directly by pointing CRONOS's command at a nonexistent path and
confirming the real tool result was unaffected.

### VIGÍA — ready
`vigia/vigia_sift_bridge.py`, FastMCP, 33 tools, stdio-only by construction
(`_verify_transport_security()` hard-aborts on any other transport). Launched
via `launch_vigia_mcp.sh`, which already exports every env var this server
needs — CUARTEL does not re-declare them, to avoid a second source of truth
for evidence/work-directory confinement.

### CRONOS — ready (fixed a real failure)
`mcp_server.py`, 10 tools. This session's own CRONOS MCP connection had
actually failed (`CONNECTION_CLOSED`) before this registry existed. Root
cause, found by reproducing it directly rather than guessing: the server
hard-requires anyio's `trio` backend
(`anyio.run(mcp.run_stdio_async, backend="trio")`), and `trio` — declared in
`pyproject.toml` — was never installed for the bare `python3` the old config
pointed at. No venv existed, and `pip install --user` is blocked here by PEP
668. Fixed by creating `cronos/.venv` and running `pip install -e .` there,
then repointing both this registry and `~/.claude.json`'s own
`mcpServers.cronos` entry at `.venv/bin/python3`.

### MNEME — ready (curated)
MNEME's own `mcp_server.py` exposes 26 tools, most of them mutating (store,
supersede, grant, quarantine, propagate taint...). That full server is right
for an agent that uses MNEME as its memory layer; it is wrong for a
read-only fleet registry. `mcp_server_readonly.py` (built for this registry,
living in MNEME's own repo) exposes exactly the three tools ZAYNOR had
already vetted and allowlisted for this purpose
(`zaynor/docs/adr/0001-separate-mcp-capability-planes.md`): `mneme_info`,
`mneme_verify_bundle`, `mneme_custody_chain`. Implementations are copied
verbatim from the main server, not reimplemented. It uses `mcp.run()`
(asyncio default) instead of the main server's forced `trio` backend, since
`trio` is not installed there and none of these three tools needs it.

### mneme_memory_mcp — planned (superseded)
A separate GitHub repository (`annatchijova/mneme_memory_mcp`), an earlier
and smaller snapshot of the same lineage as MNEME — 9 tools against MNEME's
26, missing the `authority`/`causality`/`claims`/`counterfactual` modules.
MNEME is a functional superset. Not built or registered separately: it would
be a second, staler source of truth for the same thing.

### raven-memory — ready (curated)
raven-memory's own `mcp_server.py` exposes 12 tools. Five are obvious writes
(`store`, `reinforce`, `forget`, `create_link`, `consolidate`). A sixth,
`raven_recall`, looks read-only but is not: `memory_engine.py`'s `recall()`
calls `self._db.store_audit(...)` and `self._db.update_activations(...)` on
every call, and — only when `RAVEN_STYLO_ENFORCE=1` — can flip a memory's
state to `FORGOTTEN`. None of those six are in the curated bridge.
`mcp_server_readonly.py` keeps exactly: `raven_stats`, `raven_get_memory`,
`raven_audit_trail`, `raven_export_graph`, `raven_verify_chain`,
`raven_info`. Since none of those six embeds text, the curated file skips
constructing the Qwen/sentence-transformers embedding provider entirely —
one fewer heavy dependency path for a bridge that never needs it.

MNEME's own README documents fusing STIGMERGY's and raven-memory's field
mechanics, so there is real conceptual overlap between MNEME and
raven-memory. Both are registered anyway, as two independent memory systems
with their own engines and audit chains — not as a duplicate view of the
same data.

### ZAYNOR — ready
`zaynor-mcp` console script, 6 tools: `zaynor_info`,
`zaynor_verify_audit`, `zaynor_verify_memory`, `zaynor_list_memory`,
`zaynor_add_hypothesis`, `zaynor_note_question`. None creates, modifies, or
recalculates `result.json` or `result.seal.json` (ADR-0001). ZAYNOR is
itself an MCP client of VIGÍA/CRONOS/MNEME — that wiring is internal to
ZAYNOR and is not duplicated here; CUARTEL only registers ZAYNOR's own
server.

### VELO — ready (unblocked a stale finding)
`dist/src/mcp/server.js`, 13 tools. A Spanish red-team report
(`velo/docs/informe-red-team-VELO.md`) had flagged a critical path-traversal
(F1) in `caseId` handling as unresolved. Checked against the live code
first, per audit-before-patch discipline: the fix was already there —
regex validation at the schema boundary (`server.ts`) plus
`resolve()`/prefix-containment in the store (`store.ts`), both commented
"Red team F1" — landed in commit `ef0caa4` ("Red team round 1"). That Spanish
report predates six further English red-team rounds
(`docs/RED_TEAM_ROUND_1..6.md`). Verified live by running VELO's own
`tests/caseid.test.ts` — 4/4 pass, including "the store refuses to read or
write outside its directory." The remaining open items in round 6 (F20-F25)
are Medium/Low severity and do not touch `caseId`/MCP path handling — out of
scope for this registration.

### annaconda — ready (built from scratch)
Had zero MCP surface before this registry existed. `service/mcp_server.py`
is a thin stdio wrapper (stdlib `urllib` only — no new runtime dependency
besides `mcp` itself) over a curated GET-only subset of `service/app.py`'s
existing HTTP routes: `health`, `registry`, `catalog`, `hunts`,
`list_cases`, `get_case`, `get_case_stix`, `get_case_cacao`. Excludes by
construction every route that creates a case, starts a live investigation,
or pushes to an external system (`POST /cases`, `/investigate`,
`/cases/{id}/investigate`, `/fleet-investigate`,
`/cases/{id}/push-to-secops`, `/injection-demo`, `/tasks/sweep`). It proxies
the live annaconda service over HTTP rather than reimplementing its logic,
because annaconda's live state (sweep counters, Firestore-vs-memory backend
choice) genuinely lives in that running process — a second process
importing `build_case_store()` independently would silently diverge from it
under the memory-backend fallback. **Requires the annaconda service to
already be running** (`uvicorn service.app:app --port 8080`).

### PANCITO-RED-TEAM — ready (gated by construction)
Had zero MCP surface before this registry existed. `offensive/mcp_server.py`
exposes exactly two tools: `pancito_openapi_triage` and
`pancito_purple_evaluate`, wrapping `offensive.openapi_cli` and
`offensive.purple_cli` as subprocesses — the only two of roughly twenty
`offensive.*_cli` commands that are passive, local-file analysis with no
network action. Every other CLI (`bola_cli`, `cors_misconfiguration_cli`,
`ssrf_outbound_fetch_cli`, ...) actively executes real network actions
against a manifest-declared loopback target. Growing this tool list requires
a separately reviewed authorization/loopback-enforcement design at the MCP
layer — not an edit to this file. Verified with a real end-to-end call
against hand-built fixtures matching
`pancito-red-team/tests/test_openapi_cli.py`'s own expected values
byte-for-byte.

### SIBERIAN — planned on purpose, not for lack of work
`siberian/mcp_server.py` exists and is verified: 6 read-only subcommands
(`validate`, `analyze`, `explain`, `seal`, `verify`, `rivals`), none of
which writes, mutates, or creates a file. Deliberately excludes
`import-plaso` and the Level 6 adapters (`import-mft`/`prefetch`/`amcache`/
`shimcache`/`shellbags`, `batch`) — those write output files and/or need
optional extras not installed here, and SIBERIAN's own Build Levels table
still marks Level 6 "Partial." The server working is not the gate: SIBERIAN's
own README still says "UNDER CONSTRUCTION — NOT READY FOR OPERATIONAL USE."
Flip this to `ready` when SIBERIAN itself says so, not when its bridge does.

### FORGE — ready (consolidated two diverged directories first)
`forge/mcp_server.py`, 22 tools. There were two local directories of the
same project: `/home/labestiadevigia/forge` (remote `forge.git`) and
`/home/labestiadevigia/forge-nuevo` (remote `forge-improved.git`),
diverged since commit `6bee0de`. Anna's own belief that forge-nuevo "has
more languages" turned out correct, but not yet pulled locally:
`forge-improved.git`'s `origin/main` had 11 unpulled commits adding real
C/C++, Java, C#, Ruby, and PHP support via an already-merged PR, sitting
on top of 6 local commits of determinism/honesty fixes and a SARIF 2.1.0
exporter — none of which the older `forge` directory has. `forge` only
received 2 doc-only commits after the fork point.

Consolidation performed: merged `feat/sarif-output` into forge-nuevo's
`main` (fast-forward), cherry-picked forge's doc-cleanup commit
(`3a4f361`) onto it, fetched and merged `origin/main`'s 11-commit
language-pack lineage — one real conflict in `forge/detector/stack.py`
(two independent, non-overlapping limitations-list additions, both kept)
— and ran the full suite (482 passed, 5 skipped) before pushing.
forge-nuevo's `main` is now the verified canonical state. The original
`forge` directory and its `forge.git` remote were **not** deleted —
left as-is, pending Anna's own decision on what to do with that remote
and the local directory name.

Registered as-is (all 22 tools), matching what was already configured in
Anna's own `~/.claude.json` before this registry existed — a `PYTHONPATH`
pointing at `forge-nuevo` under the server name `"forge"`. Not re-curated
here, same posture as CORVUS below.

### CORVUS — ready
`mcp_server.py`, 7 tools: `analyze_message`, `get_user_baseline`,
`get_user_history`, `get_channel_stats`, `verify_audit_chain`,
`export_audit_chain`, `corvus_info`. Six are pure reads; `analyze_message`
defaults to `persist=False` and only writes to memory/baseline/audit chain
if the caller explicitly passes `persist=True` — an opt-in write, not a
hidden side effect like raven-memory's `raven_recall`, so it did not need
the same exclusion treatment. No external dependency: local SQLite
(`~/.corvus/memory.db`, auto-created), no venv required. Standalone — no
functional connection to the rest of the fleet beyond a borrowed
input-sanitization pattern comment referencing vigia-repo. Already
configured in Anna's own `~/.claude.json` before this registry existed;
registered as-is, all 7 tools, per explicit request.

### STIGMERGY — not built
No MCP server exists. CockroachDB is not a secondary or optional dependency
here — it is the only coordination channel between agents and the primary
store: a native `VECTOR` column with a `VECTOR INDEX` for `recall()`
(a CockroachDB v25.2+ feature, required by the hackathon STIGMERGY was built
for), an authority model bound to CockroachDB's own `current_user`/RBAC
(`ops/authority.py`), changefeeds pushing to Lambda, and retry logic keyed to
CockroachDB's own `SQLSTATE 40001`. There is no ORM or repository layer
anywhere in the code — raw SQL is spread across twelve files (`ops/*.py`,
`audit/*.py`, `lambdas/*.py`). Worse, for a read-only bridge specifically:
`recall()` itself writes — it updates access metadata and can trigger a
`REDISCOVERED` state transition in the same transaction. It is not a read
despite the name.

Decoupling a read-only path with moderate effort is not realistic here. If a
read-only view is wanted later, the honest path is a periodic
exporter/snapshot (ETL to SQLite or JSON) built **outside** STIGMERGY's own
code, with an MCP bridge over that snapshot — not a live bridge against
CockroachDB, and not an edit to `ops/` or `audit/`.

## A real gotcha: Claude Code's global scope ignores `cwd`

Found 2026-10-09 the hard way: after merging a render into the live
`~/.claude.json`, 5 of 6 new entries failed with `CONNECTION_CLOSED` on
reconnect. Reproduced directly: Claude Code's global **"User MCPs"**
scope (the top-level `mcpServers` in `~/.claude.json`, as opposed to a
project-local `.mcp.json`) does not apply the `cwd` field. Any entry whose
`args` contains a relative path, or whose command needs the working
directory on `sys.path` for a `-m module` invocation, fails immediately
in that scope — even though the identical entry works in a project-scoped
config.

`cwd` is still declared in `registry.yaml` (harmless if another client
honors it, e.g. a project-local Claude config, Codex, or OpenCode), but
every entry's `command`/`args`/`env` must also be fully self-sufficient
without it:

- Any script path in `args` must be absolute, not relative.
- Any `-m <package>` invocation needs `PYTHONPATH` set in `env` to that
  package's root (the same pattern FORGE's entry already used, which is
  why it was never affected).

Before trusting a new entry, reproduce both directions yourself, the same
way this was found: run the exact configured command from an unrelated
directory with `cwd` NOT set, confirm it fails the same way
`CONNECTION_CLOSED` would, then confirm the absolute-path/`PYTHONPATH`
fix succeeds with a real stdio handshake. Don't infer this from reading
the entry — the failure mode is silent until something actually tries to
connect.

## Adding a server

1. The project builds and verifies its **own** MCP server first — a real
   handshake, a real tool call, a checked error path. CUARTEL never
   contains forensic or security logic of its own.
2. Add an entry to `registry.yaml` with `status: ready`, following the
   schema above, including the verification you actually did in `notes`.
3. Re-run `render.py doctor` to confirm the command resolves, then
   `render.py <target>` (or `--out` straight to the runtime's config path)
   to pick it up.

If the project's full MCP server mixes read and write tools, and only the
read side belongs in a shared registry like this one, write a small
curated file in that project's own repository (see MNEME's and
raven-memory's `mcp_server_readonly.py`) rather than trying to filter tools
from CUARTEL's side — the curation belongs with the project that owns the
authority boundary.
