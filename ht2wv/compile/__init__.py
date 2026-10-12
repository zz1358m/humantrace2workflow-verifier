"""events.jsonl -> signals.jsonl + day.md (the compact, greppable view a coding agent starts from)."""
from __future__ import annotations

import json
from collections import Counter

from .. import config, store
from .signals import build_spans, detect

_ICON = {"prompt": "🧑→🤖", "reply": "🤖", "abort": "⛔", "deny": "🚫", "visit": "🌐", "msg": "💬", "commit": "📦", "mark": "📌", "file": "💾", "cmd": "⌨", "open": "📂"}


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _span_line(s: dict) -> str:
    bits = []
    if s["typed"]:
        bits.append(f"typed {s['typed']}" + (f" ⌫{s['bs']}" if s["bs"] else ""))
    combos = Counter(k["combo"] for k in s["keys"])
    bits += [f"{c}×{n}" if n > 1 else c for c, n in combos.most_common(6)]
    if s["scroll"]:
        bits.append(f"scroll {sum(x['n'] for x in s['scroll'])}")
    if s["clips"]:
        c = s["clips"][-1]
        bits.append(f"copied {c['n']}ch" + (f" “{_clip(c['preview'], 40)}”" if c.get("preview") else ""))
    line = f"- {store.hms(s['t0'])} +{int(s['dur'])}s **{s['app']}** — {_clip(s['title'], 80)}"
    if bits:
        line += f"  [{', '.join(bits)}]"
    if s["shots"]:
        line += f"  📷 {s['shots'][0]['path']}"
    return line


def _event_line(e: dict) -> str | None:
    k, ts = e["k"], store.hms(e["t"])
    ic = _ICON.get(k, "")
    if k == "prompt":
        return f"- {ts} {ic} [{e['agent']}:{e['session']}] {_clip(e['text'], 300)}"
    if k == "reply":
        tools = Counter(e.get("tools", []))
        t = ", ".join(f"{n}×{c}" for n, c in tools.most_common(5))
        return f"- {ts} {ic} [{e['agent']}:{e['session']}] {_clip(e.get('text', ''), 160)}" + (f"  (tools: {t})" if t else "")
    if k in ("abort", "deny"):
        return f"- {ts} {ic} [{e['agent']}:{e['session']}] {k}" + (f" {e.get('tool', '')}" if k == "deny" else "")
    if k == "visit":
        return f"- {ts} {ic} {_clip(e.get('title', ''), 70)} <{_clip(e['url'], 90)}>"
    if k == "msg":
        return f"- {ts} {ic} {'me' if e.get('me') else e.get('peer', '?')}→ {_clip(e['text'], 160)}"
    if k == "commit":
        return f"- {ts} {ic} {e['repo']} {e['sha']} {_clip(e['subject'], 100)} ({len(e.get('files', []))} files)"
    if k == "mark":
        return f"- {ts} {ic} MARK: {e.get('text', '')}"
    if k == "cmd":
        return f"- {'~' if e.get('undated') else ''}{ts} {ic} [{e['host']}] {_clip(e['cmd'], 200)}"
    if k == "open":
        return f"- {ts} {ic} opened {_clip(e['name'], 100)}"
    if k == "file":
        return f"- {ts} {ic} {e['op']} {e['path']}" + (f"  blob:{e['sha']}" if e.get("sha") else "")
    return None


def compile_day(day: str, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    cc = cfg["compile"]
    events = store.read_events(day)
    if not events:
        raise SystemExit(f"no events for {day}")
    spans = build_spans(events, cc["episode_gap_s"])
    sigs = detect(events, spans, cc)
    d = config.day_dir(day)
    with open(d / "signals.jsonl", "w", encoding="utf-8") as f:
        for s in sigs:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # timeline rows: focus spans (pass-through alt-tabs dropped, repeats merged) + discrete events + standalone frames
    rows: list[tuple[float, str]] = []
    prev = None
    for s in spans:
        active = s["typed"] or s["keys"] or s["clips"] or s["files"]
        if s["dur"] < 1.5 and not active:
            continue
        if prev and prev["key"] == s["key"] and not active and not (prev["typed"] or prev["keys"]):
            continue
        rows.append((s["t0"], _span_line(s)))
        prev = s
    visits_seen = set()
    for e in events:
        if e["k"] == "visit":
            key = (e["url"], int(e["t"] // 300))
            if key in visits_seen:
                continue
            visits_seen.add(key)
        line = _event_line(e)
        if line:
            rows.append((e["t"], line))
    if not spans:
        rows += [(e["t"], f"- {store.hms(e['t'])} 📷 {e['path']}") for e in events if e["k"] == "shot"]
    rows += [(s["t0"], f"- {store.hms(s['t0'])} ⚑ **{s['kind']}** `{s['id']}` " +
              _clip(json.dumps({k: v for k, v in s.items() if k not in ('kind', 'id', 't0', 't1')}, ensure_ascii=False), 260)) for s in sigs]
    rows.sort(key=lambda r: r[0])

    kinds = Counter(s["kind"] for s in sigs)
    srcs = Counter(e["src"].split(":")[0] for e in events)
    out = [f"# Trace digest {day}", "",
           f"- events: {len(events)}  (" + ", ".join(f"{k} {v}" for k, v in srcs.most_common()) + ")",
           f"- span: {store.hms(events[0]['t'])} – {store.hms(events[-1]['t'])}",
           "- off-mainline signals: " + (", ".join(f"{k} {v}" for k, v in kinds.most_common()) or "none"),
           "", "Raw data: `events.jsonl` (everything), `signals.jsonl` (⚑ rows in full), `shots/` (frames), `blobs/` (file versions by sha).",
           "⚑ rows are heuristic candidates, not conclusions. ⌨ rows with a `~` time come from history files without timestamps: "
           "their order is real, their time is not.", ""]
    hour = None
    for t, line in rows:
        h = store.hms(t)[:2]
        if h != hour:
            hour = h
            out += ["", f"## {h}:00"]
        out.append(line)
    (d / "day.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"day": day, "events": len(events), "spans": len(spans), "signals": dict(kinds), "digest": str(d / "day.md")}
