import shutil
from pathlib import Path

import pytest
import yaml

from ht2wv import loop, verifier


SKILL = "weekly-metrics-report"


@pytest.fixture
def demo_skill(tmp_path, monkeypatch):
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo"
    home = tmp_path / "demo"
    shutil.copytree(demo, home)
    monkeypatch.setenv("HT2WV_HOME", str(home))
    return home / "skills" / SKILL


def _read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _rows(report):
    return {row["case"]: row for row in report["cases"]}


def _judge_only(d):
    path = d / "verifier.yaml"
    v = _read(path)
    v["items"] = [item for item in v["items"] if item["id"] not in {"O1", "P1"}]
    _write(path, v)
    style_path = d.parents[1] / "profile" / "acceptance-style.yaml"
    style = _read(style_path)
    next(item for item in style["items"] if item["id"] == "ST1")["cases"] = ["w40-first", "w41-first"]
    _write(style_path, style)


def test_unmodified_demo_agrees_with_labelled_cases(demo_skill):
    report = loop.lint(SKILL)
    assert report["ok"], report["errors"]
    rows = _rows(report)
    for cid in ("w40-first", "w41-first"):
        assert rows[cid]["failed"] == ["O1", "P1"]
        assert rows[cid]["coverage"] == "check:O1,P1"
        assert rows[cid]["checks_verdict"] == rows[cid]["verdict"] == "reject"
    for cid in ("w40-final", "w41-final"):
        assert rows[cid]["failed"] == []
        assert rows[cid]["verdict"] == "accept"
    assert all(row["pending"] == ["ST1", "ST2"] for row in rows.values())


def test_inherited_judges_do_not_cover_reject_cases(demo_skill):
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    v["items"] = [item for item in v["items"] if item["id"] == "O2"]
    _write(path, v)
    report = loop.lint(SKILL)
    assert not report["ok"]
    rows = _rows(report)
    for cid in ("w40-first", "w41-first"):
        assert any(cid in error and "nothing in the verifier can fail it" in error for error in report["errors"])
        assert rows[cid]["failed"] == []
        assert rows[cid]["coverage"] == "none"
        assert rows[cid]["verdict"] == "accept"
        assert rows[cid]["pending"] == ["ST1", "ST2"]


def test_reject_verdict_cannot_be_accepted_despite_failed_checks(demo_skill):
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    v["accept_threshold"] = 0.0
    for item in v["items"]:
        item.pop("hard", None)
    _write(path, v)
    for cid in ("w40-first", "w41-first"):
        c = demo_skill / "cases" / cid
        rep = verifier.run(demo_skill, c / "output", c / "input")
        assert rep["score"] == 0.2857 and rep["hard_fail"] == []
        assert rep["verdict"] == "accept"
    report = loop.lint(SKILL)
    assert not report["ok"]
    for cid in ("w40-first", "w41-first"):
        assert any(cid in error and "verdict is accept" in error for error in report["errors"])
        assert _rows(report)[cid]["coverage"] == "check:O1,P1"


def test_accept_case_cannot_have_reject_verdict(demo_skill):
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    v["accept_threshold"] = 1.1
    _write(path, v)
    report = loop.lint(SKILL)
    assert not report["ok"]
    for cid in ("w40-final", "w41-final"):
        assert any(cid in error and "verdict is reject" in error for error in report["errors"])
        assert _rows(report)[cid]["failed"] == []
        assert _rows(report)[cid]["verdict"] == "reject"


def test_named_inherited_judge_covers_only_named_reject_cases(demo_skill):
    _judge_only(demo_skill)
    style_path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"
    style = _read(style_path)
    next(item for item in style["items"] if item["id"] == "ST1")["cases"] = ["w40-first"]
    _write(style_path, style)
    report = loop.lint(SKILL)
    assert not report["ok"]
    assert not any("w40-first" in error for error in report["errors"])
    assert any("w41-first" in error for error in report["errors"])
    row = _rows(report)["w40-first"]
    assert row["coverage"] == "judge-named:ST1"
    assert row["checks_verdict"] == "accept"
    assert row["verdict"] == "reject"
    assert row["verdict_depends_on"] == ["ST1"]
    assert row["pending"] == ["ST1", "ST2"]


@pytest.mark.parametrize("threshold, ok, verdict", [(0.8, True, "reject"), (0.5, False, "accept")])
def test_named_judge_failure_must_actually_reject(demo_skill, threshold, ok, verdict):
    _judge_only(demo_skill)
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    v["accept_threshold"] = threshold
    _write(path, v)
    c = demo_skill / "cases" / "w40-first"
    rep = verifier.run(demo_skill, c / "output", c / "input", {"ST1": {"pass": False}})
    assert rep["score"] == 0.5 and rep["verdict"] == verdict
    report = loop.lint(SKILL)
    assert report["ok"] is ok, report["errors"]
    for cid in ("w40-first", "w41-first"):
        row = _rows(report)[cid]
        assert row["failed"] == []
        assert row["coverage"] == "judge-named:ST1"
        assert row["checks_verdict"] == "accept"
        assert row["verdict"] == verdict
        assert row["verdict_depends_on"] == ["ST1"]
        if not ok:
            assert any(cid in error and "pending judge items" in error and "ST1" in error for error in report["errors"])


