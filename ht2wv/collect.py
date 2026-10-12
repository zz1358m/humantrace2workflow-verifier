"""Collect from every source the user has allowed, and only those."""
from __future__ import annotations

from . import config, consent
from .sources import agents, extra, misc


def collect_allowed(since: float, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    ok = {sid for sid, v in consent.decisions().items() if v == "allow"}
    available = {s.id for s in consent.discover(cfg) if s.available}
    report: dict = {"skipped_not_allowed": sorted(available - ok)}

    def step(sid, fn):
        if sid in ok and sid in available:
            try:
                report[sid] = fn()
            except Exception as e:  # noqa: BLE001 - one broken source must not stop the others
                report[sid] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    # agent logs first: git discovery reads the working directories they mention
    for name in ("claude", "codex"):
        step(name, lambda name=name: agents.collect(since, cfg, only=(name,)).get(name, 0))
    for name in cfg["sources"]["browsers"]:
        step(name, lambda name=name: misc.browsers(since, cfg, only=(name,)).get(name, 0))
    step("shell", lambda: extra.shell_local(since, cfg))
    for host in consent.ssh_hosts(cfg):
        step(f"ssh:{host}", lambda host=host: extra.shell_remote(host, since, cfg))
        step(f"ssh-agents:{host}", lambda host=host: extra.agents_remote(host, since, cfg))
    s = cfg["sources"]
    step("wx", lambda: misc.chat_export(s["wx_export"], s.get("wx_me") or "", "wx", cfg))
    step("recent", lambda: extra.recent_files(since))
    step("git", lambda: {"repos": (r := extra.discover_repos(since, cfg)), "commits": misc.git(since, cfg, r)})
    step("docs", lambda: extra.docs(since, cfg))
    return report
