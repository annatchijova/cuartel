#!/usr/bin/env python3
"""CUARTEL — render registry.yaml into Claude Code / Codex CLI / OpenCode MCP config.

This script does one thing: read registry.yaml and emit the config format a
given agent runtime expects. It contains no forensic logic and makes no
decision about any project's output — it is a dumb templater over metadata
that each fleet project already owns.

Only entries with status: ready are ever emitted. "blocked" and "planned"
entries are listed by `doctor` but never written into a runtime config.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).parent / "registry.yaml"

# Level 1 of ROADMAP.md: known failure signatures from this project's own
# incident history. Each is (pattern over captured stderr, diagnosis + the
# fix that actually worked last time) -- a diagnosis should never be just
# the raw error when a past incident already named the cause.
FAILURE_SIGNATURES: list[tuple[str, str]] = [
    (
        r"No module named ['\"]trio['\"]",
        "Missing 'trio' dependency (cronos/mneme's main server need it). "
        "Fix: create a venv for this project and `pip install -e .` there "
        "-- do not pip install --user system-wide (PEP 668 blocks it here).",
    ),
    (
        r"No such file or directory",
        "A relative path was not found. This entry likely depends on `cwd`, "
        "which Claude Code's global \"User MCPs\" scope does NOT apply "
        "(see TECHNICAL_README.md). Fix: use an absolute path in `args`.",
    ),
    (
        r"ModuleNotFoundError: No module named '[^']+'",
        "Python could not import a package for a `-m module` invocation "
        "-- likely missing PYTHONPATH (cwd is not applied in the global "
        "scope, so the package root must be on sys.path another way). "
        "Fix: add PYTHONPATH pointing at the project's root to this "
        "entry's env (see forge's or annaconda's entry for the pattern).",
    ),
    (
        r"ECONNREFUSED|Connection refused",
        "The process started but a connection it depends on was refused. "
        "Check whether a required backing service is actually running "
        "(e.g. annaconda's own `uvicorn service.app:app --port 8080`).",
    ),
]


def _diagnose(stderr_text: str) -> str | None:
    for pattern, diagnosis in FAILURE_SIGNATURES:
        if re.search(pattern, stderr_text):
            return diagnosis
    return None


def load_registry() -> dict:
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("servers", {})


def ready_servers(servers: dict) -> dict:
    return {name: cfg for name, cfg in servers.items() if cfg.get("status") == "ready"}


def render_claude(servers: dict) -> str:
    mcp_servers = {}
    for name, cfg in ready_servers(servers).items():
        entry = {"command": cfg["command"], "args": cfg.get("args") or []}
        if cfg.get("env"):
            entry["env"] = cfg["env"]
        if cfg.get("cwd"):
            entry["cwd"] = cfg["cwd"]
        mcp_servers[name] = entry
    return json.dumps({"mcpServers": mcp_servers}, indent=2, ensure_ascii=False) + "\n"


def render_codex(servers: dict) -> str:
    lines = []
    for name, cfg in ready_servers(servers).items():
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f'command = "{cfg["command"]}"')
        args = cfg.get("args") or []
        args_str = ", ".join(f'"{a}"' for a in args)
        lines.append(f"args = [{args_str}]")
        if cfg.get("cwd"):
            lines.append(f'cwd = "{cfg["cwd"]}"')
        if cfg.get("env"):
            for k, v in cfg["env"].items():
                lines.append(f'env.{k} = "{v}"')
        lines.append("enabled = true")
        lines.append("")
    return "\n".join(lines) + ("\n" if lines else "")


def render_opencode(servers: dict) -> str:
    mcp = {}
    for name, cfg in ready_servers(servers).items():
        command = [cfg["command"], *(cfg.get("args") or [])]
        entry = {"type": "local", "command": command, "enabled": True}
        if cfg.get("env"):
            entry["environment"] = cfg["env"]
        mcp[name] = entry
    return json.dumps({"mcp": mcp}, indent=2, ensure_ascii=False) + "\n"


def cmd_doctor(servers: dict) -> int:
    ok = True
    for name, cfg in servers.items():
        status = cfg.get("status")
        if status != "ready":
            print(f"[{status.upper():7}] {name} — {cfg.get('notes', '').strip()[:100]}")
            continue
        cmd = cfg.get("command")
        exists = cmd is not None and Path(cmd).exists()
        marker = "OK" if exists else "MISSING"
        if not exists:
            ok = False
        print(f"[{marker:7}] {name} — command: {cmd}")
    return 0 if ok else 1


async def _handshake(name: str, cfg: dict, timeout: float) -> dict:
    """A real stdio MCP handshake against one entry -- never assumed from
    reading its command. Deliberately does NOT pass `cwd`: this is the
    same worst case Claude Code's global "User MCPs" scope actually
    exercises, so a pass here means the entry is truly self-sufficient,
    not just "would work if cwd were honored"."""
    import tempfile

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=cfg["command"], args=cfg.get("args") or [], env=cfg.get("env") or None,
    )
    stderr_text = ""
    try:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
            try:
                async with asyncio.timeout(timeout):
                    async with stdio_client(params, errlog=errlog) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            return {"result": "connected", "tool_count": len(tools.tools)}
            finally:
                errlog.seek(0)
                stderr_text = errlog.read()
    except Exception as exc:
        diagnosis = _diagnose(stderr_text) or _diagnose(str(exc))
        return {
            "result": "failed",
            "error": str(exc),
            "stderr": stderr_text.strip()[-500:],
            "diagnosis": diagnosis,
        }


async def _doctor_deep_async(servers: dict, timeout: float) -> int:
    ok = True
    ready = ready_servers(servers)
    for name, cfg in servers.items():
        status = cfg.get("status")
        if status != "ready":
            print(f"[{status.upper():7}] {name} — {cfg.get('notes', '').strip()[:100]}")
            continue
        outcome = await _handshake(name, cfg, timeout)
        expected = cfg.get("tool_count")
        if outcome["result"] == "connected":
            count = outcome["tool_count"]
            if expected is not None and count != expected:
                print(f"[DRIFT  ] {name} — handshake OK, {count} tools "
                      f"(registry says {expected}) — update tool_count in registry.yaml")
            else:
                print(f"[OK     ] {name} — {count} tools, matches registry")
        else:
            ok = False
            print(f"[FAIL   ] {name} — {outcome['error']}")
            if outcome["diagnosis"]:
                print(f"           diagnosis: {outcome['diagnosis']}")
            elif outcome["stderr"]:
                print(f"           stderr: {outcome['stderr'][:200]}")
    return 0 if ok else 1


def cmd_doctor_deep(servers: dict, timeout: float = 10.0) -> int:
    return asyncio.run(_doctor_deep_async(servers, timeout))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="target", required=True)

    for target in ("claude", "codex", "opencode"):
        p = sub.add_parser(target)
        p.add_argument("--out", type=Path, default=None, help="write to this path instead of stdout")

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument(
        "--deep", action="store_true",
        help="real stdio handshake per ready entry, tool-count drift check, "
             "and diagnosis-with-fix for known failure signatures (ROADMAP.md Level 1)",
    )
    doctor_parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="seconds to wait per handshake with --deep (default: 10)",
    )

    args = parser.parse_args()
    servers = load_registry()

    renderers = {
        "claude": render_claude,
        "codex": render_codex,
        "opencode": render_opencode,
    }

    if args.target == "doctor":
        if args.deep:
            return cmd_doctor_deep(servers, args.timeout)
        return cmd_doctor(servers)

    output = renderers[args.target](servers)
    if getattr(args, "out", None):
        args.out.write_text(output, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
