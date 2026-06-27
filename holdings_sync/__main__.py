"""独立运行入口：python -m holdings_sync"""
from .parser import sync, _render

result = sync()
print("\n" + _render(result))
