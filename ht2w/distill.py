"""Orchestrate the agent sessions: one to profile the person and list tasks, then one per skill."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import yaml

from . import agent, config, loop, store
from .compile import compile_day


def profile(days: list[str], cfg: dict) -> agent.Result:
    for d in days:
        compile_day(d, cfg)
    return agent.run("profile", agent.render("profile", days=", ".join(days)), config.home(), cfg)


def tasks() -> list[dict]:
    p = config.home() / "profile" / "tasks.yaml"
    if not p.exists():
        return []
    t = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("tasks", [])
    return sorted(t, key=lambda x: -float(x.get("score", 0)))


def build_skill(name: str, cfg: dict) -> dict:
    res = agent.run(f"skill-{name}", agent.render("skill", name=name), config.home(), cfg)
    out = {"skill": name, "session": res.session_dir.name, "agent_ok": res.ok, "cost": res.cost}
    if (config.home() / "skills" / name / "verifier.yaml").exists():
        lint = loop.lint(name)
        out.update(lint_ok=lint["ok"], lint_errors=lint["errors"], cases=len(lint["cases"]))
    else:
        out.update(lint_ok=False, lint_errors=["agent produced no verifier.yaml: " + res.text[:300]])
    return out


def distill(days: list[str] | None = None, top: int = 3, only: list[str] | None = None, parallel: int = 1,
            skip_profile: bool = False, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    days = days or store.days()[-1:]
    if not days:
        raise SystemExit("no traces yet: run `ht2w collect ...` or `ht2w record` first")
    report = {"days": days}
    if not skip_profile:
        res = profile(days, cfg)
        report["profile"] = {"session": res.session_dir.name, "ok": res.ok, "cost": res.cost, "summary": res.text[-1500:]}
        if cfg["agent"]["backend"] == "manual":
            return report
    names = only or [t["name"] for t in tasks()[:top]]
    report["tasks"] = names
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        report["skills"] = list(ex.map(lambda n: build_skill(n, cfg), names))
    report["spent_usd"] = round(agent.spent(), 4)
    return report
