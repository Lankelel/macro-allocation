"""独立运行入口：python -m clock"""
from .clock import run_clock, _render

result = run_clock()
print("\n" + _render(result))
