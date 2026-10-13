"""The week-long sample: state carries from day to day, and each day is judged against her rules applied
to the state the run itself left behind. Scripted agents stand in for the model."""
import csv
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ht2wv import agent, bench

WEEK = Path(__file__).resolve().parent.parent / "examples" / "samples" / "refund-week"
spec = importlib.util.spec_from_file_location("refund_week_policy", WEEK / "policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def test_week_sample_is_valid_and_every_probe_fails_some_day_rubric(home):
    s = bench.load(WEEK)
    assert bench.validate(s) == []
    gold = bench.gold_selfcheck(s)
    assert gold["passed"] == gold["total"] == 6 * 7 + 1, [i for i in gold["items"] if not i["pass"]]
    # breaking any process rule changes what the back office ends up with, so the day's rubric notices
    for st in s["style"]:
        if "dir" in (st.get("probe") or {}):
            d = st["day"]
            tmp = home / "p" / st["id"]
            bench._write_tree(tmp / "input", bench.day_context(s, d))
            bench._write_tree(tmp / "output", bench._apply_probe(bench.day_reference(s, d), st["probe"], s["_dir"]))
            chk = bench.score_checklist(s, tmp / "output", tmp / "input", d)
            assert chk["passed"] < chk["total"], st["id"]


def _scripted_agent(break_rule_on_day: dict):
    """An 'agent' that builds a two-stage skill, then each day does what policy.py says (optionally breaking a rule)."""
    calls = []

    def fake(kind, task, cwd, cfg=None, add_dirs=()):
        calls.append(kind)
        cwd = Path(cwd)
        if kind == "profile":
            (cwd / "profile" / "tasks.yaml").write_text("tasks:\n  - {name: refunds, score: 9}\n", encoding="utf-8")
        elif kind == "skill-refunds":
            d = cwd / "skills" / "refunds"
            (d / "checks").mkdir(parents=True)
            (d / "stages").mkdir()
            (d / "SKILL.md").write_text("---\nname: refunds\ndescription: daily refunds\n---\n", encoding="utf-8")
            (d / "stages" / "01-plan.md").write_text("plan", encoding="utf-8")
            (d / "stages" / "02-act.md").write_text("act and report", encoding="utf-8")
            (d / "checks" / "has_report.py").write_text(
                'import argparse, json, pathlib\na = argparse.ArgumentParser(); a.add_argument("--input"); a.add_argument("--output"); a = a.parse_args()\n'
                'print(json.dumps({"pass": (pathlib.Path(a.output) / "REPORT.md").exists(), "detail": "no report"}))\n', encoding="utf-8")
            (d / "verifier.yaml").write_text(yaml.safe_dump({"skill": "refunds", "version": 1, "items": [
                {"id": "O1", "layer": "objective", "claim": "a report exists", "how": "check", "check": "checks/has_report.py", "hard": True,
                 "source": "stated", "evidence": ["request:R1"]}]}), encoding="utf-8")
        elif kind == "execute-refunds-s2":
            inp = cwd / "input"
            base = json.loads((inp / "orders.json").read_text(encoding="utf-8"))
            day = sorted(p.name for p in (cwd.parent.parent).glob("week-d*")).index(cwd.parent.name) + 1
            reqs = list(csv.DictReader(io.StringIO((inp / "requests.csv").read_text(encoding="utf-8"))))
            appr = list(csv.DictReader(io.StringIO((inp / "approvals.csv").read_text(encoding="utf-8")))) if (inp / "approvals.csv").exists() else []
            prev = json.loads((inp / "prev_state.json").read_text(encoding="utf-8")) if (inp / "prev_state.json").exists() else {}
            rule = break_rule_on_day.get(day)
            steps = policy.plan(base["orders"], reqs, appr, prev, base["daily_refund_cap"], rule)
            subprocess.run([sys.executable, "-B", "input/env.py", "status"], cwd=cwd, check=True, capture_output=True)
            for cmd in policy.commands(steps, base["orders"], rule):
                subprocess.run([sys.executable, "-B", "input/env.py", *cmd], cwd=cwd, check=True, capture_output=True)
            (cwd / "output" / "REPORT.md").write_text(policy.report(steps), encoding="utf-8")
            if day == 7:
                st = json.loads((cwd / "output" / "state.json").read_text(encoding="utf-8"))
                rejected = {o for o, ts in st["notified"].items() if "rejected" in ts}
                pend = sorted(o for o in st["escalated"] if o not in st["refunds"] and o not in rejected)
                assert len(list((inp / "history").glob("d*.md"))) == 6  # the run's own earlier reports are handed back each day
                (cwd / "output" / "WEEK.md").write_text(policy.week_report([], st, pend), encoding="utf-8")
        return agent.Result(True, "", 0.0, cwd)

    return fake, calls


def test_week_run_fills_seven_days_when_her_rules_are_followed(home, tmp_path, monkeypatch):
    fake, calls = _scripted_agent({})
    monkeypatch.setattr(agent, "run", fake)
    rep = bench.run_week(WEEK, judge=False, home=tmp_path / "h")
    assert rep["filled"] == 7 and all(d["filled"] for d in rep["days"])
    assert "iterate-refunds" not in calls and calls.count("execute-refunds-s1") == 7
    # state really carried: the last day's back office holds the whole week
    st = json.loads((tmp_path / "h" / "runs" / "week-d7" / "exec" / "output" / "state.json").read_text(encoding="utf-8"))
    assert len(st["refunds"]) == 23 and round(sum(st["refunds"].values()), 2) == 6026.0
    assert rep["style"]["total"] == 17 and rep["style"]["reference_verdict"] == "accept"
    assert rep["style"]["covered"] == 0  # the toy verifier only checks that a report exists, so it catches nothing
    assert "**filled 7 / 7 days**" in (tmp_path / "h" / "bench-report.md").read_text(encoding="utf-8")


def test_a_bad_monday_is_judged_on_its_own_and_carries_into_tuesday(home, tmp_path, monkeypatch):
    # Monday: sheet order instead of request time. Tuesday onwards: her rules, starting from Monday's wrong state.
    fake, calls = _scripted_agent({1: "S1", 3: "L3"})
    monkeypatch.setattr(agent, "run", fake)
    rep = bench.run_week(WEEK, judge=False, home=tmp_path / "h")
    filled = [d["filled"] for d in rep["days"]]
    assert filled[0] is False and filled[2] is False
    assert filled[1] is True  # Tuesday is graded against the state Monday really left, so doing it right counts
    assert rep["filled"] == sum(filled) and 3 <= rep["filled"] <= 5
    assert {i["id"] for i in rep["days"][0]["checklist"]["items"] if not i["pass"]} >= {"R2"}
    assert calls.count("iterate-refunds") == rep["days"].__len__() - rep["filled"]  # one revision after each failed day (none after Sunday)
    fb = (tmp_path / "h" / "feedback" / "day-1" / "checklist.json").read_text(encoding="utf-8")
    assert "R2" in fb and "S1" not in fb and "按申请时间" not in fb  # she says what was wrong, not the hidden rule
