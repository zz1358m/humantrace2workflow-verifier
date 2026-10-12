"""Unified trace store: one append-only events.jsonl per local day, every source writes the same shape.

Event = {"t": epoch seconds, "src": source name, "k": kind, ...fields}

kinds
  win      foreground window span start        app, title
  type     typing burst (content never stored) n, bs (backspace/delete count), t1
  key      shortcut                            combo ("ctrl+z")
  click    mouse click                         n, t1
  scroll   scroll burst                        n, t1
  clip     clipboard change                    n (chars), h (hash), preview?
  file     file change in a watched dir        op, path, sha?, size?
  shot     screenshot / video keyframe         path, reason
  idle     user away                           t1
  visit    browser history                     url, title, browser
  prompt   user message to a coding agent      agent, session, cwd, text
  reply    agent's final text for a turn       agent, session, text, tools
  abort    user interrupted the agent          agent, session
  deny     user rejected a tool call           agent, session, tool
  msg      chat message (exported IM logs)     peer, me (bool), text
  commit   git commit                          repo, sha, subject, files
  mark     explicit user annotation            text
  cmd      shell command                       host, cmd, undated? (order known, time is not)
  open     file opened (OS recent list)        name
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from . import config


def day_of(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def hms(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


class Writer:
    """Thread-safe appender that routes each event to its own day file."""

    def __init__(self):
        self._lock = threading.Lock()
        self._files: dict[str, object] = {}

    def emit(self, src: str, k: str, t: float | None = None, **fields) -> dict:
        ev = {"t": round(t if t is not None else time.time(), 3), "src": src, "k": k, **fields}
        day = day_of(ev["t"])
        with self._lock:
            f = self._files.get(day)
            if f is None:
                f = open(config.day_dir(day) / "events.jsonl", "a", encoding="utf-8")
                self._files[day] = f
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
        return ev

    def close(self):
        with self._lock:
            for f in self._files.values():
                f.close()
            self._files.clear()


def read_events(day: str) -> list[dict]:
    p = config.home() / "traces" / day / "events.jsonl"
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda e: e["t"])
    return out


def days() -> list[str]:
    root = config.home() / "traces"
    return sorted(d.name for d in root.iterdir() if (d / "events.jsonl").exists()) if root.exists() else []


def replace_source(src: str, events: Iterable[dict]) -> dict[str, int]:
    """Re-importable sources (logs, history) overwrite their previous rows so collect is idempotent."""
    by_day: dict[str, list[dict]] = {}
    for ev in events:
        by_day.setdefault(day_of(ev["t"]), []).append(ev)
    counts = {}
    for day, evs in by_day.items():
        p = config.day_dir(day) / "events.jsonl"
        keep = []
        if p.exists():
            with open(p, encoding="utf-8") as f:
                keep = [ln for ln in f if f'"src": "{src}"' not in ln]
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(keep)
            for ev in sorted(evs, key=lambda e: e["t"]):
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        counts[day] = len(evs)
    return counts


def iter_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
