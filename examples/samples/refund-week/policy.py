"""What this person would do on a given day, given everything that already happened.

Used twice: to build the reference week (make_week.py) and to grade a run (rubric.py). The grade is
conditional: each day is judged against her rules applied to the state the run actually left behind
the day before, so one bad day does not automatically fail the rest of the week.

`break_rule` re-plans the day with exactly one of her rules ignored; that is how the probes are made.
"""
from __future__ import annotations


def buyer_caused(o: dict) -> bool:
    return o["reason"].startswith("不想要")


def plan(orders: dict, requests: list[dict], approvals: list[dict], prev: dict, cap: float, break_rule: str | None = None) -> list[dict]:
    refunds = dict(prev.get("refunds", {}))
    escalated = dict(prev.get("escalated", {}))
    notified = {k: list(v) for k, v in prev.get("notified", {}).items()}
    rejected_before = {o for o, ts in notified.items() if "rejected" in ts}
    decided = {a["order"]: a["decision"] == "approved" for a in approvals}
    if break_rule == "L2":  # approvals are not acted on until the buyer chases
        decided = {o: ok for o, ok in decided.items() if not ok}
    if break_rule == "L5":  # rejections are silently dropped
        decided = {o: ok for o, ok in decided.items() if ok}
    # carried over: escalated only because yesterday's cap ran out
    carry = [o for o in escalated if o not in refunds and o not in rejected_before and orders[o]["amount"] <= 500]
    old = [(o, "approval") for o in decided] + [(o, "carry") for o in carry]
    new = [(r["order"], "request") for r in requests]
    key = lambda x: orders[x[0]]["first_requested_at"]
    if break_rule == "S1":  # today's sheet in row order
        queue = sorted(old, key=key) + new
    elif break_rule == "L1":  # yesterday's leftovers after today's new requests
        queue = sorted(new, key=key) + sorted(old, key=key)
    else:  # her rule: one queue, oldest first request first
        queue = sorted(old + new, key=key)

    steps, spent, seen = [], 0.0, set()
    for oid, src in queue:
        o = orders[oid]
        if oid in seen:
            if src == "request":
                steps.append({"order": oid, "kind": "none", "label": "duplicate", "amount": 0.0, "why": "重复申请"})
            continue
        seen.add(oid)
        due = round(o["amount"] - (o["shipping_fee"] if buyer_caused(o) and break_rule != "S2" else 0), 2)
        if oid in refunds:
            if break_rule == "L4" and src == "request" and spent + due <= cap:  # pays an already refunded order again
                spent += due
                steps.append({"order": oid, "kind": "refund", "label": "refund", "amount": due, "why": "再次申请，已退款"})
            else:
                steps.append({"order": oid, "kind": "none", "label": "duplicate", "amount": 0.0, "why": "此前已退款，重复申请"})
            continue
        if decided.get(oid) is False:
            steps.append({"order": oid, "kind": "rejected", "label": "rejected", "amount": 0.0, "why": "主管驳回，已通知买家"})
            continue
        if o["amount"] > 500 and decided.get(oid) is not True and break_rule != "S3":
            if oid in escalated:
                steps.append({"order": oid, "kind": "none", "label": "awaiting", "amount": o["amount"], "why": "仍在等主管审批"})
            else:
                steps.append({"order": oid, "kind": "escalate", "label": "escalate", "amount": o["amount"], "why": "超过 ¥500 需主管审批",
                              "reason": "超过500需主管审批"})
            continue
        if break_rule == "L3" and src == "request" and oid in notified:  # a return that has now arrived is treated as a duplicate
            steps.append({"order": oid, "kind": "none", "label": "duplicate", "amount": 0.0, "why": "重复申请"})
            continue
        if o["shipped"] and not o["return_received"] and break_rule != "S5":
            steps.append({"order": oid, "kind": "wait", "label": "wait", "amount": 0.0, "why": "退货未签收，已通知先寄回"})
            continue
        if spent + due > cap:
            left = round(cap - spent, 2)
            if break_rule == "S10" and left > 0:  # splits the refund to use up the cap
                spent += left
                steps.append({"order": oid, "kind": "refund", "label": "refund", "amount": left, "why": f"额度只剩 ¥{left:.2f}，先退一部分"})
            elif oid in escalated:
                steps.append({"order": oid, "kind": "none", "label": "still_pending", "amount": due, "why": f"额度仍不足（剩余 ¥{left:.2f}）"})
            else:
                steps.append({"order": oid, "kind": "escalate", "label": "escalate", "amount": due, "why": f"当日额度不足（剩余 ¥{left:.2f}）",
                              "reason": "当日额度不足"})
            continue
        spent += due
        why = "主管已批准，" if decided.get(oid) else ""
        why += "未发货，全额" if not o["shipped"] else f"买家原因，扣运费 ¥{o['shipping_fee']:.2f}" if buyer_caused(o) and break_rule != "S2" \
            else "买家原因，全额" if buyer_caused(o) else "质量问题，全额"
        steps.append({"order": oid, "kind": "refund", "label": "refund", "amount": due, "why": why})
    return steps


