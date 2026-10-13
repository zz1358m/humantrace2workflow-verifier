"""Re-run only the scripted items of the verifier the week run built, on a given version of the sample.
usage: rescore_checks.py <ht2wv home with skills/ and profile/> <sample dir> <tag>"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
home, sample_dir, tag = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
os.environ["HT2WV_HOME"] = str(home)

from ht2wv import bench, config  # noqa: E402

sample = bench.load(sample_dir)
cfg = config.load()
rdir = home / "runs" / f"rescore-{tag}"
st = bench.score_style(sample, "process-daily-refunds", rdir, cfg, judge=False)
print(f"[{tag}] checks only: covered {st['covered']} / {st['total']}; reference by day: {st.get('reference_by_day')}")
for d in (1, 2, 3, 4, 7):
    rep = json.loads((rdir / f"probe-reference-d{d}" / "report.json").read_text(encoding="utf-8"))
    bad = [(r["id"], str(r.get("detail"))[:110]) for r in rep["items"] if r["pass"] is False]
    crashed = [r["id"] for r in rep["items"] if r["how"] == "check" and r["pass"] is None]
    print(f"  reference d{d}: failed checks {bad}  crashed {crashed}  pending judge {rep['pending']}")
for i in st["items"]:
    print(f"  {i['id']:4} d{i.get('day')} covered={i['covered']} by={i['by']}")
(home / f"rescore-{tag}.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
