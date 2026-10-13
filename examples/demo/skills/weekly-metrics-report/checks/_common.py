import argparse
import csv
import json
import pathlib
import re


def load():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    inp, out = pathlib.Path(a.input), pathlib.Path(a.output)
    metrics, names = {}, []
    for f in sorted(inp.glob("metrics_*.csv")):
        names.append(f.name)
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                metrics[row["metric"]] = row["value"].strip()
    reports = sorted(out.glob("weekly_*.md"))
    return metrics, names, reports


def body_numbers(text: str) -> list[str]:
    """Numbers in the report body. The title line and the source line carry the week id, not data."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#") and "数据来源" not in ln]
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", "\n".join(lines))


def done(ok: bool, detail: str = ""):
    print(json.dumps({"pass": bool(ok), "detail": detail}, ensure_ascii=False))
