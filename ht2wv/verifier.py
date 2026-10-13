#!/usr/bin/env python
"""Run a personal verifier against a task output.

Self-contained on purpose (stdlib + pyyaml): `ht2wv install` copies this file into the skill as
`verify.py`, so the skill can check itself inside Claude Code / Codex without ht2wv installed.

verifier.yaml
  skill, version, kind: [tags]
  accept_threshold: 0.8
  inherits: path to the person-level acceptance-style.yaml (optional)
  policy:   how this person checks — check_depth, timing, on_fail, max_fix_rounds, escalate_when
  items:
    - id, layer (objective | style | preference), claim
      how: check   -> check: checks/x.py   (python x.py --input DIR --output DIR; last stdout line = {"pass": bool, "detail": str})
      how: judge   -> rubric: what a reviewer should look for
      cases: [<case id>, ...] (optional, judge only): existing reject cases this item is expected to fail
      weight, hard, confidence, source (observed | stated | corrected | hypothesized), evidence: ["<day>:<signal id>"]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

LAYERS = ("objective", "style", "preference")
SOURCES = ("observed", "stated", "corrected", "hypothesized")


def load(skill_dir: Path, file: str = "verifier.yaml") -> dict:
    skill_dir = Path(skill_dir)
    v = yaml.safe_load((skill_dir / file).read_text(encoding="utf-8")) or {}
    v.setdefault("items", [])
    v.setdefault("policy", {})
    inh = v.get("inherits")
    if inh:
        p = (skill_dir / inh).resolve()
        if p.exists():
            style = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            kinds = set(v.get("kind") or [])
            own = {i["id"] for i in v["items"]}
            for it in style.get("items", []):
                applies = it.get("applies_to", ["*"])
                if it["id"] not in own and ("*" in applies or kinds & set(applies)):
                    v["items"].append({**it, "layer": "style", "inherited": True})
            v["policy"] = {**style.get("policy", {}), **v["policy"]}
    return v


def lint(skill_dir: Path, file: str = "verifier.yaml") -> list[str]:
    skill_dir = Path(skill_dir)
    errs = []
    if not (skill_dir / "SKILL.md").exists():
        errs.append("SKILL.md missing")
    elif not (skill_dir / "SKILL.md").read_text(encoding="utf-8").lstrip().startswith("---"):
        errs.append("SKILL.md needs YAML frontmatter with name and description")
    try:
        v = load(skill_dir, file)
    except Exception as e:  # noqa: BLE001
        return errs + [f"{file} unreadable: {e}"]
    seen = set()
    if not any(i.get("layer") == "objective" for i in v["items"]):
        errs.append("no objective-layer item: every verifier needs at least one person-independent correctness check")
    for it in v["items"]:
        iid = it.get("id", "?")
        if iid in seen:
            errs.append(f"{iid}: duplicate id")
        seen.add(iid)
        if it.get("layer") not in LAYERS:
            errs.append(f"{iid}: layer must be one of {LAYERS}")
        if not it.get("claim"):
            errs.append(f"{iid}: claim missing")
        if it.get("how") == "check":
            if not it.get("check") or not (skill_dir / it["check"]).exists():
                errs.append(f"{iid}: check script not found: {it.get('check')}")
        elif it.get("how") == "judge":
            if not it.get("rubric"):
                errs.append(f"{iid}: judge item needs a rubric")
        else:
            errs.append(f"{iid}: how must be check or judge")
        if "cases" in it:
            if it.get("how") != "judge":
                errs.append(f"{iid}: cases is only allowed on how: judge items")
            if not isinstance(it["cases"], list) or not all(isinstance(cid, str) for cid in it["cases"]):
                errs.append(f"{iid}: cases must be a list of strings")
        src = it.get("source")
        if src not in SOURCES:
            errs.append(f"{iid}: source must be one of {SOURCES}")
        if it.get("layer") != "objective" and not it.get("inherited"):
            if src == "hypothesized":
                if it.get("confidence", 1) > 0.3 or it.get("hard"):
                    errs.append(f"{iid}: hypothesized items must have confidence <= 0.3 and cannot be hard")
            elif not it.get("evidence"):
                errs.append(f"{iid}: personal item without evidence; cite '<day>:<signal id>' or mark source: hypothesized")
    return errs


def _run_check(skill_dir: Path, script: str, inp: Path, out: Path) -> tuple[bool | None, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run([sys.executable, "-B", str(skill_dir / script), "--input", str(inp), "--output", str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return False, "check timed out"
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    try:
        res = json.loads(lines[-1])
        return bool(res["pass"]), str(res.get("detail", ""))
    except (IndexError, ValueError, KeyError, TypeError):
        return None, f"check did not report a verdict (exit {r.returncode}): {(r.stderr or r.stdout)[-300:]}"


def run(skill_dir: Path, output: Path, input: Path, judgments: dict | None = None, threshold: float | None = None,
        file: str = "verifier.yaml") -> dict:
    """`judgments` maps judge-item id -> {"pass": bool, "detail": str}; missing ones stay pending."""
    skill_dir = Path(skill_dir)
    v = load(skill_dir, file)
    judgments = judgments or {}
    rows = []
    for it in v["items"]:
        if it.get("how") == "check":
            ok, detail = _run_check(skill_dir, it["check"], Path(input), Path(output))
        else:
            j = judgments.get(it["id"])
            ok, detail = (bool(j["pass"]), str(j.get("detail", ""))) if j else (None, "pending judge: " + str(it.get("rubric", "")))
        rows.append({"id": it["id"], "layer": it.get("layer"), "claim": it.get("claim"), "how": it.get("how"), "pass": ok, "detail": detail,
                     "weight": float(it.get("weight", 1)), "hard": bool(it.get("hard"))})
    decided = [r for r in rows if r["pass"] is not None]
    total = sum(r["weight"] for r in decided)
    score = sum(r["weight"] for r in decided if r["pass"]) / total if total else 0.0
    hard_fail = [r["id"] for r in decided if r["hard"] and not r["pass"]]
    thr = threshold if threshold is not None else float(v.get("accept_threshold", 0.8))
    return {"skill": v.get("skill"), "version": v.get("version"), "score": round(score, 4), "threshold": thr,
            "verdict": "reject" if hard_fail or score < thr else "accept", "hard_fail": hard_fail,
            "pending": [r["id"] for r in rows if r["pass"] is None], "policy": v["policy"], "items": rows}


def render(rep: dict) -> str:
    out = [f"verdict: {rep['verdict'].upper()}  score {rep['score']:.2f} / threshold {rep['threshold']:.2f}"]
    for r in rep["items"]:
        mark = {True: "PASS", False: "FAIL", None: "TODO"}[r["pass"]]
        out.append(f"  [{mark}] {r['id']} ({r['layer']}{', hard' if r['hard'] else ''}, w={r['weight']:g}) {r['claim']}")
        if r["pass"] is not True and r["detail"]:
            out.append(f"         {r['detail']}")
    if rep["pending"]:
        out.append("TODO items need a reviewer's judgment (you, if you are the agent running this skill): "
                   "assess each against its rubric honestly, fix failures, then report them alongside this output.")
    if rep["policy"]:
        out.append("policy: " + json.dumps(rep["policy"], ensure_ascii=False))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run this skill's personal verifier on an output directory.")
    ap.add_argument("--skill", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--judgments", help="JSON file: {item id: {pass, detail}} for judge items")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    j = json.loads(Path(a.judgments).read_text(encoding="utf-8")) if a.judgments else None
    rep = run(Path(a.skill), Path(a.output), Path(a.input), j)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else render(rep))
    return 0 if rep["verdict"] == "accept" else 1


if __name__ == "__main__":
    raise SystemExit(main())
