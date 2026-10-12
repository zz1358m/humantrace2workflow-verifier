"""Local coding-agent conversations (Claude Code, Codex) -> prompt / reply / abort / deny events.

These logs are the densest verifier signal on the machine: every time the user pushes back,
interrupts, or refuses a tool call, they are stating an acceptance criterion in their own words.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .. import config, store
from ..redact import redact

_NOISE = re.compile(r"^\s*(<(system-reminder|command-name|local-command|task-notification|environment_context|user_instructions|turn_aborted|user_shell)"
                    r"|# AGENTS\.md instructions|This session is being continued from|Caveat: )", re.I)
_TAGS = re.compile(r"<(system-reminder|ide_[a-z_]+|environment_context)>.*?</\1>", re.S)


def _ts(s) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _clean(text: str, cap: int, extra) -> str:
    text = _TAGS.sub("", text).strip()
    if len(text) > cap:
        text = text[: cap * 2 // 3] + f"\n…[{len(text) - cap} chars cut]…\n" + text[-cap // 3 :]
    return redact(text, extra)


def _blocks_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))
    return ""


def claude_code(root: Path, since: float, cap: int, extra) -> list[dict]:
    evs = []
    for f in root.glob("*/*.jsonl"):
        if f.stat().st_mtime < since:
            continue
        sid = f.stem[:8]
        tools: list[str] = []
        last_text, last_t = "", None

        def flush():
            nonlocal tools, last_text, last_t
            if last_t and (last_text or tools):
                evs.append({"t": last_t, "src": "claude", "k": "reply", "agent": "claude", "session": sid,
                            "text": _clean(last_text, cap // 2, extra), "tools": tools[:40]})
            tools, last_text, last_t = [], "", None

        for d in store.iter_jsonl(f):
            t = _ts(d.get("timestamp"))
            if t is None or t < since or d.get("isSidechain"):
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            content = msg.get("content")
            if d.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if b.get("type") == "tool_use":
                        tools.append(b.get("name", "?"))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        last_text, last_t = b["text"], t
                last_t = last_t or t
            elif d.get("type") == "user":
                if isinstance(content, list):
                    for b in content:
                        if b.get("type") == "tool_result" and b.get("is_error"):
                            body = _blocks_text(b.get("content")) or str(b.get("content", ""))
                            if "doesn't want to proceed" in body or "user rejected" in body.lower() or "was rejected" in body:
                                evs.append({"t": t, "src": "claude", "k": "deny", "agent": "claude", "session": sid,
                                            "tool": tools[-1] if tools else "?", "text": _clean(body, 300, extra)})
                text = _blocks_text(content)
                if not text.strip() or _NOISE.match(text):
                    continue
                if "[Request interrupted by user" in text:
                    flush()
                    evs.append({"t": t, "src": "claude", "k": "abort", "agent": "claude", "session": sid})
                    continue
                if isinstance(content, list) and any(b.get("type") == "tool_result" for b in content):
                    continue
                flush()
                evs.append({"t": t, "src": "claude", "k": "prompt", "agent": "claude", "session": sid,
                            "cwd": d.get("cwd", ""), "text": _clean(text, cap, extra)})
        flush()
    return evs


def codex(root: Path, since: float, cap: int, extra) -> list[dict]:
    evs = []
    for f in root.rglob("*.jsonl"):
        if f.stat().st_mtime < since:
            continue
        sid, cwd = f.stem[-8:], ""
        tools: list[str] = []
        for d in store.iter_jsonl(f):
            t = _ts(d.get("timestamp"))
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            if d.get("type") in ("session_meta", "turn_context"):
                cwd = p.get("cwd", cwd)
            if t is None or t < since:
                continue
            base = {"t": t, "src": "codex", "agent": "codex", "session": sid}
            pt = p.get("type")
            if d.get("type") == "response_item":
                if pt in ("function_call", "custom_tool_call"):
                    tools.append(p.get("name", "?"))
                elif pt == "message" and p.get("role") == "user":
                    text = _blocks_text(p.get("content"))
                    if text.strip() and not _NOISE.match(text):
                        evs.append({**base, "k": "prompt", "cwd": cwd, "text": _clean(text, cap, extra)})
            elif d.get("type") == "event_msg":
                if pt == "task_complete":
                    evs.append({**base, "k": "reply", "text": _clean(p.get("last_agent_message") or "", cap // 2, extra), "tools": tools[:40]})
                    tools = []
                elif pt == "turn_aborted":
                    evs.append({**base, "k": "abort", "reason": str(p.get("reason", ""))})
                    tools = []
    return evs


def collect(since: float, cfg: dict | None = None) -> dict[str, int]:
    cfg = cfg or config.load()
    s = cfg["sources"]
    extra = cfg["privacy"]["redact_extra"]
    out = {}
    for name, fn, key in (("claude", claude_code, "claude_dir"), ("codex", codex, "codex_dir")):
        root = config.expand(s[key])
        if root.exists():
            seen, evs = set(), []
            for e in fn(root, since, s["msg_max_chars"], extra):  # resumed/forked sessions repeat their history
                key = (e["k"], round(e["t"]), e.get("text", "")[:120])
                if key not in seen:
                    seen.add(key)
                    evs.append(e)
            store.replace_source(name, evs)
            out[name] = len(evs)
    return out
