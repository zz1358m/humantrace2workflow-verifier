"""Render each figure on its own, in English and Chinese, as PNGs for the READMEs.

    python make_figs.py          # needs pdflatex, xelatex (with ctex) and pdftoppm on PATH
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "docs" / "img"
FIGS = ["triangle", "idea", "ladder", "week", "method"]
PRE = {
    "en": ("pdflatex", "\\documentclass[tikz,border=6pt]{standalone}\n\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}\n\\usepackage{amsmath,amssymb}\n"
                       "\\newcommand{\\T}[2]{#1}\n"),
    "zh": ("xelatex", "\\documentclass[tikz,border=6pt]{standalone}\n\\usepackage[UTF8,scheme=plain]{ctex}\n\\usepackage{amsmath,amssymb}\n"
                      "\\newcommand{\\T}[2]{#2}\n"),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name in FIGS:
        for lang, (engine, pre) in PRE.items():
            job = f"_fig_{name}_{lang}"
            (HERE / f"{job}.tex").write_text(pre + "\\input{figs/style}\n\\begin{document}\n\\input{figs/" + name + "}\n\\end{document}\n", encoding="utf-8")
            r = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error", f"{job}.tex"], cwd=HERE, capture_output=True, text=True, errors="replace")
            if r.returncode != 0:
                sys.exit(f"{job}: {engine} failed\n" + r.stdout[-1500:])
            # relative target: pdftoppm cannot write to an absolute path containing non-ASCII characters on Windows
            subprocess.run(["pdftoppm", "-r", "200", "-png", "-singlefile", f"{job}.pdf", f"../docs/img/{name}.{lang}"], cwd=HERE, check=True)
            for ext in ("tex", "pdf", "aux", "log"):
                (HERE / f"{job}.{ext}").unlink(missing_ok=True)
            print(f"wrote docs/img/{name}.{lang}.png")
