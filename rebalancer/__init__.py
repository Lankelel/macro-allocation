"""V2.4 再平衡纪律：当前持仓 vs 目标权重，偏离超阈值则生成调仓信号。"""

from .checker import check_rebalance

__all__ = ["check_rebalance"]
