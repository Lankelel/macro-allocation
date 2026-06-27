"""
③ E3 波动率目标（Volatility Targeting）

降股票风险处方的第④步——唯一"动态、不永久牺牲收益"的杠杆：
平时满仓股票拿收益，只在**近期波动飙升的危险期**机械减仓转现金，风平浪静再回满仓。
补上 ①(篮子校准)②(地域BL) 这类"静态结构优化"够不到的**时间维度**。

核心公式（一行）：
    乘数 = 目标波动 / 近期实测波动        然后裁剪到 [下限, 上限]
    股票目标权重 = SAA股票权重 × 乘数
    减下来的钱 → 现金

直觉：
- 近期波动 > 目标 → 乘数<1 → 减仓（市场越危险砍越多）
- 近期波动 ≤ 目标 → 乘数=1（上限，无杠杆不超配）→ 满仓不动
- 用**短窗口(60日≈1季度)**算实测波动，比诊断/BL的504日长窗更灵敏，才能捕捉"飙升"。
- 与"再平衡"分工：再平衡把仓位拉回**固定**目标；vol_target 动态调整这个**目标本身**。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from risk_engine.fetcher import fetch_returns

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
TRADING_DAYS = 252


def _stock_sleeve_returns(lookback_days: int) -> pd.Series:
    """从 class_representatives.stock.basket 按篮子权重合成股票 sleeve 的日收益序列。"""
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    basket = holdings["class_representatives"]["stock"]["basket"]

    underlying = {f"{leg['code']}": leg["code"] for leg in basket}
    legs = [(leg["code"], float(leg["w"])) for leg in basket]
    rets = fetch_returns(underlying, lookback_days=lookback_days)

    avail = [(c, w) for c, w in legs if c in rets.columns]
    tot = sum(w for _, w in avail)
    sleeve = sum(rets[c] * (w / tot) for c, w in avail)  # 缺失腿自动剔除并重新归一
    return sleeve.dropna()


def run_vol_target() -> dict:
    """
    E3 主入口：算股票 sleeve 近期波动 vs 目标 → 仓位乘数 → 股票目标权重 + 转现金金额。
    """
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f).get("vol_target", {})
    mode = cfg.get("mode", "relative")
    target_vol_abs = cfg.get("target_vol", 0.12)
    baseline_lb = int(cfg.get("baseline_lookback", 252))
    lookback = int(cfg.get("lookback_short", 60))
    max_mult = cfg.get("max_multiplier", 1.0)
    floor_mult = cfg.get("floor_multiplier", 0.5)

    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    total = holdings["total_assets_wan"]
    locked = holdings.get("locked", {}).get("insurance_wan", 0.0)
    investable = total - locked                         # 非保险池
    saa_stock = holdings["saa_target"]["stock"]

    # 拉足够长的 sleeve 收益：relative 模式要长窗口算基准
    need = max(baseline_lb, lookback) + 20
    sleeve = _stock_sleeve_returns(lookback_days=need)
    window = sleeve.iloc[-lookback:]
    realized_vol = float(window.std() * np.sqrt(TRADING_DAYS))   # 近期波动

    # 目标波动：relative=该 sleeve 自身长期波动作基准（自适应）；absolute=固定值
    if mode == "relative":
        baseline_vol = float(sleeve.iloc[-baseline_lb:].std() * np.sqrt(TRADING_DAYS))
        target_vol = baseline_vol
    else:
        baseline_vol = None
        target_vol = target_vol_abs

    # 乘数 = 目标/近期，裁剪到 [下限, 上限]
    raw_mult = target_vol / realized_vol if realized_vol > 0 else max_mult
    mult = float(min(max_mult, max(floor_mult, raw_mult)))

    stock_target_w = saa_stock * mult
    derisk_w = saa_stock - stock_target_w               # 减掉的股票权重 → 现金
    derisk_wan = derisk_w * investable
    stock_wan_before = saa_stock * investable
    stock_wan_after = stock_target_w * investable

    if realized_vol <= target_vol:
        regime = "calm"        # 平静：满仓不动
    elif mult <= floor_mult + 1e-9:
        regime = "extreme"     # 极端：已砍到下限
    else:
        regime = "elevated"    # 偏高：按比例减仓

    result = {
        "mode": mode,
        "target_vol": round(target_vol, 4),
        "baseline_vol": round(baseline_vol, 4) if baseline_vol is not None else None,
        "baseline_lookback": baseline_lb if mode == "relative" else None,
        "realized_vol": round(realized_vol, 4),
        "lookback_days": lookback,
        "window_period": f"{window.index[0].date()} ~ {window.index[-1].date()}",
        "raw_multiplier": round(float(raw_mult), 4),
        "multiplier": round(mult, 4),
        "bounds": {"floor": floor_mult, "max": max_mult},
        "regime": regime,
        "saa_stock_weight": saa_stock,
        "stock_target_weight": round(stock_target_w, 4),
        "derisk_to_cash_wan": round(derisk_wan, 2),
        "stock_wan_before": round(stock_wan_before, 2),
        "stock_wan_after": round(stock_wan_after, 2),
        "investable_wan": investable,
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "vol_target.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "vol_target.md").write_text(_render(result), encoding="utf-8")
    print(f"[E3] ✅ 已写入 outputs/vol_target.json 和 .md")
    return result


def _render(r: dict) -> str:
    regime_cn = {
        "calm": "🟢 平静期：近期波动未超目标 → 满仓股票（无杠杆不超配）",
        "elevated": "🟡 波动偏高：按比例机械减仓股票、转现金",
        "extreme": "🔴 极端波动：已砍到仓位下限（防过度空仓踏空反弹）",
    }
    lines = ["# 波动率目标 - 动态削峰（③ E3）", ""]
    if r["mode"] == "relative":
        tgt_desc = f"目标=该sleeve自身长期波动 **{r['target_vol']*100:.1f}%**（{r['baseline_lookback']}日基准，自适应）"
    else:
        tgt_desc = f"目标年化波动 **{r['target_vol']*100:.0f}%**（固定）"
    lines.append(f"> 模式 `{r['mode']}`｜{tgt_desc}｜短窗口 {r['lookback_days']} 交易日"
                 f"（{r['window_period']}）｜乘数界 [{r['bounds']['floor']:.1f}, {r['bounds']['max']:.1f}]")
    lines.append("")
    lines.append("## 测算")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    if r["mode"] == "relative":
        lines.append(f"| 该 sleeve 长期基准波动 | {r['target_vol']*100:.1f}% |")
    lines.append(f"| 股票近期实测年化波动 | **{r['realized_vol']*100:.1f}%** |")
    if r["mode"] == "absolute":
        lines.append(f"| 目标波动(固定) | {r['target_vol']*100:.0f}% |")
    lines.append(f"| 原始乘数(目标/实测) | {r['raw_multiplier']:.2f} |")
    lines.append(f"| **裁剪后仓位乘数** | **{r['multiplier']:.2f}** |")
    lines.append(f"| 股票权重：SAA → 目标 | {r['saa_stock_weight']*100:.0f}% → **{r['stock_target_weight']*100:.0f}%** |")
    lines.append(f"| 股票金额：当前 → 目标 | {r['stock_wan_before']:.1f}w → {r['stock_wan_after']:.1f}w |")
    lines.append(f"| **建议转入现金** | **{r['derisk_to_cash_wan']:.1f}w** |")
    lines.append("")
    lines.append("## 信号")
    lines.append(f"- {regime_cn[r['regime']]}")
    if r["regime"] == "calm":
        lines.append("- 当前不触发减仓：放心持有股票拿收益。波动率目标只在危险期才出手，平时不损收益。")
    else:
        lines.append(f"- 机械减仓 **{r['derisk_to_cash_wan']:.1f}w** 股票转现金，把股票 sleeve 波动拉回 ~{r['target_vol']*100:.0f}% 目标。")
        lines.append("- 这是**临时削峰**，非永久减配：波动回落后乘数回升到 1.0，自动满仓回来。")
    lines.append("")
    lines.append("> 与再平衡分工：再平衡把仓位拉回**固定** SAA 目标；波动率目标动态调整**这个目标本身**（危险期调低）。")
    return "\n".join(lines)
