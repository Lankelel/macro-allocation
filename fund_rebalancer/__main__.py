"""独立运行入口：
  python -m fund_rebalancer            大类回 SAA 下推到单只
  python -m fund_rebalancer --swap     额外叠加低波处方（卖纳指/沪深300→买道指/红利低波）
  --trim-stock                         配平：用股票超配部分补足买入资金（默认不主动减持股票）
  --theta 0.5                          低波替换比例（默认 1.0=全换）
  --min-trade 0.3                      最小交易额(w)，过滤碎单（默认 0.3）
  --fill commodity=石油                N6：该大类买入额改由选基选具体新标的（可多次，如再 --fill high_risk=黄金）
  --use-screen                         接法A：读 holdings_screen.json，用末位淘汰名单在「超配大类额度内」执行具体卖出，卖出现金计入可用资金（需先跑 python -m holdings_screener）
"""
import sys

from .planner import plan_fund_level

argv = sys.argv
theta = 1.0
min_trade = 0.3
if "--theta" in argv:
    theta = float(argv[argv.index("--theta") + 1])
if "--min-trade" in argv:
    min_trade = float(argv[argv.index("--min-trade") + 1])
# --fill 大类=主题（可重复）
fill_themes = {}
for i, a in enumerate(argv):
    if a == "--fill" and i + 1 < len(argv) and "=" in argv[i + 1]:
        cls, theme = argv[i + 1].split("=", 1)
        fill_themes[cls.strip()] = theme.strip()

result = plan_fund_level(swap="--swap" in argv, theta=theta, min_trade=min_trade,
                         trim_stock="--trim-stock" in argv, fill_themes=fill_themes,
                         use_screen="--use-screen" in argv)
from .planner import _render
print("\n" + _render(result))
