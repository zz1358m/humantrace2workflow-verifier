"""A small scripted day, so the pipeline can be exercised (and tested) without recording anyone.

Story: the person writes two weekly metric reports from CSVs. Both times they paste numbers,
glance back at the sheet without copying anything, save, leave, and come back to fix the report.
They also ask a coding agent for a draft and push back on it.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from . import config, store

SRC = "synth"

CSV = {
    "W40": "metric,value\nsignups,1284\nrevenue_usd,48210\nchurn_pct,2.1\n",
    "W41": "metric,value\nsignups,1410\nrevenue_usd,51730\nchurn_pct,1.8\n",
}
BAD = {  # first save: a transposed number and no source line
    "W40": "# 周报 W40\n\n本周表现不错，各项指标稳步增长，团队状态很好。\n\n- 注册 1284\n- 收入 $42810\n- 流失率 2.1%\n",
    "W41": "# 周报 W41\n\n本周表现不错，各项指标稳步增长，团队状态很好。\n\n- 注册 1410\n- 收入 $51370\n- 流失率 1.8%\n",
}
GOOD = {
    "W40": "# 周报 W40\n\n- 注册 1284\n- 收入 $48210\n- 流失率 2.1%\n\n数据来源：metrics_W40.csv\n",
    "W41": "# 周报 W41\n\n- 注册 1410\n- 收入 $51730\n- 流失率 1.8%\n\n数据来源：metrics_W41.csv\n",
}


def write(day: str = "2026-01-05") -> dict:
    base = datetime.strptime(day, "%Y-%m-%d").timestamp()
    ddir = config.day_dir(day)
    bdir = ddir / "blobs"
    bdir.mkdir(exist_ok=True)
    evs: list[dict] = []

    def ev(t, k, **f):
        evs.append({"t": round(base + t, 3), "src": SRC, "k": k, **f})

    def blob(text: str, ext: str) -> str:
        sha = hashlib.sha256(text.encode()).hexdigest()[:16]
        (bdir / f"{sha}{ext}").write_text(text, encoding="utf-8")
        return sha

    def report(week: str, t: float):
        sheet, doc = f"metrics_{week}.csv - Excel", f"weekly_{week}.md - Typora"
        path = f"D:\\work\\reports\\weekly_{week}.md"
        ev(t - 5, "file", op="modified", path=f"D:\\work\\reports\\metrics_{week}.csv", sha=blob(CSV[week], ".csv"), size=len(CSV[week]))
        ev(t, "win", app="EXCEL.EXE", title=sheet)
        ev(t + 8, "key", combo="ctrl+c")
        ev(t + 8.2, "clip", n=24, h="aa11", preview=" ".join(ln.split(",")[1] for ln in CSV[week].split()[1:]))
        ev(t + 12, "win", app="Typora.exe", title=doc)
        ev(t + 14, "key", combo="ctrl+v")
        ev(t + 16, "type", n=120, bs=4, t1=base + t + 70)
        ev(t + 75, "win", app="EXCEL.EXE", title=sheet)  # glance: nothing copied
        ev(t + 77, "scroll", n=3, t1=base + t + 80)
        ev(t + 90, "win", app="Typora.exe", title=doc)
        ev(t + 92, "type", n=30, bs=2, t1=base + t + 110)
        ev(t + 112, "key", combo="ctrl+s")
        ev(t + 113, "file", op="modified", path=path, sha=blob(BAD[week], ".md"), size=len(BAD[week]))
        ev(t + 120, "win", app="chrome.exe", title="Inbox - Gmail - Google Chrome")
        ev(t + 300, "win", app="EXCEL.EXE", title=sheet)
        ev(t + 320, "win", app="Typora.exe", title=doc)  # back to fix it
        ev(t + 322, "key", combo="ctrl+z")
        ev(t + 324, "key", combo="ctrl+z")
        ev(t + 326, "type", n=60, bs=40, t1=base + t + 380)
        ev(t + 382, "scroll", n=4, t1=base + t + 388)
        ev(t + 392, "scroll", n=3, t1=base + t + 398)
        ev(t + 402, "key", combo="ctrl+s")
        ev(t + 403, "file", op="modified", path=path, sha=blob(GOOD[week], ".md"), size=len(GOOD[week]))
        ev(t + 410, "win", app="OUTLOOK.EXE", title=f"周报 {week} - 邮件")
        ev(t + 415, "type", n=40, bs=0, t1=base + t + 430)
        ev(t + 450, "key", combo="ctrl+enter")

    report("W40", 9 * 3600 + 600)
    report("W41", 14 * 3600 + 1200)

    c0 = 16 * 3600
    conv = {"agent": "claude", "session": "demo0001"}
    ev(c0, "prompt", **conv, cwd="D:\\work\\reports", text="根据 metrics_W41.csv 帮我起草周报")
    ev(c0 + 40, "reply", **conv, text="已起草周报：本周各项指标表现亮眼，注册量大幅增长……", tools=["Read", "Write"])
    ev(c0 + 70, "prompt", **conv, text="不对，不要形容词和总结性的话，只列数字。另外数字你核对过 csv 吗？")
    ev(c0 + 110, "reply", **conv, text="已改为三条数字，并逐项对照 csv。", tools=["Read", "Edit"])
    ev(c0 + 130, "prompt", **conv, text="最后加一行数据来源，写文件名")
    ev(c0 + 160, "reply", **conv, text="已添加“数据来源：metrics_W41.csv”。", tools=["Edit"])
    ev(c0 + 175, "prompt", **conv, text="可以")

    # Synthetic events use milliseconds; replace this local day through its last millisecond.
    until = (datetime.fromtimestamp(base) + timedelta(days=1)).timestamp() - 0.001
    counts = store.replace_source(SRC, evs, base, until)
    return {"day": day, "events": counts.get(day, 0), "dir": str(ddir)}
