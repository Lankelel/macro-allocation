"""
低波红利替换 - RBSA 收益回归核心（Sharpe 1992 风格分析）

为什么用 RBSA 而非看名字/看标签：
  基金名常与实际持仓严重不符（"价值"基金重仓成长股是常态）。RBSA 不碰名字，
  而是把基金的**收益序列**对一组**风格指数**做约束回归，回归系数=这只基金
  "行为上"的风格暴露。系数解读为"它的涨跌 behaves like X% 红利低波 + Y% 成长 ..."。

约束（Sharpe 经典做法）：系数 wᵢ ≥ 0 且 Σwᵢ = 1
  → 系数像"风格配比"，可直接读成百分比；用 scipy SLSQP 求解。
R² = 这套风格指数能解释基金收益的比例（越高说明风格归因越可信）。
"""
from __future__ import annotations

import akshare as ak
import numpy as np
import pandas as pd
from scipy.optimize import minimize


def fetch_index_returns(code: str, lookback_days: int | None = 504) -> pd.Series:
    """拉风格指数的日收益率（csindex 接口，用官方涨跌幅列）。"""
    df = ak.stock_zh_index_hist_csindex(symbol=code, start_date="20180101", end_date="20991231")
    df = df[["日期", "涨跌幅"]].copy()
    df["日期"] = pd.to_datetime(df["日期"])
    s = df.set_index("日期").sort_index()["涨跌幅"]
    s = pd.to_numeric(s, errors="coerce").dropna() / 100.0   # 涨跌幅是百分数
    if lookback_days is not None and len(s) > lookback_days:
        s = s.iloc[-lookback_days:]
    return s


def fetch_factor_returns(factor_indices: dict[str, str], lookback_days: int = 504) -> pd.DataFrame:
    """拉多个风格因子指数，对齐成一张日收益表。"""
    series = {}
    for label, code in factor_indices.items():
        try:
            series[label] = fetch_index_returns(code, lookback_days=None)  # 先全量，最后统一对齐截尾
            print(f"[风格] ✅ 因子 {label}({code}) 拉到 {len(series[label])} 条")
        except Exception as e:
            print(f"[风格] ⚠️ 因子 {label}({code}) 拉取失败：{e}")
    df = pd.DataFrame(series).dropna()
    if lookback_days is not None and len(df) > lookback_days:
        df = df.iloc[-lookback_days:]
    return df


def run_rbsa(fund_ret: pd.Series, factor_ret: pd.DataFrame) -> dict:
    """
    对单只基金做约束 RBSA。

    Args:
        fund_ret: 基金日收益序列
        factor_ret: 风格因子日收益表（列=因子）
    Returns:
        {"loadings": {因子: 权重}, "r2": float, "n_obs": int}
    """
    # 对齐共同交易日（基金与因子的日期交集）
    df = pd.concat([fund_ret.rename("__fund__"), factor_ret], axis=1, join="inner").dropna()
    y = df["__fund__"].values
    X = df.drop(columns="__fund__").values
    factors = list(factor_ret.columns)
    k = len(factors)

    # 目标：最小化 ‖y - Xw‖²，约束 w≥0、Σw=1
    def obj(w):
        resid = y - X @ w
        return float(resid @ resid)

    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = [(0.0, 1.0)] * k
    w0 = np.full(k, 1.0 / k)
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0, None)
    w = w / w.sum() if w.sum() > 0 else w

    # R²
    ss_res = float(((y - X @ w) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "loadings": {factors[i]: round(float(w[i]), 4) for i in range(k)},
        "r2": round(r2, 4),
        "n_obs": int(len(df)),
    }
