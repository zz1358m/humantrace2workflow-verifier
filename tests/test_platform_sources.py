import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ht2wv import collect, config, consent, store
from ht2wv.sources import extra


@pytest.mark.parametrize("platform,browsers,powershell", [
    ("win32", {
        "chrome": "~/AppData/Local/Google/Chrome/User Data/Default/History",
        "edge": "~/AppData/Local/Microsoft/Edge/User Data/Default/History",
    }, "~/AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt"),
    ("darwin", {
        "chrome": "~/Library/Application Support/Google/Chrome/Default/History",
        "edge": "~/Library/Application Support/Microsoft Edge/Default/History",
        "chromium": "~/Library/Application Support/Chromium/Default/History",
    }, "~/.local/share/powershell/PSReadLine/ConsoleHost_history.txt"),
    ("linux", {
        "chrome": "~/.config/google-chrome/Default/History",
        "edge": "~/.config/microsoft-edge/Default/History",
        "chromium": "~/.config/chromium/Default/History",
    }, "~/.local/share/powershell/PSReadLine/ConsoleHost_history.txt"),
])
def test_platform_defaults(platform, browsers, powershell):
    defaults = config.platform_defaults(platform)
    assert defaults["browsers"] == browsers
    assert defaults["shell_history"] == [powershell, "~/.bash_history", "~/.zsh_history"]
    assert defaults["recent"] == ("~/AppData/Roaming/Microsoft/Windows/Recent" if platform == "win32" else None)


def _cfg(platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    cfg = config.load()
    defaults = config.platform_defaults(platform)
    cfg["sources"]["browsers"] = defaults["browsers"]
    cfg["sources"]["shell_history"] = defaults["shell_history"]
    monkeypatch.setattr(consent, "ssh_hosts", lambda cfg: [])
    monkeypatch.setattr(consent, "wsl_distros", lambda: [])
    monkeypatch.setattr(consent.shutil, "which", lambda name: None)
    return cfg


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_discover_native_paths_and_no_recent(platform, tmp_path, monkeypatch):
    cfg = _cfg(platform, monkeypatch)
    for path in [*cfg["sources"]["browsers"].values(), *cfg["sources"]["shell_history"]]:
        p = config.expand(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    original_stat = os.stat

    def native_stat(path, *args, **kwargs):
        assert "AppData" not in str(path).replace(str(tmp_path), "<tmp>")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", native_stat)
    found = {s.id: s for s in consent.discover(cfg)}
    assert all(found[sid].available for sid in [*cfg["sources"]["browsers"], "shell"])
    assert not found["recent"].available and found["recent"].note
    assert all("AppData" not in s.reads for s in found.values())
    assert extra.recent_files(0) == 0
    assert not store.days()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_local_shell_uses_discovered_candidates(platform, index, monkeypatch):
    cfg = _cfg(platform, monkeypatch)
    p = config.expand(cfg["sources"]["shell_history"][index])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f": 1767600100:0;echo history-{index}\n", encoding="utf-8")
    assert next(s for s in consent.discover(cfg) if s.id == "shell").available
    assert extra.shell_local(1767600050, cfg) == 1
    events = store.read_events(store.day_of(1767600100))
    assert [e["cmd"] for e in events] == [f"echo history-{index}"]
    assert all(e["src"] == "shell@local" for e in events)



def test_custom_shell_candidate_is_shared(tmp_path, monkeypatch):
    cfg = _cfg("linux", monkeypatch)
    p = tmp_path / "custom_history"
    p.write_text(": 1767600100:0;echo custom\n", encoding="utf-8")
    cfg["sources"]["shell_history"] = [str(p)]
    assert next(s for s in consent.discover(cfg) if s.id == "shell").available
    assert extra.shell_local(1767600050, cfg) == 1
    assert store.read_events(store.day_of(1767600100))[0]["cmd"] == "echo custom"


def test_user_path_overrides_preserve_merge(home):
    (home / "config.yaml").write_text(yaml.safe_dump({"sources": {
        "browsers": {"chrome": "~/custom/History"},
        "shell_history": ["~/custom/history"],
        "wsl": {"distros": ["Ubuntu Work"], "roots": {"Ubuntu Work": "D:/fixture"}},
    }}), encoding="utf-8")
    cfg = config.load()
    assert cfg["sources"]["browsers"]["chrome"] == "~/custom/History"
    assert cfg["sources"]["browsers"]["edge"] == config.DEFAULTS["sources"]["browsers"]["edge"]
    assert cfg["sources"]["shell_history"] == ["~/custom/history"]
    assert cfg["sources"]["wsl"] == {"distros": ["Ubuntu Work"], "roots": {"Ubuntu Work": "D:/fixture"}}


def _wsl_cfg(tmp_path, monkeypatch, distro="Ubuntu-26.04"):
    cfg = _cfg("win32", monkeypatch)
    monkeypatch.setattr(consent, "wsl_distros", lambda: [distro, "docker-desktop", "docker-desktop-data"])
    cfg["sources"]["wsl"] = {"distros": "auto", "roots": {distro: str(tmp_path / "distro")}}
    return cfg, tmp_path / "distro"


def test_wsl_discovery_never_stats_filesystem(tmp_path, monkeypatch):
    cfg, root = _wsl_cfg(tmp_path, monkeypatch)
    original_stat = os.stat

    def local_stat(path, *args, **kwargs):
        text = str(path).replace("/", "\\").lower()
        assert not text.startswith("\\\\wsl")
        assert not text.startswith(str(root).replace("/", "\\").lower())
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", local_stat)
    for roots in ({}, {"Ubuntu-26.04": str(root)}):
        cfg["sources"]["wsl"]["roots"] = roots
        found = {s.id: s for s in consent.discover(cfg)}
        assert found["wsl:Ubuntu-26.04"].available
        assert found["wsl-agents:Ubuntu-26.04"].available
        assert "/home" in found["wsl:Ubuntu-26.04"].reads and "/root" in found["wsl:Ubuntu-26.04"].reads
        assert ".claude/projects" in found["wsl-agents:Ubuntu-26.04"].reads
        assert ".codex/sessions" in found["wsl-agents:Ubuntu-26.04"].reads
        assert not any("docker-desktop" in sid for sid in found)


def test_wsl_explicit_selection_requires_registration(tmp_path, monkeypatch):
    cfg, _ = _wsl_cfg(tmp_path, monkeypatch)
    cfg["sources"]["wsl"]["distros"] = ["Ubuntu-26.04", "Missing", "docker-desktop"]
    found = {s.id: s for s in consent.discover(cfg)}
    assert found["wsl:Ubuntu-26.04"].available
    assert not found["wsl:Missing"].available and found["wsl:Missing"].note
    assert not found["wsl-agents:Missing"].available
    assert not any("docker-desktop" in sid for sid in found)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_wsl_unavailable_off_windows(platform, monkeypatch):
    cfg = _cfg(platform, monkeypatch)
    monkeypatch.setattr(consent, "wsl_distros", lambda: pytest.fail("WSL registry queried off Windows"))
    assert not any(s.id.startswith(("wsl:", "wsl-agents:")) for s in consent.discover(cfg))


def test_wsl_registry_errors_and_non_windows(monkeypatch):
    def fail(*args):
        raise OSError("registry unavailable")

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(OpenKey=fail, HKEY_CURRENT_USER=object()))
    monkeypatch.setattr(sys, "platform", "win32")
    assert consent.wsl_distros() == []
    monkeypatch.setattr(sys, "platform", "linux")
    assert consent.wsl_distros() == []


