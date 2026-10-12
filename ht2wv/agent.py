"""Open a headless session in someone else's coding agent (Claude Code / Codex) and let it do the reading.

Every session is a directory under sessions/ holding the TASK.md it was given and what came back,
so a run can be audited or re-issued by hand. Spend is metered in ledger.jsonl against a hard cap.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

TOOLS = "Read,Glob,Grep,Write,Edit,Bash(python:*),Bash(ls:*),Bash(git log:*)"


@dataclass
class Result:
    ok: bool
    text: str
    cost: float
    session_dir: Path


def spent() -> float:
    p = config.home() / "ledger.jsonl"
    if not p.exists():
        return 0.0
    return sum(json.loads(ln).get("cost", 0) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())


def _ledger(kind: str, cost: float, backend: str, ok: bool):
    with open(config.home() / "ledger.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time()), "kind": kind, "backend": backend, "cost": cost, "ok": ok}) + "\n")


def run(kind: str, task: str, cwd: Path, cfg: dict | None = None, add_dirs: tuple = ()) -> Result:
    cfg = cfg or config.load()
    ac = cfg["agent"]
    base = config.home() / "sessions" / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}"
    sdir, n = base, 1
    while True:  # sessions may be launched in parallel
        try:
            sdir.mkdir(parents=True)
            break
        except FileExistsError:
            n += 1
            sdir = base.with_name(f"{base.name}~{n}")
    (sdir / "TASK.md").write_text(task, encoding="utf-8")
    backend = ac["backend"]
    remaining = ac["budget_usd"] - spent()
    if backend != "manual" and remaining <= 0:
        (sdir / "result.txt").write_text("skipped: budget exhausted", encoding="utf-8")
        return Result(False, f"budget of ${ac['budget_usd']} exhausted (see ledger.jsonl)", 0.0, sdir)

    if backend == "manual":
        msg = f"manual backend: open your agent in {cwd} and give it {sdir / 'TASK.md'}"
        (sdir / "result.txt").write_text(msg, encoding="utf-8")
        return Result(False, msg, 0.0, sdir)

    exe = shutil.which(backend)
    if not exe:
        return Result(False, f"`{backend}` CLI not found on PATH", 0.0, sdir)
    if backend == "claude":
        cmd = [exe, "-p", "--output-format", "json", "--max-turns", str(ac["max_turns"]), "--permission-mode", "acceptEdits",
               "--allowedTools", TOOLS, "--max-budget-usd", f"{remaining:.2f}"]
        if ac.get("model"):
            cmd += ["--model", ac["model"]]
        for d in add_dirs:
            cmd += ["--add-dir", str(d)]
    elif backend == "codex":
        cmd = [exe, "exec", "-s", "workspace-write", "--skip-git-repo-check", "--color", "never", "-C", str(cwd),
               "-o", str(sdir / "last_message.txt")]
        if ac.get("model"):
            cmd += ["-m", ac["model"]]
        cmd += ["-"]
    else:
        return Result(False, f"unknown backend {backend}", 0.0, sdir)
    try:
        r = subprocess.run(cmd, input=task, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=ac["timeout_s"])
    except subprocess.TimeoutExpired:
        _ledger(kind, 0.0, backend, False)
        return Result(False, "agent session timed out", 0.0, sdir)
    text, cost, ok = r.stdout, 0.0, r.returncode == 0
    if backend == "claude":
        try:
            j = json.loads(r.stdout)
            text, cost = j.get("result") or "", float(j.get("total_cost_usd") or 0)
            ok = ok and not j.get("is_error")
        except ValueError:
            pass
    elif (sdir / "last_message.txt").exists():  # codex reports no cost, so the budget cap only meters claude sessions
        text = (sdir / "last_message.txt").read_text(encoding="utf-8", errors="replace")
    if not ok and not text.strip():
        text = r.stderr.strip()[-1500:]
    (sdir / "result.txt").write_text(text + ("\n\n[stderr]\n" + r.stderr[-4000:] if r.stderr.strip() else ""), encoding="utf-8")
    _ledger(kind, cost, backend, ok)
    return Result(ok, text, cost, sdir)


def render(template: str, /, **vars) -> str:
    text = (Path(__file__).parent / "prompts" / f"{template}.md").read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text
