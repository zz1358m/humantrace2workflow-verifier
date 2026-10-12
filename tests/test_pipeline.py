import json
import shutil
import subprocess
import sys
from collections import Counter

import yaml

from ht2w import agent, config, distill, loop, store, synth, verifier
from ht2w.compile import compile_day
from ht2w.compile.signals import build_spans, conversation_signals, screen_signals
from ht2w.redact import is_private, redact

CC = config.DEFAULTS["compile"]
DAY = "2026-01-05"

CHECK = r'''
import argparse, csv, json, pathlib, re
a = argparse.ArgumentParser(); a.add_argument("--input"); a.add_argument("--output"); a = a.parse_args()
want = [r["value"] for f in pathlib.Path(a.input).glob("*.csv") for r in csv.DictReader(open(f, encoding="utf-8"))]
text = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path(a.output).glob("*.md"))
missing = [w for w in want if not re.search(r"(?<![\d.])" + re.escape(w) + r"(?![\d.])", text)]
print(json.dumps({"pass": not missing, "detail": f"missing {missing}"}))
'''


def test_redact():
    out = redact("mail a.b@x.com key sk-abcdefghijklmnopqrstuv password: hunter22 tel 13812345678")
    assert "a.b@x.com" not in out and "sk-abc" not in out and "hunter22" not in out and "13812345678" not in out
    assert is_private("chrome.exe", "Sign in - 1Password", ["1password"])


