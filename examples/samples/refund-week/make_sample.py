"""Assemble sample.yaml for the week: the single-day sample's records plus the cross-day ones.

Run after make_week.py (the report probes are derived from the generated reference reports).

    python make_sample.py
"""
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
base = yaml.safe_load((HERE.parent / "refund-ops" / "sample.yaml").read_text(encoding="utf-8"))
d1 = (HERE / "week" / "d1" / "reference" / "REPORT.md").read_text(encoding="utf-8")
head, rows = d1.split("|---|---|---|---|\n")[0], [ln for ln in d1.split("|---|---|---|---|\n")[1].splitlines() if ln.startswith("|")]
tail = d1.split(rows[-1] + "\n")[1]
mine = [r for r in rows if "【待你处理】" in r]
buried = head + "|---|---|---|---|\n" + "\n".join([r for r in rows if r not in mine] + [r.replace("【待你处理】", "") for r in mine]) + "\n" + tail
cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
story = d1.splitlines()[0] + "\n\n我先把今天的申请按时间排了序，然后逐个查询处理。" + "".join(
    f"接着查询了 {o}，{why}，所以处理结果是{act.replace('【待你处理】', '')}，金额 {amt}。" for o, act, amt, why in cells) + "最后还有一条重复申请，我没有重复处理。\n"

sample = {
    "id": "refund-week",
    "persona": base["persona"],
    "purpose": ("我每天要处理一批退款申请，一周七天都要做。每天给你当天的申请表、主管的审批结果、昨天收工时的后台状态和之前的汇报，\n"
                "替我把当天该处理的都处理完，结果要和我自己做的一样，然后在 output/REPORT.md 里向我汇报；周日再给我一份周汇总 output/WEEK.md。\n"
                "后台里的动作都是真的，退出去的钱和发出去的通知收不回来，所以先后顺序不能乱；前一天留下的事，第二天要接着办。\n"),
    "rubric": [
        {"id": "R1", "claim": "产出 journal.jsonl 和 state.json（由后台生成，不是手写的）以及 REPORT.md"},
        {"id": "R2", "claim": "今天每一单的结果（退多少 / 升级 / 暂不退 / 驳回 / 不动）和我自己处理的一样，包括前几天留下来的单"},
        {"id": "R3", "claim": "每一单在做任何动作之前都先查询过"},
        {"id": "R4", "claim": "通知买家是这一单当天的最后一个动作，当天恰好通知一次，模板和结果对得上；今天不该动的单不通知"},
        {"id": "R5", "claim": "没有被支付系统拒绝的退款；任何订单都没有被退两次，包括前几天已经退过的"},
        {"id": "R6", "claim": "REPORT.md 第一行是一句话结论，里面的退款单数、退款合计、升级单数与后台当天实际一致"},
        {"id": "R7", "claim": "（周日）WEEK.md 第一行是一句话结论，本周退款单数与合计、仍待处理的单数与后台累计一致", "days": [7]},
    ],
    "style": [],
    "week": {"dir": "week", "days": 7, "inbox": ["requests.csv", "approvals.csv"]},  # inbox: still waiting the next day if a day is skipped
    "workdir": dict(base["workdir"]),
    "records": base["records"],
}
by_id = {s["id"]: s for s in base["style"]}
for sid in ("S1", "S2", "S3", "S4", "S5", "S10"):
    sample["style"].append({"id": sid, "statement": by_id[sid]["statement"], "day": 1, "probe": {"dir": f"probes/{sid}"}})
sample["style"] += [
    {"id": "S6", "statement": by_id["S6"]["statement"], "day": 1, "probe": {"file": "REPORT.md", "regex": [r"^今日[^\n]*\n", "以下是今天退款申请的处理情况，请查收。\n"]}},
    {"id": "S7", "statement": by_id["S7"]["statement"], "day": 1, "probe": {"file": "REPORT.md", "set": story}},
    {"id": "S8", "statement": by_id["S8"]["statement"], "day": 1, "probe": {"file": "REPORT.md", "set": buried}},
    {"id": "S9", "statement": by_id["S9"]["statement"], "day": 1, "probe": {"file": "REPORT.md", "regex": [r"¥(\d+)\.00", r"\1元"]}},
    {"id": "S11", "statement": by_id["S11"]["statement"], "day": 1, "probe": {"file": "REPORT.md", "append": "\n执行记录：\n" + "\n".join(
        f"python input/env.py {c}" for c in ("lookup W103", "refund W103 259.00", "notify W103 refunded", "lookup W102", "escalate W102 超过500需主管审批",
                                             "notify W102 escalated", "lookup W101", "refund W101 187.00", "restock W101", "notify W101 refunded"))}},
    {"id": "L1", "statement": "前一天因额度不足没退成的单，第二天和新申请排成一队，按最初申请时间先后处理，所以它们排在最前面", "day": 2, "probe": {"dir": "probes/L1"}},
    {"id": "L2", "statement": "主管批准的单，批准后的当天就退，不等买家再来催", "day": 2, "probe": {"dir": "probes/L2"}},
    {"id": "L3", "statement": "之前通知过“先寄回”的单，买家寄回签收后再申请要正常退，不算重复", "day": 3, "probe": {"dir": "probes/L3"}},
    {"id": "L4", "statement": "之前任何一天已经退过款的订单再来申请，一律不重复退", "day": 3, "probe": {"dir": "probes/L4"}},
    {"id": "L5", "statement": "主管驳回的单要通知买家（rejected），不退款，也不能放着不管", "day": 4, "probe": {"dir": "probes/L5"}},
    {"id": "L6", "statement": "周日的周汇总第一行是一句话结论：本周共退几单合计多少、还有几单待处理；下面每天一行", "day": 7,
     "probe": {"file": "WEEK.md", "regex": [r"^本周[^\n]*\n", "以下是本周退款处理情况的汇总，请查收。\n"]}},
]

