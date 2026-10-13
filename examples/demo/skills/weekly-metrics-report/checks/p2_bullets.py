import sys

from _common import done, load

sys.stdout.reconfigure(encoding="utf-8")
metrics, _, reports = load()
text = reports[0].read_text(encoding="utf-8") if reports else ""
bullets = [ln for ln in text.splitlines() if ln.lstrip().startswith(("- ", "* "))]
done(len(bullets) == len(metrics), f"列表项 {len(bullets)} 个，csv 指标 {len(metrics)} 个")
