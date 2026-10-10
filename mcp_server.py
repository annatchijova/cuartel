"""CUARTEL's own MCP server — read-only introspection over the fleet it registers.

ROADMAP.md Level 2: a fresh agent session, with no memory of how this
registry came to be, should be able to ask "what do I have for X" and get
a correct answer sourced from registry.yaml and real handshakes — not have
to read YAML and four Markdown files first.

Every tool here is read-only by construction: nothing in this file writes
to registry.yaml, to any fleet project's own files, or to any fleet
project's own MCP server beyond calling its read-only `list_tools()`.
CUARTEL does not gain decision authority over the fleet by having its own
MCP server — it gains a voice to describe the fleet's existing authority
boundaries accurately.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))

import render  # noqa: E402 — cuartel's own render.py, reused, not duplicated

mcp = FastMCP("cuartel")


async def _log_usage(tool_name: str, objective: str, result_summary: str, success: bool) -> None:
    """ROADMAP.md Level 3: best-effort usage logging to CRONOS. Opens one
    trace per call under agent_id="cuartel", records the call, closes it
    with a decision — so `cronos_list_traces(agent_id="cuartel")` becomes
    CUARTEL's own usage history: which tool, when, with what outcome.

    NEVER raises and NEVER blocks the real tool's result on this
    succeeding: if CRONOS is unreachable, misconfigured, or not status:
    ready, this silently no-ops. Logging usage is not part of the
    authority of any tool here -- a telemetry failure must never look
    like a tool failure. post_to_slack is always False; this is internal
    telemetry, not something anyone needs pinged about."""
    try:
        servers = render.load_registry()
        cronos_cfg = servers.get("cronos")
        if not cronos_cfg or cronos_cfg.get("status") != "ready":
            return
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=cronos_cfg["command"], args=cronos_cfg.get("args") or [],
            env=cronos_cfg.get("env") or None,
        )
        async with asyncio.timeout(5):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    opened = await session.call_tool("cronos_open_trace", {
                        "agent_id": "cuartel", "objective": objective,
                    })
                    trace_id = json.loads(opened.content[0].text)["trace_id"]
                    await session.call_tool("cronos_record_tool_call", {
                        "trace_id": trace_id, "tool_name": tool_name,
                        "result_summary": result_summary[:500],
                    })
                    await session.call_tool("cronos_close_trace", {
                        "trace_id": trace_id,
                        "decision": "success" if success else "failure",
                        "confidence_num": 100 if success else 50,
                        "post_to_slack": False,
                    })
    except Exception:
        pass  # best-effort telemetry; never surface as a tool failure


@mcp.tool()
async def cuartel_list_servers() -> dict:
    """List every project in the fleet CUARTEL knows about: name, status
    (ready/blocked/planned), capability plane, and tool count. Read-only
    — sourced from registry.yaml, not a live handshake (fast; use
    cuartel_run_doctor for live verification)."""
    servers = render.load_registry()
    result = {
        "servers": [
            {
                "name": name,
                "display_name": cfg.get("display_name", name),
                "status": cfg.get("status"),
                "plane": cfg.get("plane"),
                "tool_count": cfg.get("tool_count", 0),
            }
            for name, cfg in servers.items()
        ]
    }
    await _log_usage("cuartel_list_servers", "list the fleet",
                      f"{len(result['servers'])} servers listed", True)
    return result


@mcp.tool()
async def cuartel_describe_server(name: str) -> dict:
    """Full detail for one fleet project: its capability plane, authority
    note, status, tool count, and the verification notes recorded when it
    was registered. Read-only, sourced from registry.yaml."""
    servers = render.load_registry()
    cfg = servers.get(name)
    if cfg is None:
        await _log_usage("cuartel_describe_server", f"describe '{name}'",
                          "not found in registry", False)
        return {"error": f"'{name}' is not in the registry.",
                "known_servers": sorted(servers.keys())}
    result = {
        "name": name,
        "display_name": cfg.get("display_name", name),
        "repo": cfg.get("repo"),
        "status": cfg.get("status"),
        "plane": cfg.get("plane"),
        "authority": cfg.get("authority"),
        "tool_count": cfg.get("tool_count", 0),
        "notes": cfg.get("notes"),
    }
    await _log_usage("cuartel_describe_server", f"describe '{name}'",
                      f"status={cfg.get('status')}", True)
    return result


@mcp.tool()
async def cuartel_run_doctor(deep: bool = False, timeout: float = 10.0) -> dict:
    """Run the fleet health check. deep=False (default) only checks that
    each `ready` entry's command exists on disk — fast. deep=True does a
    real stdio MCP handshake against every `ready` entry, comparing its
    live tool count against the registry (OK/DRIFT), and diagnoses FAILs
    against a library of this project's own past incident signatures.
    Read-only: this only connects to each server's existing stdio
    interface, the same as any MCP client would, and reports what it
    found."""
    servers = render.load_registry()
    if not deep:
        results = []
        for name, cfg in servers.items():
            status = cfg.get("status")
            if status != "ready":
                results.append({"name": name, "status": status, "result": "skipped"})
                continue
            cmd = cfg.get("command")
            exists = cmd is not None and Path(cmd).exists()
            results.append({"name": name, "status": status,
                             "result": "ok" if exists else "missing", "command": cmd})
        missing = [r["name"] for r in results if r.get("result") == "missing"]
        await _log_usage("cuartel_run_doctor", "shallow fleet check",
                          f"{len(results)} entries, missing={missing}", not missing)
        return {"mode": "shallow", "results": results}
    report = await render.doctor_deep_data(servers, timeout)
    fails = [r["name"] for r in report if r.get("result") == "fail"]
    drifts = [r["name"] for r in report if r.get("result") == "drift"]
    await _log_usage(
        "cuartel_run_doctor", "deep fleet check",
        f"{len(report)} entries, fail={fails}, drift={drifts}", not fails,
    )
    return {"mode": "deep", "results": report}


@mcp.tool()
async def cuartel_find_capability(query: str, timeout: float = 10.0) -> dict:
    """Search across every ready fleet server's ACTUAL, LIVE tool list for
    one that matches a capability you need — e.g. "verify a sealed case",
    "read entropy", "custody chain". Does a real handshake to each ready
    server (in parallel) and searches tool names and descriptions as they
    exist right now — never a second, potentially stale copy of them.
    Read-only: only calls list_tools() on each server, never invokes any
    tool itself."""
    servers = render.load_registry()
    ready = render.ready_servers(servers)

    names = list(ready.keys())
    results = await asyncio.gather(
        *(render.handshake(name, ready[name], timeout, include_tools=True) for name in names)
    )
    outcomes = dict(zip(names, results))

    terms = [t.lower() for t in query.split() if t.strip()]
    matches = []
    unreachable = []
    for server_name, outcome in outcomes.items():
        if outcome["result"] != "connected":
            unreachable.append({"server": server_name, "error": outcome.get("error")})
            continue
        for tool in outcome.get("tools", []):
            haystack = f"{tool['name']} {tool['description']}".lower()
            if any(term in haystack for term in terms):
                matches.append({
                    "server": server_name,
                    "tool": tool["name"],
                    "description": tool["description"],
                })
    await _log_usage(
        "cuartel_find_capability", f"search: {query}",
        f"{len(matches)} matches across "
        f"{len({m['server'] for m in matches})} servers, "
        f"unreachable={[u['server'] for u in unreachable]}",
        bool(matches),
    )
    return {"query": query, "matches": matches, "unreachable_servers": unreachable}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
