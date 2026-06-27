"""
低波红利替换（处方第①步，最高效）- 主编排

保持股票总占比 40% 与地域权重不变，只把股票内部的风格从高波宽基/成长，挪向低波/价值/蓝筹
→ 降低股票 sleeve 自身波动 → 降风险贡献。依据"低波动异象"：低波股长期风险调整后收益不输，
故这是"几乎不损收益"的最高效杠杆。

风格/低波的认定一律靠数据，绝不靠名字：
  - A股基金：RBSA 收益回归（对红利低波/成长/价值指数）+ 看穿真实重仓股 双重验证
  - 美股QDII：A股风格指数回归不适用（R²为负），改用「波动率 + 与纳指相关性」验证低波属性

四部分：
  1. RBSA 风格体检（A股有效，海外标注不适用）
  2. 看穿持仓交叉验证（A股真实重仓）
  3. 美股低波标的验证（波动/相关性，因风格回归不适用）
  4. 替换测算（多地域：CN 沪深300→红利低波、US 纳指→道琼斯；单地域+合并效果）
"""
from __future__ import annotations

import json
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import yaml

from risk_engine.fetcher import fetch_returns
from .rbsa import fetch_factor_returns, run_rbsa

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
TRADING_DAYS = 252


def _load_cfg():
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        st = yaml.safe_load(f)["style_tilt"]
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    return st, holdings


def _top_holdings(code: str, n: int = 5) -> list[str]:
    """看穿持仓交叉验证：拉真实前 N 大重仓股（名实对照）。"""
    try:
        df = ak.fund_portfolio_hold_em(symbol=code, date="2024").head(n)
        return [f"{r['股票名称']}({r['占净值比例']}%)" for _, r in df.iterrows()]
    except Exception as e:
        return [f"（看穿失败：{e}）"]


def _ann_vol(s: pd.Series) -> float:
    return float(s.std() * np.sqrt(TRADING_DAYS))