def test_wsl_registry_enumeration_filters_docker(monkeypatch):
    class Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    names = {"{a}": "Ubuntu-26.04", "{b}": "docker-desktop", "{c}": "Ubuntu Work"}
    fake = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=lambda parent, path: Key(path),
        QueryInfoKey=lambda key: (len(names), 0, 0),
        EnumKey=lambda key, i: list(names)[i],
        QueryValueEx=lambda key, value: (names[key.path], 1),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    assert consent.wsl_distros() == ["Ubuntu-26.04", "Ubuntu Work"]


def _write_logs(user_home, label):
    for path, text in {
        ".bash_history": ": 1767600000:0;echo old\n: 1767600100:0;echo " + label + "\n",
        ".claude/projects/p/s.jsonl": json.dumps({
            "timestamp": "2026-01-05T08:01:40Z", "type": "user",
            "message": {"content": "inspect " + label},
        }) + "\n",
        ".codex/sessions/x.jsonl": json.dumps({
            "timestamp": "2026-01-05T08:01:40Z", "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "check " + label}]},
        }) + "\n",
    }.items():
        p = user_home / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("distro", ["Ubuntu-26.04", "Ubuntu Work (26.04)"])
def test_wsl_collection_sources_stats_and_since(tmp_path, monkeypatch, distro):
    cfg, root = _wsl_cfg(tmp_path, monkeypatch, distro)
    for path, label in [("home/alice", "alice"), ("home/bob", "bob"), ("root", "root")]:
        _write_logs(root / path, label)
    consent.decide({f"wsl:{distro}": "allow", f"wsl-agents:{distro}": "allow"})
    calls = []
    original_replace = store.replace_source

    def replace(src, events, since, *args, **kwargs):
        calls.append((src, since))
        return original_replace(src, events, since, *args, **kwargs)

    monkeypatch.setattr(store, "replace_source", replace)
    since = 1767600050
    rep = collect.collect_allowed(since, cfg)
    host = "wsl-" + re.sub(r"[^A-Za-z0-9._-]", "_", distro)
    sources = {f"{kind}@{host}" for kind in ("shell", "claude", "codex")}
    events = [e for day in store.days() for e in store.read_events(day)]
    assert len(events) == 9 and {e["src"] for e in events} == sources
    assert all(e["host"] == host and e["t"] >= since for e in events)
    assert len(calls) == 3 and set(calls) == {(src, since) for src in sources}
    assert rep[f"wsl:{distro}"] == {"ok": True, "commands": 3}
    assert rep[f"wsl-agents:{distro}"]["claude"] == 3
    assert rep[f"wsl-agents:{distro}"]["codex"] == 3
    for kind in ("claude", "codex"):
        stats = rep["parse"][f"{kind}@{host}"]
        assert len(stats) == 3
        assert all(s["user_turns"] == s["prompts"] == 1 for s in stats.values())
    collect.collect_allowed(since, cfg)
    assert sum(len(store.read_events(day)) for day in store.days()) == 9


