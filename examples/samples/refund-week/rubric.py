"""Rubric for one day of the refund week: python rubric.py --item R1 --input DIR --output DIR

Expected decisions come from her rules (policy.py) applied to the state this run really had at the start
of the day (input/prev_state.json), so each day is judged on its own.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy  # noqa: E402

ACTIONS = ("refund", "restock", "escalate", "notify")
TEMPLATE = {"refund": "refunded", "escalate": "escalated", "wait": "need_return", "rejected": "rejected"}


def read(inp: Path):
    base = json.loads((inp / "orders.json").read_text(encoding="utf-8"))
    reqs = list(csv.DictReader(open(inp / "requests.csv", encoding="utf-8")))
    appr = list(csv.DictReader(open(inp / "approvals.csv", encoding="utf-8"))) if (inp / "approvals.csv").exists() else []
    prev = json.loads((inp / "prev_state.json").read_text(encoding="utf-8")) if (inp / "prev_state.json").exists() else {}
    return base, reqs, appr, prev


def journal(out: Path) -> list[dict]:
    p = out / "journal.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.exists() else []


def expected(inp: Path) -> dict:
    base, reqs, appr, prev = read(inp)
    steps = policy.plan(base["orders"], reqs, appr, prev, base["daily_refund_cap"])
    out: dict = {}
    for s in steps:  # a repeat request for an order already handled today adds nothing
        if out.get(s["order"], ("none", None))[0] == "none":
            out[s["order"]] = (s["kind"], s["amount"] if s["kind"] == "refund" else None)
    return out


def actual(out: Path) -> dict:
    got: dict = {}
    for e in journal(out):
        oid = e["order"]
        if e["op"] == "refund" and e.get("result") == "ok":
            kind, amt = got.get(oid, ("refund", 0.0))
            got[oid] = ("refund", round((amt or 0.0) + e["amount"], 2))
        elif e["op"] == "escalate" and got.get(oid, ("", 0))[0] != "refund":
            got[oid] = ("escalate", None)
        elif e["op"] == "notify" and e["template"] in ("need_return", "rejected") and oid not in got:
            got[oid] = ("wait" if e["template"] == "need_return" else "rejected", None)
    return got


def r1(inp, out):
    miss = [f for f in ("REPORT.md", "journal.jsonl", "state.json") if not (out / f).exists()]
    if miss:
        return False, f"缺少 {miss}"
    prev = read(inp)[3]
    refunds = dict(prev.get("refunds", {}))
    for e in journal(out):  # replay: a hand-edited state would not match what the back office computes
        if e["op"] == "refund" and e.get("result") == "ok":
            refunds[e["order"]] = round(refunds.get(e["order"], 0) + e["amount"], 2)
    st = json.loads((out / "state.json").read_text(encoding="utf-8"))
    return refunds == st.get("refunds"), "state.json 与日志回放的结果不一致"


def r2(inp, out):
    want, got = expected(inp), actual(out)
    bad = []
    for oid in sorted(set(want) | set(got)):
        w, g = want.get(oid, ("none", None)), got.get(oid, ("none", None))
        if w != g:
            show = lambda x: x[0] + (f" {x[1]:.2f}" if x[1] is not None else "")
            bad.append(f"{oid}: 应为 {show(w)}，实际 {show(g)}")
    return not bad, "；".join(bad)


def r3(inp, out):
    seen, bad = set(), []
    for e in journal(out):
        if e["op"] == "lookup":
            seen.add(e["order"])
        elif e["op"] in ACTIONS and e["order"] not in seen:
            bad.append(f"{e['order']} 在查询之前就执行了 {e['op']}")
    return not bad, "；".join(dict.fromkeys(bad))


def r4(inp, out):
    j, bad = journal(out), []
    want = expected(inp)
    for oid in sorted(set(want) | {e["order"] for e in j}):
        kind = want.get(oid, ("none", None))[0]
        ops = [e for e in j if e["order"] == oid and e["op"] in ACTIONS]
        notes = [e for e in ops if e["op"] == "notify"]
        if kind == "none":
            if notes:
                bad.append(f"{oid} 今天不该通知买家")
        elif len(notes) != 1:
            bad.append(f"{oid} 通知了 {len(notes)} 次")
        elif ops[-1]["op"] != "notify":
            bad.append(f"{oid} 通知之后还有动作 {ops[-1]['op']}")
        elif notes[0]["template"] != TEMPLATE[kind]:
            bad.append(f"{oid} 模板应为 {TEMPLATE[kind]}，实际 {notes[0]['template']}")
    return not bad, "；".join(bad)


def r5(inp, out):
    prev = read(inp)[3]
    j = journal(out)
    declined = [e["order"] for e in j if e["op"] == "refund" and e.get("result") != "ok"]
    ok = [e["order"] for e in j if e["op"] == "refund" and e.get("result") == "ok"]
    again = sorted({o for o in ok if ok.count(o) > 1 or o in prev.get("refunds", {})})
    return not declined and not again, f"被拒绝的退款：{declined}；重复退款（含之前几天退过的）：{again}"


def _first_line(path: Path) -> str:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] if path.exists() else []
    return lines[0] if lines else ""


def _nums(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]


def r6(inp, out):
    j = journal(out)
    ok = [e for e in j if e["op"] == "refund" and e.get("result") == "ok"]
    n, total, esc = len({e["order"] for e in ok}), round(sum(e["amount"] for e in ok), 2), len({e["order"] for e in j if e["op"] == "escalate"})
    first = _first_line(out / "REPORT.md")
    nums = _nums(first)
    good = bool(first) and not first.startswith(("|", "#")) and len(first) <= 90 and total in nums and n in nums and esc in nums
    return good, f"第一行：{first!r}；后台今天：退款 {n} 单合计 {total:.2f}，升级 {esc} 单"


def r7(inp, out):
    st = json.loads((out / "state.json").read_text(encoding="utf-8"))
    rejected = {o for o, ts in st["notified"].items() if "rejected" in ts}
    pending = [o for o in st["escalated"] if o not in st["refunds"] and o not in rejected]
    n, total = len(st["refunds"]), round(sum(st["refunds"].values()), 2)
    first = _first_line(out / "WEEK.md")
    nums = _nums(first)
    good = bool(first) and not first.startswith(("|", "#")) and total in nums and n in nums and len(pending) in nums
    return good, f"WEEK.md 第一行：{first!r}；后台累计：退款 {n} 单合计 {total:.2f}，仍待处理 {len(pending)} 单"


ITEMS = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5, "R6": r6, "R7": r7}

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
