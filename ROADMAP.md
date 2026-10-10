[English](README.md) · [Español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md) · [Roadmap](ROADMAP.md) · [Hoja de ruta en español](ROADMAP_ES.md)

# CUARTEL — roadmap toward a self-aware fleet

## Destination

CUARTEL today is a static registry: a human (or an agent on her behalf)
edits `registry.yaml` and runs `render.py`. The destination is a control
plane that **knows its own state, explains itself to any agent that asks,
notices when something drifts, and closes the loop between "something
changed" and "the registry says so"** — without ever becoming a second
decision authority over any fleet project's own verdicts.

No calendar attached to this on purpose. Each level below is complete and
useful on its own; the next one builds on it whenever there's room for it
— a free afternoon, a week, or six months from now. Stopping after Level 2
leaves something genuinely finished, not a half-built promise.

## Invariants every level inherits (not added later)

These are true starting at Level 1, the same way they were true for the
very first version of `registry.yaml`:

1. **CUARTEL never becomes a decision authority.** It can detect, log,
   suggest, and draft — it never silently rewrites a fleet project's code,
   never auto-exposes a tool it hasn't verified is read-only, and never
   auto-applies a registry change to a live client config without the change
   being shown first.
2. **"Automated" never means "unverified."** Every new capability keeps the
   same discipline already established: a real stdio handshake, a real tool
   call, before anything is trusted — whether a human runs that check or a
   cron job does.
3. **Curation authority stays with each project.** CUARTEL can notice that
   a fleet project grew a new tool; it cannot decide on its own that the
   tool is safe to expose. That decision is always surfaced for a human (or
   an agent acting explicitly on her behalf) to make.

## Level 1 — The doctor actually diagnoses, not just pings — BUILT 2026-10-09

Today, `render.py doctor` only checks that a command's file exists. It
missed the real failure mode entirely: 5 of 6 new entries failed with
`CONNECTION_CLOSED` on the first real reconnect, for a reason `doctor`
never checked (the global scope's `cwd` quirk).

**What this level builds:** `doctor --deep` performs a real stdio
handshake against every `status: ready` entry — `initialize()` +
`list_tools()` — and compares the returned tool count against the
registry's `tool_count`. Three outcomes per entry: `OK` (handshake
succeeded, count matches), `DRIFT` (handshake succeeded, count changed —
exactly what happened with VELO going from 13 to 19 tools unnoticed), or
`FAIL` (handshake failed — and here the tool carries a small library of
*known* failure signatures from this project's own history: "no module
named trio" → missing venv; "No such file or directory" on a relative
arg → the cwd-not-honored pattern; `ModuleNotFoundError` on a `-m`
invocation → missing `PYTHONPATH`. Each match prints the diagnosis AND
the fix that worked last time, not just the raw error).

Useful standalone: this alone would have caught today's incident before
Anna did, with the actual root cause already named, the day it happened.

**Built as `render.py doctor --deep`.** First real run against the whole
fleet caught a genuine drift immediately: VIGÍA's registry said 33 tools,
the live handshake said 32 — fixed on the spot, which is exactly the
loop this level exists to close. The diagnosis library itself needed one
real fix before it worked: the first regex for the cwd-not-honored
signature didn't match Python's actual error wording
(`can't open file '...'` comes before "No such file or directory", not
after it) — found by deliberately triggering the failure path with a
broken fake entry and reading the real output, not assumed from writing
the regex.

## Level 2 — CUARTEL can explain itself to whoever asks — BUILT 2026-10-09

Right now, "knowing how to use CUARTEL" means reading `registry.yaml` and
two Markdown files. A fresh Claude Code session with zero memory of this
conversation — or Anna herself in six months — has to rediscover the whole
fleet by reading files.

**What this level builds:** `cuartel/mcp_server.py` — CUARTEL gets its own
MCP server (joining the fleet it manages), exposing read-only
introspection:

- `cuartel_list_servers()` — the fleet, with status and one-line purpose.
- `cuartel_describe_server(name)` — plane, authority note, tool list, and
  the exact verification that was done, straight from the registry.
- `cuartel_find_capability(query)` — "which server can read a sealed
  case?" → a ranked list of tools across the whole fleet, read from each
  entry's own tool docstrings, not a second, drifting copy of them.
