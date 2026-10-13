"""The bench loop end to end with a scripted agent: no model, but every file hand-off is real."""
from pathlib import Path

import pytest
import yaml

from ht2wv import agent, bench, config

SAMPLES = Path(__file__).resolve().parent.parent / "examples" / "samples"
CHECK = '''import argparse, json, pathlib
a = argparse.ArgumentParser(); a.add_argument("--input"); a.add_argument("--output"); a = a.parse_args()
text = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path(a.output).glob("*.md"))
print(json.dumps({"pass": "数据来源" in text, "detail": "no source line"}))
'''


@pytest.mark.parametrize("name", sorted(p.name for p in SAMPLES.iterdir() if (p / "sample.yaml").exists()))
def test_samples_are_valid_and_fair(name, home):
    s = bench.load(SAMPLES / name)
    assert bench.validate(s) == []
    gold = bench.gold_selfcheck(s)
    assert gold["passed"] == gold["total"], gold["items"]
    # every probe must break the reference in a way the rubric alone would not always notice
    assert sum(1 for st in s["style"] if st.get("probe")) >= 5


def test_rendered_records_do_not_leak_the_answer_key(home, tmp_path):
    s = bench.load(SAMPLES / "weekly-report")
    info = bench.prepare(s, tmp_path / "h")
    blob = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in Path(info["home"]).rglob("*") if p.is_file() and p.name != "History")
    assert '"from"' not in blob and "statement" not in blob and "W42.md" not in blob  # no tags, no style text, no reference output
    assert "56120" not in blob.replace("metrics", "")  # the held-out week's numbers never appear in the records
    assert info["ingested"]["agents"] == {"claude": 17, "codex": 11} and info["ingested"]["chat"] == 10


def test_bench_run_scores_rubric_and_style(home, tmp_path, monkeypatch):
    sample = bench.load(SAMPLES / "weekly-report")
    seen = []

    def fake(kind, task, cwd, cfg=None, add_dirs=()):
        seen.append(kind)
        cwd = Path(cwd)
        if kind == "profile":
            (cwd / "profile" / "tasks.yaml").write_text("tasks:\n  - {name: weekly, score: 9}\n", encoding="utf-8")
        elif kind == "skill-weekly":
            d = cwd / "skills" / "weekly"
            (d / "checks").mkdir(parents=True)
            (d / "stages").mkdir()
            (d / "SKILL.md").write_text("---\nname: weekly\ndescription: weekly report\n---\n", encoding="utf-8")
            (d / "stages" / "01-gather.md").write_text("读 csv，把数写进 work/numbers.json", encoding="utf-8")
            (d / "stages" / "02-write.md").write_text("写周报并验收", encoding="utf-8")
            (d / "checks" / "src.py").write_text(CHECK, encoding="utf-8")
            (d / "verifier.yaml").write_text(yaml.safe_dump({"skill": "weekly", "version": 1, "items": [
                {"id": "O1", "layer": "objective", "claim": "has a source line", "how": "check", "check": "checks/src.py",
                 "hard": True, "source": "stated", "evidence": ["request:R5"]}]}, allow_unicode=True), encoding="utf-8")
        elif kind.startswith("execute-weekly-s"):
            assert "# 验收标准（本 workflow 的所有会话共用）" in task and "has a source line" in task  # every session gets the shared verifier
            if kind.endswith("s1"):
                (cwd / "work" / "numbers.json").write_text("{}", encoding="utf-8")
            else:
                assert (cwd / "work" / "numbers.json").exists()  # hand-over from the previous session
                out = "# 周报 W42\n\n- 注册 1375（环比 -2.5%）\n- 收入 $56120（环比 +8.5%）\n- ⚠ 流失率 2.4%（环比 +33.3%）\n"
                if "iterate-weekly" in seen:  # second round: the workflow was "fixed"
                    out += "\n数据来源：metrics_W42.csv、metrics_W41.csv\n"
                (cwd / "output" / "weekly_W42.md").write_text(out, encoding="utf-8")
        return agent.Result(True, "", 0.0, cwd)

    monkeypatch.setattr(agent, "run", fake)
    rep = bench.run(SAMPLES / "weekly-report", rounds=1, judge=False, home=tmp_path / "h")
    r0, r1 = rep["rounds"]
    assert (r0["checklist"]["passed"], r1["checklist"]["passed"]) == (4, 5)
    assert [i["id"] for i in r0["checklist"]["items"] if not i["pass"]] == ["R5"]
    assert r1["style"]["covered"] == 1 and r1["style"]["total"] == 6 and r1["style"]["reference_verdict"] == "accept"
    assert [i["id"] for i in r1["style"]["items"] if i["covered"]] == ["S3"]
    assert seen.count("execute-weekly-s1") == 2 and "iterate-weekly" in seen
    fb = Path(rep["prepare"]["home"]) / "feedback" / "round-0" / "checklist.json"
    assert "R5" in fb.read_text(encoding="utf-8") and "S3" not in fb.read_text(encoding="utf-8")  # rubric is fed back, hidden style is not
    assert "| 1 | 5/5 | 1/6" in (Path(rep["prepare"]["home"]) / "bench-report.md").read_text(encoding="utf-8")
    assert config.home() == tmp_path / "h"
