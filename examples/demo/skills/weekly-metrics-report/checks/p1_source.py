import sys

from _common import done, load

sys.stdout.reconfigure(encoding="utf-8")
_, names, reports = load()
text = reports[0].read_text(encoding="utf-8") if reports else ""
lines = [ln for ln in text.splitlines() if ln.strip().startswith("数据来源")]
ok = any(n in ln for ln in lines for n in names)
done(ok, "" if ok else f"需要一行“数据来源：{names[0] if names else '<csv 文件名>'}”")
