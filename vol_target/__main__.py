"""独立运行入口：python -m vol_target"""
from .targeter import run_vol_target, _render

result = run_vol_target()
print("\n" + _render(result))