def test_synth_day_signals(home):
    synth.write(DAY)
    k = compile_day(DAY)["signals"]
    assert k["crosscheck"] == 2 and k["rework"] == 2 and k["undo_burst"] == 2 and k["pre_commit_review"] == 2
    assert k["correction"] == 1 and k["acceptance"] == 1
    assert "version_churn" not in k  # W40 / W41 are different reports, not versions of one
    sigs = [json.loads(ln) for ln in (home / "traces" / DAY / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    rw = next(s for s in sigs if s["kind"] == "rework")
    blobs = home / "traces" / DAY / "blobs"
    assert (blobs / f"{rw['rejected_sha']}.md").exists() and (blobs / f"{rw['kept_sha']}.md").exists()
    assert "⚑ **crosscheck**" in (home / "traces" / DAY / "day.md").read_text(encoding="utf-8")


def _ev(t, k, **f):
    return {"t": t, "src": "screen", "k": k, **f}


def _kinds(evs):
    return Counter(s["kind"] for s in screen_signals(build_spans(evs, 300), evs, CC))


def test_lookup_is_mainline_crosscheck_is_not():
    base = [_ev(0, "win", app="word", title="doc"), _ev(5, "type", n=50, bs=0, t1=20), _ev(30, "win", app="excel", title="sheet")]
    back = [_ev(40, "win", app="word", title="doc"), _ev(41, "key", combo="ctrl+v"), _ev(60, "win", app="x", title="y")]
    copied = _kinds(base + [_ev(33, "clip", n=5, h="h")] + back)
    assert copied["lookup"] == 1 and copied["crosscheck"] == 0
    assert _kinds(base + back)["crosscheck"] == 1


def test_version_churn():
    evs = [_ev(0, "win", app="w", title="d")] + [_ev(i, "file", op="modified", path=f"D:\\x\\{n}") for i, n in
                                                enumerate(["report.docx", "report_v2.docx", "report final.docx", "plan_W40.md", "plan_W41.md"], 1)]
    churn = [s for s in screen_signals(build_spans(evs, 300), evs, CC) if s["kind"] == "version_churn"]
    assert len(churn) == 1 and len(churn[0]["versions"]) == 3


def test_ai_paste_verdicts():
    def run(after):
        evs = [_ev(0, "win", app="chrome.exe", title="ChatGPT - Chrome"), _ev(2, "clip", n=400, h="h"),
               _ev(5, "win", app="word", title="doc"), _ev(6, "key", combo="ctrl+v")] + after + [_ev(100, "win", app="x", title="y")]
        return [s for s in screen_signals(build_spans(evs, 300), evs, CC) if s["kind"] == "ai_paste"][0]["verdict"]

    assert run([]) == "accepted"
    assert run([_ev(10, "type", n=30, bs=12, t1=25)]) == "edited"
    assert run([_ev(10, "key", combo="ctrl+z")]) == "rejected"


def test_conversation_signals():
    c = {"agent": "claude", "session": "s"}
    evs = [{"t": 0, "k": "prompt", "text": "write the parser", **c}, {"t": 10, "k": "reply", "text": "done", "tools": ["Edit"], **c},
           {"t": 20, "k": "prompt", "text": "did you run the tests?", **c}, {"t": 30, "k": "reply", "text": "yes", **c},
           {"t": 35, "k": "abort", **c}, {"t": 40, "k": "prompt", "text": "no, that's not what I asked", **c}]
    assert [s["kind"] for s in conversation_signals(evs)] == ["verify_request", "abort", "correction"]


def _make_skill(home):
    synth.write(DAY)
    compile_day(DAY)
    (home / "profile" / "acceptance-style.yaml").write_text(yaml.safe_dump({
        "policy": {"check_depth": "full", "on_fail": "fix_then_recheck"},
        "items": [{"id": "ST1", "claim": "no filler adjectives", "how": "judge", "rubric": "only facts", "applies_to": ["writing"],
                   "weight": 1, "source": "corrected", "evidence": [f"{DAY}:S013"]},
                  {"id": "ST9", "claim": "code only", "how": "judge", "rubric": "x", "applies_to": ["code"], "source": "stated", "evidence": ["x"]}]},
        allow_unicode=True), encoding="utf-8")
    d = home / "skills" / "weekly-report"
    (d / "checks").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: weekly-report\ndescription: write the weekly metrics report\n---\n# steps\n", encoding="utf-8")
    (d / "checks" / "numbers.py").write_text(CHECK, encoding="utf-8")
    (d / "verifier.yaml").write_text(yaml.safe_dump({
        "skill": "weekly-report", "version": 1, "kind": ["writing"], "accept_threshold": 0.8, "inherits": "../../profile/acceptance-style.yaml",
        "items": [{"id": "O1", "layer": "objective", "claim": "every number equals the csv", "how": "check", "check": "checks/numbers.py",
                   "weight": 3, "hard": True, "source": "observed", "evidence": [f"{DAY}:S002"]}]}), encoding="utf-8")
    blobs = home / "traces" / DAY / "blobs"
    sigs = [json.loads(ln) for ln in (home / "traces" / DAY / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    rw = next(s for s in sigs if s["kind"] == "rework" and "W41" in s["path"])
    csv_sha = next(e["sha"] for e in store.read_events(DAY) if e["k"] == "file" and "metrics_W41" in e["path"])
    for cid, sha, label in (("w41-first", rw["rejected_sha"], "reject"), ("w41-final", rw["kept_sha"], "accept")):
        c = d / "cases" / cid
        (c / "input").mkdir(parents=True)
        (c / "output").mkdir()
        shutil.copyfile(blobs / f"{csv_sha}.csv", c / "input" / "metrics_W41.csv")
        shutil.copyfile(blobs / f"{sha}.md", c / "output" / "weekly_W41.md")
        (c / "case.yaml").write_text(f"label: {label}\n", encoding="utf-8")
    return d


def test_verifier_inherits_style_and_agrees_with_person(home):
    d = _make_skill(home)
    v = verifier.load(d)
    assert [i["id"] for i in v["items"]] == ["O1", "ST1"]  # ST9 applies to code only
    assert v["policy"]["check_depth"] == "full"
    res = loop.lint("weekly-report")
    assert res["ok"], res["errors"]
    assert {r["case"]: r["checks_verdict"] for r in res["cases"]} == {"w41-first": "reject", "w41-final": "accept"}
    assert loop.evaluate("weekly-report")["agreement"] == 1.0
    rep = verifier.run(d, d / "cases/w41-final/output", d / "cases/w41-final/input", {"ST1": {"pass": False, "detail": "adjectives"}})
    assert rep["verdict"] == "reject" and rep["score"] == 0.75 and not rep["hard_fail"]


def test_lint_rejects_unevidenced_personal_items(home):
    d = _make_skill(home)
    v = yaml.safe_load((d / "verifier.yaml").read_text(encoding="utf-8"))
    v["items"].append({"id": "P1", "layer": "preference", "claim": "short", "how": "judge", "rubric": "r", "source": "observed"})
    (d / "verifier.yaml").write_text(yaml.safe_dump(v), encoding="utf-8")
    assert any("P1" in e and "evidence" in e for e in loop.lint("weekly-report")["errors"])


def test_export_is_self_contained_and_feedback_becomes_case(home, tmp_path):
    d = _make_skill(home)
    dest = loop.install("weekly-report", str(tmp_path / "agent_skills"))
    v = yaml.safe_load((dest / "verifier.yaml").read_text(encoding="utf-8"))
    assert "inherits" not in v and {i["id"] for i in v["items"]} == {"O1", "ST1"}
    assert (dest / "verify.py").exists() and not (dest / "cases").exists()
    c = d / "cases" / "w41-first"
    r = subprocess.run([sys.executable, str(dest / "verify.py"), "--input", str(c / "input"), "--output", str(c / "output")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "REJECT" in r.stdout and "51730" in r.stdout

    run = home / "runs" / "r1"
    shutil.copytree(c / "input", run / "input")
    shutil.copytree(c / "output", run / "output")
    (run / "report.json").write_text(json.dumps(verifier.run(d, run / "output", run / "input")), encoding="utf-8")
    row = loop.feedback("r1", "reject", "number is wrong")
    assert row["verifier_verdict"] == "reject" and (d / "cases" / "fb-r1" / "case.yaml").exists()
    assert loop.evaluate("weekly-report")["verifier_vs_person_on_runs"] == 1.0


def test_prompts_render_and_manual_backend_writes_task(home):
    for tpl, kw in (("profile", {"days": DAY}), ("skill", {"name": "x"}), ("execute", {}), ("judge", {}), ("compare", {}),
                    ("improve", {"name": "x", "round_dir": "runs/r"}), ("evolve", {"name": "x"})):
        assert "{{" not in agent.render(tpl, **kw), tpl
    cfg = config.load()
    cfg["agent"]["backend"] = "manual"
    out = distill.build_skill("x", cfg)
    assert not out["lint_ok"] and "skills/x/" in (home / "sessions" / out["session"] / "TASK.md").read_text(encoding="utf-8")
    assert agent.spent() == 0
