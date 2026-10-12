"""Cheap structured sources: browser history, git, exported chat logs, time-tracker exports."""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .. import config, store
from ..redact import is_private, redact

_CHROME_EPOCH = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def browsers(since: float, cfg: dict | None = None) -> dict[str, int]:
    cfg = cfg or config.load()
    deny, extra = cfg["privacy"]["deny"], cfg["privacy"]["redact_extra"]
    out = {}
    for name, path in cfg["sources"]["browsers"].items():
        src = config.expand(path)
        if not src.exists():
            continue
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "History"
            shutil.copyfile(src, tmp)  # the live DB is locked while the browser runs
            con = sqlite3.connect(tmp)
            try:
                rows = con.execute(
                    "SELECT v.visit_time, u.url, u.title FROM visits v JOIN urls u ON u.id = v.url "
                    "WHERE v.visit_time > ? ORDER BY v.visit_time",
                    (int((since + _CHROME_EPOCH) * 1e6),),
                ).fetchall()
            finally:
                con.close()
        evs = []
        for vt, url, title in rows:
            if is_private(url, title or "", deny):
                continue
            u = urlsplit(url)
            # query strings routinely carry tokens and search terms: keep host + path only
            evs.append({"t": round(vt / 1e6 - _CHROME_EPOCH, 3), "src": name, "k": "visit", "browser": name,
                        "url": f"{u.scheme}://{u.netloc}{u.path}"[:300], "title": redact(title or "", extra)[:200]})
        store.replace_source(name, evs)
        out[name] = len(evs)
    return out


def git(since: float, cfg: dict | None = None) -> int:
    cfg = cfg or config.load()
    evs = []
    for repo in cfg["sources"]["git_repos"]:
        repo = config.expand(repo)
        r = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since=@{int(since)}", "--name-only", "--pretty=format:\x1e%H\x1f%at\x1f%s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        for chunk in r.stdout.split("\x1e")[1:]:
            head, _, files = chunk.partition("\n")
            sha, at, subject = head.split("\x1f", 2)
            evs.append({"t": float(at), "src": "git", "k": "commit", "repo": repo.name, "sha": sha[:10],
                        "subject": subject, "files": [f for f in files.split("\n") if f][:30]})
    store.replace_source("git", evs)
    return len(evs)


def _parse_time(s: str) -> float | None:
    s = s.strip()
    if re.fullmatch(r"\d{10}(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"\d{13}", s):
        return int(s) / 1000
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


_TXT_LINE = re.compile(r"^(\d{4}[-/]\d{1,2}[-/]\d{1,2} \d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)\s*$")


def chat_export(path: str, me: str, name: str = "wx", cfg: dict | None = None) -> int:
    """Import chat logs the user has exported themselves (WeChat/QQ/Slack exporters all produce
    one of these shapes). We deliberately do not read WeChat's encrypted local database.

      .csv / .jsonl : columns/keys  time, sender, text  [, peer]
      .txt          : "2026-10-12 09:30:01 Alice" header line, message body on following lines
    """
    cfg = cfg or config.load()
    extra, cap = cfg["privacy"]["redact_extra"], cfg["sources"]["msg_max_chars"]
    evs = []
    for f in ([Path(path)] if Path(path).is_file() else sorted(Path(path).rglob("*"))):
        peer = f.stem
        rows: list[tuple[float | None, str, str, str]] = []
        if f.suffix == ".csv":
            with open(f, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    r = {k.lower().strip(): v for k, v in r.items() if k}
                    rows.append((_parse_time(r.get("time") or r.get("strtime") or r.get("timestamp") or ""),
                                 r.get("sender") or r.get("nickname") or r.get("talker") or "",
                                 r.get("text") or r.get("content") or r.get("strcontent") or "", r.get("peer") or peer))
        elif f.suffix == ".jsonl":
            for r in store.iter_jsonl(f):
                rows.append((_parse_time(str(r.get("time", ""))), r.get("sender", ""), r.get("text", ""), r.get("peer", peer)))
        elif f.suffix == ".txt":
            cur = None
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _TXT_LINE.match(line)
                if m and _parse_time(m.group(1)):
                    cur = [_parse_time(m.group(1)), m.group(2), "", peer]
                    rows.append(cur)
                elif cur is not None:
                    cur[2] += line + "\n"
            rows = [tuple(r) for r in rows]
        for t, sender, text, pr in rows:
            if t is None or not str(text).strip():
                continue
            evs.append({"t": t, "src": name, "k": "msg", "peer": redact(str(pr), extra), "me": sender.strip() == me,
                        "text": redact(str(text).strip()[:cap], extra)})
    store.replace_source(name, evs)
    return len(evs)


def timelog(path: str, cfg: dict | None = None) -> int:
    """Time-tracker export -> win events. CSV with start/app/title columns (ManicTime, RescueTime, custom),
    or an ActivityWatch bucket export (.json)."""
    cfg = cfg or config.load()
    extra = cfg["privacy"]["redact_extra"]
    evs = []
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        buckets = data.get("buckets", {"_": data}) if isinstance(data, dict) else {"_": {"events": data}}
        for b in buckets.values():
            for e in b.get("events", []):
                t = _parse_time(e.get("timestamp", ""))
                d = e.get("data", {})
                if t and (d.get("app") or d.get("title")):
                    evs.append({"t": t, "src": "timelog", "k": "win", "app": d.get("app", ""), "title": redact(d.get("title", ""), extra),
                                "dur": e.get("duration")})
    else:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r = {k.lower().strip(): v for k, v in r.items() if k}
                t = _parse_time(r.get("start") or r.get("time") or r.get("timestamp") or "")
                if t:
                    evs.append({"t": t, "src": "timelog", "k": "win", "app": r.get("app") or r.get("process") or r.get("name") or "",
                                "title": redact(r.get("title") or r.get("activity") or r.get("notes") or "", extra)})
    store.replace_source("timelog", evs)
    return len(evs)
