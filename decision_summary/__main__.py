"""调仓结论汇总：python -m decision_summary
读 risk_diagnostic + theme_decision + rebalance_fund → 合并成 outputs/调仓结论.md（一页看全）。
先跑过 diagnostic / theme_decider / fund_rebalancer(最好带 --swap --fill)。"""
from .summarize import summarize

print("\n" + summarize())