def test_named_judge_does_not_override_check_covered_accept_verdict(demo_skill):
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    v["accept_threshold"] = 0.0
    for item in v["items"]:
        item.pop("hard", None)
    style_path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"
    style = _read(style_path)
    judge = next(item for item in style["items"] if item["id"] == "ST1")
    judge["cases"] = ["w40-first", "w41-first"]
    judge["hard"] = True
    _write(style_path, style)
    _write(path, v)
    report = loop.lint(SKILL)
    assert not report["ok"]
    for cid in ("w40-first", "w41-first"):
        row = _rows(report)[cid]
        assert row["coverage"] == "check:O1,P1"
        assert row["verdict"] == "accept"
        assert row["verdict_depends_on"] == []
        assert any(cid in error and "verdict is accept" in error for error in report["errors"])


@pytest.mark.parametrize("cid, reason", [("missing-case", "unknown case"), ("w40-final", "labelled reject")])
def test_judge_cases_must_name_existing_reject_cases(demo_skill, cid, reason):
    path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"
    style = _read(path)
    next(item for item in style["items"] if item["id"] == "ST1")["cases"] = [cid]
    _write(path, style)
    report = loop.lint(SKILL)
    assert not report["ok"]
    assert any("ST1" in error and cid in error and reason in error for error in report["errors"])


def test_cases_field_is_for_judges_only(demo_skill):
    path = demo_skill / "verifier.yaml"
    v = _read(path)
    next(item for item in v["items"] if item["id"] == "O1")["cases"] = ["w40-first"]
    _write(path, v)
    assert any("O1" in error and "cases" in error and "judge" in error for error in verifier.lint(demo_skill))
    assert not loop.lint(SKILL)["ok"]


@pytest.mark.parametrize("value", ["w40-first", {"w40-first": True}, [1], ["w40-first", None], None])
def test_judge_cases_must_be_a_list_of_strings(demo_skill, value):
    path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"
    style = _read(path)
    next(item for item in style["items"] if item["id"] == "ST1")["cases"] = value
    _write(path, style)
    assert any("ST1" in error and "cases must be a list of strings" in error for error in verifier.lint(demo_skill))
    assert not loop.lint(SKILL)["ok"]


def test_proposed_verifier_uses_same_lint_rules(demo_skill):
    v = _read(demo_skill / "verifier.yaml")
    v["items"] = [item for item in v["items"] if item["id"] == "O2"]
    _write(demo_skill / "verifier.proposed.yaml", v)
    report = loop.lint(SKILL, proposed=True)
    assert not report["ok"]
    assert report["file"] == "verifier.proposed.yaml"
    assert all(any(cid in error for error in report["errors"]) for cid in ("w40-first", "w41-first"))


def test_export_ships_what_the_workflow_links_to(demo_skill, tmp_path):
    # a week-long run lost a day because SKILL.md told sessions to read references/contracts.md and export left it behind
    (demo_skill / "references").mkdir()
    (demo_skill / "references" / "contracts.md").write_text("fields and decision table\n", encoding="utf-8")
    (demo_skill / "stages").mkdir(exist_ok=True)
    (demo_skill / "stages" / "01-collect.md").write_text("read [the contracts](../references/contracts.md)\n", encoding="utf-8")
    skill_md = demo_skill / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nFields: [contracts](references/contracts.md#fields). "
                        "Report like [this](REPORT.md) and see https://example.com/spec.\n", encoding="utf-8")
    assert loop.unshipped_links(demo_skill) == []
    dest = loop.export(SKILL, tmp_path / "out")
    assert (dest / "references" / "contracts.md").read_text(encoding="utf-8") == "fields and decision table\n"
    assert (dest / "stages" / "01-collect.md").exists() and not (dest / "cases").exists()


def test_lint_flags_links_executing_sessions_cannot_follow(demo_skill):
    (demo_skill / "evidence.md").write_text("where each item came from\n", encoding="utf-8")
    skill_md = demo_skill / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nSee [evidence](evidence.md) and [the table](references/missing.md).\n", encoding="utf-8")
    errors = loop.lint(SKILL)["errors"]
    assert any("evidence.md" in e and "not copied" in e for e in errors)
    assert any("references/missing.md" in e and "does not exist" in e for e in errors)
    assert len(errors) == 2
