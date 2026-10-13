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
import os
import tempfile
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


def replace_source(src: str, events: Iterable[dict], since: float, until: float | None = None) -> dict[str, int]:
    """Replace a source's inclusive window, and re-snapshot all its undated rows.

    The default upper bound includes both now and the latest supplied event.
    An explicit upper bound must cover every supplied event.
    """
    events = list(events)
    latest = max((ev["t"] for ev in events), default=since)
    if until is None:
        until = max(time.time(), latest)
    if until < since or until < latest:
        raise ValueError("until must be >= since and every new event's t")

    by_day: dict[str, list[tuple[float, str]]] = {}
    for ev in events:
        if ev.get("undated") is True or since <= ev["t"] <= until:
            line = json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n"
            by_day.setdefault(day_of(ev["t"]), []).append((ev["t"], line))
    counts = {day: len(evs) for day, evs in sorted(by_day.items())}
    first_day, last_day = day_of(since), day_of(until)
    root = config.home() / "traces"
    src_hint = json.dumps(src, ensure_ascii=False)[1:-1]
    # Undated rows can be pinned outside the window, so inspect every existing day.
    for day in sorted(set(days()) | set(by_day)):
        full_day = first_day <= day <= last_day or day in by_day
        p = root / day / "events.jsonl"
        keep = []
        removed = False
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                for line in f:
                    # Unicode escapes can hide source values or the undated key.
                    unicode_escape = "\\u" in line
                    if ((src not in line and src_hint not in line and not unicode_escape
                         and not ("/" in src and "\\/" in line))
                            or (not full_day and "undated" not in line and not unicode_escape)):
                        keep.append(line)
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        keep.append(line)
                        continue
                    if (isinstance(row, dict) and row.get("src") == src
                            and (row.get("undated") is True
                                 or (full_day and since <= row["t"] <= until))):
                        removed = True
                    else:
                        keep.append(line)
        evs = by_day.get(day, [])
        if not removed and not evs:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="",
                                             dir=p.parent, delete=False) as f:
                temp = Path(f.name)
                f.writelines(keep)
                if keep and evs and not keep[-1].endswith(("\n", "\r")):
                    f.write("\n")
                f.writelines(line for _, line in sorted(evs))
            os.replace(temp, p)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
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
