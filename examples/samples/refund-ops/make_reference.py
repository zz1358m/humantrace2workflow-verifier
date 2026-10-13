"""Build reference/ and probes/<style id>/ by really running the task environment.

The reference is what this person would do. Each process probe re-runs the whole day with exactly one of her
rules broken, so journal, state and report stay consistent with each other: a verifier can only catch the
probe by knowing the rule, not by spotting a mismatch between files.

    python make_reference.py
"""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT = HERE / "task_input"
ORDERS = json.loads((INPUT / "orders.json").read_text(encoding="utf-8"))
CAP = ORDERS["daily_refund_cap"]


def run_day(dest: Path, break_rule: str | None = None) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    work = dest / "_run"
    (work / "input").mkdir(parents=True)
    for f in INPUT.iterdir():
        shutil.copy(f, work / "input" / f.name)

    def env(*args):
        subprocess.run([sys.executable, "-B", "input/env.py", *map(str, args)], cwd=work, check=True, capture_output=True)

    reqs = list(csv.DictReader(open(INPUT / "requests.csv", encoding="utf-8")))
    if break_rule != "S1":  # her rule: oldest request first, not file order
        reqs.sort(key=lambda r: r["requested_at"])
    spent, rows, seen, dups = 0.0, [], set(), []
    for r in reqs:
        oid, o = r["order"], ORDERS["orders"][r["order"]]
        if oid in seen:
            dups.append(f"{oid}（{r['requested_at'][-5:]}）")
            continue
        seen.add(oid)
        buyer_caused = r["reason"].startswith("不想要")
        env("lookup", oid)
        amount = o["amount"] - (o["shipping_fee"] if buyer_caused and break_rule != "S2" else 0)
        if o["amount"] > 500 and break_rule != "S3":
            env("escalate", oid, "超过500需主管审批")
            env("notify", oid, "escalated")
            rows.append((oid, "【待你处理】升级", o["amount"], "超过 ¥500 需主管审批"))
            continue
        if o["shipped"] and not o["return_received"] and break_rule != "S5":
            env("notify", oid, "need_return")
            rows.append((oid, "暂不退", 0.0, "退货未签收，已通知先寄回"))
            continue
        if spent + amount > CAP:
            left = round(CAP - spent, 2)
            if break_rule == "S10" and left > 0:  # partial refund up to the cap instead of escalating the whole order
                env("refund", oid, left)
                env("restock", oid)
                env("notify", oid, "refunded")
                spent += left
                rows.append((oid, "已退款", left, f"额度只剩 ¥{left:.2f}，先退一部分"))
            else:
                env("escalate", oid, "当日额度不足")
                env("notify", oid, "escalated")
                rows.append((oid, "【待你处理】升级", amount, f"当日额度不足（剩余 ¥{left:.2f}）"))
            continue
        if break_rule == "S4":  # tell the buyer before the money has moved
            env("notify", oid, "refunded")
        env("refund", oid, amount)
        spent += amount
        if o["return_received"]:
            env("restock", oid)
        if break_rule != "S4":
            env("notify", oid, "refunded")
        why = "未发货，全额" if not o["shipped"] else f"买家原因，扣运费 ¥{o['shipping_fee']:.2f}" if buyer_caused and break_rule != "S2" \
            else "买家原因，全额" if buyer_caused else "质量问题，全额"
        rows.append((oid, "已退款", amount, why))

    n_ref = sum(1 for x in rows if x[1] == "已退款")
    n_esc = sum(1 for x in rows if "升级" in x[1])
    n_wait = sum(1 for x in rows if x[1] == "暂不退")
    lines = [f"今日 {len(reqs)} 条申请：退款 {n_ref} 单合计 ¥{spent:.2f}，升级 {n_esc} 单，暂不退 {n_wait} 单，重复 {len(dups)} 条。", "",
             "| 订单 | 处理 | 金额 | 原因 |", "|---|---|---|---|"]
    rank = lambda x: 0 if "升级" in x[1] else 1 if x[1] == "已退款" else 2  # what needs her goes first
    lines += [f"| {o} | {a} | ¥{m:.2f} | {w} |" for o, a, m, w in sorted(rows, key=rank)]
    if dups:
        lines += ["", "重复申请：" + "、".join(dups) + " 未重复处理。"]
    for name in ("journal.jsonl", "state.json"):
        shutil.copy(work / "output" / name, dest / name)
    (dest / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(work)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run_day(HERE / "reference")
    for rule in ("S1", "S2", "S3", "S4", "S5", "S10"):
        run_day(HERE / "probes" / rule, rule)
    print((HERE / "reference" / "REPORT.md").read_text(encoding="utf-8"))
    print((HERE / "reference" / "journal.jsonl").read_text(encoding="utf-8"))