def run_style_tilt() -> dict:
    st, holdings = _load_cfg()
    lookback = int(st["lookback_days"])
    factors = st["factor_indices"]
    swaps = st["swaps"]
    basket = holdings["class_representatives"]["stock"]["basket"]

    # ---------- 拉数据 ----------
    factor_ret = fetch_factor_returns(factors, lookback_days=lookback)

    # 篮子各腿（region__code） + 各替换标的（TO__code）
    fund_codes, region_of, name_of = {}, {}, {}
    for leg in basket:
        lab = f"{leg['region']}__{leg['code']}"
        fund_codes[lab] = leg["code"]
        region_of[lab] = leg["region"]
        name_of[lab] = leg["name"]
    for sw in swaps:
        to = sw["to"]
        lab = f"TO__{to['code']}"
        fund_codes[lab] = to["code"]
        region_of[lab] = sw["region"]
        name_of[lab] = to["name"]
    fund_ret = fetch_returns(fund_codes, lookback_days=lookback)

    # ---------- 1. RBSA 风格体检 ----------
    style_report = {}
    for lab in fund_ret.columns:
        reg = region_of.get(lab, "?")
        rb = run_rbsa(fund_ret[lab], factor_ret)
        rb["region"] = reg
        rb["name"] = name_of.get(lab, lab)
        rb["overseas"] = reg in ("US", "Asia")   # 海外对A股风格指数回归无意义，R²会很低
        rb["annual_vol"] = round(_ann_vol(fund_ret[lab]), 4)
        style_report[lab] = rb

    # ---------- 2. 看穿持仓交叉验证（A股）----------
    cross_check = {code: _top_holdings(code) for code in st.get("holdings_check", [])}

    # ---------- 3. 美股低波标的验证（波动 + 相关性）----------
    us_labs = [lab for lab in fund_ret.columns if region_of.get(lab) == "US"]
    us_verify = None
    if len(us_labs) >= 2:
        corr = fund_ret[us_labs].corr()
        us_verify = {
            "labels": {lab: name_of[lab] for lab in us_labs},
            "annual_vol": {lab: round(_ann_vol(fund_ret[lab]), 4) for lab in us_labs},
            "annual_return": {lab: round(float(fund_ret[lab].mean() * TRADING_DAYS), 4) for lab in us_labs},
            "corr": {a: {b: round(float(corr.loc[a, b]), 2) for b in us_labs} for a in us_labs},
        }

    # ---------- 4. 替换测算（多地域）----------
    swap = _swap_analysis(fund_ret, basket, swaps, region_of, name_of)

    result = {
        "factors": list(factor_ret.columns),
        "lookback_days": lookback,
        "n_obs": int(len(factor_ret)),
        "style_report": style_report,
        "cross_check": cross_check,
        "us_verify": us_verify,
        "swap": swap,
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "style_tilt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "style_tilt.md").write_text(_render(result), encoding="utf-8")
    print("[风格] ✅ 已写入 outputs/style_tilt.json 和 .md")
    return result


def _sleeve_vol(fund_ret: pd.DataFrame, weights: dict[str, float]) -> float:
    """给定篮子各腿权重，合成 sleeve 日收益 → 年化波动。"""
    avail = {lab: w for lab, w in weights.items() if lab in fund_ret.columns and w > 0}
    tot = sum(avail.values())
    sleeve = sum(fund_ret[lab] * (w / tot) for lab, w in avail.items())
    return float(sleeve.std() * np.sqrt(TRADING_DAYS))


def _swap_analysis(fund_ret, basket, swaps, region_of, name_of) -> dict:
    """
    多地域替换：每个 swap 在同地域内把「高波腿(from)」按比例 θ 挪到「低波腿(to)」，
    保持股票总占比与各地域权重不变。报告单地域曲线 + 全替换(各θ=1)合并效果。
    """
    base_w = {f"{leg['region']}__{leg['code']}": float(leg["w"]) for leg in basket}
    baseline_vol = _sleeve_vol(fund_ret, base_w)

    per_swap = []
    for sw in swaps:
        region, from_code, to = sw["region"], sw["from_code"], sw["to"]
        from_lab = next((l for l in base_w if region_of.get(l) == region and l.endswith(from_code)), None)
        to_lab = f"TO__{to['code']}"
        if from_lab is None or to_lab not in fund_ret.columns:
            continue
        leg_w = base_w[from_lab]
        curve = []
        for theta in [0.0, 0.25, 0.5, 0.75, 1.0]:
            w = dict(base_w)
            w[from_lab] = leg_w * (1 - theta)
            w[to_lab] = leg_w * theta
            curve.append({"theta": theta, "sleeve_vol": round(_sleeve_vol(fund_ret, w), 4)})
        per_swap.append({
            "region": region,
            "from": {"label": from_lab, "name": name_of.get(from_lab), "vol": round(_ann_vol(fund_ret[from_lab]), 4)},
            "to": {"label": to_lab, "name": to["name"], "vol": round(_ann_vol(fund_ret[to_lab]), 4)},
            "leg_weight": round(leg_w, 4),
            "curve": curve,
            "reduction_pp": round((curve[0]["sleeve_vol"] - curve[-1]["sleeve_vol"]) * 100, 2),
        })

    # 合并：所有 swap 全替换（θ=1）
    w_all = dict(base_w)
    for sw in swaps:
        region, from_code, to = sw["region"], sw["from_code"], sw["to"]
        from_lab = next((l for l in base_w if region_of.get(l) == region and l.endswith(from_code)), None)
        to_lab = f"TO__{to['code']}"
        if from_lab is None or to_lab not in fund_ret.columns:
            continue
        w_all[to_lab] = w_all.get(to_lab, 0) + w_all[from_lab]
        w_all[from_lab] = 0.0
    combined_vol = _sleeve_vol(fund_ret, w_all)

    return {
        "baseline_vol": round(baseline_vol, 4),
        "per_swap": per_swap,
        "combined_full_vol": round(combined_vol, 4),
        "combined_reduction_pp": round((baseline_vol - combined_vol) * 100, 2),
    }


def _render(r: dict) -> str:
    sr = r["style_report"]
    factors = r["factors"]
    lines = ["# 低波红利替换 - 风格体检 + 替换测算（处方第①步）", ""]
    lines.append(f"> 风格/低波认定一律靠数据，不靠名字｜A股因子：{' / '.join(factors)}｜"
                 f"窗口 {r['n_obs']} 交易日｜RBSA 约束：系数≥0 且 和=1")
    lines.append("")

    # 1. RBSA 风格体检
    lines.append("## 1. RBSA 风格体检（A股有效；海外看 R²，不适用则改用第3节）")
    lines.append("| 基金 | 地域 | 年化波动 | " + " | ".join(factors) + " | R² | 判定 |")
    lines.append("|------|------|------|" + "------|" * len(factors) + "----|------|")
    for lab, rb in sr.items():
        cells = " | ".join(f"{rb['loadings'][f]*100:.0f}%" for f in factors)
        note = "⚠️海外,风格回归不适用" if rb["overseas"] else "✅A股可信"
        lines.append(f"| {rb['name']} | {rb['region']} | {rb['annual_vol']*100:.1f}% | {cells} | {rb['r2']:.2f} | {note} |")
    lines.append("")
    lines.append("> 读法：系数=该基金收益“behaves like”多少比例的对应风格；R² 越高归因越可信。海外基金 R² 必然很低（甚至为负），结论无效。")
    lines.append("")

    # 2. 看穿持仓
    lines.append("## 2. 看穿持仓交叉验证（A股真实重仓，核对 RBSA）")
    for code, holds in r["cross_check"].items():
        lines.append(f"- **{code}** 前5大重仓：{' / '.join(holds)}")
    lines.append("")

    # 3. 美股低波验证
    uv = r.get("us_verify")
    if uv:
        lines.append("## 3. 美股低波标的验证（风格回归不适用 → 用波动/相关性）")
        labs = list(uv["labels"].keys())
        lines.append("| 美股基金 | 年化波动 | 年化收益 |")
        lines.append("|------|------|------|")
        for lab in labs:
            lines.append(f"| {uv['labels'][lab]} | {uv['annual_vol'][lab]*100:.1f}% | {uv['annual_return'][lab]*100:.1f}% |")
        lines.append("")
        lines.append("相关性矩阵：")
        lines.append("| | " + " | ".join(uv['labels'][l] for l in labs) + " |")
        lines.append("|" + "---|" * (len(labs) + 1))
        for a in labs:
            row = " | ".join(f"{uv['corr'][a][b]:+.2f}" for b in labs)
            lines.append(f"| **{uv['labels'][a]}** | {row} |")
        lines.append("")
        lines.append("> 低波标的判据：波动显著低于纳指、且与纳指相关性更低（有真分散）。")
        lines.append("")

    # 4. 替换测算
    sw = r["swap"]
    lines.append("## 4. 替换测算：同地域内 高波腿 → 低波腿（股票占比/地域权重不变）")
    lines.append(f"> 现状股票 sleeve 年化波动：**{sw['baseline_vol']*100:.2f}%**")
    lines.append("")
    cn = {"US": "美国", "CN": "中国", "Asia": "亚洲"}
    for ps in sw["per_swap"]:
        lines.append(f"### {cn.get(ps['region'],ps['region'])}：{ps['from']['name']}(波动{ps['from']['vol']*100:.1f}%) "
                     f"→ {ps['to']['name']}(波动{ps['to']['vol']*100:.1f}%)　篮内该腿权重 {ps['leg_weight']*100:.0f}%")
        lines.append("| 替换比例 θ | 股票 sleeve 波动 |")
        lines.append("|------|------|")
        for pt in ps["curve"]:
            flag = "（现状）" if pt["theta"] == 0 else ("（全换）" if pt["theta"] == 1 else "")
            lines.append(f"| {pt['theta']*100:.0f}% | {pt['sleeve_vol']*100:.2f}% {flag}|")
        lines.append(f"- 单独全换可降 **{ps['reduction_pp']:.2f}pp**")
        lines.append("")
    lines.append(f"## 合并效果（CN+US 全替换）")
    lines.append(f"- 现状 **{sw['baseline_vol']*100:.2f}%** → 合并全换 **{sw['combined_full_vol']*100:.2f}%**，"
                 f"共降 **{sw['combined_reduction_pp']:.2f}pp**")
    lines.append("> 依据低波动异象：低波股长期风险调整后收益不输，故这是处方里最高效、最该先用的杠杆。"
                 "实操不必全换，按可接受的收益/波动取舍选 θ。")
    return "\n".join(lines)
