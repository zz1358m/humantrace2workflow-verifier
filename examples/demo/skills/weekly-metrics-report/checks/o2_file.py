import re
import sys

from _common import done, load

sys.stdout.reconfigure(encoding="utf-8")
_, names, reports = load()
if len(reports) != 1:
    done(False, f"期望恰好一份 weekly_*.md，实际 {len(reports)} 份")
elif not reports[0].read_text(encoding="utf-8").strip():
    done(False, f"{reports[0].name} 是空的")
else:
    week = re.sub(r"^weekly_|\.md$", "", reports[0].name)
    done(any(week in n for n in names), "" if any(week in n for n in names) else f"报告周次 {week} 与输入 {names} 对不上")
