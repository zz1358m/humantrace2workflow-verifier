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
    return s


def _t(at: str) -> float:
    return datetime.strptime(str(at), "%Y-%m-%d %H:%M:%S").timestamp()


def _iso(at: str) -> str:
    return datetime.fromtimestamp(_t(at)).astimezone().isoformat()


def validate(sample: dict) -> list[str]:
    """Structural checks, plus the one that matters: every style item must leave a trace in the records,
    otherwise no pipeline could recover it and the sample is unfair."""
    errs = []
    for key in ("id", "purpose", "rubric", "style", "records", "task"):
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
    ref = sample["task"].get("reference_output") or {}
    for st in sample["style"]:
        p = st.get("probe")
        if p and p.get("file") not in ref:
            errs.append(f"style {st['id']}: probe file {p.get('file')} is not in task.reference_output")
        elif p:
            if _apply_probe(ref, p) == ref:
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
        (root / name).write_text(content, encoding="utf-8")


def _apply_probe(ref: dict, p: dict) -> dict:
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


def score_checklist(sample: dict, out_dir: Path, in_dir: Path) -> dict:
    rows = []
    for c in sample["rubric"]:
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
    task = sample["task"]
    ref = task["reference_output"]

    def run(tag: str, files: dict) -> dict:
        d = rdir / tag
        _write_tree(d / "input", task["input"])
        _write_tree(d / "output", files)
        return loop.score(name, d, cfg, judge)

    base = run("probe-reference", ref)
    base_failed = {r["id"] for r in base["items"] if r["pass"] is False}
    rows = []
    for st in sample["style"]:
        if not st.get("probe"):
            rows.append({"id": st["id"], "statement": st["statement"], "covered": None, "by": [], "note": "no output probe (process-level standard); not auto-scored"})
            continue
        rep = run(f"probe-{st['id']}", _apply_probe(ref, st["probe"]))
        by = sorted({r["id"] for r in rep["items"] if r["pass"] is False} - base_failed)
        rows.append({"id": st["id"], "statement": st["statement"], "covered": bool(by), "by": by, "verdict": rep["verdict"]})
    scored = [r for r in rows if r["covered"] is not None]
    return {"covered": sum(r["covered"] for r in scored), "total": len(scored), "reference_verdict": base["verdict"],
            "reference_failed": sorted(base_failed), "pending_judge": bool(base["pending"]), "items": rows}


def gold_selfcheck(sample: dict) -> dict:
    """The reference output must pass the whole checklist, or the sample contradicts itself."""
    tmp = config.home() / "runs" / "bench-gold"
    _write_tree(tmp / "input", sample["task"]["input"])
    _write_tree(tmp / "output", sample["task"]["reference_output"])
    return score_checklist(sample, tmp / "output", tmp / "input")


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


def render_report(rep: dict) -> str:
    out = [f"# Bench report: {rep['sample']}", "", f"skill built: `{rep.get('skill')}`", ""]
    if rep.get("stopped"):
        out += [f"**stopped**: {rep['stopped']}", ""]
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



