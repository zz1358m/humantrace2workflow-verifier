"""Deterministic detectors for *off-mainline* behaviour — the part task mining throws away.

Mainline events say how the work was done (-> workflow). These say what the person would not
let pass (-> verifier). Detectors are deliberately high-recall and dumb: each hit is a
*candidate* with pointers into the trace; the distilling agent decides what it means.

Screen signals        crosscheck, lookup, undo_burst, paste_fix, ai_paste, pre_commit_review,
                      hesitation, rework, version_churn
Conversation signals  correction, abort, deny, verify_request, acceptance, respec, spec
Explicit              mark
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePath

AI_APPS = re.compile(r"chatgpt|claude|copilot|gemini|kimi|deepseek|豆包|通义|文心|perplexity|cursor|codex", re.I)

# Lexicons are candidates filters, not classifiers. Short messages right after an agent reply matter most.
_CORRECTION = re.compile(
    r"不对|不是这|错了|有问题|不行|重做|重新|别|不要|为什么(没|不)|怎么(没|还|又)|我说的是|没让你|你确定|搞错|漏了|少了|还是没|并没有|太长|太啰嗦|"
    r"\b(no[,.! ]|wrong|incorrect|not what|don't|do not|stop|revert|undo|why did(n't)? you|you (missed|forgot|broke)|that's not|still (fails|broken|wrong)|again)\b",
    re.I,
)
_VERIFY = re.compile(
    r"确定吗|验证|检查一下|核对|跑一下|跑通|测试|证据|来源|出处|截图|复现|对比|对照|有没有(跑|测|验)|真的|"
    r"\b(are you sure|verify|double[- ]check|prove|evidence|source|run the tests?|did you (run|test|check)|reproduce|show me)\b",
    re.I,
)
_ACCEPT = re.compile(r"^(好的?|可以|行|不错|很好|完美|ok(ay)?|lgtm|great|perfect|nice|thanks|谢谢|就这样|没问题|继续|go ahead|ship it)[\s,.!，。！]*", re.I)
_SPEC = re.compile(r"硬性约束|必须停下|不得|产出|预算|上限|验收|阶段\s*\d|must not|hard constraint|acceptance|deliverable|budget", re.I)


def title_key(app: str, title: str) -> str:
    t = re.sub(r"^[●*•\s]+|\s*[-—–]\s*[^-—–]*$", "", title or "") if app else title
    return f"{app.lower()}|{t.strip().lower()}"


def build_spans(events: list[dict], episode_gap: float) -> list[dict]:
    """Collapse the event stream into focus spans carrying their input activity."""
    spans: list[dict] = []
    cur = None
    for ev in events:
        k = ev["k"]
        if k == "win":
            if cur:  # no input for a long stretch means the person left, even if no idle event says so
                cur["t1"] = ev["t"] if ev["t"] - cur["last"] <= episode_gap else cur["last"] + 60
            cur = {"t0": ev["t"], "t1": ev["t"] + (ev.get("dur") or 0), "app": ev.get("app", ""), "title": ev.get("title", ""),
                   "last": ev["t"], "typed": 0, "bs": 0, "keys": [], "clicks": 0, "scroll": [], "clips": [], "files": [], "shots": [], "bursts": []}
            spans.append(cur)
            continue
        if cur is None or ev.get("src", "").split(":")[0] not in ("screen", "video", "synth"):
            continue
        cur["t1"] = max(cur["t1"], ev.get("t1", ev["t"]))
        cur["last"] = cur["t1"]
        if k == "type":
            cur["typed"] += ev["n"]
            cur["bs"] += ev.get("bs", 0)
            cur["bursts"].append(ev)
        elif k == "key":
            cur["keys"].append(ev)
        elif k == "click":
            cur["clicks"] += ev["n"]
        elif k == "scroll":
            cur["scroll"].append(ev)
        elif k == "clip":
            cur["clips"].append(ev)
        elif k == "file":
            cur["files"].append(ev)
        elif k == "shot":
            cur["shots"].append(ev)
        elif k == "idle":
            cur["t1"] = min(cur["t1"], ev["t"]) if ev["t"] > cur["t0"] else cur["t1"]
    ep = 0
    for i, s in enumerate(spans):
        if i and s["t0"] - spans[i - 1]["t1"] > episode_gap:
            ep += 1
        s["ep"] = ep
        s["key"] = title_key(s["app"], s["title"])
        s["dur"] = max(0.0, s["t1"] - s["t0"])
    return spans


def _combos(span, combo):
    return [k for k in span["keys"] if k["combo"] == combo]


def _sig(kind, t0, t1, **f):
    return {"kind": kind, "t0": round(t0, 3), "t1": round(t1, 3), **f}


def screen_signals(spans: list[dict], events: list[dict], cc: dict) -> list[dict]:
    out = []
    # crosscheck / lookup: A -> B -> A with a short, typing-free stay in B
    for a, b, a2 in zip(spans, spans[1:], spans[2:]):
        if a["key"] == a2["key"] and b["key"] != a["key"] and b["dur"] <= cc["glance_max_s"] and b["typed"] <= 5 and b["dur"] >= 1.5:
            worked = a["typed"] + a2["typed"] > 0 or _combos(a, "ctrl+v") or _combos(a2, "ctrl+v")
            if not worked:
                continue
            transferred = bool(b["clips"]) and bool(_combos(a2, "ctrl+v"))
            out.append(_sig("lookup" if transferred else "crosscheck", b["t0"], b["t1"], work=a["title"], work_app=a["app"],
                            consulted=b["title"], consulted_app=b["app"], dwell=round(b["dur"], 1),
                            shot=(b["shots"] or [{}])[0].get("path"),
                            note="copied data back" if transferred else "looked, changed nothing there, returned"))
    last_clip_src = None  # (span) where the clipboard was last filled
    for s in spans:
        # undo bursts
        z = _combos(s, "ctrl+z")
        i = 0
        while i < len(z):
            j = i
            while j + 1 < len(z) and z[j + 1]["t"] - z[j]["t"] <= 15:
                j += 1
            if j - i + 1 >= 2:
                retyped = sum(b["n"] for b in s["bursts"] if z[j]["t"] < b["t"] <= z[j]["t"] + 60)
                out.append(_sig("undo_burst", z[i]["t"], z[j]["t"], app=s["app"], title=s["title"], n=j - i + 1, retyped_after=retyped))
            i = j + 1
        # paste then fix / AI output handling
        for v in _combos(s, "ctrl+v"):
            after = [b for b in s["bursts"] if v["t"] <= b["t"] <= v["t"] + 45]
            bs = sum(b.get("bs", 0) for b in after)
            typed = sum(b["n"] for b in after)
            undone = any(v["t"] < u["t"] <= v["t"] + 45 for u in z)
            from_ai = last_clip_src is not None and AI_APPS.search(f"{last_clip_src['app']} {last_clip_src['title']}")
            if from_ai:
                verdict = "rejected" if undone else "edited" if bs >= 5 or typed >= 20 else "accepted"
                out.append(_sig("ai_paste", v["t"], v["t"] + 45, app=s["app"], title=s["title"], source=last_clip_src["title"],
                                verdict=verdict, deleted=bs, typed_after=typed))
            elif undone or bs >= 5:
                out.append(_sig("paste_fix", v["t"], v["t"] + 45, app=s["app"], title=s["title"],
                                source=last_clip_src["title"] if last_clip_src else None, deleted=bs, undone=undone))
        if s["clips"]:
            last_clip_src = s
        # pre-commit review & hesitation
        for c in s["keys"]:
            if c["combo"] not in ("ctrl+s", "ctrl+enter", "ctrl+p", "ctrl+shift+s"):
                continue
            w0 = c["t"] - 120
            scrolls = [x for x in s["scroll"] if w0 <= x["t"] <= c["t"]]
            typing = [b for b in s["bursts"] if w0 <= b["t"] <= c["t"]]
            last_typing = max((b.get("t1", b["t"]) for b in typing), default=max(w0, s["t0"]))
            review = [x for x in scrolls if x["t"] >= last_typing]
            if len(review) >= 2 and c["t"] - last_typing >= 8:
                out.append(_sig("pre_commit_review", last_typing, c["t"], app=s["app"], title=s["title"], commit=c["combo"],
                                seconds=round(c["t"] - last_typing, 1), scrolls=sum(x["n"] for x in review)))
            elif c["combo"] == "ctrl+enter":
                last_input = max([x.get("t1", x["t"]) for x in s["bursts"] + s["scroll"] if x["t"] < c["t"]] + [s["t0"]])
                if c["t"] - last_input >= 15:
                    out.append(_sig("hesitation", last_input, c["t"], app=s["app"], title=s["title"], seconds=round(c["t"] - last_input, 1)))
    # rework: same file saved again after the person had moved on
    by_path = defaultdict(list)
    for ev in events:
        if ev["k"] == "file" and ev.get("op") != "deleted":
            by_path[ev["path"]].append(ev)
    wins = [e["t"] for e in events if e["k"] == "win"]
    for path, saves in by_path.items():
        for p, q in zip(saves, saves[1:]):
            gap = q["t"] - p["t"]
            left = sum(1 for t in wins if p["t"] < t < q["t"]) >= 2
            if cc["rework_min_gap_s"] <= gap <= cc["rework_max_gap_s"] and left and p.get("sha") != q.get("sha"):
                out.append(_sig("rework", p["t"], q["t"], path=path, gap_min=round(gap / 60, 1), rejected_sha=p.get("sha"), kept_sha=q.get("sha"),
                                note="earlier save was not good enough for its author: rejected/accepted pair"))
    # version churn: report.docx, report_v2.docx, report_final.docx ...
    stems = defaultdict(set)
    for path in by_path:
        pp = PurePath(path)
        stem = re.sub(r"(?:[-_ (（]+(?:v\d+|final|最终版?|终稿|改\d*|修订|副本|copy|\d{1,2})[)）]?)+$", "", pp.stem, flags=re.I)
        stems[(str(pp.parent), stem.lower(), pp.suffix.lower())].add(pp.name)
    for (parent, stem, _), names in stems.items():
        if len(names) >= 2 and stem:
            ts = [e["t"] for p in by_path for e in by_path[p] if PurePath(p).name in names and str(PurePath(p).parent) == parent]
            out.append(_sig("version_churn", min(ts), max(ts), dir=parent, versions=sorted(names)))
    return out


def conversation_signals(events: list[dict]) -> list[dict]:
    out = []
    by_session = defaultdict(list)
    for ev in events:
        if ev["k"] in ("prompt", "reply", "abort", "deny"):
            by_session[(ev.get("agent"), ev.get("session"))].append(ev)
    for (agent, sid), evs in by_session.items():
        prev_reply = None
        n_prompt = 0
        for ev in evs:
            base = {"agent": agent, "session": sid}
            if ev["k"] == "reply":
                prev_reply = ev
            elif ev["k"] == "abort":
                out.append(_sig("abort", ev["t"], ev["t"], **base, note="user interrupted the agent mid-turn"))
            elif ev["k"] == "deny":
                out.append(_sig("deny", ev["t"], ev["t"], **base, tool=ev.get("tool"), note="user refused a tool call"))
            elif ev["k"] == "prompt":
                n_prompt += 1
                text = ev.get("text", "")
                head = text[:400]
                quote = text[:240]
                if n_prompt == 1 or len(text) > 1500:
                    if _SPEC.search(text):
                        out.append(_sig("spec", ev["t"], ev["t"], **base, chars=len(text), quote=quote,
                                        note="user-authored task spec: explicit constraints / deliverables / stop conditions"))
                    continue
                if prev_reply is None:
                    continue
                if _CORRECTION.search(head):
                    out.append(_sig("correction", prev_reply["t"], ev["t"], **base, quote=quote,
                                    after_tools=prev_reply.get("tools", [])[-5:], latency_s=round(ev["t"] - prev_reply["t"], 1)))
                elif _VERIFY.search(head):
                    out.append(_sig("verify_request", prev_reply["t"], ev["t"], **base, quote=quote,
                                    note="user asked for proof/checking instead of taking the result on trust"))
                elif _ACCEPT.match(head) and len(text) < 200:
                    out.append(_sig("acceptance", prev_reply["t"], ev["t"], **base, quote=quote, latency_s=round(ev["t"] - prev_reply["t"], 1)))
                else:
                    out.append(_sig("respec", prev_reply["t"], ev["t"], **base, quote=quote))
    return out


def detect(events: list[dict], spans: list[dict], cc: dict) -> list[dict]:
    sigs = screen_signals(spans, events, cc) + conversation_signals(events)
    sigs += [_sig("mark", e["t"], e["t"], text=e.get("text", "")) for e in events if e["k"] == "mark"]
    sigs.sort(key=lambda s: s["t0"])
    for i, s in enumerate(sigs):
        s["id"] = f"S{i + 1:03d}"
    return sigs
