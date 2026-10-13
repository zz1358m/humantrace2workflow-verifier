import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ht2wv import agent, config, loop, verifier


SKILL = "weekly-metrics-report"


@pytest.fixture
def demo_skill(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo"
    home = tmp_path / "demo"
    shutil.copytree(demo, home, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    monkeypatch.setenv("HT2WV_HOME", str(home))
    return home / "skills" / SKILL


@pytest.fixture
def fake_agent(demo_skill, monkeypatch):
    def install(improve=None):
        def run(kind: str, task: str, cwd: Path, cfg: dict | None = None, add_dirs: tuple = ()) -> agent.Result:
            if kind.startswith("execute-"):
                # optimize deduplicates inputs and may choose a rejected case;
                # always replay the accepted output for that case's week.
                kept = demo_skill / "cases" / cwd.name.replace("-first", "-final")
                meta = yaml.safe_load((kept / "case.yaml").read_text(encoding="utf-8"))
                assert meta["label"] == "accept"
                assert {p.name: p.read_bytes() for p in (kept / "input").iterdir()} == {
                    p.name: p.read_bytes() for p in (cwd / "input").iterdir()
                }
                shutil.copytree(kept / "output", cwd / "output", dirs_exist_ok=True)
            elif kind.startswith("judge-"):
                pass  # No judgments file: inherited judge items remain pending.
            elif kind.startswith("improve-"):
                if improve is not None:
                    improve()
            else:
                raise AssertionError(f"unexpected agent session: {kind}")
            return agent.Result(ok=True, text="", cost=0.0, session_dir=cwd)

        monkeypatch.setattr(agent, "run", run)
        monkeypatch.setattr(agent, "spent", lambda: 0.0)

    return install


def _append(path, text):
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_noop_improver_does_not_void_rounds_or_write_bytecode(demo_skill, fake_agent):
    fake_agent()
    report = loop.optimize(SKILL, rounds=2, cfg=config.load())
    assert len(report["rounds"]) == 2
    assert all("void" not in row["status"] for row in report["rounds"])
    assert report["baseline_val"] == report["final_val"] == 1.0
    assert report["spent_usd"] == 0.0
    assert not list((demo_skill / "checks").rglob("__pycache__"))
    assert not list((demo_skill / "checks").rglob("*.pyc"))


def test_check_edit_voids_round_and_restores_workflow(demo_skill, fake_agent):
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")

    def improve():
        _append(workflow, "\nChanged workflow.\n")
        _append(demo_skill / "checks" / "o1_numbers.py", "\n# Changed check.\n")

    fake_agent(improve)
    report = loop.optimize(SKILL, rounds=2, cfg=config.load())
    assert len(report["rounds"]) == 1
    assert report["rounds"][0]["status"] == "void: the verifier was modified"
    assert workflow.read_text(encoding="utf-8") == original


def test_inherited_style_edit_voids_round(demo_skill, fake_agent):
    style_path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"

    def improve():
        style = yaml.safe_load(style_path.read_text(encoding="utf-8"))
        style["items"] = []
        style_path.write_text(yaml.safe_dump(style, allow_unicode=True), encoding="utf-8")

    fake_agent(improve)
    report = loop.optimize(SKILL, rounds=2, cfg=config.load())
    assert len(report["rounds"]) == 1
    assert report["rounds"][0]["status"] == "void: the verifier was modified"


def test_workflow_only_edit_is_kept(demo_skill, fake_agent):
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")
    change = "\nUpdated workflow steps.\n"
    fake_agent(lambda: _append(workflow, change))
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert len(report["rounds"]) == 1
    assert "void" not in report["rounds"][0]["status"]
    assert report["rounds"][0]["status"] == "kept"
    assert workflow.read_text(encoding="utf-8") == original + change


def test_tree_hash_ignores_bytecode_and_cache_directories(tmp_path):
    checks = tmp_path / "checks"
    checks.mkdir()
    source = checks / "check.py"
    source.write_bytes(b"original source")
    frozen = loop._tree_hash(tmp_path, ("checks",))

    cache = checks / "nested" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "_common.cpython-310.pyc").write_bytes(b"compiled code")
    (cache / "other.txt").write_bytes(b"also ignored")
    bytecode = checks / "check.pyc"
    bytecode.write_bytes(b"legacy compiled code")
    assert loop._tree_hash(tmp_path, ("checks",)) == frozen

    (cache / "_common.cpython-310.pyc").write_bytes(b"changed compiled code")
    bytecode.unlink()
    assert loop._tree_hash(tmp_path, ("checks",)) == frozen

    source.rename(checks / "renamed.py")
    renamed = loop._tree_hash(tmp_path, ("checks",))
    assert renamed != frozen  # Relative paths are part of the hash.
    (checks / "renamed.py").write_bytes(b"changed source")
    assert loop._tree_hash(tmp_path, ("checks",)) != renamed


def test_run_check_disables_bytecode_in_command_and_copied_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "0")
    monkeypatch.setenv("HT2WV_CHECK_TEST", "preserved")
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(stdout='{"pass": true, "detail": "ok"}', stderr="", returncode=0)

    monkeypatch.setattr(verifier.subprocess, "run", run)
    inp, out = tmp_path / "input", tmp_path / "output"
    assert verifier._run_check(tmp_path, "checks/check.py", inp, out) == (True, "ok")
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [sys.executable, "-B", str(tmp_path / "checks/check.py"),
                   "--input", str(inp), "--output", str(out)]
    assert kwargs["env"] == {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "0"