@pytest.mark.parametrize("allowed", [None, "wsl", "wsl-agents"])
def test_wsl_reads_require_separate_consent(tmp_path, monkeypatch, allowed):
    cfg, _ = _wsl_cfg(tmp_path, monkeypatch)
    calls = []

    def shell(*args):
        assert allowed == "wsl"
        calls.append("wsl")
        return {"ok": True, "commands": 0}

    def agents(*args):
        assert allowed == "wsl-agents"
        calls.append("wsl-agents")
        return {"ok": True, "parse": {}}

    monkeypatch.setattr(extra, "shell_wsl", shell)
    monkeypatch.setattr(extra, "agents_wsl", agents)
    if allowed:
        consent.decide({f"{allowed}:Ubuntu-26.04": "allow"})
    rep = collect.collect_allowed(1767600050, cfg)
    assert calls == ([allowed] if allowed else [])
    assert not any(isinstance(v, dict) and v.get("ok") is False for v in rep.values())
    if allowed is None:
        assert {"wsl:Ubuntu-26.04", "wsl-agents:Ubuntu-26.04"} <= set(rep["skipped_not_allowed"])
    assert not store.days()


def test_wsl_unc_root_fallback(tmp_path, monkeypatch):
    cfg, root = _wsl_cfg(tmp_path, monkeypatch)
    _write_logs(root / "home/alice", "alice")
    cfg["sources"]["wsl"]["roots"] = {}
    original_path = Path
    seen = []

    def path(value):
        text = str(value)
        if text.startswith("\\\\wsl"):
            seen.append(text)
            return tmp_path / "missing" if "wsl.localhost" in text else root
        return original_path(value)

    monkeypatch.setattr(extra, "Path", path)
    assert extra.shell_wsl("Ubuntu-26.04", 1767600050, cfg)["commands"] == 1
    assert seen == [r"\\wsl.localhost\Ubuntu-26.04", r"\\wsl$\Ubuntu-26.04"]


def test_wsl_unreadable_root_user_is_skipped(tmp_path, monkeypatch):
    cfg, root = _wsl_cfg(tmp_path, monkeypatch)
    _write_logs(root / "home/alice", "alice")
    _write_logs(root / "root", "root")
    original_stat = os.stat

    def readable_stat(path, *args, **kwargs):
        if str(path).startswith(str(root / "root")):
            raise PermissionError("root is private")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", readable_stat)
    consent.decide({"wsl:Ubuntu-26.04": "allow", "wsl-agents:Ubuntu-26.04": "allow"})
    rep = collect.collect_allowed(1767600050, cfg)
    assert rep["wsl:Ubuntu-26.04"]["commands"] == 1
    assert rep["wsl-agents:Ubuntu-26.04"]["claude"] == 1
    assert rep["wsl-agents:Ubuntu-26.04"]["codex"] == 1


def test_wsl_missing_root_reports_error_only_after_consent(tmp_path, monkeypatch):
    cfg, _ = _wsl_cfg(tmp_path, monkeypatch)
    consent.decide({"wsl:Ubuntu-26.04": "allow", "wsl-agents:Ubuntu-26.04": "allow"})
    rep = collect.collect_allowed(1767600050, cfg)
    for sid in ("wsl:Ubuntu-26.04", "wsl-agents:Ubuntu-26.04"):
        assert rep[sid]["ok"] is False
        assert "FileNotFoundError" in rep[sid]["error"]
    assert not store.days()


def test_windows_recent_still_collects(monkeypatch):
    cfg = _cfg("win32", monkeypatch)
    monkeypatch.setattr(consent, "wsl_distros", lambda: [])
    recent = config.expand(config.platform_defaults("win32")["recent"])
    recent.mkdir(parents=True)
    link = recent / "report.lnk"
    link.write_text("fake shortcut", encoding="utf-8")
    os.utime(link, (1767600100, 1767600100))
    assert next(s for s in consent.discover(cfg) if s.id == "recent").available
    assert extra.recent_files(1767600050) == 1
    assert store.read_events(store.day_of(1767600100)) == [
        {"t": 1767600100.0, "src": "recent", "k": "open", "name": "report"}]
