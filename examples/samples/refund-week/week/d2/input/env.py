#!/usr/bin/env python
"""售后后台（模拟）。每条命令都是真实动作：执行了就记进 output/journal.jsonl，不能撤销。

  python input/env.py lookup  ORDER            查询订单：支付、发货、退货签收、最初申请时间，以及这单之前被做过什么
  python input/env.py refund  ORDER AMOUNT     退款。超过当日剩余额度会被支付系统拒绝（也会记入日志）
  python input/env.py restock ORDER            把退回的商品重新入库
  python input/env.py escalate ORDER REASON    升级给主管
  python input/env.py notify  ORDER TEMPLATE   通知买家。TEMPLATE: refunded | escalated | need_return | rejected
  python input/env.py status                   当日额度、累计退款、还挂着没结的单

后台记得以前每一天发生过的事（input/prev_state.json 是昨天收工时的状态），退款额度每天重置。
后台不会替你判断该不该做：退错了、退重了、通知早了，它都会照做。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path("output")
TEMPLATES = ("refunded", "escalated", "need_return", "rejected")


def load(base):
    OUT.mkdir(exist_ok=True)
    p = OUT / "state.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    prev = HERE / "prev_state.json"
    if prev.exists():  # a new day on top of everything that happened before
        state = json.loads(prev.read_text(encoding="utf-8"))
        state.update(day=base["day"], cap=base["daily_refund_cap"], refunded_today=0.0, declined_today=[])
        return state
    return {"day": base["day"], "cap": base["daily_refund_cap"], "refunded_today": 0.0, "declined_today": [],
            "refunds": {}, "restocked": [], "escalated": {}, "notified": {}}


def pending(state):
    rejected = {o for o, ts in state["notified"].items() if "rejected" in ts}
    return sorted(o for o in state["escalated"] if o not in state["refunds"] and o not in rejected)


def save(state, entry):
    (OUT / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    base = json.loads((HERE / "orders.json").read_text(encoding="utf-8"))
    orders, state, op = base["orders"], load(base), argv[0]
    if op == "status":
        print(json.dumps({"day": state["day"], "daily_refund_cap": state["cap"], "refunded_today": state["refunded_today"],
                          "remaining_today": round(state["cap"] - state["refunded_today"], 2), "refunded_orders_so_far": len(state["refunds"]),
                          "refunded_total_so_far": round(sum(state["refunds"].values()), 2), "pending": pending(state)}, ensure_ascii=False))
        return 0
    if len(argv) < 2 or argv[1] not in orders:
        print(f"unknown order: {argv[1:2]}")
        return 2
    oid, o = argv[1], orders[argv[1]]
    entry = {"op": op, "order": oid}
    if op == "lookup":
        print(json.dumps({"order": oid, **o, "already_refunded": state["refunds"].get(oid, 0.0), "escalated": state["escalated"].get(oid),
                          "notified_before": state["notified"].get(oid, [])}, ensure_ascii=False))
    elif op == "refund":
        amount = round(float(argv[2]), 2)
        entry["amount"] = amount
        if state["refunded_today"] + amount > state["cap"] + 1e-9:
            entry["result"] = "declined"
            state["declined_today"].append(oid)
            print(f"DECLINED: 超过当日退款额度（剩余 {state['cap'] - state['refunded_today']:.2f}）")
        else:
            entry["result"] = "ok"
            state["refunded_today"] = round(state["refunded_today"] + amount, 2)
            state["refunds"][oid] = round(state["refunds"].get(oid, 0.0) + amount, 2)
            print(f"OK: 已向 {oid} 退款 {amount:.2f}")
    elif op == "restock":
        state["restocked"].append(oid)
        print(f"OK: {o['sku']} 入库 +1")
    elif op == "escalate":
        entry["reason"] = " ".join(argv[2:])
        state["escalated"][oid] = entry["reason"]
        print(f"OK: {oid} 已升级给主管")
    elif op == "notify":
        if len(argv) < 3 or argv[2] not in TEMPLATES:
            print(f"template must be one of {TEMPLATES}")
            return 2
        entry["template"] = argv[2]
        state["notified"].setdefault(oid, []).append(argv[2])
        print(f"OK: 已通知 {oid} 的买家（{argv[2]}）")
    else:
        print(__doc__)
        return 2
    save(state, entry)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
