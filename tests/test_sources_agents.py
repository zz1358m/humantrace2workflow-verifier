import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from ht2wv import collect as allowed_collect, config, consent, store
from ht2wv.sources import agents, extra


STAMP = "2026-01-05T12:00:00Z"
REMINDER = "<system-reminder>ctx</system-reminder>"


def _user(kind, content, timestamp=STAMP, **fields):
    if kind == "claude":
        return {"type": "user", "timestamp": timestamp,
                "message": {"content": content}, "cwd": "project", **fields}
    return {"type": "response_item", "timestamp": timestamp,
            "payload": {"type": "message", "role": "user", "content": content}, **fields}


def _text(kind, text):
    return [{"type": "text" if kind == "claude" else "input_text", "text": text}]


def _log(tmp_path, kind, records, session="session01"):
    root = tmp_path / kind
    path = root / "project" / (session + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "codex":
        records = [{"type": "session_meta", "timestamp": STAMP,
                    "payload": {"cwd": "project"}}] + records
    path.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in records), encoding="utf-8")
    return root, path


def _parse(kind, root, since=0, **kwargs):
    fn = agents.claude_code if kind == "claude" else agents.codex
    return fn(root, since, 4000, [], **kwargs)


def _prompts(events):
    return [e["text"] for e in events if e["k"] == "prompt"]


@pytest.mark.parametrize("kind", ["claude", "codex"])
@pytest.mark.parametrize("as_string", [False, True], ids=["blocks", "string"])
def test_reminder_prefix_keeps_real_user_text(tmp_path, kind, as_string):
    text = REMINDER + "\n真正的问题"
    content = text if as_string else _text(kind, text)
    root, _ = _log(tmp_path, kind, [_user(kind, content)])
    events = _parse(kind, root)
    assert _prompts(events) == ["真正的问题"]
    assert events[0]["cwd"] == "project"


