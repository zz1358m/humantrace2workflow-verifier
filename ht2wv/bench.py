"""Synthetic samples: a pre-filled personal style conditions the records; the pipeline must recover it.

A sample (sample.yaml + checklist/*.py) holds
  purpose, checklist   what the person wants done and how they will tick it off   -> visible to the pipeline (request.md)
  style                the person's standards, written down before any data exists -> HIDDEN; it is the answer key
  records, workdir     access records and files generated under that style        -> rendered into each source's native format
  task                 a held-out instance, with the output this person would keep -> input visible, reference hidden

Two scores come out:
  checklist   the built skill is executed on the held-out input; how many checklist items its output passes
  style       for every style item, the reference output is broken in exactly that one way; the built
              verifier covers the item if it fails the broken output on something it passes on the reference
Rounds feed checklist failures back (the person would say them out loud). Style misses are never fed back.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from . import agent, config, distill, loop, store, verifier
from .compile import compile_day
from .sources import agents, extra, misc

_CHROME_EPOCH = 11644473600
SOURCES = ("claude", "codex", "shell", "browser", "chat")


def load(sample_dir: Path) -> dict:
    s = yaml.safe_load((Path(sample_dir) / "sample.yaml").read_text(encoding="utf-8"))
    s["_dir"] = Path(sample_dir).resolve()
    task = s.get("task") or {}
    for key, src in (("input", "input_dir"), ("reference_output", "reference_dir")):  # larger tasks keep their files on disk
        if task.get(src):
            task[key] = _read_tree(s["_dir"] / task[src])
    return s


def _read_tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def _t(at: str) -> float:
    return datetime.strptime(str(at), "%Y-%m-%d %H:%M:%S").timestamp()


def _iso(at: str) -> str:
    return datetime.fromtimestamp(_t(at)).astimezone().isoformat()


def validate(sample: dict) -> list[str]:
    """Structural checks, plus the one that matters: every style item must leave a trace in the records,
    otherwise no pipeline could recover it and the sample is unfair."""
    errs = []
    week = bool(sample.get("week"))
    for key in ("id", "purpose", "rubric", "style", "records", "week" if week else "task"):
        if not sample.get(key):
            errs.append(f"missing {key}")
    if errs:
        return errs
    tagged: dict[str, set] = {}
    rec = sample["records"]

    def tag(src, entry):
        for sid in entry.get("from") or []:
            tagged.setdefault(sid, set()).add(src)

    for kind in ("claude", "codex"):
        for sess in rec.get(kind) or []:
            for turn in sess.get("turns", []):
                tag(kind, turn)
    for kind in ("shell", "browser", "chat"):
        for e in rec.get(kind) or []:
            tag(kind, e)
    ids = [s["id"] for s in sample["style"]]
    for sid in ids:
        if sid not in tagged:
            errs.append(f"style {sid} conditions no record (tag at least one record with from: [{sid}])")
    for sid in tagged:
        if sid not in ids:
            errs.append(f"records reference unknown style id {sid}")
    for st in sample["style"]:
        p = st.get("probe")
        ref = day_reference(sample, st.get("day", 1)) if week else sample["task"].get("reference_output") or {}
        if p and "dir" in p and not (sample["_dir"] / p["dir"]).is_dir():
            errs.append(f"style {st['id']}: probe dir {p['dir']} not found")
        elif p and "dir" not in p and p.get("file") not in ref:
            errs.append(f"style {st['id']}: probe file {p.get('file')} is not in task.reference_output")
        elif p:
            if _apply_probe(ref, p, sample["_dir"]) == ref:
                errs.append(f"style {st['id']}: probe does not change the reference output")
    if not (sample["_dir"] / "rubric.py").exists():
        errs.append("rubric.py not found next to sample.yaml")
    return errs


# ---- render records into each interface's native format ----
def render(sample: dict, out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    rec = sample["records"]
    for sess in rec.get("claude") or []:
        f = out / "claude" / "project" / f"{sess['session']}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        base = {"cwd": sess.get("cwd", ""), "sessionId": sess["session"], "isSidechain": False}
        for i, t in enumerate(sess["turns"]):
            ts = _iso(t["at"])
            if "user" in t:
                rows.append({**base, "type": "user", "timestamp": ts, "message": {"role": "user", "content": t["user"]}})
            elif "assistant" in t:
                blocks = [{"type": "tool_use", "id": f"tu{i}_{j}", "name": n, "input": {}} for j, n in enumerate(t.get("tools") or [])]
                blocks.append({"type": "text", "text": t["assistant"]})
                rows.append({**base, "type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": blocks}})
            elif t.get("abort"):
                rows.append({**base, "type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}})
            elif t.get("deny"):
                rows.append({**base, "type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": f"tu{i}", "name": t["deny"], "input": {}}]}})
                rows.append({**base, "type": "user", "timestamp": ts, "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"tu{i}", "is_error": True,
                     "content": "The user doesn't want to proceed with this tool use. The tool use was rejected."}]}})
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    for sess in rec.get("codex") or []:
        day = str(sess["turns"][0]["at"])[:10].split("-")
        f = out / "codex" / day[0] / day[1] / day[2] / f"rollout-{sess['session']}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"timestamp": _iso(sess["turns"][0]["at"]), "type": "session_meta", "payload": {"cwd": sess.get("cwd", "")}}]
        for t in sess["turns"]:
            ts = _iso(t["at"])
            if "user" in t:
                rows.append({"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t["user"]}]}})
            elif "assistant" in t:
                rows += [{"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": n}} for n in t.get("tools") or []]
                rows.append({"timestamp": ts, "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": t["assistant"]}})
            elif t.get("abort"):
                rows.append({"timestamp": ts, "type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}})
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    by_host: dict[str, list] = {}
    for e in rec.get("shell") or []:
        by_host.setdefault(e.get("host", "local"), []).append(e)
    for host, es in by_host.items():
        f = out / "shell" / f"{host}.bash_history"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(f"#{int(_t(e['at']))}\n{e['cmd']}\n" for e in sorted(es, key=lambda e: _t(e["at"]))), encoding="utf-8")
    if rec.get("browser"):
        f = out / "browser" / "History"
        f.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(f)
        con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
        con.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
        for i, e in enumerate(rec["browser"], 1):
            con.execute("INSERT INTO urls VALUES (?,?,?)", (i, e["url"], e.get("title", "")))
            con.execute("INSERT INTO visits VALUES (?,?,?)", (i, i, int((_t(e["at"]) + _CHROME_EPOCH) * 1e6)))
        con.commit()
        con.close()
    if rec.get("chat"):
        f = out / "chat" / "export.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "sender", "text", "peer"])
            for e in rec["chat"]:
                w.writerow([e["at"], e["sender"], e["text"], e.get("peer", "")])
    return out


def _times(sample: dict) -> list[float]:
    rec, ts = sample["records"], []
    for kind in ("claude", "codex"):
        ts += [_t(t["at"]) for s in rec.get(kind) or [] for t in s["turns"]]
    for kind in ("shell", "browser", "chat"):
        ts += [_t(e["at"]) for e in rec.get(kind) or []]
    return ts


def ingest(sample: dict, records: Path, cfg: dict) -> dict:
    """Read the rendered files back through the real collectors, exactly as they would read a user's machine."""
    since = min(_times(sample)) - 1
    cfg["sources"]["claude_dir"] = str(records / "claude")
    cfg["sources"]["codex_dir"] = str(records / "codex")
    cfg["sources"]["browsers"] = {"chrome": str(records / "browser" / "History")}
    out = {"agents": {k: v for k, v in agents.collect(since, cfg).items() if k != "parse"}}
    out["browser"] = misc.browsers(since, cfg)
    if (records / "chat" / "export.csv").exists():
        out["chat"] = misc.chat_export(str(records / "chat" / "export.csv"), sample.get("persona", {}).get("name", ""), "wx", cfg)
    for f in sorted((records / "shell").glob("*.bash_history")) if (records / "shell").exists() else []:
        host = f.name.removesuffix(".bash_history")
        evs = extra.parse_history(f.read_text(encoding="utf-8"), f.stat().st_mtime, host, since, 300, [])
        store.replace_source(f"shell@{host}", evs, since)
        out[f"shell@{host}"] = len(evs)
    return out


