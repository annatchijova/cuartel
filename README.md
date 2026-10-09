# CUARTEL

A single source of truth for Anna's forensic tool fleet's MCP servers,
rendered into whichever agent runtime she's using that day — Claude Code,
Codex CLI, or OpenCode.

## What this is not

This is **not** an MCP server. It does not proxy, aggregate, or flatten any
project's tools into one combined catalog. Each project in the fleet
(vigia-repo, zaynor, velo, annaconda, pancito-red-team, siberian) owns and
runs its own MCP server, with its own authority boundary.
Mixing them into one server would collapse distinct trust levels — read-only
evidence access is not the same thing as case memory, and neither is the
same thing as a gated offensive action. zaynor's own
[`docs/adr/0001-separate-mcp-capability-planes.md`](https://github.com/annatchijova/zaynor/blob/main/docs/adr/0001-separate-mcp-capability-planes.md)
made this same call at a smaller scale; this repo generalizes it across the
whole fleet instead of re-deciding it per project.

If a target runtime someday cannot load more than one MCP server, the
documented fallback is a typed multiplexer that preserves these same
capability-plane boundaries — not a flat proxy. That multiplexer does not
exist yet.

## What this is

`registry.yaml` — one entry per project's MCP server: how to launch it,
what capability plane it operates in, its authority note, and its status
(`ready` / `blocked` / `planned`). `render.py` reads that registry and emits:

```
python3 render.py claude              # .mcp.json format, to stdout
python3 render.py codex                # config.toml [mcp_servers.*] snippet
python3 render.py opencode             # opencode.json mcp block
python3 render.py doctor               # sanity-check every entry's command exists
python3 render.py claude --out ~/some/path/.mcp.json
```

Only `status: ready` entries are ever rendered into a runtime config.
`blocked` and `planned` entries show up in `doctor` output so the gap stays
visible, never silently.

## Current fleet status

| Server | Status | Plane |
|---|---|---|
| vigia | ready | read-only-evidence-and-analysis |
| cronos | ready | reasoning-trace-and-audit — fixed a real CONNECTION_CLOSED (missing `trio`, no venv existed) |
| zaynor | ready | case-memory-and-audit |
| velo | ready | zk-attestation — F1 path-traversal fixed in `ef0caa4`, re-verified live (`tests/caseid.test.ts`, 4/4 pass) |
| annaconda | ready | read-only, proxies a GET-only subset of its own HTTP API; requires the service to already be running |
| pancito-red-team | ready | exposes only its 2 passive/no-network CLIs (openapi triage, purple evaluate); every offensive network-action CLI stays deliberately unexposed |
| siberian | planned | server built and verified (6 tools), but kept unregistered on purpose — siberian's own README still says NOT READY FOR OPERATIONAL USE |

## Adding a server

1. The project builds and verifies its **own** MCP server first (handshake
   confirmed, tool count known) — this repo never contains forensic or
   security logic of its own.
2. Add an entry to `registry.yaml` with `status: ready` once that's done.
3. Re-run `render.py <target>` and point the runtime's config at the output
   (or `--out` directly to the runtime's config path).

## Requirements

`pip install pyyaml` (or system package) — stdlib otherwise.
