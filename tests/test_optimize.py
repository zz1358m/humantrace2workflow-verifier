import os
import shutil
import sys
import uuid
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
    def install(improve=None, execute=None):
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
                if execute is not None:
                    execute(cwd)
            elif kind.startswith("judge-"):
                pass  # No judgments file: inherited judge items remain pending.
            elif kind.startswith("improve-"):
                if improve is not None:
                    assert not add_dirs
                    improve(cwd)
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

    def improve(cwd):
        _append(cwd / "skill" / "SKILL.md", "\nChanged workflow.\n")
        _append(demo_skill / "checks" / "o1_numbers.py", "\n# Changed check.\n")

    fake_agent(improve)
    report = loop.optimize(SKILL, rounds=2, cfg=config.load())
    assert len(report["rounds"]) == 1
    assert report["rounds"][0]["status"] == "void: the verifier was modified"
    assert workflow.read_text(encoding="utf-8") == original


def test_inherited_style_edit_voids_round(demo_skill, fake_agent):
    style_path = demo_skill.parents[1] / "profile" / "acceptance-style.yaml"

    def improve(cwd):
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
    fake_agent(lambda cwd: _append(cwd / "skill" / "SKILL.md", change))
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert len(report["rounds"]) == 1
    assert "void" not in report["rounds"][0]["status"]
    assert report["rounds"][0]["status"] == "kept"
    assert workflow.read_text(encoding="utf-8") == original + change


def test_improver_cannot_discover_validation_canary(demo_skill, fake_agent):
    canary = str(uuid.uuid4())
    cs = loop.cases(SKILL)
    distinct = list({loop._tree_hash(c["dir"], ("input",)): c for c in cs}.values())
    val_hashes = {loop._tree_hash(c["dir"], ("input",)) for c in distinct[1::2]}
    val_cases = [c for c in cs if loop._tree_hash(c["dir"], ("input",)) in val_hashes]
    assert val_cases
    for c in val_cases:
        for subdir in ("input", "output"):
            (c["dir"] / subdir / "canary.txt").write_text(canary, encoding="utf-8")

    sandboxes, writes, val_outputs = [], [], []

    def execute(cwd):
        if cwd.parent.name.endswith("-val"):
            path = cwd / "output" / "run-canary.txt"
            path.write_text(canary, encoding="utf-8")
            val_outputs.append(path)

    def improve(cwd):
        sandboxes.append(cwd)
        contents = []
        for path in cwd.rglob("*"):
            try:
                contents.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                pass
        discovered = "\n".join(contents)
        # Also exercise the old data-root cwd so the regression fails on leakage.
        skill = cwd / "skill" if (cwd / "skill").is_dir() else demo_skill
        workflow = skill / "SKILL.md"
        _append(workflow, "\n" + discovered)
        changelog = skill / "CHANGELOG.md"
        changelog.write_text(discovered, encoding="utf-8")
        notes = cwd / "improver-notes.txt"
        notes.write_text(discovered, encoding="utf-8")
        writes.extend((path, path.read_text(encoding="utf-8")) for path in (workflow, changelog, notes))

    fake_agent(improve, execute)
    report = loop.optimize(SKILL, rounds=2, cfg=config.load())
    assert set(report["val"]) <= {c["id"] for c in val_cases}
    assert len(sandboxes) == len(set(sandboxes)) == 2
    assert val_outputs and all(canary in p.read_text(encoding="utf-8") for p in val_outputs)
    assert all(row["status"] == "kept" for row in report["rounds"])
    for filename in ("SKILL.md", "CHANGELOG.md"):
        assert canary not in (demo_skill / filename).read_text(encoding="utf-8")
    for run in (config.home() / "runs").iterdir():
        audits = list(run.glob("r*-improve"))
        assert len(audits) == 2
        for audit in audits:
            assert (audit / "SKILL.md").is_file()
            for path in audit.rglob("*"):
                if path.is_file():
                    assert canary not in path.read_text(encoding="utf-8")
    assert writes and all(canary not in contents for _, contents in writes)
    assert all(not path.exists() for path in sandboxes)
    assert all(not path.exists() for path, _ in writes)


def test_improver_gets_only_export_and_current_train_results(demo_skill, fake_agent):
    changelog = demo_skill / "CHANGELOG.md"
    changelog.write_text("Previous change.\n", encoding="utf-8")
    original = (demo_skill / "SKILL.md").read_text(encoding="utf-8")
    sandboxes, train_ids = [], []

    def execute(cwd):
        (cwd / "session.log").write_text("private session log", encoding="utf-8")
        (cwd / "skill" / "extra.txt").write_text("execution skill copy", encoding="utf-8")

    def improve(cwd):
        sandboxes.append(cwd)
        assert not cwd.resolve().is_relative_to(config.home().resolve())
        assert cwd.name.startswith("ht2wv-improve-")
        assert {p.name for p in cwd.iterdir()} == {"skill", "train"}
        skill = cwd / "skill"
        assert {p.name for p in skill.iterdir()} == {
            "SKILL.md", "CHANGELOG.md", "verifier.yaml", "verify.py", "checks"
        }
        objective = yaml.safe_load((skill / "verifier.yaml").read_text(encoding="utf-8"))
        assert "inherits" not in objective
        assert objective == {k: v for k, v in verifier.load(demo_skill).items() if k != "inherits"}
        assert (skill / "SKILL.md").read_text(encoding="utf-8") == original
        assert (skill / "CHANGELOG.md").read_text(encoding="utf-8") == "Previous change.\n"
        train = list((cwd / "train").iterdir())
        assert train
        train_ids.extend(p.name for p in train)
        for case in train:
            assert {p.name for p in case.iterdir()} == {"input", "output", "report.json"}
            source = next((config.home() / "runs").glob(f"*/r1-train/{case.name}"))
            assert {p.relative_to(case): p.read_bytes() for p in case.rglob("*") if p.is_file()} == {
                p.relative_to(source): p.read_bytes() for subdir in ("input", "output", "report.json")
                for p in ([source / subdir] if (source / subdir).is_file() else (source / subdir).rglob("*"))
                if p.is_file()
            }

    fake_agent(improve, execute)
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert train_ids == report["train"]
    assert report["rounds"][0]["status"] == "kept"
    assert sandboxes and all(not p.exists() for p in sandboxes)


