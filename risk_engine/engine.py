"""
V2.1 风险/相关性引擎 - 核心计算层

从对齐的日收益率表，算出后续 V2.2(诊断)/V2.3(BL)/E3(波动目标) 都要用的"风险地基"：
  - 年化波动率：单只资产的风险大小
  - 相关性矩阵：资产两两之间同涨同跌的程度（弱/负相关才是真分散）
  - 协方差矩阵（Ledoit-Wolf 收缩，年化）：BL/有效前沿优化的核心输入

概念科普：
- 波动率(volatility)：收益率的标准差，衡量"波动有多大"。年化 = 日波动 × √252。
- 相关性(correlation)：-1~+1。+1 完全同涨同跌（无分散）；0 不相关；-1 完全对冲。
  组合降波动的本质，就是找相关性低/负的资产凑一起。
- 协方差(covariance)：相关性 × 两者波动率，是优化器真正吃的量。
- Ledoit-Wolf 收缩：样本协方差在资产多/样本少时噪声极大、甚至不可逆。
  收缩 = 把它向一个"结构化目标"拉近，得到更稳、更可靠的矩阵。低成本高回报。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

TRADING_DAYS = 252  # 年化因子


def compute_risk(returns: pd.DataFrame) -> dict:
    """
    从日收益率表计算风险地基。

    Args:
        returns: 行=交易日，列=资产，值=日收益率（来自 fetcher.fetch_returns）

    Returns:
        dict（JSON 可序列化），冻结的输出接口，供 V2.2/V2.3/E3 消费：
        {
          "assets": [...],
          "n_obs": int, "start": "YYYY-MM-DD", "end": "...",
          "annual_volatility": {asset: float},      # 年化波动率
          "annual_return": {asset: float},          # 年化平均收益（参考）
          "correlation": {a: {b: float}},           # 相关性矩阵
          "cov_annual": {a: {b: float}},            # 年化协方差(Ledoit-Wolf收缩)
          "shrinkage": float                        # 收缩强度(0~1)
        }
    """
    assets = list(returns.columns)

    # 年化波动率与年化收益
    daily_vol = returns.std()
    annual_vol = daily_vol * np.sqrt(TRADING_DAYS)
    annual_ret = returns.mean() * TRADING_DAYS

    # 相关性矩阵（直接从收益率算，直观）
    corr = returns.corr()

    # Ledoit-Wolf 收缩协方差（日频）→ 年化
    lw = LedoitWolf().fit(returns.values)
    cov_daily = lw.covariance_
    shrinkage = float(lw.shrinkage_)
    cov_annual = pd.DataFrame(cov_daily * TRADING_DAYS, index=assets, columns=assets)

    def _matrix_to_dict(m: pd.DataFrame) -> dict:
        return {a: {b: round(float(m.loc[a, b]), 6) for b in assets} for a in assets}

    return {
        "assets": assets,
        "n_obs": int(len(returns)),
        "start": str(returns.index[0].date()),
        "end": str(returns.index[-1].date()),
        "annual_volatility": {a: round(float(annual_vol[a]), 4) for a in assets},
        "annual_return": {a: round(float(annual_ret[a]), 4) for a in assets},
        "correlation": _matrix_to_dict(corr),
        "cov_annual": _matrix_to_dict(cov_annual),
        "shrinkage": round(shrinkage, 4),
    }


def format_report(risk: dict) -> str:
    """把风险结果渲染成易读的 markdown（人看）。"""
    a = risk["assets"]
    lines = [f"# 风险/相关性报告（V2.1 引擎输出）",
             f"> 区间：{risk['start']} ~ {risk['end']}（{risk['n_obs']} 个交易日）"
             f"｜Ledoit-Wolf 收缩强度：{risk['shrinkage']}", ""]

    lines.append("## 年化波动率 / 年化收益")
    lines.append("| 资产 | 年化波动率 | 年化收益 |")
    lines.append("|------|-----------|---------|")
    for x in a:
        lines.append(f"| {x} | {risk['annual_volatility'][x]*100:.1f}% | {risk['annual_return'][x]*100:.1f}% |")
    lines.append("")

    lines.append("## 相关性矩阵")
    lines.append("| | " + " | ".join(a) + " |")
    lines.append("|" + "---|" * (len(a) + 1))
    for x in a:
        row = " | ".join(f"{risk['correlation'][x][y]:+.2f}" for y in a)
        lines.append(f"| **{x}** | {row} |")
    lines.append("")
    lines.append("> 解读：相关性越低/越负，两资产凑一起越能降组合波动（真分散）。")
    return "\n".join(lines)
