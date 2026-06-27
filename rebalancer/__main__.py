"""独立运行入口：python -m rebalancer"""
from .checker import check_rebalance, _render

result = check_rebalance()
print("\n" + _render(result))