def test_sandbox_changes_copy_back_only_workflow_and_changelog(demo_skill, fake_agent):
    frozen = loop._frozen_hash(demo_skill)
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")
    change = "\nUpdated sandbox workflow.\n"
    sandboxes = []

    def improve(cwd):
        sandboxes.append(cwd)
        skill = cwd / "skill"
        _append(skill / "SKILL.md", change)
        (skill / "CHANGELOG.md").write_text("Changed workflow steps.\n", encoding="utf-8")
        _append(skill / "checks" / "o1_numbers.py", "\n# Changed sandbox check.\n")
        (skill / "verifier.yaml").write_text("items: []\n", encoding="utf-8")
        (skill / "verify.py").write_text("changed verifier runner", encoding="utf-8")
        (skill / "extra.txt").write_text("not copied", encoding="utf-8")
        (cwd / "extra.txt").write_text("not copied either", encoding="utf-8")

    fake_agent(improve)
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert report["rounds"][0]["status"] == "kept"
    assert loop._frozen_hash(demo_skill) == frozen
    assert workflow.read_text(encoding="utf-8") == original + change
    assert (demo_skill / "CHANGELOG.md").read_text(encoding="utf-8") == "Changed workflow steps.\n"
    assert not (demo_skill / "extra.txt").exists()
    assert not (demo_skill / "verify.py").exists()
    assert not (config.home() / "extra.txt").exists()
    audit = next((config.home() / "runs").glob("*/r1-improve"))
    assert {p.name for p in audit.iterdir()} == {"SKILL.md"}
    assert (audit / "SKILL.md").read_text(encoding="utf-8") == original + change
    assert sandboxes and all(not p.exists() for p in sandboxes)


@pytest.mark.parametrize("candidate", [
    "---\nname: renamed-skill\n---\nChanged workflow.\n",
    "No frontmatter.\n",
    "---\nname: [broken\n---\nChanged workflow.\n",
    "---\n- not-a-mapping\n---\nChanged workflow.\n",
    "---\ndescription: Missing name\n---\nChanged workflow.\n",
    f"---\nname: {SKILL}\nMissing closing delimiter.\n",
])
def test_invalid_workflow_frontmatter_reverts_round(demo_skill, fake_agent, candidate):
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")
    sandboxes = []

    def improve(cwd):
        sandboxes.append(cwd)
        (cwd / "skill" / "SKILL.md").write_text(candidate, encoding="utf-8")

    fake_agent(improve)
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert report["rounds"][0]["status"] == f"reverted: SKILL.md needs frontmatter with name {SKILL}"
    assert workflow.read_text(encoding="utf-8") == original
    assert report["final_val"] == report["baseline_val"]
    audit = next((config.home() / "runs").glob("*/r1-improve/SKILL.md"))
    assert audit.read_text(encoding="utf-8") == candidate
    assert sandboxes and all(not p.exists() for p in sandboxes)


def test_worse_validation_restores_workflow_and_keeps_candidate_audit(demo_skill, fake_agent):
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")
    change = "\nCandidate workflow.\n"

    def execute(cwd):
        if cwd.parent.name == "r1-val":
            _append(next((cwd / "output").glob("weekly_*.md")), "\n- Unexpected: 999999.\n")

    fake_agent(lambda cwd: _append(cwd / "skill" / "SKILL.md", change), execute)
    report = loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert report["rounds"][0]["status"] == "reverted"
    assert report["rounds"][0]["val"] < report["baseline_val"]
    assert report["final_val"] == report["baseline_val"]
    assert workflow.read_text(encoding="utf-8") == original
    audit = next((config.home() / "runs").glob("*/r1-improve/SKILL.md"))
    assert audit.read_text(encoding="utf-8") == original + change


def test_sandbox_removed_when_improver_raises(demo_skill, fake_agent):
    workflow = demo_skill / "SKILL.md"
    original = workflow.read_text(encoding="utf-8")
    sandboxes = []

    def improve(cwd):
        sandboxes.append(cwd)
        _append(cwd / "skill" / "SKILL.md", "\nPartial edit.\n")
        raise RuntimeError("improver failed")

    fake_agent(improve)
    with pytest.raises(RuntimeError, match="improver failed"):
        loop.optimize(SKILL, rounds=1, cfg=config.load())
    assert sandboxes and all(not p.exists() for p in sandboxes)
    assert workflow.read_text(encoding="utf-8") == original


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
