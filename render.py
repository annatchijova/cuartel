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


async def handshake(name: str, cfg: dict, timeout: float, include_tools: bool = False) -> dict:
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
                            result = {"result": "connected", "tool_count": len(tools.tools)}
                            if include_tools:
                                result["tools"] = [
                                    {"name": t.name, "description": t.description or ""}
                                    for t in tools.tools
                                ]
                            return result
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


async def doctor_deep_data(servers: dict, timeout: float) -> list[dict]:
    """Pure data version of the deep doctor check -- no printing. Shared by
    the CLI (`doctor --deep`) and cuartel's own MCP server
    (`cuartel_run_doctor`), so there is exactly one implementation of this
    check, not two that can drift apart."""
    report = []
    for name, cfg in servers.items():
        status = cfg.get("status")
        if status != "ready":
            report.append({"name": name, "status": status, "result": "skipped",
                            "notes": cfg.get("notes", "").strip()})
            continue
        outcome = await handshake(name, cfg, timeout)
        expected = cfg.get("tool_count")
        entry = {"name": name, "status": status}
        if outcome["result"] == "connected":
            count = outcome["tool_count"]
            if expected is not None and count != expected:
                entry.update(result="drift", tool_count=count, expected_tool_count=expected)
            else:
                entry.update(result="ok", tool_count=count)
        else:
            entry.update(result="fail", error=outcome["error"],
                         diagnosis=outcome.get("diagnosis"), stderr=outcome.get("stderr"))
        report.append(entry)
    return report


def cmd_doctor_deep(servers: dict, timeout: float = 10.0) -> int:
    report = asyncio.run(doctor_deep_data(servers, timeout))
    ok = True
    for entry in report:
        if entry["result"] == "skipped":
            print(f"[{entry['status'].upper():7}] {entry['name']} — {entry['notes'][:100]}")
        elif entry["result"] == "ok":
            print(f"[OK     ] {entry['name']} — {entry['tool_count']} tools, matches registry")
        elif entry["result"] == "drift":
            print(f"[DRIFT  ] {entry['name']} — handshake OK, {entry['tool_count']} tools "
                  f"(registry says {entry['expected_tool_count']}) — update tool_count in registry.yaml")
        else:
            ok = False
            print(f"[FAIL   ] {entry['name']} — {entry['error']}")
            if entry.get("diagnosis"):
                print(f"           diagnosis: {entry['diagnosis']}")
            elif entry.get("stderr"):
                print(f"           stderr: {entry['stderr'][:200]}")
    return 0 if ok else 1


_MCP_SERVER_GLOBS = ["*mcp_server*.py", "**/mcp/server.js", "**/mcp/server.ts"]


_SCAN_EXCLUDE_DIR_NAMES = {"node_modules", ".venv", "venv", "site-packages", "tests", "test"}


def _find_mcp_server_files(repo: str) -> list[Path]:
    root = Path(repo)
    if not root.is_dir():
        return []
    found = set()
    for pattern in _MCP_SERVER_GLOBS:
        for f in root.rglob(pattern):
            if _SCAN_EXCLUDE_DIR_NAMES & set(f.parts):
                # Dependency internals (a vendored anthropic/fastmcp/litellm
                # SDK matching "mcp_server" in its own filenames) and test
                # files are not a fleet project's own server -- scanning
                # them produced exactly this kind of noise the first time
                # this ran for real against vigia-repo's own .venv.
                continue
            if f.suffix in (".js", ".ts") and "dist" not in f.parts:
                # Source (src/mcp/server.ts) is not what a client launches --
                # only the built dist/.../server.js is, avoiding a false
                # positive on velo's own source-vs-build pair.
                continue
            found.add(f.resolve())
    return sorted(found)


def _module_arg_to_path(repo: str, args: list) -> Path | None:
    """`-m package.module` resolves to a real file on disk relative to the
    project root (or its `src/` layout) even though no literal path
    appears in args -- without this, every entry using `-m` (annaconda,
    forge, pancito-red-team, siberian) looks like its server file is
    unknown to the registry, which is a false positive, not real drift."""
    if "-m" not in args:
        return None
    idx = args.index("-m")
    if idx + 1 >= len(args):
        return None
    rel = Path(*args[idx + 1].split(".")).with_suffix(".py")
    for base in (Path(repo), Path(repo) / "src"):
        candidate = base / rel
        if candidate.is_file():
            return candidate.resolve()
    return None


def _console_script_to_path(repo: str, command: str) -> Path | None:
    """Resolve an installed console-script command (e.g.
    `.venv/bin/zaynor-mcp`) back to its source file via the project's own
    `pyproject.toml` [project.scripts] entry -- without this, any project
    using this install pattern (zaynor) looks like its server file is
    unknown to the registry every single scan, which is a false
    positive, not real drift."""
    pyproject = Path(repo) / "pyproject.toml"
    if not pyproject.is_file():
        return None
    name = Path(command).name
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf'^{re.escape(name)}\s*=\s*"([\w.]+):', text, re.MULTILINE)
    if not m:
        return None
    rel = Path(*m.group(1).split(".")).with_suffix(".py")
    for base in (Path(repo), Path(repo) / "src"):
        candidate = base / rel
        if candidate.is_file():
            return candidate.resolve()
    return None


