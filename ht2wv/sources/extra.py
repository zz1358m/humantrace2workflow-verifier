"""Sources that need no recording: shell history (local and over ssh), agent logs on servers,
recently opened files, document modification times, auto-discovered git repos."""
from __future__ import annotations

import io
import re
import subprocess
import tarfile
import time
from pathlib import Path

from .. import config, store
from ..redact import redact
from . import agents

_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]  # BatchMode: never prompt, so only key auth works
# must start alphanumeric: nothing that reaches ssh's argv may look like an option
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(@[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_ZSH = re.compile(r"^: (\d{9,11}):\d+;(.*)$")
_DOC_EXT = {".md", ".txt", ".tex", ".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".ipynb", ".py", ".bib"}


def parse_history(text: str, mtime: float, host: str, since: float, tail: int, extra) -> list[dict]:
    """bash with HISTTIMEFORMAT ('#<epoch>' lines) and zsh extended history carry times. Plain history
    does not: those commands keep their order only, pinned just before the file's mtime, flagged undated."""
    dated, plain = [], []
    ts = None
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _ZSH.match(line)
        if m:
            dated.append((float(m.group(1)), m.group(2)))
        elif re.fullmatch(r"#\d{9,11}", line):
            ts = float(line[1:])
        elif ts is not None:
            dated.append((ts, line))
            ts = None
        else:
            plain.append(line)
    evs = [{"t": t, "src": f"shell@{host}", "k": "cmd", "host": host, "cmd": redact(c[:400], extra)} for t, c in dated if t >= since]
    plain = plain[-tail:] if not dated else []
    n = len(plain)
    evs += [{"t": round(mtime - (n - i) * 0.001, 3), "src": f"shell@{host}", "k": "cmd", "host": host, "cmd": redact(c[:400], extra), "undated": True}
            for i, c in enumerate(plain)]
    return evs


def shell_local(since: float, cfg: dict) -> int:
    home = Path.home()
    files = [home / "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt", home / ".bash_history", home / ".zsh_history"]
    evs = []
    for f in files:
        if f.exists():
            evs += parse_history(f.read_text(encoding="utf-8", errors="replace"), f.stat().st_mtime, "local", since,
                                 cfg["sources"]["shell_undated_tail"], cfg["privacy"]["redact_extra"])
    store.replace_source("shell@local", evs, since)
    return len(evs)


def shell_remote(host: str, since: float, cfg: dict) -> dict:
    if not HOST_RE.match(host):
        return {"ok": False, "error": "invalid host"}
    tail = int(cfg["sources"]["shell_remote_tail"])
    remote = ('for f in ~/.bash_history ~/.zsh_history; do [ -f "$f" ] && { echo "@@HT2WV $(stat -c %Y "$f")"; tail -n '
              + str(tail) + ' "$f"; }; done; true')
    try:
        r = subprocess.run(_SSH + [host, remote], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.decode("utf-8", "replace").strip()[-200:] or f"ssh exit {r.returncode}"}
    evs = []
    for chunk in r.stdout.decode("utf-8", "replace").split("@@HT2WV ")[1:]:
        head, _, body = chunk.partition("\n")
        try:
            mtime = float(head.strip())
        except ValueError:
            mtime = time.time()
        evs += parse_history(body, mtime, host, since, cfg["sources"]["shell_undated_tail"], cfg["privacy"]["redact_extra"])
    store.replace_source(f"shell@{host}", evs, since)
    return {"ok": True, "commands": len(evs)}


def agents_remote(host: str, since: float, cfg: dict, max_bytes: int = 300_000_000) -> dict:
    """Pull recent Claude Code / Codex session logs from a server (read-only) and parse them like local ones."""
    if not HOST_RE.match(host):
        return {"ok": False, "error": "invalid host"}
    days = max(1, int((time.time() - since) / 86400) + 1)
    remote = (f"cd ~ && find .claude/projects .codex/sessions -name '*.jsonl' -mtime -{days} 2>/dev/null | tar czf - -T - 2>/dev/null")
    try:
        r = subprocess.run(_SSH + [host, remote], capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    if not r.stdout:
        return {"ok": r.returncode == 0, "events": 0, "error": r.stderr.decode("utf-8", "replace").strip()[-200:]}
    if len(r.stdout) > max_bytes:
        return {"ok": False, "error": f"archive is {len(r.stdout) >> 20} MB, over the limit; narrow --days"}
    dest = config.home() / "remote" / re.sub(r"[^\w.@-]", "_", host)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:gz") as tf:
        tf.extractall(dest, filter="data")  # refuses absolute paths, links out of the tree, device files
    s, extra = cfg["sources"], cfg["privacy"]["redact_extra"]
    out = {"ok": True, "parse": {}}
    for kind, fn, sub in (("claude", agents.claude_code, ".claude/projects"), ("codex", agents.codex, ".codex/sessions")):
        root = dest / sub
        if root.exists():
            stats = {}
            evs = agents.dedupe(fn(root, since, s["msg_max_chars"], extra, stats=stats))
            for e in evs:
                e["src"], e["host"] = f"{kind}@{host}", host
            store.replace_source(f"{kind}@{host}", evs, since)
            out[kind] = len(evs)
            out["parse"][kind] = stats
    return out


def recent_files(since: float) -> int:
    d = Path.home() / "AppData/Roaming/Microsoft/Windows/Recent"
    evs = []
    for f in d.glob("*.lnk") if d.exists() else []:
        t = f.stat().st_mtime
        if t >= since:
            evs.append({"t": round(t, 3), "src": "recent", "k": "open", "name": f.stem})
    store.replace_source("recent", evs, since)
    return len(evs)


def docs(since: float, cfg: dict) -> int:
    evs = []
    for d in cfg["sources"].get("doc_dirs") or []:
        root = config.expand(d)
        for f in root.rglob("*") if root.is_dir() else []:
            if f.suffix.lower() in _DOC_EXT and not any(p.startswith(".") or p in ("node_modules", "__pycache__") for p in f.parts):
                try:
                    st = f.stat()
                except OSError:
                    continue
                if st.st_mtime >= since:
                    evs.append({"t": round(st.st_mtime, 3), "src": "docs", "k": "file", "op": "modified", "path": str(f), "size": st.st_size})
    store.replace_source("docs", evs, since)
    return len(evs)


def discover_repos(since: float, cfg: dict) -> list[str]:
    """Repos the person actually worked in: walk up from every working directory seen in agent prompts."""
    repos = {str(config.expand(r)) for r in cfg["sources"].get("git_repos") or []}
    for day in store.days():
        for e in store.read_events(day):
            if e["k"] == "prompt" and e.get("cwd") and e["t"] >= since and "@" not in e["src"]:
                p = Path(e["cwd"])
                for cand in (p, *p.parents):
                    if (cand / ".git").exists():
                        repos.add(str(cand))
                        break
    return sorted(repos)
