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
import json
import sys
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).parent / "registry.yaml"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="target", required=True)

    for target in ("claude", "codex", "opencode"):
        p = sub.add_parser(target)
        p.add_argument("--out", type=Path, default=None, help="write to this path instead of stdout")

    sub.add_parser("doctor")

    args = parser.parse_args()
    servers = load_registry()

    renderers = {
        "claude": render_claude,
        "codex": render_codex,
        "opencode": render_opencode,
    }

    if args.target == "doctor":
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
