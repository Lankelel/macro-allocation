"""独立运行入口：
  python -m backtest          全周期 A/B/C 对比
  python -m backtest --multi  多区间（含 2008/2015 深熊）逐窗口验证
"""
import sys

if "--multi" in sys.argv:
    from .engine import run_multiperiod, _render_multi
    print("\n" + _render_multi(run_multiperiod()))
else:
    from .engine import run_backtest, _render
    print("\n" + _render(run_backtest()))
