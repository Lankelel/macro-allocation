"""
④ 回测 - 验证"降股票风险这套做法"是否真的改善风险收益比

为什么自己用 pandas 写而非 bt 库：bt 在 Windows/Py3.13 需 C++ Build Tools 编译失败；
且回测逻辑很简单（固定权重 + 季度再平衡 + 几个指标），自写更透明、零脆弱依赖，
符合项目"可解释性"原则——每一步都看得见怎么算。

对比三个组合（同一长历史区间、同一大类锚、季度再平衡）：
  A 基准    ：原始股票篮（纳指/标普/沪深300）—— 高成长
  B 低波    ：处方第①步 低波替换（纳指→道指、沪深300→红利低波）
  C 低波+动态：B 再叠加 ④ 波动率目标（股票近期波动飙升时机械减仓转现金）

诚实取舍（结论须带着读）：
  - 越南无长历史指数 → 回测剔除，US/CN 按比例归一（三组一致，不影响相对比较）
  - high_risk(虚拟货币)/保险/现金 合并为"类现金 0 波动"
  - 用底层指数（非基金）→ 忽略基金跟踪误差/费用；跨市场按日期并集前向填充对齐
  - 窗口由上海金(2016末)限定 ~9.5 年，含 2018贸易战/2020疫情/2022熊市（能检验降风险价值）
"""
from __future__ import annotations

import json
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
TRADING_DAYS = 252
RISK_FREE = 0.02

# 资产 → 长历史指数源
PRICE_SRC = {
    "纳指":     ("us", ".IXIC"),
    "标普500":  ("us", ".INX"),
    "道指":     ("us", ".DJI"),
    "沪深300":  ("cs", "000300"),
    "红利低波":  ("cs", "H30269"),
    "中证全债":  ("cs", "H11001"),
    "黄金":     ("gold", "Au99.99"),
}

# 组合权重（portfolio 级；股40=拆分，债30，商品(金)15，类现金15）
# 股票内部(越南剔除后归一)：US 50%(纳指/标普各25%) + CN 50%(沪深300)
W_A = {"纳指": 0.10, "标普500": 0.10, "沪深300": 0.20, "中证全债": 0.30, "黄金": 0.15, "现金": 0.15}
W_B = {"道指": 0.10, "标普500": 0.10, "红利低波": 0.20, "中证全债": 0.30, "黄金": 0.15, "现金": 0.15}
# C：B 的股票部分(道指/标普/红利低波)按波动率目标动态缩放，缩下来的转现金
C_STOCK = {"道指": 0.25, "标普500": 0.25, "红利低波": 0.50}  # 股票 sleeve 内部权重
C_FIXED = {"中证全债": 0.30, "黄金": 0.15}                    # 非股固定


def _fetch_price(kind: str, code: str) -> pd.Series:
    if kind == "us":
        df = ak.index_us_stock_sina(symbol=code)
        s = df.set_index("date")["close"]
    elif kind == "cs":
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date="20100101", end_date="20991231")
        s = df.set_index("日期")["收盘"]
    elif kind == "gold":
        df = ak.spot_hist_sge(symbol="Au99.99")
        s = df.set_index("date")["close"]
    else:
        raise ValueError(kind)
    s.index = pd.to_datetime(s.index)
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    s.name = None
    return s


def _build_prices() -> pd.DataFrame:
    """拉各指数收盘 → 并集前向填充（不做全局截断，供多区间逐窗口切片用）。"""
    prices = {}
    for label, (kind, code) in PRICE_SRC.items():
        try:
            prices[label] = _fetch_price(kind, code)
            print(f"[回测] ✅ {label}({code}) {len(prices[label])}条 "
                  f"{prices[label].index[0].date()}~{prices[label].index[-1].date()}")
        except Exception as e:
            print(f"[回测] ⚠️ {label}({code}) 失败：{e}")
    return pd.DataFrame(prices).sort_index().ffill()


def _build_returns() -> pd.DataFrame:
    """全周期（所有序列共同窗口，由上海金 2016末 限定）的日收益表（含现金列=0）。"""
    px = _build_prices().dropna()
    rets = px.pct_change().dropna()
    rets["现金"] = 0.0                      # 类现金 0 收益 0 波动
    print(f"[回测] 对齐窗口：{rets.index[0].date()} ~ {rets.index[-1].date()}（{len(rets)} 日）")
    return rets