def prepare(sample: dict, home: Path) -> dict:
    """Build a fresh data root for this sample: rendered records ingested, the visible request, the work dir."""
    if home.exists():
        shutil.rmtree(home)
    os.environ["HT2WV_HOME"] = str(home)
    config.init_home()
    cfg = config.load()
    records = render(sample, home / "records")
    counts = ingest(sample, records, cfg)
    lines = [f"# 本人的要求\n\n{sample['purpose'].strip()}\n\n## Rubric（本人会逐条勾的验收清单）\n"]
    lines += [f"- `{c['id']}` {c['claim']}" for c in sample["rubric"]]
    (home / "request.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, content in (sample.get("workdir") or {}).items():
        p = home / "workdir" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    days = [d for d in store.days()]
    compiled = [compile_day(d, cfg) for d in days]
    return {"home": str(home), "ingested": counts, "days": days, "signals": {c["day"]: c["signals"] for c in compiled}}


# ---- scoring ----
def _write_tree(root: Path, files: dict):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")


def _apply_probe(ref: dict, p: dict, sample_dir: Path | None = None) -> dict:
    if "dir" in p:  # a whole alternative run: the same day done again with one rule broken
        return _read_tree(Path(sample_dir) / p["dir"])
    out = dict(ref)
    text = out[p["file"]]
    if "set" in p:
        text = p["set"]
    if "replace" in p:
        text = text.replace(p["replace"][0], p["replace"][1])
    if "regex" in p:
        text = re.sub(p["regex"][0], p["regex"][1], text)
    if "remove_line" in p:
        text = "\n".join(ln for ln in text.split("\n") if p["remove_line"] not in ln)
    if "append" in p:
        text = text.rstrip("\n") + "\n" + p["append"] + "\n"
    out[p["file"]] = text
    if "rename" in p:
        out[p["rename"]] = out.pop(p["file"])
    return out


def day_context(sample: dict, d: int, prev_state: str | None = None, history: dict | None = None) -> dict:
    """Input files for day d of a week. Without prev_state, the days before are taken from the reference
    trajectory (what the back office would look like had she done them herself)."""
    root = sample["_dir"] / sample["week"]["dir"]
    files = _read_tree(root / f"d{d}" / "input")
    if prev_state is None and d > 1:
        prev_state = (root / f"d{d - 1}" / "reference" / "state.json").read_text(encoding="utf-8")
        history = {f"d{k}.md": (root / f"d{k}" / "reference" / "REPORT.md").read_text(encoding="utf-8") for k in range(1, d)}
    if prev_state:
        files["prev_state.json"] = prev_state
    for k, v in (history or {}).items():
        files[f"history/{k}"] = v
    return files


def day_reference(sample: dict, d: int) -> dict:
    return _read_tree(sample["_dir"] / sample["week"]["dir"] / f"d{d}" / "reference")


def score_checklist(sample: dict, out_dir: Path, in_dir: Path, day: int | None = None) -> dict:
    rows = []
    for c in sample["rubric"]:
        if c.get("days") and day not in c["days"]:
            continue
        err = ""
        try:
            r = subprocess.run([sys.executable, "-B", str(sample["_dir"] / "rubric.py"), "--item", c["id"], "--input", str(in_dir), "--output", str(out_dir)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            err = r.stderr
            res = json.loads([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])
            ok, detail = bool(res["pass"]), str(res.get("detail", ""))
        except Exception as e:  # noqa: BLE001 - a crashing rubric item counts as not met
            ok, detail = False, f"rubric item crashed: {type(e).__name__}: {err[-200:]}"
        rows.append({"id": c["id"], "claim": c["claim"], "pass": ok, "detail": detail})
    return {"passed": sum(r["pass"] for r in rows), "total": len(rows), "items": rows}


def score_style(sample: dict, name: str, rdir: Path, cfg: dict, judge: bool) -> dict:
    """For each hidden style item, break the reference in exactly that way and see whether the built verifier
    fails it on something it passes on the unbroken reference. In a week, each item is probed on its own day."""
    week = bool(sample.get("week"))

    def ctx(day):
        if week:
            return day_context(sample, day), day_reference(sample, day)
        return sample["task"]["input"], sample["task"]["reference_output"]

    def run(tag: str, inp: dict, files: dict) -> dict:
        d = rdir / tag
        _write_tree(d / "input", inp)
        _write_tree(d / "output", files)
        return loop.score(name, d, cfg, judge)

    days = sorted({st.get("day", 1) for st in sample["style"] if st.get("probe")}) if week else [None]
    with ThreadPoolExecutor(max_workers=4) as ex:  # one verifier run (and maybe one judge session) per probe
        base = dict(zip(days, ex.map(lambda dd: run("probe-reference" + (f"-d{dd}" if dd else ""), *ctx(dd)), days)))
        base_failed = {dd: {r["id"] for r in rep["items"] if r["pass"] is False} for dd, rep in base.items()}

        def one(st):
            if not st.get("probe"):
                return {"id": st["id"], "statement": st["statement"], "covered": None, "by": [],
                        "note": "no output probe (process-level standard); not auto-scored"}
            dd = st.get("day", 1) if week else None
            inp, ref = ctx(dd)
            rep = run(f"probe-{st['id']}", inp, _apply_probe(ref, st["probe"], sample["_dir"]))
            by = sorted({r["id"] for r in rep["items"] if r["pass"] is False} - base_failed[dd])
            row = {"id": st["id"], "statement": st["statement"], "covered": bool(by), "by": by, "verdict": rep["verdict"]}
            return {**row, "day": dd} if week else row

        rows = list(ex.map(one, sample["style"]))
    scored = [r for r in rows if r["covered"] is not None]
    out = {"covered": sum(r["covered"] for r in scored), "total": len(scored),
           "reference_verdict": "accept" if all(rep["verdict"] == "accept" for rep in base.values()) else "reject",
           "reference_failed": sorted(set().union(*base_failed.values())), "pending_judge": any(rep["pending"] for rep in base.values()), "items": rows}
    if week:
        out["reference_by_day"] = {f"d{dd}": rep["verdict"] for dd, rep in base.items()}
    return out


def gold_selfcheck(sample: dict) -> dict:
    """The reference output must pass the whole checklist, or the sample contradicts itself."""
    tmp = config.home() / "runs" / "bench-gold"
    if not sample.get("week"):
        _write_tree(tmp / "input", sample["task"]["input"])
        _write_tree(tmp / "output", sample["task"]["reference_output"])
        return score_checklist(sample, tmp / "output", tmp / "input")
    items = []
    for d in range(1, sample["week"]["days"] + 1):
        _write_tree(tmp / f"d{d}" / "input", day_context(sample, d))
        _write_tree(tmp / f"d{d}" / "output", day_reference(sample, d))
        items += [{**i, "id": f"d{d}:{i['id']}"} for i in score_checklist(sample, tmp / f"d{d}" / "output", tmp / f"d{d}" / "input", d)["items"]]
    return {"passed": sum(i["pass"] for i in items), "total": len(items), "items": items}


def run(sample_dir: Path, rounds: int = 2, judge: bool = True, cfg_over: dict | None = None, home: Path | None = None) -> dict:
    sample = load(sample_dir)
    errs = validate(sample)
    if errs:
        raise SystemExit("invalid sample:\n  " + "\n  ".join(errs))
    base_home = config.home()
    home = home or base_home / "bench" / sample["id"]
    report: dict = {"sample": sample["id"], "prepare": prepare(sample, home), "rounds": []}
    cfg = config.load()
    for k, v in (cfg_over or {}).items():
        if v is not None:
            cfg["agent"][k] = v
    gold = gold_selfcheck(sample)
    if gold["passed"] != gold["total"]:
        raise SystemExit("reference output fails the sample's own checklist: " + json.dumps(gold["items"], ensure_ascii=False))

    def save():
        (home / "bench-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        (home / "bench-report.md").write_text(render_report(report), encoding="utf-8")

    d = distill.distill(report["prepare"]["days"], 1, None, 1, False, cfg)
    report["distill"] = d
    name = (d.get("tasks") or [None])[0]
    report["skill"] = name
    save()
    if not name or not (home / "skills" / name / "verifier.yaml").exists():
        report["stopped"] = "no skill was built (see sessions/ for the task briefs and agent output)"
        save()
        return report
    for r in range(rounds + 1):
        rdir = home / "runs" / f"bench-r{r}"
        task_in = rdir / "task-input"
        _write_tree(task_in, sample["task"]["input"])
        ex = loop.execute(name, task_in, rdir / "exec", cfg)
        entry = {"round": r, "executor_ok": ex.ok, "lint_ok": loop.lint(name)["ok"],
                 "checklist": score_checklist(sample, rdir / "exec" / "output", rdir / "exec" / "input")}
        done = r == rounds or (r > 0 and entry["checklist"]["passed"] == entry["checklist"]["total"])
        # judge sessions are the expensive part (one per probe): spend them on the final round only
        entry["style"] = score_style(sample, name, rdir, cfg, judge and done)
        report["rounds"].append(entry)
        save()
        if done:
            break
        fb = home / "feedback" / f"round-{r}"
        fb.mkdir(parents=True, exist_ok=True)
        (fb / "checklist.json").write_text(json.dumps(entry["checklist"], ensure_ascii=False, indent=1), encoding="utf-8")
        if (rdir / "exec" / "output").exists():
            shutil.copytree(rdir / "exec" / "output", fb / "output", dirs_exist_ok=True)
        agent.run(f"iterate-{name}", agent.render("iterate", name=name, fb=f"feedback/round-{r}"), home, cfg)
    report["spent_usd"] = round(agent.spent(), 4)
    save()
    return report


def _with_backlog(files: dict, backlog: dict) -> dict:
    """Put the rows of a skipped day's inbox files (csv, one header line) in front of today's."""
    if not backlog:
        return files
    out = dict(files)
    for name, old in backlog.items():
        new = files.get(name, "")
        out[name] = old.rstrip("\n") + "\n" + "".join(new.splitlines(keepends=True)[1:]) if new else old
    if "README.md" in out:
        out["README.md"] = out["README.md"].rstrip("\n") + "\n\n昨天什么都没有处理：" + "、".join(f"`{f}`" for f in backlog) + " 里保留了昨天的条目，排在今天的前面。\n"
    return out


def run_week(sample_dir: Path, judge: bool = True, cfg_over: dict | None = None, home: Path | None = None, iterate: bool = True) -> dict:
    """Long horizon: one skill, seven days. Each day starts from the state the run itself left behind the day
    before, so what was done wrong on Monday is still there on Tuesday. A day on which nothing was done at all
    leaves its inbox files (week.inbox) waiting for the next day. The score is how many days are filled,
    i.e. pass every rubric item that applies that day."""
    sample = load(sample_dir)
    errs = validate(sample)
    if errs:
        raise SystemExit("invalid sample:\n  " + "\n  ".join(errs))
    home = home or config.home() / "bench" / sample["id"]
    report: dict = {"sample": sample["id"], "prepare": prepare(sample, home), "days": []}
    cfg = config.load()
    for k, v in (cfg_over or {}).items():
        if v is not None:
            cfg["agent"][k] = v
    gold = gold_selfcheck(sample)
    if gold["passed"] != gold["total"]:
        raise SystemExit("reference week fails the sample's own rubric: " + json.dumps([i for i in gold["items"] if not i["pass"]], ensure_ascii=False))

    def save():
        report["filled"] = sum(1 for d in report["days"] if d["filled"])
        (home / "bench-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        (home / "bench-report.md").write_text(render_report(report), encoding="utf-8")

    d = distill.distill(report["prepare"]["days"], 1, None, 1, False, cfg)
    report["distill"] = d
    name = (d.get("tasks") or [None])[0]
    report["skill"] = name
    save()
    if not name or not (home / "skills" / name / "verifier.yaml").exists():
        report["stopped"] = "no skill was built (see sessions/ for the task briefs and agent output)"
        save()
        return report
    n, prev_state, history, backlog = sample["week"]["days"], None, {}, {}
    for day in range(1, n + 1):
        rdir = home / "runs" / f"week-d{day}"
        files = day_context(sample, day, prev_state or "", history) if day > 1 else day_context(sample, 1)
        files = _with_backlog(files, backlog)
        _write_tree(rdir / "day-input", files)
        ex = loop.execute(name, rdir / "day-input", rdir / "exec", cfg)
        out = rdir / "exec" / "output"
        chk = score_checklist(sample, out, rdir / "exec" / "input", day)
        report["days"].append({"day": day, "filled": chk["passed"] == chk["total"], "executor_ok": bool(ex and ex.ok), "checklist": chk,
                               "blocked": (out / "BLOCKED.md").exists()})
        if (out / "state.json").exists():  # whatever was done today is what tomorrow starts from
            prev_state = (out / "state.json").read_text(encoding="utf-8")
            backlog = {}
        else:  # nothing was done at all: what came in today does not vanish, it is still in the inbox tomorrow
            backlog = {f: files[f] for f in sample["week"].get("inbox", []) if f in files}
            report["days"][-1]["skipped"] = True
        if (out / "REPORT.md").exists():
            history[f"d{day}.md"] = (out / "REPORT.md").read_text(encoding="utf-8")
        save()
        if iterate and day < n and not report["days"][-1]["filled"]:  # she says what was wrong; the skill gets one revision before tomorrow
            fb = home / "feedback" / f"day-{day}"
            fb.mkdir(parents=True, exist_ok=True)
            (fb / "checklist.json").write_text(json.dumps(chk, ensure_ascii=False, indent=1), encoding="utf-8")
            if out.exists():
                shutil.copytree(out, fb / "output", dirs_exist_ok=True)
            agent.run(f"iterate-{name}", agent.render("iterate", name=name, fb=f"feedback/day-{day}"), home, cfg)
            report["days"][-1]["iterated"] = True
    report["lint_ok"] = loop.lint(name)["ok"]
    report["style"] = score_style(sample, name, home / "runs" / "week-style", cfg, judge)
    report["spent_usd"] = round(agent.spent(), 4)
    save()
    return report


def render_report(rep: dict) -> str:
    out = [f"# Bench report: {rep['sample']}", "", f"skill built: `{rep.get('skill')}`", ""]
    if rep.get("stopped"):
        out += [f"**stopped**: {rep['stopped']}", ""]
    if rep.get("days"):
        ids = sorted({i["id"] for d in rep["days"] for i in d["checklist"]["items"]}, key=lambda x: (len(x), x))
        out += [f"**filled {rep.get('filled', 0)} / {len(rep['days'])} days**", "", "| day | " + " | ".join(ids) + " | filled |", "|---|" + "---|" * (len(ids) + 1)]
        for d in rep["days"]:
            got = {i["id"]: i["pass"] for i in d["checklist"]["items"]}
            out.append(f"| {d['day']} | " + " | ".join("✓" if got.get(i) else "·" if i not in got else "✗" for i in ids) + f" | {'yes' if d['filled'] else 'no, nothing was done' if d.get('skipped') else 'no'} |")
        out += ["", "## Rubric items that failed", ""]
        out += [f"- day {d['day']} `{i['id']}` {i['claim']} — {i['detail']}" for d in rep["days"] for i in d["checklist"]["items"] if not i["pass"]] or ["- none"]
        if rep.get("style"):
            st = rep["style"]
            out += ["", f"## Hidden style items: {st['covered']} / {st['total']} caught" + (" (judge items pending)" if st["pending_judge"] else ""), "",
                    f"reference days accepted by the built verifier: {st.get('reference_by_day')}", ""]
            for i in st["items"]:
                mark = {True: "x", False: " ", None: "-"}[i["covered"]]
                out.append(f"- [{mark}] `{i['id']}` (day {i.get('day')}) {i['statement']}" + (f" — caught by {', '.join(i['by'])}" if i["by"] else f" — {i.get('note', 'not caught')}"))
    if rep.get("rounds"):
        out += ["| round | rubric | style covered | reference output | lint |", "|---|---|---|---|---|"]
        for r in rep["rounds"]:
            c, s = r["checklist"], r["style"]
            out.append(f"| {r['round']} | {c['passed']}/{c['total']} | {s['covered']}/{s['total']}"
                       f"{' (judge items pending)' if s['pending_judge'] else ''} | {s['reference_verdict']} | {'ok' if r['lint_ok'] else 'FAIL'} |")
        last = rep["rounds"][-1]
        out += ["", "## Rubric (last round)", ""]
        out += [f"- [{'x' if i['pass'] else ' '}] `{i['id']}` {i['claim']}" + ("" if i["pass"] else f" — {i['detail']}") for i in last["checklist"]["items"]]
        out += ["", "## Hidden style items (last round)", ""]
        for i in last["style"]["items"]:
            mark = {True: "x", False: " ", None: "-"}[i["covered"]]
            out.append(f"- [{mark}] `{i['id']}` {i['statement']}" + (f" — caught by {', '.join(i['by'])}" if i["by"] else f" — {i.get('note', 'not caught')}"))
    return "\n".join(out) + "\n"