@pytest.mark.parametrize("kind", ["claude", "codex"])
@pytest.mark.parametrize("tag", ["system-reminder", "ide_opened_file", "ide_selection", "environment_context"])
def test_tag_only_turn_is_empty(tmp_path, kind, tag):
    root, path = _log(tmp_path, kind, [_user(kind, _text(kind, f"<{tag}>injected</{tag}>"))])
    stats = {}
    assert _parse(kind, root, stats=stats) == []
    assert stats == {str(path): {"user_turns": 1, "prompts": 0, "dropped": {"empty": 1}}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_injected_prefixes_are_dropped_with_reasons(tmp_path, kind):
    injected = [
        ("<command-name>/help</command-name>", "noise:command-name"),
        ("Caveat: these are local command outputs", "noise:caveat"),
        ("This session is being continued from an earlier conversation", "noise:continuation"),
        ("# AGENTS.md instructions for project", "noise:agents_md"),
        ("<environment_context>cwd=project</environment_context>", "empty"),
        ("<user_instructions>follow these rules</user_instructions>", "noise:user_instructions"),
        ("<local-command-stdout>done</local-command-stdout>", "noise:local-command"),
        ("<task-notification>done</task-notification>", "noise:task-notification"),
        ("<turn_aborted>cancelled</turn_aborted>", "noise:turn_aborted"),
        ("<user_shell>ls</user_shell>", "noise:user_shell"),
        # Noise detection must also run on text revealed by stripping a reminder.
        (REMINDER + "\n<user_instructions>rules</user_instructions>", "noise:user_instructions"),
        (REMINDER + "\nCaveat: injected command output", "noise:caveat"),
    ]
    root, path = _log(tmp_path, kind, [_user(kind, _text(kind, text)) for text, _ in injected])
    stats = {}
    assert _parse(kind, root, stats=stats) == []
    dropped = {}
    for _, reason in injected:
        dropped[reason] = dropped.get(reason, 0) + 1
    assert stats == {str(path): {"user_turns": len(injected), "prompts": 0, "dropped": dropped}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_six_genuine_inputs_survive_mixed_log(tmp_path, kind):
    genuine = ["真正的问题", "please explain", "修复测试", "show the diff", "再检查一下", "finish"]
    injected = [REMINDER, "<ide_opened_file>project.py</ide_opened_file>",
                "<environment_context>project</environment_context>",
                "<user_instructions>rules</user_instructions>", "# AGENTS.md instructions for project"]
    records = []
    for i, text in enumerate(genuine):
        raw = REMINDER + "\n" + text if i % 2 == 0 else text
        records.append(_user(kind, raw if i % 2 else _text(kind, raw)))
        if i < len(injected):
            records.append(_user(kind, _text(kind, injected[i])))
    root, path = _log(tmp_path, kind, records)
    # Call without stats first so the regression fails on lost/extra prompts, not the new API.
    assert _prompts(_parse(kind, root)) == genuine
    stats = {}
    assert _prompts(_parse(kind, root, stats=stats)) == genuine
    assert stats == {str(path): {"user_turns": 11, "prompts": 6,
                                "dropped": {"empty": 3, "noise:user_instructions": 1, "noise:agents_md": 1}}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_tool_result_only_turn_is_not_a_prompt(tmp_path, kind):
    root, path = _log(tmp_path, kind, [_user(kind, [{"type": "tool_result", "content": "result"}])])
    assert _parse(kind, root) == []
    stats = {}
    assert _parse(kind, root, stats=stats) == []
    assert stats == {str(path): {"user_turns": 1, "prompts": 0, "dropped": {"tool_result": 1}}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_interruption_is_abort_not_prompt(tmp_path, kind):
    root, path = _log(tmp_path, kind, [_user(kind, _text(kind, "[Request interrupted by user for tool use]"))])
    events = _parse(kind, root)
    assert [e["k"] for e in events] == ["abort"]
    stats = {}
    assert _parse(kind, root, stats=stats) == events
    assert stats == {str(path): {"user_turns": 1, "prompts": 0, "dropped": {"abort": 1}}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_stats_are_per_file_and_include_timestamp_filters(tmp_path, kind):
    records = [_user(kind, _text(kind, "keep")),
               _user(kind, "old", timestamp="2026-01-04T12:00:00Z"),
               _user(kind, "bad timestamp", timestamp="invalid"), _user(kind, "   ")]
    dropped = {"before_since": 1, "invalid_timestamp": 1, "empty": 1}
    if kind == "claude":
        records.append(_user(kind, "sidechain", isSidechain=True))
        dropped["sidechain"] = 1
    root, first = _log(tmp_path, kind, records)
    _, second = _log(tmp_path, kind, [_user(kind, _text(kind, REMINDER + "\nsecond"))], "session02")
    since = agents._ts(STAMP) - 1
    stats = {}
    events = _parse(kind, root, since, stats=stats)
    assert sorted(_prompts(events)) == ["keep", "second"]
    assert stats == {
        str(first): {"user_turns": len(records), "prompts": 1, "dropped": dropped},
        str(second): {"user_turns": 1, "prompts": 1, "dropped": {}},
    }
    assert _parse(kind, root, since) == events
    for file_stats in stats.values():
        assert file_stats["user_turns"] == file_stats["prompts"] + sum(file_stats["dropped"].values())


def test_claude_tool_denial_and_reply_are_preserved(tmp_path):
    records = [
        {"type": "assistant", "timestamp": STAMP, "message": {"content": [
            {"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "reply"}]}},
        _user("claude", [{"type": "tool_result", "is_error": True, "content": "user rejected this tool"}]),
        _user("claude", _text("claude", "[Request interrupted by user]")),
        # Claude already drops mixed tool-result turns too.
        _user("claude", [{"type": "tool_result", "content": "result"}, {"type": "text", "text": "tool text"}]),
    ]
    root, path = _log(tmp_path, "claude", records)
    stats = {}
    events = _parse("claude", root, stats=stats)
    assert [e["k"] for e in events] == ["deny", "reply", "abort"]
    assert events[0]["tool"] == "Bash" and events[0]["text"] == "user rejected this tool"
    assert events[1]["text"] == "reply" and events[1]["tools"] == ["Bash"]
    assert stats == {str(path): {"user_turns": 3, "prompts": 0, "dropped": {"tool_result": 2, "abort": 1}}}


def test_codex_tool_reply_and_abort_events_are_preserved(tmp_path):
    records = [_user("codex", _text("codex", "question")),
               {"type": "response_item", "timestamp": STAMP, "payload": {"type": "function_call", "name": "shell"}},
               {"type": "event_msg", "timestamp": STAMP,
                "payload": {"type": "task_complete", "last_agent_message": "reply"}},
               {"type": "event_msg", "timestamp": STAMP, "payload": {"type": "turn_aborted", "reason": "user"}}]
    root, path = _log(tmp_path, "codex", records)
    stats = {}
    events = _parse("codex", root, stats=stats)
    assert [e["k"] for e in events] == ["prompt", "reply", "abort"]
    assert events[1]["text"] == "reply" and events[1]["tools"] == ["shell"]
    assert events[2]["reason"] == "user"
    assert stats == {str(path): {"user_turns": 1, "prompts": 1, "dropped": {}}}


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_cleaning_still_caps_and_redacts_prompts(tmp_path, kind):
    text = "prefix secret@example.com " + "x" * 200
    root, _ = _log(tmp_path, kind, [_user(kind, text)])
    fn = agents.claude_code if kind == "claude" else agents.codex
    events = fn(root, 0, 100, ["prefix"])
    assert _prompts(events) == [agents._clean(text, 100, ["prefix"])]
    assert "chars cut" in events[0]["text"] and "[EMAIL]" in events[0]["text"]
    assert "[REDACTED]" in events[0]["text"]


def _collector_config(tmp_path):
    cfg = config.load()
    paths = {}
    for kind in ("claude", "codex"):
        root, path = _log(tmp_path, kind, [_user(kind, _text(kind, REMINDER + "\nquestion"))])
        cfg["sources"][kind + "_dir"] = str(root)
        paths[kind] = path
    return cfg, paths


def test_collect_keeps_integer_counts_and_exposes_parse_stats(tmp_path, monkeypatch):
    cfg, paths = _collector_config(tmp_path)
    stored = {}
    monkeypatch.setattr(store, "replace_source", lambda source, events: stored.update({source: events}))
    report = agents.collect(0, cfg)
    assert report["claude"] == report["codex"] == 1
    assert report["parse"] == {
        kind: {str(path): {"user_turns": 1, "prompts": 1, "dropped": {}}} for kind, path in paths.items()
    }
    assert all(_prompts(events) == ["question"] for events in stored.values())
    report = agents.collect(0, cfg, only=("claude",))
    assert "codex" not in report and set(report["parse"]) == {"claude"}


def test_collect_allowed_preserves_counts_and_parse_stats(tmp_path, monkeypatch):
    cfg, paths = _collector_config(tmp_path)
    monkeypatch.setattr(consent, "decisions", lambda: {"claude": "allow", "codex": "allow"})
    monkeypatch.setattr(consent, "discover", lambda cfg: [SimpleNamespace(id=kind, available=True) for kind in paths])
    monkeypatch.setattr(consent, "ssh_hosts", lambda cfg: [])
    monkeypatch.setattr(store, "replace_source", lambda *args: None)
    report = allowed_collect.collect_allowed(0, cfg)
    assert report["claude"] == report["codex"] == 1
    assert report["parse"] == {
        kind: {str(path): {"user_turns": 1, "prompts": 1, "dropped": {}}} for kind, path in paths.items()
    }


def test_agents_remote_passes_through_parse_stats(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tf:
        for kind, sub in (("claude", ".claude/projects"), ("codex", ".codex/sessions")):
            record = _user(kind, _text(kind, REMINDER + "\nquestion"))
            body = (json.dumps(record) + "\n").encode("utf-8")
            member = tarfile.TarInfo(sub + "/project/session01.jsonl")
            member.size = len(body)
            member.mtime = agents._ts(STAMP)
            tf.addfile(member, io.BytesIO(body))
    monkeypatch.setattr(extra.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=archive.getvalue(), stderr=b"", returncode=0))
    stored = {}
    monkeypatch.setattr(store, "replace_source", lambda source, events: stored.update({source: events}))
    report = extra.agents_remote("testhost", 0, config.load())
    assert report["ok"] and report["claude"] == report["codex"] == 1
    for kind in ("claude", "codex"):
        sub = ".claude/projects" if kind == "claude" else ".codex/sessions"
        path = config.home() / "remote/testhost" / sub / "project/session01.jsonl"
        assert report["parse"][kind] == {str(path): {"user_turns": 1, "prompts": 1, "dropped": {}}}
        assert _prompts(stored[kind + "@testhost"]) == ["question"]
        assert stored[kind + "@testhost"][0]["host"] == "testhost"