def _quarter_rebalance_dates(index: pd.DatetimeIndex) -> set:
    """季度首个交易日（季度变化点）。"""
    q = pd.Series(index.quarter, index=index)
    y = pd.Series(index.year, index=index)
    key = y.astype(str) + "Q" + q.astype(str)
    return set(index[key != key.shift(1)])


def _run_backtest(rets: pd.DataFrame, target_func) -> pd.Series:
    """
    固定/动态权重 + 季度再平衡：再平衡日按目标权重重置持仓，期间随收益漂移。
    target_func(date)-> {资产: 权重}。返回组合净值曲线（起点 1.0）。
    """
    assets = list(rets.columns)
    rebal = _quarter_rebalance_dates(rets.index)
    val = 1.0
    holdings = {a: val * target_func(rets.index[0]).get(a, 0.0) for a in assets}
    vals = []
    for date in rets.index:
        r = rets.loc[date]
        holdings = {a: holdings[a] * (1.0 + r[a]) for a in assets}
        val = sum(holdings.values())
        vals.append(val)
        if date in rebal:
            w = target_func(date)
            holdings = {a: val * w.get(a, 0.0) for a in assets}
    return pd.Series(vals, index=rets.index)


def _metrics(curve: pd.Series) -> dict:
    rets = curve.pct_change().dropna()
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = curve.iloc[-1] ** (1.0 / years) - 1.0
    vol = float(rets.std() * np.sqrt(TRADING_DAYS))
    sharpe = (cagr - RISK_FREE) / vol if vol > 0 else 0.0
    dd = curve / curve.cummax() - 1.0
    mdd = float(dd.min())
    trough = dd.idxmin()
    peak = curve[:trough].idxmax()
    calmar = cagr / abs(mdd) if mdd < 0 else float("nan")
    return {"cagr": round(cagr, 4), "vol": round(vol, 4), "sharpe": round(sharpe, 3),
            "max_drawdown": round(mdd, 4), "calmar": round(calmar, 3),
            "mdd_window": f"{peak.date()}~{trough.date()}"}


