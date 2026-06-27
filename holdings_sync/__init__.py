"""⑥ 持仓自动同步：Finance.md 持仓明细表 → 单只基金明细 + 聚合（config/holdings_current.json）。"""

from .parser import parse_finance, sync

__all__ = ["parse_finance", "sync"]
