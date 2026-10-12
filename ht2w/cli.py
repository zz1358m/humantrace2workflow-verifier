from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config, store


def _since(a) -> float:
    if a.since:
        return datetime.strptime(a.since, "%Y-%m-%d").timestamp()
    return time.time() - a.days * 86400


def _days(a) -> list[str] | None:
    if getattr(a, "day", None):
        return a.day
    n = getattr(a, "last", None)
    return store.days()[-n:] if n else None


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="ht2w", description="Compile personal (workflow, verifier) skills from computer-use traces.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the data dir and a default config.yaml")
    p = sub.add_parser("record", help="record screen activity live (Ctrl+C to stop)")
    p.add_argument("--seconds", type=float)
    p.add_argument("--no-shots", action="store_true")
    p.add_argument("--watch", action="append", default=[], help="dir whose file saves are versioned (repeatable)")
    p = sub.add_parser("mark", help="drop an explicit note into the trace (e.g. what was wrong just now)")
    p.add_argument("text")

    p = sub.add_parser("setup", help="open the local questionnaire: connect servers, tick sources, start the analysis")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--token", help=argparse.SUPPRESS)
    p = sub.add_parser("sources", help="list data sources and set which ones may be read")
    p.add_argument("--ask", action="store_true", help="go through the sources one by one")
    p.add_argument("--allow", action="append", default=[], metavar="ID")
    p.add_argument("--deny", action="append", default=[], metavar="ID")
    p.add_argument("--add-host", action="append", default=[], metavar="USER@HOST", help="a server reachable by key-based ssh")
    p.add_argument("--add-doc-dir", action="append", default=[], metavar="DIR")
    p.add_argument("--wx-export", metavar="PATH", help="chat logs you exported yourself")
    p.add_argument("--wx-me", metavar="NAME", help="your display name in that export")
    p = sub.add_parser("run", help="collect allowed sources -> compile -> distill, in one go")
    p.add_argument("--days", type=float, default=1.0)
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--backend")
    p.add_argument("--model")

    p = sub.add_parser("collect", help="import a non-live source into the trace store")
    cs = p.add_subparsers(dest="source", required=True)
    for name, hlp in (("agents", "Claude Code + Codex conversation logs"), ("browser", "Chrome / Edge history"), ("git", "commits in sources.git_repos"),
                      ("all", "agents + browser + git"), ("allowed", "every source you allowed in `ht2w sources`")):
        q = cs.add_parser(name, help=hlp)
        q.add_argument("--days", type=float, default=1.0)
        q.add_argument("--since", help="YYYY-MM-DD (overrides --days)")
    q = cs.add_parser("video", help="screen recording -> keyframes")
    q.add_argument("path")
    q.add_argument("--start", help="wall-clock time of first frame, 'YYYY-MM-DD HH:MM:SS' (default: file mtime - duration)")
    q.add_argument("--every", type=float, default=2.0)
    q = cs.add_parser("chat", help="exported chat logs (WeChat etc.): .csv/.jsonl/.txt file or folder")
    q.add_argument("path")
    q.add_argument("--me", required=True, help="your display name in the export")
    q.add_argument("--name", default="wx")
    q = cs.add_parser("timelog", help="time-tracker export (.csv or ActivityWatch .json)")
    q.add_argument("path")

    p = sub.add_parser("compile", help="events -> signals.jsonl + day.md")
    p.add_argument("day", nargs="*")
    p.add_argument("--last", type=int, default=1)
    p = sub.add_parser("distill", help="open agent sessions: profile the person, then build one skill per task")
    p.add_argument("day", nargs="*")
    p.add_argument("--last", type=int, default=1, help="use the last N recorded days")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--task", action="append", help="build only this task (repeatable)")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--skip-profile", action="store_true")
    for name in ("backend", "model"):
        p.add_argument(f"--{name}")
    sub.add_parser("tasks", help="list task candidates found by the profile session")
    sub.add_parser("skills", help="list built skills")

    p = sub.add_parser("lint", help="check a skill's structure and its verifier against labelled cases")
    p.add_argument("skill")
    p.add_argument("--proposed", action="store_true")
    p = sub.add_parser("verify", help="run a skill's verifier on an output dir (checks only)")
    p.add_argument("skill")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("install", help="copy a self-contained skill into Claude Code / Codex")
    p.add_argument("skill")
    p.add_argument("--to", default="claude", help="claude | codex | any directory")
    p = sub.add_parser("optimize", help="fix the verifier, improve the workflow on replayed cases")
    p.add_argument("skill")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--no-judge", action="store_true")
    p = sub.add_parser("shadow", help="run the skill on an input next to the human's own result")
    p.add_argument("skill")
    p.add_argument("--input", required=True)
    p.add_argument("--human", help="dir with what the person actually produced")
    p.add_argument("--no-judge", action="store_true")
    p = sub.add_parser("feedback", help="record the person's verdict on a run")
    p.add_argument("run")
    p.add_argument("label", choices=["accept", "reject"])
    p.add_argument("--note", default="")
    p = sub.add_parser("evolve", help="propose a verifier update from feedback (does not take effect)")
    p.add_argument("skill")
    p = sub.add_parser("approve", help="make the proposed verifier live")
    p.add_argument("skill")
    p = sub.add_parser("eval", help="verifier/person agreement and acceptance curve")
    p.add_argument("skill")
    p.add_argument("--verifier", help="someone else's or a generic verifier.yaml (coupling control)")
    p = sub.add_parser("synth", help="write a synthetic demo day (for trying the pipeline without recording)")
    p.add_argument("--day", default="2026-01-05")
    sub.add_parser("status", help="what has been collected, built and spent")
    p = sub.add_parser("forget", help="delete a day's trace")
    p.add_argument("day")

    a = ap.parse_args(argv)
    cfg = config.load()
    config.init_home()

    if a.cmd == "init":
        print(config.home())
    elif a.cmd == "record":
        from .sources.screen import Recorder

        cfg["screen"]["screenshots"] = cfg["screen"]["screenshots"] and not a.no_shots
        cfg["screen"]["watch_dirs"] = cfg["screen"]["watch_dirs"] + a.watch
        print(f"recording to {config.home() / 'traces'} — keystroke content is never stored. Ctrl+C to stop.")
        Recorder(cfg).run(a.seconds)
    elif a.cmd == "mark":
        w = store.Writer()
        w.emit("user", "mark", text=a.text)
        w.close()
    elif a.cmd == "setup":
        from . import setup_ui

        setup_ui.serve(a.port, not a.no_browser, a.token)
    elif a.cmd == "sources":
        from . import consent

        for h in a.add_host:
            consent.set_config(["sources", "ssh_hosts"], h, append=True)
        for d in a.add_doc_dir:
            consent.set_config(["sources", "doc_dirs"], d, append=True)
        if a.wx_export:
            consent.set_config(["sources", "wx_export"], a.wx_export)
        if a.wx_me:
            consent.set_config(["sources", "wx_me"], a.wx_me)
        cfg = config.load()
        if a.allow or a.deny:
            consent.decide({**{i: "allow" for i in a.allow}, **{i: "deny" for i in a.deny}})
        if a.ask:
            consent.ask(cfg)
        for line in consent.status_lines(cfg):
            print(line)
    elif a.cmd == "run":
        from . import collect, distill
        from .compile import compile_day

        for k in ("backend", "model"):
            if getattr(a, k):
                cfg["agent"][k] = getattr(a, k)
        since = time.time() - a.days * 86400
        rep = {"collect": collect.collect_allowed(since, cfg)}
        days = [d for d in store.days() if d >= store.day_of(since)]
        rep["compile"] = [compile_day(d, cfg) for d in days]
        rep["distill"] = distill.distill(days, a.top, None, a.parallel, False, cfg)
        _print(rep)
    elif a.cmd == "collect":
        from .sources import agents, misc, video

        if a.source == "allowed":
            from . import collect

            _print(collect.collect_allowed(_since(a), cfg))

        if a.source in ("agents", "all"):
            _print({"agents": agents.collect(_since(a), cfg)})
        if a.source in ("browser", "all"):
            _print({"browser": misc.browsers(_since(a), cfg)})
        if a.source in ("git", "all"):
            _print({"git": misc.git(_since(a), cfg)})
        if a.source == "video":
            start = datetime.strptime(a.start, "%Y-%m-%d %H:%M:%S").timestamp() if a.start else None
            _print({"keyframes": video.ingest(a.path, start, a.every)})
        if a.source == "chat":
            _print({"messages": misc.chat_export(a.path, a.me, a.name, cfg)})
        if a.source == "timelog":
            _print({"spans": misc.timelog(a.path, cfg)})
    elif a.cmd == "compile":
        from .compile import compile_day

        for d in a.day or store.days()[-a.last:]:
            _print(compile_day(d, cfg))
    elif a.cmd == "distill":
        from . import distill

        for k in ("backend", "model"):
            if getattr(a, k):
                cfg["agent"][k] = getattr(a, k)
        _print(distill.distill(_days(a), a.top, a.task, a.parallel, a.skip_profile, cfg))
    elif a.cmd == "tasks":
        from . import distill

        for t in distill.tasks():
            print(f"{t.get('score', '?'):>4}  {t['name']:<32} {t.get('title', '')}")
    elif a.cmd == "skills":
        from . import verifier

        root = config.home() / "skills"
        for d in sorted(root.iterdir()):
            if (d / "verifier.yaml").exists():
                v = verifier.load(d)
                layers = {}
                for i in v["items"]:
                    layers[i.get("layer")] = layers.get(i.get("layer"), 0) + 1
                print(f"{d.name:<32} v{v.get('version', '?')}  " + "  ".join(f"{k}:{n}" for k, n in layers.items()))
    elif a.cmd == "lint":
        from . import loop

        res = loop.lint(a.skill, a.proposed)
        _print(res)
        return 0 if res["ok"] else 1
    elif a.cmd == "verify":
        from . import loop, verifier

        rep = verifier.run(loop.skill_dir(a.skill), Path(a.output), Path(a.input))
        print(verifier.render(rep))
        return 0 if rep["verdict"] == "accept" else 1
    elif a.cmd in ("install", "optimize", "shadow", "feedback", "evolve", "approve", "eval"):
        from . import loop

        if a.cmd == "install":
            print(loop.install(a.skill, a.to))
        elif a.cmd == "optimize":
            _print(loop.optimize(a.skill, a.rounds, not a.no_judge, cfg))
        elif a.cmd == "shadow":
            _print(loop.shadow(a.skill, Path(a.input), Path(a.human) if a.human else None, not a.no_judge, cfg))
        elif a.cmd == "feedback":
            _print(loop.feedback(a.run, a.label, a.note))
        elif a.cmd == "evolve":
            r = loop.evolve(a.skill, cfg)
            print(r.text)
        elif a.cmd == "approve":
            print(loop.approve(a.skill))
        elif a.cmd == "eval":
            _print(loop.evaluate(a.skill, a.verifier))
    elif a.cmd == "synth":
        from . import synth

        _print(synth.write(a.day))
    elif a.cmd == "status":
        from . import agent

        h = config.home()
        _print({"home": str(h), "days": store.days(), "skills": sorted(d.name for d in (h / "skills").iterdir() if d.is_dir()),
                "sessions": len(list((h / "sessions").iterdir())), "spent_usd": round(agent.spent(), 4), "budget_usd": cfg["agent"]["budget_usd"]})
    elif a.cmd == "forget":
        import shutil

        d = config.home() / "traces" / a.day
        if d.exists():
            shutil.rmtree(d)
            print(f"deleted {d}")
    return 0
