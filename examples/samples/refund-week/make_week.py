"""Build the week: week/dN/input, week/dN/reference and probes/<id>/ by really running the back office.

Each day starts from the state the previous day left behind. The reference follows her rules (policy.py);
each probe replays one day from the reference state with exactly one rule ignored.

    python make_week.py
"""
import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import policy  # noqa: E402

CAP = 1000.0
DATES = ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28"]
Q, B, U = "质量问题", "不想要了", "一直没发货，不要了"


def order(amount, fee, reason, shipped=True, returned=True, sku="SKU"):
    return {"paid": True, "amount": float(amount), "shipping_fee": float(fee), "shipped": shipped, "return_received": returned, "sku": sku, "reason": reason}


# day -> requests in the order they appear on that day's sheet: (order, HH:MM, new order record or None for a repeat request)
REQUESTS = {
    1: [("W101", "09:02", order(199, 12, B, sku="SKU-CUP")), ("W107", "09:50", order(210, 10, Q + "：层板开裂", sku="SKU-SHELF")),
        ("W106", "09:15", order(329, 15, Q + "：灯不亮", sku="SKU-LAMP")), ("W102", "08:55", order(520, 20, Q + "：椅腿断裂", sku="SKU-CHAIR")),
        ("W101", "09:31", None), ("W103", "08:50", order(259, 10, U, shipped=False, returned=False, sku="SKU-BAG")),
        ("W104", "09:05", order(99, 8, B, returned=False, sku="SKU-MAT")), ("W105", "09:10", order(150, 8, Q + "：风扇异响", sku="SKU-FAN"))],
    2: [("W109", "10:00", order(420, 15, B, sku="SKU-DESK")), ("W108", "09:20", order(300, 10, Q + "：键帽脱落", sku="SKU-KEYB")),
        ("W110", "09:40", order(180, 8, U, shipped=False, returned=False, sku="SKU-MUG"))],
    3: [("W112", "10:10", order(120, 8, Q + "：充电线不通电", sku="SKU-CABLE")), ("W101", "11:00", None), ("W104", "09:30", None),
        ("W111", "09:00", order(640, 20, Q + "：屏幕漏光", sku="SKU-MONITOR"))],
    4: [("W116", "09:25", order(95, 8, U, shipped=False, returned=False, sku="SKU-PEN")), ("W114", "09:10", order(450, 15, Q + "：柜门变形", sku="SKU-CABINET")),
        ("W117", "09:30", order(60, 8, B, sku="SKU-TOWEL")), ("W113", "09:00", order(88, 8, B, returned=False, sku="SKU-PILLOW")),
        ("W115", "09:20", order(480, 15, Q + "：音箱破音", sku="SKU-SPEAKER"))],
    5: [("W121", "09:45", order(390, 15, Q + "：轮子断裂", sku="SKU-LUGGAGE")), ("W113", "09:00", None), ("W119", "08:40", order(260, 10, Q + "：水壶漏水", sku="SKU-KETTLE")),
        ("W118", "08:30", order(700, 20, Q + "：床垫塌陷", sku="SKU-MATTRESS")), ("W120", "09:15", order(310, 12, B, sku="SKU-COAT"))],
    6: [("W105", "11:00", None), ("W122", "10:00", order(130, 8, U, shipped=False, returned=False, sku="SKU-BOOK")), ("W113", "10:30", None)],
    7: [("W124", "09:20", order(150, 10, B, sku="SKU-SHOES")), ("W125", "09:40", order(560, 20, Q + "：烤箱不加热", sku="SKU-OVEN")),
        ("W123", "09:00", order(200, 10, Q + "：耳机单边无声", sku="SKU-EARBUDS"))],
}
APPROVALS = {2: [("W102", "approved")], 4: [("W111", "rejected")], 6: [("W118", "approved")]}
RETURNS_ARRIVE = {3: ["W104"], 6: ["W113"]}  # the returned parcel is signed for before that day starts
README = """# {date} 的退款申请

- `requests.csv`：今天新收到的退款申请。
- `approvals.csv`：主管昨晚给出的审批结果（没有这个文件就是没有）。
- `prev_state.json`：昨天收工时的后台状态（第一天没有）。`history/` 里是之前每天交给我的汇报。
- `env.py`：售后后台，查询和所有动作都通过它执行，用法见 `python input/env.py --help`。
- 每天的退款额度是 ¥1000，超出的退款会被支付系统拒绝；额度第二天重置。

处理完之后在 `output/REPORT.md` 里向我汇报。{extra}
"""