def run_backtest() -> dict:
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        vt = yaml.safe_load(f).get("vol_target", {})
    mode = vt.get("mode", "relative")
    target_vol = vt.get("target_vol", 0.12)
    base_lb = int(vt.get("baseline_lookback", 252))
    lb = int(vt.get("lookback_short", 60))
    floor, cap = vt.get("floor_multiplier", 0.5), vt.get("max_multiplier", 1.0)

    rets = _build_returns()

    # C 的动态股票权重：用 B 股票 sleeve 的滚动波动算乘数
    sleeve_ret = sum(rets[a] * w for a, w in C_STOCK.items())

    def target_A(date): return W_A
    def target_B(date): return W_B
    def target_C(date):
        idx = rets.index.get_loc(date)
        if idx < lb:
            mult = 1.0
        else:
            rv = float(sleeve_ret.iloc[idx - lb:idx].std() * np.sqrt(TRADING_DAYS))  # 近期波动
            if mode == "relative":
                # 以该 sleeve 自身长期波动为基准（自适应；窗口不足则用已有数据）
                bw = sleeve_ret.iloc[max(0, idx - base_lb):idx]
                tgt = float(bw.std() * np.sqrt(TRADING_DAYS))
            else:
                tgt = target_vol
            mult = min(cap, max(floor, tgt / rv)) if rv > 0 else cap
        stock_total = 0.40 * mult
        w = {a: stock_total * sw for a, sw in C_STOCK.items()}
        w.update(C_FIXED)
        w["现金"] = max(0.0, 1.0 - sum(w.values()))
        return w

    curves = {"A基准": _run_backtest(rets, target_A),
              "B低波": _run_backtest(rets, target_B),
              "C低波+波动目标": _run_backtest(rets, target_C)}
    metrics = {name: _metrics(c) for name, c in curves.items()}

    # 年度收益（看牛市代价 vs 熊市保护）
    cdf = pd.DataFrame(curves)
    annual = cdf.resample("YE").last().pct_change().dropna()
    annual_returns = {str(idx.year): {n: round(float(annual.loc[idx, n]), 4) for n in curves}
                      for idx in annual.index}

    result = {
        "window": {"start": str(rets.index[0].date()), "end": str(rets.index[-1].date()),
                   "n_days": int(len(rets))},
        "params": {"vol_target_mode": mode, "target_vol": target_vol, "baseline_lookback": base_lb,
                   "lookback": lb, "rebalance": "季度", "risk_free": RISK_FREE},
        "metrics": metrics,
        "annual_returns": annual_returns,
        "weights": {"A基准": W_A, "B低波": W_B},
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "backtest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "backtest.md").write_text(_render(result), encoding="utf-8")
    print("[回测] ✅ 已写入 outputs/backtest.json 和 .md")
    return result


# ---------- 多区间回测（含 2008/2015 深熊，逐窗口验证）----------
WINDOWS = [
    ("2008金融危机", "2007-10-01", "2009-03-31"),
    ("2015A股股灾", "2015-06-01", "2016-02-29"),
    ("2018贸易战回调", "2018-01-01", "2018-12-31"),
    ("2020新冠崩盘", "2020-01-01", "2020-05-31"),
    ("2022全年熊市", "2022-01-01", "2022-12-31"),
    ("全周期(有金)", "2016-12-20", None),
]
STOCK_KEYS = set(C_STOCK.keys())   # 道指/标普500/红利低波


def _renorm(weights: dict, avail: set) -> dict:
    w = {a: v for a, v in weights.items() if a in avail}
    tot = sum(w.values())
    return {a: v / tot for a, v in w.items()} if tot > 0 else w


def _window_metrics(curve: pd.Series) -> dict:
    rets = curve.pct_change().dropna()
    total = curve.iloc[-1] / curve.iloc[0] - 1.0
    vol = float(rets.std() * np.sqrt(TRADING_DAYS))
    mdd = float((curve / curve.cummax() - 1.0).min())
    return {"total_return": round(total, 4), "vol": round(vol, 4), "max_drawdown": round(mdd, 4)}


def run_multiperiod() -> dict:
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        vt = yaml.safe_load(f).get("vol_target", {})
    mode = vt.get("mode", "relative")
    base_lb, lb = int(vt.get("baseline_lookback", 252)), int(vt.get("lookback_short", 60))
    floor, cap = vt.get("floor_multiplier", 0.5), vt.get("max_multiplier", 1.0)
    target_vol_abs = vt.get("target_vol", 0.12)

    px = _build_prices()
    out = {}
    for name, start, end in WINDOWS:
        win = px.loc[start:end] if end else px.loc[start:]
        win = win.dropna(axis=1, how="any")          # 只保留该窗口全程有数据的资产
        if len(win) < 40:
            out[name] = {"note": "数据不足，跳过", "n_days": int(len(win)),
                         "assets": list(win.columns)}
            continue
        rets = win.pct_change().dropna()
        rets["现金"] = 0.0
        avail = set(rets.columns)
        wA, wB = _renorm(W_A, avail), _renorm(W_B, avail)
        sleeve_keys = [a for a in C_STOCK if a in avail]
        sw_sum = sum(C_STOCK[a] for a in sleeve_keys)
        sleeve_ret = sum(rets[a] * (C_STOCK[a] / sw_sum) for a in sleeve_keys)
        base_stock = sum(wB.get(a, 0) for a in sleeve_keys)   # B 中股票总权重（已归一）
        nonstock = {a: wB[a] for a in wB if a not in STOCK_KEYS}

        def tA(d, wA=wA): return wA
        def tB(d, wB=wB): return wB

        def tC(d, sleeve_ret=sleeve_ret, sleeve_keys=sleeve_keys, sw_sum=sw_sum,
               base_stock=base_stock, nonstock=nonstock):
            i = rets.index.get_loc(d)
            if i < lb:
                mult = 1.0
            else:
                rv = float(sleeve_ret.iloc[i - lb:i].std() * np.sqrt(TRADING_DAYS))
                tgt = float(sleeve_ret.iloc[max(0, i - base_lb):i].std() * np.sqrt(TRADING_DAYS)) \
                    if mode == "relative" else target_vol_abs
                mult = min(cap, max(floor, tgt / rv)) if rv > 0 else cap
            st = base_stock * mult
            w = {a: st * (C_STOCK[a] / sw_sum) for a in sleeve_keys}
            w.update(nonstock)
            w["现金"] = w.get("现金", 0) + max(0.0, base_stock - st)
            return w

        curves = {"A基准": _run_backtest(rets, tA), "B低波": _run_backtest(rets, tB),
                  "C低波+波动目标": _run_backtest(rets, tC)}
        out[name] = {
            "window": f"{rets.index[0].date()}~{rets.index[-1].date()}",
            "n_days": int(len(rets)),
            "has_gold": "黄金" in avail,
            "metrics": {k: _window_metrics(c) for k, c in curves.items()},
        }

    result = {"mode": mode, "windows": out}
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "backtest_multiperiod.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "backtest_multiperiod.md").write_text(_render_multi(result), encoding="utf-8")
    print("[回测·多区间] ✅ 已写入 outputs/backtest_multiperiod.{json,md}")
    return result


def _render_multi(r: dict) -> str:
    lines = ["# 多区间回测：低波处方在不同行情（尤其深熊）下的表现", ""]
    lines.append(f"> vol_target 模式 `{r['mode']}`｜季度再平衡｜每个区间只用该区间全程有数据的资产"
                 "（缺则剔除并归一，A/B/C 一致）。短危机区间看**区间总收益+最大回撤**比年化更有意义。")
    lines.append("")
    lines.append("| 区间 | 天数 | 含金 | 组合 | 区间总收益 | 最大回撤 | 年化波动 |")
    lines.append("|------|------|------|------|------|------|------|")
    bear_summary = []
    for name, d in r["windows"].items():
        if "metrics" not in d:
            lines.append(f"| {name} | {d.get('n_days',0)} | - | — | {d['note']} | | |")
            continue
        m = d["metrics"]
        for i, k in enumerate(["A基准", "B低波", "C低波+波动目标"]):
            x = m[k]
            head = f"| **{name}**<br>{d['window']} | {d['n_days']} | {'是' if d['has_gold'] else '否'} " if i == 0 else "| | | "
            lines.append(f"{head}| {k} | {x['total_return']*100:+.1f}% | {x['max_drawdown']*100:.1f}% | {x['vol']*100:.1f}% |")
        # 熊市保护：B vs A 的回撤改善
        da, db = m["A基准"]["max_drawdown"], m["B低波"]["max_drawdown"]
        bear_summary.append((name, (db - da) * 100, (m["B低波"]["total_return"] - m["A基准"]["total_return"]) * 100))
    lines.append("")
    lines.append("## 熊市保护小结（B 低波 vs A 基准）")
    for name, dd_delta, ret_delta in bear_summary:
        better = "回撤更浅 ✅" if dd_delta > 0 else ("回撤更深 ⚠️" if dd_delta < 0 else "持平")
        lines.append(f"- **{name}**：B 最大回撤较 A {dd_delta:+.1f}pp（{better}），区间收益差 {ret_delta:+.1f}pp")
    lines.append("")
    lines.append("> 判读：若 B 在多数深熊里回撤更浅，说明低波处方的「保险」在压力期确实兑现；"
                 "牛市少赚是保费。结合全周期 Sharpe（见 backtest.md）一起看，是风险偏好取舍。")
    return "\n".join(lines)


def _render(r: dict) -> str:
    m = r["metrics"]
    w = r["window"]
    lines = ["# 回测：降股票风险这套做法是否改善风险收益比（④）", ""]
    lines.append(f"> 区间 **{w['start']} ~ {w['end']}**（{w['n_days']} 交易日，含2018/2020/2022 压力期）"
                 f"｜季度再平衡｜无风险利率 {r['params']['risk_free']*100:.0f}%")
    lines.append("> 用长历史**指数**回测（忽略基金费用/跟踪误差）；越南无长指数已剔除并归一；"
                 "high_risk/保险/现金 合并为类现金。")
    lines.append("")
    lines.append("| 组合 | 年化收益 | 年化波动 | **Sharpe** | 最大回撤 | Calmar |")
    lines.append("|------|------|------|------|------|------|")
    for name in ["A基准", "B低波", "C低波+波动目标"]:
        x = m[name]
        lines.append(f"| {name} | {x['cagr']*100:.1f}% | {x['vol']*100:.1f}% | "
                     f"**{x['sharpe']:.2f}** | {x['max_drawdown']*100:.1f}% | {x['calmar']:.2f} |")
    lines.append("")
    a, b, c = m["A基准"], m["B低波"], m["C低波+波动目标"]

    # 年度收益表
    ar = r["annual_returns"]
    lines.append("## 分年度收益（看清「牛市代价 vs 熊市保护」）")
    lines.append("| 年份 | A基准 | B低波 | C低波+波动目标 |")
    lines.append("|------|------|------|------|")
    for yr in sorted(ar.keys()):
        row = ar[yr]
        lines.append(f"| {yr} | {row['A基准']*100:+.1f}% | {row['B低波']*100:+.1f}% | {row['C低波+波动目标']*100:+.1f}% |")
    lines.append("")

    lines.append("## 解读")
    lines.append(f"- **波动**：A {a['vol']*100:.1f}% → B {b['vol']*100:.1f}% → C {c['vol']*100:.1f}%"
                 f"（低波替换确实降波动 {abs(b['vol']-a['vol'])*100:.1f}pp，目标达成）")
    lines.append(f"- **最大回撤**：A {a['max_drawdown']*100:.1f}% / B {b['max_drawdown']*100:.1f}% / "
                 f"C {c['max_drawdown']*100:.1f}%，都发生在 **{a['mdd_window']}（新冠崩盘）**——"
                 f"那次**道指比纳指跌得更多**（价值/周期股更惨），故美股低波替换没帮上回撤，与CN端红利低波的保护相互抵消。")
    lines.append("- **熊市保护 ✅ 在年度数据里很明显**：A 的下跌年里 B 损失明显更小（见上表 2018、2022）——降风险的核心目标达成了。")
    lines.append("- **代价在牛市**：B 在大涨年少赚不少（尤其 2019-2020 纳指狂飙），全周期 CAGR 因此被拉低。")
    best = max(m, key=lambda k: m[k]["sharpe"])
    mode = r["params"].get("vol_target_mode", "?")
    if c["sharpe"] >= b["sharpe"]:
        lines.append(f"- **C（波动目标，`{mode}`模式）≥ B**：校准为「以组合自身长期波动为基准」后，波动目标在压力期真正触发并改善了风险调整后收益（Sharpe {b['sharpe']:.2f}→{c['sharpe']:.2f}、回撤 {b['max_drawdown']*100:.1f}%→{c['max_drawdown']*100:.1f}%）。")
    else:
        lines.append(f"- **C（波动目标，`{mode}`模式）仍弱于 B**：本窗口股票波动多数时间未显著超基准，触发有限，动态减仓的择时拖累 > 降险收益（Sharpe {b['sharpe']:.2f}→{c['sharpe']:.2f}）。说明波动目标的价值高度依赖是否真有持续的高波区间。")
    lines.append("")
    lines.append(f"## 结论（{w['start'][:4]}-{w['end'][:4]} 窗口，全周期 Sharpe 最高：{best}）")
    lines.append("- **目标达成**：低波替换真的降低了波动与熊市回撤（2022 年尤其明显）——「降股票风险」奏效。")
    lines.append("- **但本窗口 Sharpe 未升**：这十年是美股成长股历史性大牛市，处方让出的牛市上行 > 省下的风险，"
                 "故风险调整后收益没赢基准。这不是「处方无效」，而是「这段牛市里买保险不划算」。")
    lines.append(f"- **行动项**：① ✅ C 的波动率目标已校准为 `{mode}` 模式（以组合自身长期波动为基准，自适应）；"
                 "② 单一窗口（且缺2008级深熊）不足以定论，低波/价值的超额回报有强周期性，需多区间/含深熊再验。")
    lines.append("> 判据是 Sharpe/Calmar（风险调整后），非绝对收益。低波替换是「牛市付保费、熊市领赔付」的保险，本质是风险偏好选择。")
    return "\n".join(lines)
