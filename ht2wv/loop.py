"""Everything after extraction: lint, replay, optimise the workflow against a frozen verifier,
shadow-run next to the human, and feed corrections back into the verifier behind a human gate."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import yaml

from . import agent, config, verifier

AGENT_DIRS = {"claude": "~/.claude/skills", "codex": "~/.codex/skills"}


def skill_dir(name: str) -> Path:
    d = config.home() / "skills" / name
    if not (d / "verifier.yaml").exists():
        raise SystemExit(f"no such skill: {name} (looked in {d})")
    return d


def cases(name: str) -> list[dict]:
    out = []
    root = skill_dir(name) / "cases"
    for c in sorted(root.iterdir()) if root.exists() else []:
        meta = c / "case.yaml"
        if meta.exists() and (c / "output").is_dir():
            m = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            out.append({"id": c.name, "dir": c, "label": m.get("label"), **{k: v for k, v in m.items() if k != "label"}})
    return out


# ---- lint: is the verifier well-formed, and does it agree with what this person actually kept? ----
def lint(name: str, proposed: bool = False) -> dict:
    d = skill_dir(name)
    file = "verifier.proposed.yaml" if proposed else "verifier.yaml"
    errs = verifier.lint(d, file)
    rows = []
    if not any("unreadable" in e for e in errs):
        labelled = cases(name)
        by_id = {c["id"]: c for c in labelled}
        named_judges = {c["id"]: [] for c in labelled}
        for it in verifier.load(d, file)["items"]:
            if it.get("how") != "judge" or "cases" not in it:
                continue
            ids = it["cases"]
            if not isinstance(ids, list) or not all(isinstance(cid, str) for cid in ids):
                continue  # verifier.lint reports malformed cases fields
            for cid in ids:
                if cid not in by_id:
                    errs.append(f"{it['id']}: cases names unknown case {cid}")
                elif by_id[cid]["label"] != "reject":
                    errs.append(f"{it['id']}: case {cid} in cases must be labelled reject")
                else:
                    named_judges[cid].append(it["id"])
        for c in labelled:
            rep = verifier.run(d, c["dir"] / "output", c["dir"] / "input", file=file)
            failed = [r["id"] for r in rep["items"] if r["how"] == "check" and r["pass"] is False]
            broken = [r["id"] for r in rep["items"] if r["how"] == "check" and r["pass"] is None]
            errs += [f"case {c['id']}: check {b} crashed or printed no verdict" for b in broken]
            if c["label"] == "accept" and failed:
                errs.append(f"case {c['id']}: the person kept this output but checks {failed} fail on it")
            named = named_judges[c["id"]]
            coverage = "check:" + ",".join(failed) if failed else "none"
            verdict = rep["verdict"]
            depends_on = []
            if c["label"] == "accept" and verdict == "reject":
                errs.append(f"case {c['id']}: the person kept this output but the verifier verdict is reject")
            if c["label"] == "reject":
                if not failed and not named:
                    errs.append(f"case {c['id']}: the person rejected this output but nothing in the verifier can fail it; "
                                "a failing check or a judge item explicitly naming it in cases is required")
                if not failed and named:
                    coverage = "judge-named:" + ",".join(named)
                    depends_on = named
                    judgments = {iid: {"pass": False, "detail": f"expected failure for case {c['id']}; judge still pending"}
                                 for iid in named}
                    judged = verifier.run(d, c["dir"] / "output", c["dir"] / "input", judgments=judgments, file=file)
                    verdict = judged["verdict"]
                    if verdict != "reject":
                        errs.append(f"case {c['id']}: rejection depends on pending judge items {named}, "
                                    f"but with those items failed the verifier verdict is {verdict}, not reject")
                elif verdict == "accept":
                    errs.append(f"case {c['id']}: the person rejected this output but the verifier verdict is accept")
            rows.append({"case": c["id"], "label": c["label"], "checks_verdict": rep["verdict"], "failed": failed,
                         "pending": rep["pending"], "coverage": coverage, "verdict": verdict, "verdict_depends_on": depends_on})
    return {"skill": name, "file": file, "ok": not errs, "errors": errs, "cases": rows}


# ---- export: flattened, self-contained copy (used for sandboxes and for installing into an agent) ----
def export(name: str, dest: Path) -> Path:
    d = skill_dir(name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copyfile(d / "SKILL.md", dest / "SKILL.md")
    if (d / "checks").is_dir():
        shutil.copytree(d / "checks", dest / "checks")
    v = verifier.load(d)
    v.pop("inherits", None)  # personal style layer is merged in, so the copy stands alone
    (dest / "verifier.yaml").write_text(yaml.safe_dump(v, allow_unicode=True, sort_keys=False), encoding="utf-8")
    shutil.copyfile(Path(verifier.__file__), dest / "verify.py")
    return dest


def install(name: str, to: str) -> Path:
    root = config.expand(AGENT_DIRS.get(to, to))
    return export(name, root / name)


# ---- replay ----
def _new_run(kind: str, name: str) -> Path:
    d = config.home() / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{name}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def execute(name: str, input_dir: Path, run_dir: Path, cfg: dict) -> agent.Result:
    run_dir.mkdir(parents=True, exist_ok=True)
    export(name, run_dir / "skill")
    if (run_dir / "input").exists():
        shutil.rmtree(run_dir / "input")
    shutil.copytree(input_dir, run_dir / "input")
    (run_dir / "output").mkdir(exist_ok=True)
    return agent.run(f"execute-{name}", agent.render("execute"), run_dir, cfg)


def score(name: str, run_dir: Path, cfg: dict, judge: bool = True, file: str = "verifier.yaml") -> dict:
    d = skill_dir(name)
    v = verifier.load(d, file)
    judgments = None
    items = [{"id": i["id"], "claim": i["claim"], "rubric": i.get("rubric", "")} for i in v["items"] if i.get("how") == "judge"]
    if judge and items:
        (run_dir / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        (run_dir / "policy.json").write_text(json.dumps(v["policy"], ensure_ascii=False, indent=1), encoding="utf-8")
        (run_dir / "judgments.json").unlink(missing_ok=True)
        agent.run(f"judge-{name}", agent.render("judge"), run_dir, cfg)
        jp = run_dir / "judgments.json"
        if jp.exists():
            try:
                judgments = json.loads(jp.read_text(encoding="utf-8"))
            except ValueError:
                judgments = None
    rep = verifier.run(d, run_dir / "output", run_dir / "input", judgments, file=file)
    (run_dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def _tree_hash(d: Path, names: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for n in names:
        p = d / n
        for f in ([p] if p.is_file() else sorted(p.rglob("*")) if p.exists() else []):
            if f.is_file() and "__pycache__" not in f.relative_to(d).parts and f.suffix != ".pyc":
                h.update(f.relative_to(d).as_posix().encode())
                h.update(f.read_bytes())
    return h.hexdigest()


def _frozen_hash(d: Path) -> str:
    """Freeze verifier inputs, including the person-level style outside the skill."""
    h = hashlib.sha256(_tree_hash(d, ("verifier.yaml", "checks", "cases")).encode())
    v = yaml.safe_load((d / "verifier.yaml").read_text(encoding="utf-8")) or {}
    if v.get("inherits"):
        style = (d / v["inherits"]).resolve()
        if style.exists():
            h.update(b"\0inherited-style\0")
            h.update(style.read_bytes())
    return h.hexdigest()


def _round(name: str, ids: list[dict], rdir: Path, cfg: dict, judge: bool) -> float:
    scores = []
    for c in ids:
        cdir = rdir / c["id"]
        execute(name, c["dir"] / "input", cdir, cfg)
        rep = score(name, cdir, cfg, judge)
        scores.append(0.0 if rep["hard_fail"] else rep["score"])
    return sum(scores) / len(scores) if scores else 0.0


def optimize(name: str, rounds: int = 2, judge: bool = True, cfg: dict | None = None) -> dict:
    """Fix the verifier, search over workflows. A candidate SKILL.md is kept only if it does not
    lose on held-out cases; the improving agent never sees those."""
    cfg = cfg or config.load()
    d = skill_dir(name)
    cs = [c for c in cases(name) if (c["dir"] / "input").is_dir()]
    inputs = list({hashlib.sha1(_tree_hash(c["dir"], ("input",)).encode()).hexdigest(): c for c in cs}.values())  # one per distinct input
    if not inputs:
        raise SystemExit("no cases with input/ to replay")
    train, val = (inputs[0::2], inputs[1::2]) if len(inputs) > 1 else (inputs, inputs)
    run = _new_run("optimize", name)
    frozen = _frozen_hash(d)
    log = {"skill": name, "train": [c["id"] for c in train], "val": [c["id"] for c in val], "rounds": []}
    best_val = _round(name, val, run / "r0-val", cfg, judge)
    log["baseline_val"] = best_val
    for r in range(1, rounds + 1):
        tr = _round(name, train, run / f"r{r}-train", cfg, judge)
        backup = (d / "SKILL.md").read_text(encoding="utf-8")
        rel = (run / f"r{r}-train").relative_to(config.home()).as_posix()
        agent.run(f"improve-{name}", agent.render("improve", name=name, round_dir=rel), config.home(), cfg)
        entry = {"round": r, "train": tr}
        if _frozen_hash(d) != frozen:
            entry["status"] = "void: the verifier was modified"  # we cannot trust anything from this round
            log["rounds"].append(entry)
            (d / "SKILL.md").write_text(backup, encoding="utf-8")
            break
        v = _round(name, val, run / f"r{r}-val", cfg, judge)
        entry["val"] = v
        if v >= best_val:
            best_val, entry["status"] = v, "kept"
        else:
            (d / "SKILL.md").write_text(backup, encoding="utf-8")
            entry["status"] = "reverted"
        log["rounds"].append(entry)
        (run / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        if agent.spent() >= cfg["agent"]["budget_usd"]:
            log["stopped"] = "budget exhausted"
            break
    log["final_val"] = best_val
    log["spent_usd"] = round(agent.spent(), 4)
    (run / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return log


# ---- shadow run + feedback -> verifier ----
def shadow(name: str, input_dir: Path, human_dir: Path | None = None, judge: bool = True, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    run = _new_run("shadow", name)
    res = execute(name, input_dir, run, cfg)
    rep = score(name, run, cfg, judge)
    out = {"run": run.name, "verdict": rep["verdict"], "score": rep["score"], "executor_ok": res.ok}
    if human_dir:
        shutil.copytree(human_dir, run / "human")
        agent.run(f"compare-{name}", agent.render("compare"), run, cfg)
        if (run / "diff.yaml").exists():
            pdir = skill_dir(name) / "proposals"
            pdir.mkdir(exist_ok=True)
            shutil.copyfile(run / "diff.yaml", pdir / f"{run.name}.yaml")
            try:
                out["same_enough"] = (yaml.safe_load((run / "diff.yaml").read_text(encoding="utf-8")) or {}).get("same_enough")
            except yaml.YAMLError:
                pass
    (run / "shadow.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def feedback(run_name: str, label: str, note: str = "") -> dict:
    """The person's verdict on a run. It becomes a labelled case, i.e. new ground truth for the verifier."""
    run = config.home() / "runs" / run_name
    if not (run / "report.json").exists():
        raise SystemExit(f"no scored run at {run}")
    rep = json.loads((run / "report.json").read_text(encoding="utf-8"))
    name = rep["skill"]
    d = skill_dir(name)
    cid = f"fb-{run_name}"
    cdir = d / "cases" / cid
    if not cdir.exists():
        shutil.copytree(run / "input", cdir / "input")
        shutil.copytree(run / "output", cdir / "output")
    (cdir / "case.yaml").write_text(yaml.safe_dump({"label": label, "origin": f"feedback on {run_name}", "note": note}, allow_unicode=True), encoding="utf-8")
    row = {"t": round(time.time()), "run": run_name, "label": label, "note": note, "verifier_verdict": rep["verdict"],
           "verifier_version": rep.get("version"), "score": rep["score"], "failed": [r["id"] for r in rep["items"] if r["pass"] is False]}
    with open(d / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def evolve(name: str, cfg: dict | None = None) -> agent.Result:
    skill_dir(name)
    return agent.run(f"evolve-{name}", agent.render("evolve", name=name), config.home(), cfg or config.load())


def approve(name: str) -> str:
    d = skill_dir(name)
    prop = d / "verifier.proposed.yaml"
    if not prop.exists():
        raise SystemExit("nothing to approve")
    res = lint(name, proposed=True)
    if not res["ok"]:
        raise SystemExit("proposed verifier fails lint:\n  " + "\n  ".join(res["errors"]))
    old = yaml.safe_load((d / "verifier.yaml").read_text(encoding="utf-8")) or {}
    hist = d / "history"
    hist.mkdir(exist_ok=True)
    shutil.copyfile(d / "verifier.yaml", hist / f"verifier.v{old.get('version', 0)}.yaml")
    prop.replace(d / "verifier.yaml")
    return f"verifier v{old.get('version', 0)} archived to {hist}; proposed version is now live"


# ---- evaluation (proposal §4) ----
def evaluate(name: str, other_verifier: str | None = None) -> dict:
    """agreement: verifier verdict vs the person's label, on labelled cases (check items only unless reports exist).
    acceptance: share of runs the person accepted, in order, i.e. the learning curve.
    other_verifier: path to someone else's / a generic verifier.yaml -> its agreement with *this* person (the coupling control)."""
    d = skill_dir(name)
    file = "verifier.yaml"
    if other_verifier:
        shutil.copyfile(other_verifier, d / "_other.yaml")
        file = "_other.yaml"
    try:
        rows = []
        for c in cases(name):
            if c["label"] not in ("accept", "reject"):
                continue
            rep = verifier.run(d, c["dir"] / "output", c["dir"] / "input", file=file)
            rows.append({"case": c["id"], "label": c["label"], "verdict": rep["verdict"], "pending": len(rep["pending"])})
    finally:
        (d / "_other.yaml").unlink(missing_ok=True)
    agree = sum(r["label"] == r["verdict"] for r in rows)
    fb = [json.loads(ln) for ln in (d / "feedback.jsonl").read_text(encoding="utf-8").splitlines()] if (d / "feedback.jsonl").exists() else []
    curve, acc = [], 0
    for i, r in enumerate(fb, 1):
        acc += r["label"] == "accept"
        curve.append(round(acc / i, 3))
    return {"skill": name, "verifier": other_verifier or "own", "n_cases": len(rows),
            "agreement": round(agree / len(rows), 3) if rows else None,
            "false_accept": [r["case"] for r in rows if r["label"] == "reject" and r["verdict"] == "accept"],
            "false_reject": [r["case"] for r in rows if r["label"] == "accept" and r["verdict"] == "reject"],
            "note": "judge items are pending here; agreement reflects check items only" if any(r["pending"] for r in rows) else "",
            "feedback_runs": len(fb), "acceptance_curve": curve,
            "verifier_vs_person_on_runs": round(sum(r["label"] == r["verifier_verdict"] for r in fb) / len(fb), 3) if fb else None}
