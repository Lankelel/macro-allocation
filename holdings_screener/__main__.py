"""持仓末位淘汰：python -m holdings_screener [--pct 20] [--min-group 5]
读 holdings_current.json → 同类内综合分排序 → 末位淘汰建议 + 腾现金 + 替代提示。"""
import sys

from .screener import screen

argv = sys.argv[1:]
pct, min_group = 20, 5
if "--pct" in argv:
    pct = int(argv[argv.index("--pct") + 1])
if "--min-group" in argv:
    min_group = int(argv[argv.index("--min-group") + 1])
screen(pct=pct, min_group=min_group)
