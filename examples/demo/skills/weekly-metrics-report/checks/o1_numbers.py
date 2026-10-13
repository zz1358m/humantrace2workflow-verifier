import sys

from _common import body_numbers, done, load

sys.stdout.reconfigure(encoding="utf-8")
metrics, _, reports = load()
if not metrics or not reports:
    done(False, "missing input csv or weekly_*.md")
    raise SystemExit
found = body_numbers(reports[0].read_text(encoding="utf-8"))
want = set(metrics.values())
missing = {m: v for m, v in metrics.items() if v not in found}
extra = [n for n in found if n not in want]
problems = [f"{m}: csv 里是 {v}，报告里没有这个值" for m, v in missing.items()]
problems += [f"报告里的 {n} 不在 csv 里" for n in extra]
done(not problems, "；".join(problems))
