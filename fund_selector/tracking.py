"""指数基金跟踪误差（N4）：真 TE = 年化 std(基金日收益 − 基准指数日收益)。

难点是"业绩比较基准文字 → 可拉取的指数日收益"跨指数家族碎片化。采用**策底图**(curated map)：
维护 业绩基准关键词 → (指数代码, 数据源)，先接中证(csindex)/国证(cni)——覆盖大多 A 股主题指数基金；
能解析的算真 TE，标普/恒生等暂未接的标"—基准未接"。覆盖随策库扩展（与概念图谱同一哲学）。

仅对指数型基金算（主动基金无跟踪标的，TE 无意义）。低 TE = 复制更紧，是指数基金的核心选择标准。

✅ 分红口径（已修）：红利类/沪深300/中证500 已改用【全收益(TR)指数】(含分红再投，与基金净值口径一致)，
   消除了"价格指数除息日跳水→TE 被抬高"的偏差，绝对 TE 现在更可信。
   残留局限：国证(深证/国证红利)无全收益接口、及低分红宽基(中证800/1000/科创等)仍用价格指数——
   但这些分红小、偏差有限；海外(标普/恒生)指数家族暂未接(标"—基准未接")。
"""
from __future__ import annotations

import akshare as ak
import numpy as np
import pandas as pd

from style_tilt.rbsa import fetch_index_returns  # 中证 csindex 日收益（复用）

TRADING_DAYS = 252
TE_HIGH = 0.04   # 年化跟踪误差 > 4% 视为偏大（被动指数基金本应贴合，过大=复制差）

# 业绩比较基准关键词 → (指数代码, 源)。源：'csindex'(中证) | 'cni'(国证)。
# 顺序：具体/长的在前，避免"中证红利"抢先命中"中证红利低波动100"。未命中→标"—基准未接"。
# 原则：只收录【已实测拉取通过】的代码。宁可标"未接"，也不映射到错指数给出误导性 TE。新指数家族(标普/恒生)随策库扩。
# 全收益(TR)：红利/沪深300/中证500 用全收益指数（含分红口径，与基金净值一致）→ 消除"价格指数除息跳水"偏差。
BENCHMARK_INDEX = [
    # 红利类：全收益(TR)，高股息分红影响最大，优先
    ("中证红利低波动100", "H30270", "csindex"),   # 全收益(价格码 H30269)
    ("红利低波动100", "H30270", "csindex"),
    ("中证红利低波", "H30270", "csindex"),
    ("上证红利", "H00015", "csindex"),             # 全收益(价格 000015)
    ("中证红利", "H20269", "csindex"),             # 全收益(价格 000922)
    ("深证红利", "399324", "cni"),                 # 国证无全收益接口，留价格
    ("国证红利", "399321", "cni"),
    # 宽基：沪深300/中证500 全收益；其余低分红留价格
    ("沪深300", "H00300", "csindex"),              # 全收益(价格 000300)
    ("中证500", "H00905", "csindex"),              # 全收益(价格 000905)
    ("中证800", "000906", "csindex"),
    ("中证1000", "000852", "csindex"),
    ("上证50", "000016", "csindex"),
    ("科创板50", "000688", "csindex"),
    ("科创50", "000688", "csindex"),
    ("创业板", "399006", "cni"),                   # 创业板指(国证)
    # 行业
    ("国证石油天然气", "399439", "cni"),
    ("国证油气", "399439", "cni"),
    ("石油天然气", "399439", "cni"),
    ("半导体", "980017", "cni"),                   # 国证半导体
    ("中证主要消费", "000932", "csindex"),
    ("主要消费", "000932", "csindex"),
    ("中证医药卫生", "000933", "csindex"),
    ("医药卫生", "000933", "csindex"),
    ("中证全指", "000985", "csindex"),
]

_IDX_CACHE: dict = {}


def resolve_benchmark(benchmark_text: str, fund_type: str) -> tuple | None:
    """业绩基准文字 + 基金类型 → (匹配关键词, 指数代码, 源)。非指数基金或未命中策库 → None。"""
    if "指数" not in str(fund_type):   # 仅被动/增强指数基金；主动基金无跟踪标的
        return None
    t = str(benchmark_text or "")
    for pat, code, src in BENCHMARK_INDEX:
        if pat in t:
            return (pat, code, src)
    return None


def _fetch_bench_returns(code: str, src: str) -> pd.Series:
    """拉基准指数日收益（进程内缓存）。中证用 csindex 涨跌幅；国证用收盘价 pct_change（其涨跌幅为分数、口径不一，自算更稳）。"""
    key = (code, src)
    if key in _IDX_CACHE:
        return _IDX_CACHE[key]
    if src == "csindex":
        s = fetch_index_returns(code, lookback_days=None)
    else:  # cni 国证
        df = ak.index_hist_cni(symbol=code, start_date="20180101", end_date="20991231")
        df = df[["日期", "收盘价"]].copy()
        df["日期"] = pd.to_datetime(df["日期"])
        s = df.set_index("日期").sort_index()["收盘价"].astype(float).pct_change().dropna()
    _IDX_CACHE[key] = s
    return s


def tracking_error(fund_ret: pd.Series, lookback: int, benchmark_text: str, fund_type: str) -> dict | None:
    """算单只指数基金的年化跟踪误差。返回 {te, bench, code} 或 None（非指数/未接/数据不足）。"""
    resolved = resolve_benchmark(benchmark_text, fund_type)
    if resolved is None:
        return None
    pat, code, src = resolved
    try:
        bench = _fetch_bench_returns(code, src)
    except Exception:
        return {"te": None, "bench": pat, "code": code, "note": "基准拉取失败"}
    df = pd.concat([fund_ret.rename("f"), bench.rename("b")], axis=1, join="inner").dropna()
    if len(df) < 60:
        return {"te": None, "bench": pat, "code": code, "note": "重叠样本不足"}
    df = df.iloc[-lookback:]
    te = float((df["f"] - df["b"]).std() * np.sqrt(TRADING_DAYS))
    return {"te": round(te, 4), "bench": pat, "code": code, "note": ""}
