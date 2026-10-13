"""Rubric for the weekly-report sample: python rubric.py --item R1 --input DIR --output DIR"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

LABEL = {"signups": "注册", "revenue_usd": "收入", "churn_pct": "流失率"}


def load(inp: Path, out: Path):
    weeks = sorted(re.search(r"W(\d+)", f.name).group(1) for f in inp.glob("metrics_W*.csv"))
    prev, cur = weeks[-2], weeks[-1]
    read = lambda w: {r["metric"]: r["value"] for r in csv.DictReader(open(inp / f"metrics_W{w}.csv", encoding="utf-8"))}
    report = out / f"weekly_W{cur}.md"
    text = report.read_text(encoding="utf-8") if report.exists() else ""
    return cur, prev, read(cur), read(prev), text


def line_of(text, label):
    return next((ln for ln in text.splitlines() if label in ln and ln.lstrip().startswith(("-", "*"))), "")


def pct(cur, prev):
    return (float(cur) - float(prev)) / float(prev) * 100


def r1(inp, out):
    cur = load(inp, out)[0]
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    return files == [f"weekly_W{cur}.md"], f"output files: {files}"


def r2(inp, out):
    _, _, cur, _, text = load(inp, out)
    bad = [LABEL[m] for m, v in cur.items() if not re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d.])", line_of(text, LABEL[m]))]
    return not bad, f"value missing or wrong on line: {bad}"


def r3(inp, out):
    _, _, cur, prev, text = load(inp, out)
    bad = [f"{LABEL[m]} expects {pct(cur[m], prev[m]):+.1f}%" for m in cur if f"{pct(cur[m], prev[m]):+.1f}%" not in line_of(text, LABEL[m])]
    return not bad, "; ".join(bad)


def r4(inp, out):
    _, _, cur, prev, text = load(inp, out)
    bad = []
    for m in cur:
        ln = line_of(text, LABEL[m])
        flagged = bool(re.match(r"\s*[-*]\s*⚠", ln))
        if flagged != (abs(pct(cur[m], prev[m])) > 20):
            bad.append(f"{LABEL[m]} {'should' if not flagged else 'should not'} be flagged")
    return not bad, "; ".join(bad)


def r5(inp, out):
    cur, prev, _, _, text = load(inp, out)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    ok = last.startswith("数据来源") and f"metrics_W{cur}.csv" in last and f"metrics_W{prev}.csv" in last
    return ok, f"last line: {last!r}"


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
