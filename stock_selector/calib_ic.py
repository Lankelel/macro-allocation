"""轻量单因子 IC 抽查（A3 权重校准用·常驻校准工具，手动跑）。
每维"打分方向对齐"的因子值 vs 未来126日收益的横截面 Spearman 秩相关(IC)，多时点求均值+IR。
point-in-time:基本面用"报告期+125天发布滞后≤T"的年报防前视;估值=EPS/价;波动/流动性=T前滚动窗。
跑法: PYTHONIOENCODING=utf-8 py -3.13 -m uv run python -m stock_selector.calib_ic
⚠️ 小样本(60股×6时点·单一区间)→ IC 仅作"方向抽查"输入,不可照搬定权(因子有效性轮动,易过拟合)。
2026-06-17 首跑结论见 PROBE.md「单因子IC抽查」。"""
from __future__ import annotations

import sys

import akshare as ak
import numpy as np
import pandas as pd

from stock_selector.datasource import _sina_symbol, _with_timeout

# 多元股票池(6行业×环节，与相关性校准同源)
UNIVERSE = [
    "300308", "300502", "300394", "002463", "300476", "600183", "688256", "688041", "300474",
    "601138", "000977", "000938", "300750", "300014", "002074", "688005", "300073", "300769",
    "300124", "600580", "002196", "603348", "002101", "600933", "600519", "000858", "000568",
    "603288", "600872", "603027", "600887", "600597", "002946", "600276", "002422", "600196",
    "603259", "002821", "300347", "300760", "688271", "300003", "601398", "601939", "601288",
    "600036", "601166", "000001", "600030", "300059", "601211", "600438", "688303", "002129",
    "300274", "300763", "688390", "601012", "002459", "688599",
]
FORM_DATES = ["2024-06-28", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30"]
FWD_DAYS = 126            # 未来收益窗(~6个月交易日)
VOL_LB, LIQ_LB = 252, 60
PUBLISH_LAG = pd.Timedelta(days=125)   # 年报发布滞后(period_end+125天才视为公开)


def _fetch_price(code):
    def _f():
        d = ak.stock_zh_a_daily(symbol=_sina_symbol(code))
        d = d.set_index(pd.to_datetime(d["date"]))
        return d[["close", "amount"]].astype(float).sort_index()
    return _with_timeout(_f, 12.0, None)


def _fetch_annuals(code):
    """取年报行(period_end, ROE, 营收增速, 净利增速, 每股收益)。"""
    def _f():
        return ak.stock_financial_analysis_indicator(symbol=code, start_year="2022")
    df = _with_timeout(_f, 15.0, None)
    if df is None or len(df) == 0:
        return None
    dcol = "日期" if "日期" in df.columns else df.columns[0]
    df = df.copy()
    df["_dt"] = pd.to_datetime(df[dcol], errors="coerce")
    ann = df[(df["_dt"].dt.month == 12) & (df["_dt"].dt.day == 31)].dropna(subset=["_dt"]).sort_values("_dt")

    def col(name):
        return pd.to_numeric(ann[name], errors="coerce") if name in ann.columns else pd.Series([np.nan] * len(ann))
    out = pd.DataFrame({
        "end": ann["_dt"].values,
        "roe": col("加权净资产收益率(%)").values,
        "rev_g": col("主营业务收入增长率(%)").values,
        "prof_g": col("净利润增长率(%)").values,
        "eps": col("加权每股收益(元)").values,
    })
    return out


def _asof_annual(annuals, T):
    """取 period_end+125天 ≤ T 的最近年报(point-in-time 防前视)。"""
    if annuals is None:
        return None
    elig = annuals[pd.to_datetime(annuals["end"]) + PUBLISH_LAG <= T]
    return elig.iloc[-1] if len(elig) else None


def main():
    px, am, annuals = {}, {}, {}
    n = len(UNIVERSE)
    for i, code in enumerate(UNIVERSE, 1):
        print(f"[progress] {i}/{n} {code}", file=sys.stderr, flush=True)
        d = _fetch_price(code)
        if d is not None and len(d) > 300:
            px[code] = d["close"]
            am[code] = d["amount"]
            annuals[code] = _fetch_annuals(code)
    price = pd.DataFrame(px).sort_index()
    amount = pd.DataFrame(am).sort_index()
    ret = price.pct_change()
    idx = price.index

    factors = ["fin", "grw", "val", "liq", "risk"]
    ic_rows = {f: [] for f in factors}
    for ds in FORM_DATES:
        T = pd.Timestamp(ds)
        tpos = idx.searchsorted(T, side="right") - 1     # 最近 ≤ T 的交易日
        if tpos < VOL_LB or tpos + FWD_DAYS >= len(idx):
            continue
        rows = []
        for code in price.columns:
            p = price[code]
            if pd.isna(p.iloc[tpos]) or pd.isna(p.iloc[tpos + FWD_DAYS]):
                continue
            fwd = p.iloc[tpos + FWD_DAYS] / p.iloc[tpos] - 1.0
            vol = float(ret[code].iloc[tpos - VOL_LB:tpos].std() * np.sqrt(252))
            liq = float(amount[code].iloc[tpos - LIQ_LB:tpos].mean())
            a = _asof_annual(annuals.get(code), T)
            roe = float(a["roe"]) if a is not None and pd.notna(a["roe"]) else np.nan
            grw = np.nanmean([a["rev_g"], a["prof_g"]]) if a is not None else np.nan
            eps = float(a["eps"]) if a is not None and pd.notna(a["eps"]) else np.nan
            ey = (eps / p.iloc[tpos]) if (eps == eps) else np.nan   # 盈利收益率=EPS/价(估值,高=便宜)
            rows.append({"fwd": fwd, "fin": roe, "grw": grw, "val": ey,
                         "liq": liq, "risk": -vol})                  # 方向对齐打分(risk=低波好)
        cs = pd.DataFrame(rows).dropna(subset=["fwd"])
        if len(cs) < 15:
            continue
        for f in factors:
            ic = cs[f].corr(cs["fwd"], method="spearman")           # 横截面秩相关
            if ic == ic:
                ic_rows[f].append(ic)

    print(f"\n样本池 {len(price.columns)}/{n} 只 / 有效时点 {len(ic_rows['risk'])} 个 / 未来窗 {FWD_DAYS}日")
    print(f"\n{'因子':<6}{'方向':<14}{'均值IC':>8}{'IC标准差':>9}{'IR':>7}{'胜率':>7}{'n':>4}")
    interp = {"fin": "ROE↑好", "grw": "成长↑好", "val": "盈利收益率↑(便宜)好", "liq": "流动性↑好", "risk": "低波↑好"}
    summ = {}
    for f in ["fin", "grw", "val", "liq", "risk"]:
        a = np.array(ic_rows[f])
        if len(a) == 0:
            print(f"{f:<6}{interp[f]:<14}{'—':>8}"); continue
        mean, std = a.mean(), a.std(ddof=0)
        ir = mean / std if std > 0 else float("nan")
        win = (a > 0).mean() * 100
        summ[f] = mean
        print(f"{f:<6}{interp[f]:<16}{mean:>+8.3f}{std:>9.3f}{ir:>7.2f}{win:>6.0f}%{len(a):>4}")

    # 按 正均值IC 归一给"IC建议权重"(仅作参考)
    cur = {"fin": 20, "grw": 15, "val": 25, "liq": 20, "risk": 20}
    pos = {f: max(summ.get(f, 0), 0) for f in factors}
    s = sum(pos.values())
    print("\nIC 建议权重(按正均值IC归一,仅参考) vs 当前权重:")
    for f in factors:
        sug = f"{pos[f]/s*100:5.1f}%" if s > 0 else "  —  "
        print(f"  {f:<5} 建议 {sug}   当前 {cur[f]}%")


if __name__ == "__main__":
    main()
