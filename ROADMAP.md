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

## Level 3 — Usage becomes a signal, not just an event — BUILT 2026-10-09

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

**Built — with a scope correction worth stating honestly.** CUARTEL does
not actually mediate fleet tool *invocations* (it never calls a fleet
tool, only `list_tools()` on it — that boundary is deliberate, see the
invariants at the top of this document). So what gets logged is CUARTEL's
own four tools being called, each as one CRONOS trace under
`agent_id="cuartel"` (`cronos_open_trace` → `cronos_record_tool_call` →
`cronos_close_trace`, `post_to_slack=False`). That's narrower than "every
call across the fleet," but it's the honest version: `cuartel_run_doctor`
and `cuartel_find_capability` calls are now a queryable history
(`cronos_list_traces(agent_id="cuartel")`), including which fleet servers
each one touched and what it found. Verified: ran all four tools once
each, confirmed all 4 traces in CRONOS with `chain_ok: 1`. Also verified
the degradation path directly — pointed cronos's command at a
nonexistent path and confirmed the real tool call still succeeded with
correct data; a telemetry failure never surfaces as a tool failure.

## Level 4 — Checks run themselves, on a schedule that makes sense — BUILT 2026-10-10

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

**The diff/digest half is built as `render.py digest`.** It runs the same
deep check as Level 1, compares each entry against `.doctor_state.json`
(gitignored — local run state, not registry content), and prints only
transitions: a new fail, a resolved fail, a tool-count change — "no
changes" otherwise. Exit code stays nonzero while any entry is actually
failing, even across "no changes" runs, so a cron job's own exit-code
alerting still works. Verified all three paths directly: a clean first
run (everything "unseen before"), a stable second run ("no changes"), and
a tampered-state test that confirmed the comparison catches a tool-count
change even when both runs independently say "ok" against the registry
(the first version of this logic missed that case — found and fixed by
testing it, not by reading it).

**Decided 2026-10-10: a Claude Code SessionStart hook, throttled to once
a day.** A scheduled cloud agent was ruled out first, for a reason worth
stating plainly: the whole fleet runs as local stdio processes on this
machine, so a cloud-side cron literally cannot reach them to do a real
handshake. Of the remaining local options (cron, systemd timer, session
hook), Anna picked the session hook — she sees the digest exactly when
it matters (she's working), with no separate infrastructure to maintain,
at the cost of not running on days she never opens Claude Code at all —
an acceptable tradeoff for drift that moves in days, not minutes.

Built as `daily_digest_hook.sh` (registered in
`~/.claude/settings.json`'s `hooks.SessionStart`): a marker file
(`.doctor_state.json`'s sibling, `.digest_last_run`, gitignored) tracks
the last calendar day it actually ran `render.py digest`. Every other
session start that same day exits silently — opening ten sessions in one
day doesn't nag ten times. On the day it does run, it prints a
`systemMessage` so the digest actually surfaces in the session, not just
to a log file nobody reads. Verified directly, not assumed: ran it twice
in a row — first run executed the digest and printed valid JSON with
the result; immediate second run exited with no output at all.

In the same sitting, found and removed a real exposure while reading
`~/.claude/settings.json` to add this: a separate, schema-invalid
`mcpServers` block there (not an official settings.json key — the real
one lives in `~/.claude.json`) had a live Anthropic API key sitting in
plaintext in VIGÍA's `env`. Removed at Anna's explicit confirmation;
flagged for her to consider rotating that key.

## Level 5 — Drift becomes a draft, not a surprise — BUILT 2026-10-10

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

**Built as `render.py scan`.** Two checks, neither of which ever writes
`registry.yaml`: (1) a filename-pattern search (`*mcp_server*.py`, built
`mcp/server.js`) across every `ready`/`blocked` repo for a file no
entry's `args` resolves to — covering literal paths, `-m package.module`
invocations, and installed console scripts (resolved via the project's
own `pyproject.toml` `[project.scripts]`, so ZAYNOR's install pattern
doesn't look unknown every run); (2) whether SIBERIAN's own README still
carries the "NOT READY FOR OPERATIONAL USE" banner `status: planned` is
keyed to.

The first version of check (1), run for real against the whole fleet,
returned 22 "new files" — almost all noise: vendored SDK internals inside
`vigia-repo/.venv` whose filenames happen to match the pattern, test
files, and every entry that uses `-m` or a console script (which have no
literal path for the naive check to match against at all). Fixed by
excluding `.venv`/`site-packages`/`node_modules`/`tests` directories,
resolving `-m module` args and console-script entries back to a real
file path, and restricting the scan to `ready`/`blocked` repos only
(`planned` repos are either unbuilt or a decision already made and
documented — rescanning them is noise, not new drift). That took it from
22 down to 3 real, still-standing false positives, documented rather than
chased further: MNEME's and raven-memory's own full (uncurated)
`mcp_server.py` genuinely exist and genuinely aren't registered — by
design, since only their curated read-only siblings are — and FORGE's
`cronos_mcp_server.py` matches the filename pattern without actually
being an MCP server. A content check (does the file actually instantiate
`FastMCP(...)`) would resolve the third one; left as a known limitation
for now rather than built, in the spirit of a kickoff that doesn't have
to be perfect.

Also verified the SIBERIAN maturity check directly, without touching the
real file: monkeypatched `Path.read_text` to return README content
without the banner, confirmed `scan` drafted the status-flip suggestion;
restored, confirmed it goes quiet again.

## What "done" looks like if time runs out at any level

Each level above stands on its own if nothing further gets built. Level 1
alone is a real improvement over today. Level 1 + 2 is a fleet that
explains itself. Adding 3 makes it accountable to its own history. Adding
4 and 5 makes it proactive. There is no level here that is scaffolding
for a later one — every one of them is something Anna could stop at and
have gained something real, the same way CUARTEL itself didn't wait for
all six fleet projects to be ready before being useful with two.