def _known_script_paths(servers: dict) -> set[Path]:
    paths = set()
    for cfg in servers.values():
        args = cfg.get("args") or []
        for a in args:
            if isinstance(a, str) and a.endswith((".py", ".js", ".ts")):
                paths.add(Path(a).resolve())
        if cfg.get("repo"):
            resolved = _module_arg_to_path(cfg["repo"], args)
            if resolved:
                paths.add(resolved)
            if not args and cfg.get("command"):
                resolved = _console_script_to_path(cfg["repo"], cfg["command"])
                if resolved:
                    paths.add(resolved)
    return paths


def cmd_scan(servers: dict) -> int:
    """ROADMAP.md Level 5: looks for drift this registry doesn't know
    about yet and drafts what it would change -- NEVER writes
    registry.yaml itself. Two checks:

    1. A new mcp_server*.py (or built mcp/server.js) file inside a repo
       this registry already tracks, that no entry's `args` points at --
       a second server appearing, or the known one being renamed/moved.
    2. For SIBERIAN specifically: whether its own README still carries
       the "NOT READY FOR OPERATIONAL USE" banner that this registry's
       `status: planned` decision is keyed to.

    Every finding is printed as a draft for a human (or an agent acting
    on her explicit instruction) to review -- promoting a draft to an
    actual registry.yaml change is never this function's decision."""
    known_paths = _known_script_paths(servers)
    # Only scan repos of ready/blocked entries: a "planned" entry is either
    # not built at all (nothing to find) or built but deliberately held
    # back with the reason already in `notes` (siberian) or already
    # superseded (mneme_memory_mcp) -- re-surfacing that every scan is
    # noise, not new drift.
    seen_repos = sorted({
        cfg["repo"] for cfg in servers.values()
        if cfg.get("repo") and cfg.get("status") in ("ready", "blocked")
    })
    drafts = []

    for repo in seen_repos:
        for f in _find_mcp_server_files(repo):
            if f not in known_paths:
                drafts.append(
                    f"NEW FILE not referenced by any entry's args: {f}\n"
                    f"  (repo already tracked in registry.yaml: {repo})\n"
                    f"  draft: this may be a new server, or the existing one "
                    f"renamed/moved -- verify with a real handshake before "
                    f"adding or editing a registry.yaml entry, same as every "
                    f"other entry here."
                )

    siberian_readme = Path("/home/labestiadevigia/siberian/README.md")
    if siberian_readme.is_file():
        text = siberian_readme.read_text(encoding="utf-8", errors="replace")
        if "NOT READY FOR OPERATIONAL USE" not in text:
            drafts.append(
                "siberian/README.md no longer contains \"NOT READY FOR "
                "OPERATIONAL USE\" -- registry.yaml's status: planned for "
                "siberian is keyed to that exact banner.\n"
                "  draft: re-read siberian's own current maturity claim, then "
                "consider flipping siberian's status: planned -> ready in "
                "registry.yaml if its own project now says it's ready."
            )

    if not drafts:
        print(f"No drift detected across {len(seen_repos)} tracked repos -- nothing to draft.")
        return 0
    print(f"{len(drafts)} draft(s) found -- review before touching registry.yaml:\n")
    for d in drafts:
        print(f"- {d}\n")
    return 0


STATE_PATH = Path(__file__).parent / ".doctor_state.json"


def _load_last_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(report: list[dict]) -> None:
    snapshot = {entry["name"]: entry for entry in report}
    STATE_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def cmd_digest(servers: dict, timeout: float) -> int:
    """ROADMAP.md Level 4: a scheduled run's digest. Compares this run's
    deep-check result against the last saved state and prints only what
    changed -- "N entries checked, all stable" most runs, a short list of
    transitions otherwise. The schedule itself (cron, a systemd timer, a
    session-start hook) is a separate decision left to whoever wires this
    in; this is only the part that decides what's worth printing when it
    runs, instead of a wall of repeated OKs."""
    report = asyncio.run(doctor_deep_data(servers, timeout))
    last = _load_last_state()
    changed = []
    for entry in report:
        name = entry["name"]
        prev = last.get(name)
        prev_result = prev.get("result") if prev else None
        cur_result = entry["result"]
        prev_count = prev.get("tool_count") if prev else None
        cur_count = entry.get("tool_count")
        count_changed = (
            prev_count is not None and cur_count is not None and prev_count != cur_count
        )
        if prev_result != cur_result or count_changed:
            changed.append((name, prev_result, prev_count, entry))

    if not changed:
        print(f"No changes since last check ({len(report)} entries, all stable).")
    else:
        print(f"{len(changed)} change(s) since last check:")
        for name, prev_result, prev_count, entry in changed:
            cur_result = entry["result"]
            cur_count = entry.get("tool_count")
            label = prev_result or "unseen before"
            line = f"  {name}: {label} -> {cur_result}"
            if prev_count is not None and cur_count is not None and prev_count != cur_count:
                line += f" ({prev_count} -> {cur_count} tools)"
            if cur_result == "fail":
                line += f" — {entry.get('diagnosis') or entry.get('error')}"
            print(line)

    _save_state(report)
    return 0 if not any(e["result"] == "fail" for e in report) else 1


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

    digest_parser = sub.add_parser(
        "digest", help="deep check, but only report what changed since last run (ROADMAP.md Level 4)",
    )
    digest_parser.add_argument("--timeout", type=float, default=10.0)

    sub.add_parser("scan", help="draft registry.yaml changes for undetected drift; never applies them (ROADMAP.md Level 5)")

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

    if args.target == "digest":
        return cmd_digest(servers, args.timeout)

    if args.target == "scan":
        return cmd_scan(servers)

    output = renderers[args.target](servers)
    if getattr(args, "out", None):
        args.out.write_text(output, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