rec = sample["records"]
rec["claude"] += [
    {"session": "carry0617", "cwd": "/home/xuqing/aftersale/0617", "turns": [
        {"at": "2026-06-17 09:30:00", "user": "处理今天的申请。先看 prev_state.json，昨天有两单因为额度不够升级了没退成"},
        {"at": "2026-06-17 09:36:00", "assistant": "已按今天 requests.csv 的申请时间处理完 4 单，共退 ¥965.00。昨天遗留的 F6003、F6005 我排在了最后，轮到它们时额度已不够，今天仍未能退。", "tools": ["Read", "Bash", "Bash", "Bash", "Bash"]},
        {"at": "2026-06-17 09:37:00", "user": "顺序反了。昨天没退成的是最早申请的，要和今天的新单排成一队，按最初申请时间来，它们自然在最前面。现在额度被今天的新单占了，人家又要多等一天", "from": ["L1"]},
        {"at": "2026-06-17 09:37:40", "assistant": "明白：结转的单和当天新单合并成一个队列，按后台里的最初申请时间排序。", "tools": []},
        {"at": "2026-06-17 09:38:20", "user": "还有，老唐昨晚批了 F6001，approvals.csv 里写着 approved，你怎么没退？批了当天就退，别等买家再来催", "from": ["L2"]},
        {"at": "2026-06-17 09:39:00", "assistant": "F6001 的最初申请时间最早，本应排第一；今天额度已用尽，无法补退。", "tools": ["Bash"]},
        {"at": "2026-06-17 09:39:30", "user": "所以我说顺序要紧。明天第一件事就是它"},
    ]},
    {"session": "again0618", "cwd": "/home/xuqing/aftersale/0618", "turns": [
        {"at": "2026-06-18 10:00:00", "user": "今天的申请里 E5003 又来了，你标成重复没处理？"},
        {"at": "2026-06-18 10:00:40", "assistant": "E5003 在 6 月 9 日已经通知过买家（need_return），所以我按重复申请跳过了。", "tools": ["Bash"]},
        {"at": "2026-06-18 10:01:30", "user": "那次是让他先把货寄回来，一分钱没退。现在后台显示签收了，这次要正常退，买家原因照样扣运费。只有以前退过钱的再来申请才算重复", "from": ["L3", "L4"]},
        {"at": "2026-06-18 10:03:00", "assistant": "已为 E5003 退款并入库、通知。另外 C3002 在 6 月 10 日已退过 ¥240.00，今天的再次申请我没有动，记为重复。", "tools": ["Bash", "Bash", "Bash", "Bash"]},
        {"at": "2026-06-18 10:03:30", "user": "对，退过的一律不动", "from": ["L4"]},
        {"at": "2026-06-18 10:04:10", "user": "D4002 老唐驳回了，你就这么放着？要发 rejected 通知买家，不退钱，但不能让人家干等", "from": ["L5"]},
        {"at": "2026-06-18 10:04:50", "assistant": "已通知 D4002 的买家（rejected），未退款。", "tools": ["Bash", "Bash"]},
        {"at": "2026-06-18 10:05:10", "user": "好"},
    ]},
    {"session": "week0621", "cwd": "/home/xuqing/aftersale/0621", "turns": [
        {"at": "2026-06-21 17:00:00", "user": "今天周日，处理完当天的再给我一份周汇总，写到 WEEK.md"},
        {"at": "2026-06-21 17:06:00", "assistant": "已写好 WEEK.md：本周我每天都按时处理了退款申请。周一共收到 6 条申请，我先查询了……周二……", "tools": ["Read", "Bash", "Write"]},
        {"at": "2026-06-21 17:06:50", "user": "周汇总和日报一个规矩：第一行一句话——本周共退几单合计多少钱、还有几单没处理完；下面每天一行的表。数字要和后台的累计对得上", "from": ["L6"]},
        {"at": "2026-06-21 17:08:00", "assistant": "已重写：本周共退款 19 单合计 ¥4380.00，截至周日仍待处理 2 单；下面按天列表。", "tools": ["Bash", "Write"]},
        {"at": "2026-06-21 17:08:20", "user": "行"},
    ]},
]
rec["shell"] += [
    {"at": "2026-06-17 09:40:10", "cmd": "python env.py status", "from": ["L1"]},
    {"at": "2026-06-18 09:05:00", "cmd": "cat approvals.csv", "from": ["L2"]},
    {"at": "2026-06-18 09:05:40", "cmd": "python env.py lookup F6001", "from": ["L2"]},
    {"at": "2026-06-18 09:06:10", "cmd": "python env.py refund F6001 880.00"},
    {"at": "2026-06-18 09:06:30", "cmd": "python env.py restock F6001"},
    {"at": "2026-06-18 09:06:50", "cmd": "python env.py notify F6001 refunded"},
    {"at": "2026-06-18 09:07:30", "cmd": "python env.py lookup F6003", "from": ["L1"]},
    {"at": "2026-06-18 09:08:00", "cmd": "python env.py lookup D4002"},
    {"at": "2026-06-18 09:08:20", "cmd": "python env.py notify D4002 rejected", "from": ["L5"]},
    {"at": "2026-06-21 17:10:00", "cmd": "python env.py status", "from": ["L6"]},
]
rec["chat"] += [
    {"at": "2026-06-17 11:00:00", "peer": "售后组", "sender": "小马", "text": "昨天额度不够剩下的那几单，我一般放到今天最后再弄"},
    {"at": "2026-06-17 11:03:00", "peer": "售后组", "sender": "许晴", "text": "我是放最前面。人家昨天就申请了，和今天的排成一队按最初申请时间来", "from": ["L1"]},
    {"at": "2026-06-17 18:20:00", "peer": "主管老唐", "sender": "主管老唐", "text": "我昨晚批的那单今天退了吗？买家投诉到我这了"},
    {"at": "2026-06-17 18:24:00", "peer": "主管老唐", "sender": "许晴", "text": "今天被助手排乱了没退成，明天第一单就退。以后你批了的我当天就退，不等买家催", "from": ["L2"]},
    {"at": "2026-06-18 14:00:00", "peer": "售后组", "sender": "小马", "text": "驳回的单我就不管了，反正不退"},
    {"at": "2026-06-18 14:03:00", "peer": "售后组", "sender": "许晴", "text": "驳回也得通知买家一声，不然他一直等着，最后还是来投诉", "from": ["L5"]},
    {"at": "2026-06-19 10:10:00", "peer": "财务小周", "sender": "财务小周", "text": "这周有一单被退了两次，是你那边的吗"},
    {"at": "2026-06-19 10:14:00", "peer": "财务小周", "sender": "许晴", "text": "不是我的。退过款的订单再来申请我一律不动；只有之前让先寄回、后来签收了再申请的，我才正常退", "from": ["L4", "L3"]},
    {"at": "2026-06-21 17:20:00", "peer": "主管老唐", "sender": "许晴", "text": "周汇总发你了，第一行是总数和还没处理完的单数，下面每天一行", "from": ["L6"]},
]
rec["shell"].sort(key=lambda e: e["at"])
rec["chat"].sort(key=lambda e: e["at"])
sample["workdir"]["0621/WEEK_v1.md"] = "本周我每天都按时处理了退款申请。周一共收到 6 条申请，我先查询了每一单，然后……周二共收到 5 条申请……\n"
sample["workdir"]["0621/WEEK.md"] = ("本周共退款 19 单合计 ¥4380.00，截至周日仍待处理 2 单。\n\n| 日期 | 退款 | 金额 | 升级 | 暂不退 | 驳回 |\n|---|---|---|---|---|---|\n"
                                     "| 2026-06-15 | 3 单 | ¥640.00 | 1 | 0 | 0 |\n| 2026-06-16 | 2 单 | ¥248.00 | 1 | 0 | 0 |\n| 2026-06-17 | 4 单 | ¥965.00 | 2 | 0 | 0 |\n"
                                     "| 2026-06-18 | 4 单 | ¥990.00 | 0 | 1 | 1 |\n| 2026-06-19 | 3 单 | ¥702.00 | 1 | 1 | 0 |\n| 2026-06-20 | 2 单 | ¥515.00 | 0 | 0 | 0 |\n"
                                     "| 2026-06-21 | 1 单 | ¥320.00 | 1 | 0 | 0 |\n\n【待你处理】仍待处理：G7004、G7009\n")


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))
header = ("# 一周七天的退款处理：状态跨天延续。由 make_sample.py 生成（记录沿用 refund-ops，并加入跨天规则的痕迹）。\n"
          "# style 是预填的个人风格，对管线隐藏：S* 是单日内的顺序与汇报，L* 是跨天才会出现的规则。\n")
(HERE / "sample.yaml").write_text(header + yaml.dump(sample, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(f"wrote sample.yaml: {len(sample['style'])} style items, {sum(len(s['turns']) for s in rec['claude'])} agent turns, {len(rec['shell'])} shell, {len(rec['chat'])} chat")
