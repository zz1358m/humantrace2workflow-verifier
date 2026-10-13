"""Rubric for the refund-ops sample: python rubric.py --item R1 --input DIR --output DIR

The expected decisions are what this person would do; they are derived from her rules, which the
pipeline only ever sees through her records.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ACTIONS = ("refund", "restock", "escalate", "notify")


def journal(out: Path) -> list[dict]:
    return [json.loads(ln) for ln in (out / "journal.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]


def expected(inp: Path) -> dict:
    """order -> ("refund", amount) | ("escalate", None) | ("wait", None), following her rules in request-time order."""
    base = json.loads((inp / "orders.json").read_text(encoding="utf-8"))
    reqs = sorted(csv.DictReader(open(inp / "requests.csv", encoding="utf-8")), key=lambda r: r["requested_at"])
    spent, out = 0.0, {}
    for r in reqs:
        oid, o = r["order"], base["orders"][r["order"]]
        if oid in out:
            continue
        amount = o["amount"] - (o["shipping_fee"] if r["reason"].startswith("不想要") else 0)
        if o["amount"] > 500:
            out[oid] = ("escalate", None)
        elif o["shipped"] and not o["return_received"]:
            out[oid] = ("wait", None)
        elif spent + amount > base["daily_refund_cap"]:
            out[oid] = ("escalate", None)
        else:
            spent += amount
            out[oid] = ("refund", round(amount, 2))
    return out


def r1(inp, out):
    need = ["REPORT.md", "journal.jsonl", "state.json"]
    miss = [f for f in need if not (out / f).exists()]
    if miss:
        return False, f"missing {miss}"
    # replay the journal: a hand-written state would not match what the back office computes
    st = json.loads((out / "state.json").read_text(encoding="utf-8"))
    refunds: dict = {}
    for e in journal(out):
        if e["op"] == "refund" and e.get("result") == "ok":
            refunds[e["order"]] = round(refunds.get(e["order"], 0) + e["amount"], 2)
    return refunds == st.get("refunds"), "state.json does not match a replay of journal.jsonl"


def r2(inp, out):
    st = json.loads((out / "state.json").read_text(encoding="utf-8"))
    bad = []
    for oid, (kind, amount) in expected(inp).items():
        got = ("refund", st["refunds"][oid]) if oid in st["refunds"] else ("escalate", None) if oid in st["escalated"] \
            else ("wait", None) if "need_return" in st["notified"].get(oid, []) else ("nothing", None)
        if got != (kind, amount):
            bad.append(f"{oid}: 应为 {kind} {amount if amount is not None else ''}，实际 {got[0]} {got[1] if got[1] is not None else ''}".strip())
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
    want = {"refund": "refunded", "escalate": "escalated", "wait": "need_return"}
    for oid, (kind, _) in expected(inp).items():
        ops = [e for e in j if e["order"] == oid and e["op"] in ACTIONS]
        notes = [e for e in ops if e["op"] == "notify"]
        if len(notes) != 1:
            bad.append(f"{oid} 通知了 {len(notes)} 次")
        elif ops[-1]["op"] != "notify":
            bad.append(f"{oid} 的通知之后还有动作 {ops[-1]['op']}")
        elif notes[0]["template"] != want[kind]:
            bad.append(f"{oid} 模板应为 {want[kind]}，实际 {notes[0]['template']}")
    return not bad, "；".join(bad)


def r5(inp, out):
    j = journal(out)
    declined = [e["order"] for e in j if e["op"] == "refund" and e.get("result") != "ok"]
    ok_refunds = [e["order"] for e in j if e["op"] == "refund" and e.get("result") == "ok"]
    twice = sorted({o for o in ok_refunds if ok_refunds.count(o) > 1})
    return not declined and not twice, f"被拒绝的退款：{declined}；重复退款：{twice}"


def r6(inp, out):
    st = json.loads((out / "state.json").read_text(encoding="utf-8"))
    lines = [ln for ln in (out / "REPORT.md").read_text(encoding="utf-8").splitlines() if ln.strip()]
    first = lines[0] if lines else ""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", first)]
    ok = (not first.startswith(("|", "#")) and len(first) <= 80 and round(st["refunded_total"], 2) in nums
          and len(st["refunds"]) in nums and len(st["escalated"]) in nums)
    return ok, f"第一行：{first!r}；后台：退款 {len(st['refunds'])} 单合计 {st['refunded_total']:.2f}，升级 {len(st['escalated'])} 单"


ITEMS = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5, "R6": r6}

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