def commands(steps: list[dict], orders: dict, break_rule: str | None = None) -> list[list[str]]:
    """The back-office calls she would make, in her order: look first, money before goods, the buyer last."""
    out = []
    for s in steps:
        oid = s["order"]
        if s["kind"] == "none":
            continue
        out.append(["lookup", oid])
        if s["kind"] == "refund":
            if break_rule == "S4":
                out.append(["notify", oid, "refunded"])
            out.append(["refund", oid, f"{s['amount']:.2f}"])
            if orders[oid]["return_received"]:
                out.append(["restock", oid])
            if break_rule != "S4":
                out.append(["notify", oid, "refunded"])
        elif s["kind"] == "escalate":
            out += [["escalate", oid, s["reason"]], ["notify", oid, "escalated"]]
        elif s["kind"] == "wait":
            out.append(["notify", oid, "need_return"])
        elif s["kind"] == "rejected":
            out.append(["notify", oid, "rejected"])
    return out


def day_stats(steps: list[dict]) -> dict:
    ref = [s for s in steps if s["kind"] == "refund"]
    return {"handled": sum(1 for s in steps if s["label"] != "duplicate"), "refunded": len(ref), "amount": round(sum(s["amount"] for s in ref), 2),
            "escalated": sum(1 for s in steps if s["kind"] == "escalate"), "waiting": sum(1 for s in steps if s["kind"] == "wait"),
            "rejected": sum(1 for s in steps if s["kind"] == "rejected"), "duplicates": sum(1 for s in steps if s["label"] == "duplicate")}


def report(steps: list[dict], n_requests: int) -> str:
    """Her daily report: the verdict in one line, what needs her first, one order per row, nothing else.
    The first line opens with how many requests came in today, the way the reports she kept do."""
    st = day_stats(steps)
    lines = [f"今日 {n_requests} 条申请：退款 {st['refunded']} 单合计 ¥{st['amount']:.2f}，升级 {st['escalated']} 单，"
             f"暂不退 {st['waiting']} 单，" + (f"驳回 {st['rejected']} 单，" if st["rejected"] else "") + f"重复 {st['duplicates']} 条。", "",
             "| 订单 | 处理 | 金额 | 原因 |", "|---|---|---|---|"]
    name = {"escalate": "【待你处理】升级", "still_pending": "【待你处理】仍未退", "awaiting": "待主管审批", "refund": "已退款",
            "wait": "暂不退", "rejected": "已驳回"}
    rank = {"escalate": 0, "still_pending": 0, "awaiting": 1, "refund": 2, "wait": 3, "rejected": 3}
    rows = [s for s in steps if s["label"] != "duplicate"]
    lines += [f"| {s['order']} | {name[s['label']]} | ¥{s['amount']:.2f} | {s['why']} |" for s in sorted(rows, key=lambda s: rank[s["label"]])]
    dups = [s["order"] for s in steps if s["label"] == "duplicate"]
    if dups:
        lines += ["", "重复申请：" + "、".join(dups) + "，未重复处理。"]
    return "\n".join(lines) + "\n"


def week_report(days: list[tuple[str, dict]], state: dict, pending: list[str]) -> str:
    total = round(sum(state["refunds"].values()), 2)
    lines = [f"本周共退款 {len(state['refunds'])} 单合计 ¥{total:.2f}，截至周日仍待处理 {len(pending)} 单。", "",
             "| 日期 | 退款 | 金额 | 升级 | 暂不退 | 驳回 |", "|---|---|---|---|---|---|"]
    lines += [f"| {d} | {s['refunded']} 单 | ¥{s['amount']:.2f} | {s['escalated']} | {s['waiting']} | {s['rejected']} |" for d, s in days]
    if pending:
        lines += ["", "【待你处理】仍待处理：" + "、".join(pending)]
    return "\n".join(lines) + "\n"
