"""
V2.1 风险/相关性引擎 - 数据抓取层

职责：用 akshare 拉各持仓基金的历史净值，转成"对齐的日收益率表"。
这是整个量化层的数据地基——波动率、相关性、协方差都从这张收益表算出来。

概念科普：
- 净值(NAV)：基金每份额的价格。我们要的不是价格本身，而是「日收益率」。
- 日收益率：今天相对昨天涨跌的百分比。一串日收益率 = 这只基金的"风险指纹"。
- 为什么要"对齐"：算相关性必须用同一批交易日的收益。不同基金成立时间/停牌不同，
  只能取它们的「共同交易日」(日期交集)来比较。
"""
from __future__ import annotations

import time

import akshare as ak
import pandas as pd


def fetch_fund_returns(code: str, retries: int = 3) -> pd.Series:
    """
    拉单只基金的历史日收益率（按净值日期索引）。

    用 akshare 的「单位净值走势」，直接取官方「日增长率」列（已是%，除以100转小数）。
    用官方日增长率而非自己算 pct_change，可避免分红除权造成的假跳水。
    带重试：akshare 偶发网络抖动时重试 retries 次，提高健壮性。
    """
    last_err = None
    for attempt in range(retries):
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            df = df[["净值日期", "日增长率"]].copy()
            df["净值日期"] = pd.to_datetime(df["净值日期"])
            df = df.set_index("净值日期").sort_index()
            # 日增长率是百分数（如 2.33 表示 +2.33%），转成小数 0.0233
            ret = pd.to_numeric(df["日增长率"], errors="coerce") / 100.0
            ret = ret.dropna()
            if len(ret) > 0:
                return ret
            last_err = ValueError("空数据")
        except Exception as e:
            last_err = e
        if attempt < retries - 1:
            time.sleep(1.5)  # 退避后重试
    raise RuntimeError(f"{code} 拉取失败（重试 {retries} 次）：{last_err}")


def fetch_returns(assets: dict[str, str], lookback_days: int | None = 504) -> pd.DataFrame:
    """
    拉多只基金的日收益率，对齐成一张表。

    Args:
        assets: {可读标签: 基金代码}，如 {"gold": "002610", "oil": "160416"}
        lookback_days: 只保留最近 N 个交易日（默认 504 ≈ 2 年）；None=全历史

    Returns:
        DataFrame：行=共同交易日，列=各资产标签，值=日收益率
    """
    series = {}
    for label, code in assets.items():
        try:
            series[label] = fetch_fund_returns(code)
            print(f"[V2.1] ✅ {label}({code}) 拉到 {len(series[label])} 条日收益")
        except Exception as e:
            print(f"[V2.1] ⚠️ {label}({code}) 拉取失败：{e}")

    if not series:
        raise RuntimeError("没有任何基金拉取成功")

    # 按日期交集对齐（inner join）——只保留所有资产都有数据的交易日
    df = pd.DataFrame(series).dropna()
    if lookback_days is not None and len(df) > lookback_days:
        df = df.iloc[-lookback_days:]
    print(f"[V2.1] 对齐后：{len(df)} 个共同交易日 × {len(df.columns)} 个资产 "
          f"（{df.index[0].date()} ~ {df.index[-1].date()}）")
    return df
