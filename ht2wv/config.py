"""Paths and user config. Everything lives under one home dir so it can be inspected and deleted."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "agent": {
        "backend": "claude",  # claude | codex | manual
        "model": None,
        "effort": None,  # reasoning effort, e.g. "xhigh" (codex: model_reasoning_effort; claude: --effort)
        "context_window": None,  # codex only: model_context_window, in tokens
        "fast": False,  # codex only: service_tier = "fast"
        "max_turns": 80,
        "timeout_s": 3600,
        "budget_usd": 10.0,  # total cap across all agent sessions, enforced via ledger.jsonl
    },
    "screen": {
        "poll_s": 0.5,
        "idle_s": 120,
        "screenshots": True,
        "shot_interval_s": 60,
        "shot_max_width": 1280,
        "shot_quality": 60,
        "watch_dirs": [],  # dirs whose file saves are tracked (and small files versioned)
        "blob_max_bytes": 2_000_000,
        "blob_exts": [".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".tex", ".py", ".docx", ".xlsx", ".pptx"],
        "clip_preview": 120,  # chars of redacted clipboard text to keep; 0 = hash only
    },
    "privacy": {
        # window (exe or title) matching any of these is recorded as "[private]" and never screenshotted
        "deny": ["1password", "keepass", "bitwarden", "lastpass", "inprivate", "incognito", "无痕", "网银", "bank"],
        "redact_extra": [],  # extra regexes to mask
    },
    "sources": {
        "claude_dir": "~/.claude/projects",
        "codex_dir": "~/.codex/sessions",
        "browsers": {
            "chrome": "~/AppData/Local/Google/Chrome/User Data/Default/History",
            "edge": "~/AppData/Local/Microsoft/Edge/User Data/Default/History",
        },
        "git_repos": [],
        "ssh_hosts": [],  # user@host entries; hosts in ~/.ssh/config are picked up as well
        "shell_remote_tail": 5000,  # lines of each history file fetched from a server
        "shell_undated_tail": 300,  # history without timestamps: keep only the last N commands
        "wx_export": None,  # path to chat logs you exported yourself
        "wx_me": None,  # your display name in that export
        "doc_dirs": [],
        "msg_max_chars": 4000,  # per user message kept in the trace
    },
    "compile": {"episode_gap_s": 300, "glance_max_s": 60, "rework_min_gap_s": 60, "rework_max_gap_s": 7200},
    "verifier": {"accept_threshold": 0.8},
}


def home() -> Path:
    env = os.environ.get("HT2WV_HOME")
    return Path(env).expanduser() if env else Path(__file__).resolve().parent.parent / "data"


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = home() / "config.yaml"
    if p.exists():
        _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return cfg


def init_home() -> Path:
    h = home()
    for d in ("traces", "profile", "skills", "sessions", "runs"):
        (h / d).mkdir(parents=True, exist_ok=True)
    p = h / "config.yaml"
    if not p.exists():
        p.write_text(yaml.safe_dump(DEFAULTS, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return h


def day_dir(day: str) -> Path:
    d = home() / "traces" / day
    d.mkdir(parents=True, exist_ok=True)
    return d


def expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser()
