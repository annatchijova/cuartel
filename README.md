[English](README.md) · [Español](README_ES.md) · [Technical README](TECHNICAL_README.md) · [Referencia técnica en español](TECHNICAL_README_ES.md)

# CUARTEL

Anna runs a fleet of independent forensic and security tools — VIGÍA, CRONOS,
MNEME, raven-memory, ZAYNOR, VELO, annaconda, PANCITO-RED-TEAM, SIBERIAN,
STIGMERGY, FORGE, CORVUS — each its own repository, its own tests, its own
release cadence.
Several already speak MCP. Connecting all of them to an agent runtime (Claude
Code today; Codex CLI or OpenCode if she ever needs a fallback) meant hand
editing a different config file format for each client, every time a server
was added, moved, or fixed.

CUARTEL is the single place that knows how to launch each one and in what
format each runtime expects to hear about it.

## What it is not

CUARTEL is **not** an MCP server, and it does not aggregate anyone's tools
into one combined catalog. Each project in the fleet keeps running its own
MCP server, under its own authority boundary. Mixing a read-only evidence
bridge, a memory-mutation bridge, and a gated offensive-action bridge into
one process would collapse exactly the distinctions that make each of them
safe to expose at all — the same call ZAYNOR's own
[ADR-0001](https://github.com/annatchijova/zaynor/blob/main/docs/adr/0001-separate-mcp-capability-planes.md)
already made at a smaller scale.

## What it is

A metadata registry (`registry.yaml`) plus a renderer (`render.py`) that
translates it into Claude Code's `.mcp.json`, Codex CLI's `config.toml`, and
OpenCode's `opencode.json` — so changing where a server lives, or adding a
new one, is a one-line edit followed by one command, not three.

```bash
python3 render.py claude --out ~/.claude.json-mcp-snippet
python3 render.py codex
python3 render.py opencode
python3 render.py doctor      # sanity-checks every registered command
```

## Current fleet

| Server | Status |
|---|---|
| VIGÍA, CRONOS, MNEME, raven-memory, ZAYNOR, VELO, annaconda, PANCITO-RED-TEAM, FORGE, CORVUS | ready |
| SIBERIAN | built, kept disabled — its own README says not ready for operational use |
| mneme_memory_mcp | superseded by MNEME, not registered |
| STIGMERGY | not built — see [Technical README](TECHNICAL_README.md) for why |

Full detail, the architecture decision behind it, and the registry schema are
in the [Technical README](TECHNICAL_README.md).

## Requirements

`pip install pyyaml` (or your system package) — stdlib otherwise.
