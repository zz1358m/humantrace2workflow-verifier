"""Rubric for the video-publish sample: python rubric.py --item R1 --input DIR --output DIR"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIELDS = ["title", "description", "tags", "publish_at", "thumbnail_text"]


def data(out: Path) -> dict:
    return json.loads((out / "publish.json").read_text(encoding="utf-8"))


def notes(inp: Path) -> str:
    return (inp / "video_notes.md").read_text(encoding="utf-8")


def r1(inp, out):
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    if files != ["publish.json"]:
        return False, f"output files: {files}"
    miss = [f for f in FIELDS if f not in data(out)]
    return not miss, f"missing fields: {miss}"


def r2(inp, out):
    chapter_line = next(ln for ln in notes(inp).splitlines() if "章节" in ln)
    want = re.findall(r"\d{2}:\d{2}", chapter_line)
    got = re.findall(r"\d{2}:\d{2}", data(out)["description"])
    ok = [t for t in got if t in want] == want and got[:1] == ["00:00"]
    return ok, f"want {want}, description has {got}"


def r3(inp, out):
    n = len(data(out)["title"])
    return 0 < n <= 20, f"title has {n} characters"


def r4(inp, out):
    shot = datetime.strptime(re.search(r"拍摄日期[:：]\s*(\d{4}-\d{2}-\d{2})", notes(inp)).group(1), "%Y-%m-%d")
    days = (5 - shot.weekday()) % 7 or 7  # the next Saturday strictly after the shoot
    want = (shot + timedelta(days=days)).replace(hour=18, tzinfo=timezone(timedelta(hours=8)))
    got = datetime.fromisoformat(str(data(out)["publish_at"]))
    return got.tzinfo is not None and got == want, f"want {want.isoformat()}, got {data(out)['publish_at']}"


def r5(inp, out):
    tags = data(out)["tags"]
    return isinstance(tags, list) and 5 <= len(tags) <= 8 and len(set(tags)) == len(tags), f"{len(tags)} tags"


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
