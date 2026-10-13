"""Rubric for the guest-reply sample: python rubric.py --item R1 --input DIR --output DIR"""
import argparse
import json
import re
import sys
from pathlib import Path


def reply(out: Path) -> str:
    p = out / "reply.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def r1(inp, out):
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    return files == ["reply.txt"], f"output files: {files}"


def r2(inp, out):
    t = reply(out)
    need = {"提前入住": r"13[:：点]", "宠物": r"(小型犬|宠物|小狗|狗)", "总价": r"1040"}
    miss = [k for k, rx in need.items() if not re.search(rx, t)]
    return not miss, f"not answered: {miss}"


def r3(inp, out):
    t = reply(out)
    ok = "520" in t and "1040" in t and "380" not in t
    return ok, "needs the holiday rate 520 and the total 1040, and must not quote the weekday rate"


def r4(inp, out):
    t = reply(out)
    grants = re.search(r"12[:：点](00)?[^。；;\n]{0,8}(可以|没问题|能办|行)(?!李)", t) and not re.search(r"12[:：点](00)?[^。；;\n]{0,10}(不|无法|安排不了|暂时)", t)
    return not grants and bool(re.search(r"13[:：点]", t)), "must not grant a 12:00 check-in; the earliest allowed is 13:00"


def r5(inp, out):
    n = len(re.sub(r"\s", "", reply(out)))
    return 0 < n <= 200, f"{n} characters"


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
