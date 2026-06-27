"""④ 回测：用长历史指数验证"降股票风险这套做法(低波替换+波动率目标)"是否改善风险收益比。"""

from .engine import run_backtest, run_multiperiod

__all__ = ["run_backtest", "run_multiperiod"]