- `cuartel_run_doctor()` — triggers Level 1's deep check and returns the
  report as structured data an agent can act on, not just text a human
  reads.

Useful standalone: any agent session, including one that has never seen
this conversation, can now ask "what do I have for X" and get a correct
answer instead of guessing or re-deriving it from scratch.

**Built as `mcp_server.py`, registered in the fleet it manages.** Found
two real bugs only by calling the two live-handshake tools end-to-end,
not by reading the code: both `cuartel_run_doctor(deep=True)` and
`cuartel_find_capability` originally called `asyncio.run()` from inside
FastMCP's own already-running event loop and crashed on the first real
call with "asyncio.run() cannot be called from a running event loop" —
fixed by making them `async def` tools that `await` directly. Verified
afterward with the same two calls: a full deep doctor run across all 11
ready entries in ~5 seconds, and `find_capability("custody chain")`
correctly surfacing relevant tools across 8 different servers from their
live descriptions.

## Level 3 — Usage becomes a signal, not just an event

Today, a tool call across the fleet leaves no trace anywhere CUARTEL can
see. There's no way to know which tools actually get used, which ones
silently always error, or which project's bridge has gone stale because
nobody's called it in months.

**What this level builds:** CUARTEL's own MCP server (from Level 2) logs
every call it mediates — which tool, which server, success or failure,
timestamp — to a local append-only store. CRONOS already exists for
exactly this purpose (reasoning-trace and audit, sealed with a hash
chain) — the natural choice is a dedicated CRONOS trace rather than a new
bespoke log format, so this reuses the fleet instead of growing it.

This is the actual feedback loop: Level 1's `doctor --deep` can now also
ask "which `ready` entries have zero real calls in N months?" — turning
dead weight visible instead of invisible. A tool that always fails when
called shows up as a pattern, not as scattered one-off frustration.

Useful standalone: even before anything "acts" on this data, having it
recorded is strictly better than not — the same principle behind every
audit chain in this fleet (VIGÍA, MNEME, CRONOS, raven-memory all already
believe this).

## Level 4 — Checks run themselves, on a schedule that makes sense

Today, `doctor` only runs when someone remembers to run it — which is how
VELO quietly grew 6 tools and 5 entries quietly broke without anyone
noticing until a real session hit them.

**What this level builds:** a scheduled run of `doctor --deep` (daily is
a reasonable default, but the actual cadence is Anna's call, not a
deadline anyone else sets) that diffs against the last known-good state
and produces a short digest — not noise: "all N servers still match,"
or "VELO: 19 → 22 tools, DRIFT" — written to a file or surfaced the next
time a session starts, never an interrupt for its own sake.

Useful standalone: this is the difference between finding out about drift
when it bites, versus finding out about it on a schedule Anna controls.

## Level 5 — Drift becomes a draft, not a surprise

Today, when something in the fleet changes — a new MCP server appears in
a project, a tool count shifts, a project's own maturity status flips
(SIBERIAN's "NOT READY" banner coming off, say) — nothing notices until a
human happens to look.

**What this level builds:** Level 4's scheduled check, when it finds
something new (a `mcp_server*.py` appearing in a known fleet repo that
isn't in `registry.yaml` yet; a status-worthy change in a project's own
README), drafts the `registry.yaml` edit it *would* make — as a diff,
never an applied change — plus the verification steps Level 1 already
knows to run before it could become `ready`. Anna (or an agent acting on
her explicit instruction) reviews and decides; CUARTEL never promotes its
own draft to `ready` on its own authority.

Useful standalone: the gap between "this fleet grew" and "the registry
knows it grew" shrinks from however long it takes someone to notice, to
however long it takes to review one draft.

## What "done" looks like if time runs out at any level

Each level above stands on its own if nothing further gets built. Level 1
alone is a real improvement over today. Level 1 + 2 is a fleet that
explains itself. Adding 3 makes it accountable to its own history. Adding
4 and 5 makes it proactive. There is no level here that is scaffolding
for a later one — every one of them is something Anna could stop at and
have gained something real, the same way CUARTEL itself didn't wait for
all six fleet projects to be ready before being useful with two.