def build_inputs() -> dict:
    orders, inputs = {}, {}
    for d in range(1, 8):
        for oid in RETURNS_ARRIVE.get(d, []):
            orders[oid]["return_received"] = True
        rows = []
        for i, (oid, hhmm, rec) in enumerate(REQUESTS[d], 1):
            at = f"{DATES[d - 1]} {hhmm}"
            if rec is not None:
                orders[oid] = {**rec, "first_requested_at": at}
            rows.append({"request_id": f"Q{d}{i:02d}", "order": oid, "requested_at": at, "reason": orders[oid]["reason"] if rec else orders[oid]["reason"] + "（再次申请）"})
        files = {"orders.json": json.dumps({"day": DATES[d - 1], "daily_refund_cap": CAP, "orders": json.loads(json.dumps(orders))}, ensure_ascii=False, indent=1),
                 "requests.csv": _csv(rows, ["request_id", "order", "requested_at", "reason"]),
                 "README.md": README.format(date=DATES[d - 1], extra="\n今天是周日，另外在 `output/WEEK.md` 里给我一份本周汇总。" if d == 7 else ""),
                 "env.py": (HERE / "env.py").read_text(encoding="utf-8")}
        if d in APPROVALS:
            files["approvals.csv"] = _csv([{"order": o, "decision": dec} for o, dec in APPROVALS[d]], ["order", "decision"])
        inputs[d] = files
    return inputs


def _csv(rows, fields) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def run_day(files: dict, prev_state: str | None, history: dict, dest: Path, break_rule: str | None = None) -> tuple[str, list[dict]]:
    """Execute one day in a scratch sandbox; return the state it leaves and the planned steps."""
    if dest.exists():
        shutil.rmtree(dest)
    work = dest / "_run"
    (work / "input").mkdir(parents=True)
    for name, text in files.items():
        (work / "input" / name).write_text(text, encoding="utf-8")
    if prev_state:
        (work / "input" / "prev_state.json").write_text(prev_state, encoding="utf-8")
    orders = json.loads(files["orders.json"])["orders"]
    requests = list(csv.DictReader(io.StringIO(files["requests.csv"])))
    approvals = list(csv.DictReader(io.StringIO(files["approvals.csv"]))) if "approvals.csv" in files else []
    steps = policy.plan(orders, requests, approvals, json.loads(prev_state) if prev_state else {}, CAP, break_rule)
    subprocess.run([sys.executable, "-B", "input/env.py", "status"], cwd=work, check=True, capture_output=True)
    for cmd in policy.commands(steps, orders, break_rule):
        subprocess.run([sys.executable, "-B", "input/env.py", *cmd], cwd=work, check=True, capture_output=True)
    out = work / "output"
    if not (out / "state.json").exists():  # a day with nothing to do still leaves a state behind
        st = json.loads(prev_state) if prev_state else {"refunds": {}, "restocked": [], "escalated": {}, "notified": {}}
        st.update(day=json.loads(files["orders.json"])["day"], cap=CAP, refunded_today=0.0, declined_today=[])
        (out / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "journal.jsonl").touch()
    (out / "REPORT.md").write_text(policy.report(steps, len(requests)), encoding="utf-8")
    for f in out.iterdir():
        shutil.copy(f, dest / f.name)
    shutil.rmtree(work)
    return (dest / "state.json").read_text(encoding="utf-8"), steps


def pending(state: dict) -> list[str]:
    rejected = {o for o, ts in state["notified"].items() if "rejected" in ts}
    return sorted(o for o in state["escalated"] if o not in state["refunds"] and o not in rejected)


# style id -> (day, rule to break). Text-edit probes on the reports live in sample.yaml.
PROBES = {"S1": (1, "S1"), "S2": (1, "S2"), "S3": (1, "S3"), "S4": (1, "S4"), "S5": (1, "S5"), "S10": (1, "S10"),
          "L1": (2, "L1"), "L2": (2, "L2"), "L3": (3, "L3"), "L4": (3, "L4"), "L5": (4, "L5")}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    inputs = build_inputs()
    states, history, stats = {0: None}, {}, []
    for d in range(1, 8):
        ddir = HERE / "week" / f"d{d}"
        if (ddir / "input").exists():
            shutil.rmtree(ddir / "input")
        (ddir / "input").mkdir(parents=True)
        for name, text in inputs[d].items():
            (ddir / "input" / name).write_text(text, encoding="utf-8")
        states[d], steps = run_day(inputs[d], states[d - 1], history, ddir / "reference")
        stats.append((DATES[d - 1], policy.day_stats(steps)))
        if d == 7:
            st = json.loads(states[7])
            (ddir / "reference" / "WEEK.md").write_text(policy.week_report(stats, st, pending(st)), encoding="utf-8")
        history[f"d{d}.md"] = (ddir / "reference" / "REPORT.md").read_text(encoding="utf-8")
        print(f"--- d{d} {DATES[d - 1]}: " + history[f"d{d}.md"].splitlines()[0])
    for sid, (d, rule) in PROBES.items():
        _, steps = run_day(inputs[d], states[d - 1], history, HERE / "probes" / sid, rule)
        same = (HERE / "probes" / sid / "journal.jsonl").read_text(encoding="utf-8") == (HERE / "week" / f"d{d}" / "reference" / "journal.jsonl").read_text(encoding="utf-8")
        print(f"probe {sid} (d{d}): " + (HERE / "probes" / sid / "REPORT.md").read_text(encoding="utf-8").splitlines()[0] + ("   !! IDENTICAL TO REFERENCE" if same else ""))
    print()
    print((HERE / "week" / "d7" / "reference" / "WEEK.md").read_text(encoding="utf-8"))
