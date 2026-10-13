"""Rubric for the swe-bugfix sample: python rubric.py --item R1 --input DIR --output DIR"""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path


def r1(inp, out):
    files = sorted(p.name for p in out.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return files == ["COMMIT_MSG.txt", "pricing.py", "test_pricing.py"], f"output files: {files}"


def r2(inp, out):
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from pricing import final_price as f; "
            "assert f(100, True, 10) == 80.0, f(100, True, 10); assert f(5, False, 10) == 0, f(5, False, 10); "
            "assert f(100) == 100; assert f(200, member=True) == 180; print('ok')")
    r = subprocess.run([sys.executable, "-B", "-c", code, str(out)], capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stderr.strip().splitlines() or ["ok"])[-1][:200]


def _sig(path: Path):
    fn = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "final_price")
    return [a.arg for a in fn.args.args], [ast.unparse(d) for d in fn.args.defaults]


def r3(inp, out):
    return _sig(inp / "pricing.py") == _sig(out / "pricing.py"), f"{_sig(out / 'pricing.py')}"


def _tests(path: Path):
    return {n.name: ast.unparse(n) for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef)}


def r4(inp, out):
    before, after = _tests(inp / "test_pricing.py"), _tests(out / "test_pricing.py")
    bad = [n for n, src in before.items() if after.get(n) != src]
    return not bad, f"changed or removed: {bad}"


def r5(inp, out):
    text = (out / "COMMIT_MSG.txt").read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    issue = re.search(r"#(\d+)", (inp / "ISSUE.md").read_text(encoding="utf-8")).group(1)
    ok = bool(re.match(r"fix\(pricing\): \S", first)) and len(first) <= 72 and f"#{issue}" in text
    return ok, f"first line: {first!r}"


ITEMS = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        ok, detail = ITEMS[a.item](Path(a.input), Path(a.output))
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    print(json.dumps({"pass": bool(ok), "detail": detail}, ensure_ascii=False))
