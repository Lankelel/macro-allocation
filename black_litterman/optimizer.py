"""
V2.3 Black-Litterman 融合（决策 A2）

用 BL 把"4 大师评分(M2)"以数学自洽的方式映射成 sleeve 内部目标权重，
替代 M3 现在"评分×±2% 直接拍"的粗糙做法。

BL 三步直觉（你有经济学基础，按这个理解）：
1. 反推均衡先验 Π：假设"基准权重(等权)就是市场最优"，反推出市场隐含的预期收益
   （公式 Π = δ·Σ·w，δ=风险厌恶，Σ=协方差，w=基准权重）。
2. 融合观点 Q + 置信度 Ω：把大师评分转成"我认为某资产收益会偏离 Π 多少"(Q)，
   并带置信度——评分越极端越自信(Ω越小)；评分0=无观点，不发表。
3. 后验收益 → 优化：BL 按置信度加权融合 Π 和 Q 得后验收益，再跑均值-方差优化出权重。
   好处：分歧/低置信→几乎不动(贴近基准)；高置信→才倾斜；且全程尊重相关性，不出极端解。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pypfopt import BlackLittermanModel, EfficientFrontier, black_litterman
from sklearn.covariance import LedoitWolf

from risk_engine.fetcher import fetch_returns

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
TRADING_DAYS = 252


def _bl_params() -> dict:
    """从 settings.yaml 读 BL 校准参数（带兜底默认）。"""
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        bl = yaml.safe_load(f).get("bl", {})
    return {
        "delta": bl.get("delta", 2.5),
        "step_return": bl.get("step_return", 0.015),
        "confidence_scale": bl.get("confidence_scale", 0.5),
        "max_weight": bl.get("max_weight", 0.50),
        "risk_free": bl.get("risk_free", 0.02),
    }


def _annual_cov(returns: pd.DataFrame) -> pd.DataFrame:
    """Ledoit-Wolf 收缩协方差（年化），DataFrame 形式供 pypfopt 用。"""
    lw = LedoitWolf().fit(returns.values)
    cov = pd.DataFrame(lw.covariance_ * TRADING_DAYS,
                       index=returns.columns, columns=returns.columns)
    return cov


def run_bl_on_sleeve(sleeve_name: str = "commodity", lookback_days: int = 504) -> dict:
    """
    对某个 sleeve 跑 BL，输出 sleeve 内部目标权重。

    Args:
        sleeve_name: holdings.yaml sleeves 下的键（默认 commodity）
        lookback_days: 回溯交易日
    """
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    sleeve = holdings["sleeves"][sleeve_name]          # {label: {code, name, ...}}
    labels = list(sleeve.keys())
    assets = {lab: sleeve[lab]["code"] for lab in labels}

    # M2 观点（directions.json 的 commodities 块）
    dpath = OUTPUTS_DIR / "directions.json"
    scores = {}
    if dpath.exists():
        final = json.loads(dpath.read_text(encoding="utf-8"))["final"]
        block = final.get("commodities" if sleeve_name == "commodity" else "regions", {})
        scores = {lab: block.get(lab, {}).get("strength", 0) for lab in labels}
    else:
        scores = {lab: 0 for lab in labels}
    print(f"[V2.3] {sleeve_name} M2 评分：{scores}")

    p = _bl_params()

    # 1) 协方差 + 等权基准先验
    returns = fetch_returns(assets, lookback_days=lookback_days)
    labels = list(returns.columns)  # 以实际拉到的为准
    cov = _annual_cov(returns)
    w_mkt = pd.Series(1.0 / len(labels), index=labels)          # 等权基准
    pi = black_litterman.market_implied_prior_returns(w_mkt, p["delta"], cov, p["risk_free"])

    # 2) 评分 → 绝对观点 + 置信度（评分0不发表观点）
    #    校准：step_return 偏移更温和，置信度乘 confidence_scale 进一步降低观点强度
    abs_views, confidences = {}, []
    for lab in labels:
        s = scores.get(lab, 0)
        if s == 0:
            continue
        abs_views[lab] = float(pi[lab] + s * p["step_return"])
        confidences.append(min(abs(s) / 2.0, 1.0) * p["confidence_scale"])

    # 3) BL 融合 → 后验收益 → 优化
    if abs_views:
        bl = BlackLittermanModel(cov, pi=pi, absolute_views=abs_views,
                                 omega="idzorek", view_confidences=confidences)
        post_ret = bl.bl_returns()
    else:
        post_ret = pi  # 无任何观点 → 退回先验

    ef = EfficientFrontier(post_ret, cov, weight_bounds=(0.0, p["max_weight"]))
    ef.max_sharpe(risk_free_rate=p["risk_free"])
    w = ef.clean_weights()

    # 对照：等权基准
    base = {lab: round(1.0 / len(labels), 4) for lab in labels}

    result = {
        "sleeve": sleeve_name,
        "assets": {lab: sleeve[lab]["name"] for lab in labels},
        "scores": {lab: scores.get(lab, 0) for lab in labels},
        "prior_implied_return": {lab: round(float(pi[lab]), 4) for lab in labels},
        "posterior_return": {lab: round(float(post_ret[lab]), 4) for lab in labels},
        "baseline_weight": base,
        "bl_weight": {lab: round(float(w[lab]), 4) for lab in labels},
        "params": {"delta": p["delta"], "step_return": p["step_return"],
                   "confidence_scale": p["confidence_scale"],
                   "bounds": f"0~{int(p['max_weight']*100)}%"},
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / f"bl_{sleeve_name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / f"bl_{sleeve_name}.md").write_text(_render(result), encoding="utf-8")
    print(f"[V2.3] ✅ 已写入 outputs/bl_{sleeve_name}.json 和 .md")
    return result


def _region_returns(lookback_days: int):
    """从 class_representatives.stock.basket 按 region 分组，构造各地域收益序列。"""
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    basket = holdings["class_representatives"]["stock"]["basket"]

    # 按 region 分组：region -> [(标签, 篮子内权重)]
    underlying, groups = {}, {}
    for leg in basket:
        region = leg["region"]
        lab = f"{region}__{leg['code']}"
        underlying[lab] = leg["code"]
        groups.setdefault(region, []).append((lab, float(leg["w"])))

    rets = fetch_returns(underlying, lookback_days=lookback_days)
    region_df = pd.DataFrame(index=rets.index)
    for region, legs in groups.items():
        avail = [(lab, w) for lab, w in legs if lab in rets.columns]
        tot = sum(w for _, w in avail)
        if tot > 0:
            region_df[region] = sum(rets[lab] * (w / tot) for lab, w in avail)

    # 基线地域权重（holdings stock_region 的 target_pct，非零归一）
    sr = holdings["sleeves"]["stock_region"]
    base = {r: sr[r]["target_pct"] for r in region_df.columns if r in sr}
    s = sum(base.values())
    base = {r: base[r] / s for r in base}
    return region_df.dropna(), base


def run_bl_stock_regions(lookback_days: int = 504) -> dict:
    """
    ② BL 用到股票地域(US/CN/Asia)：M2 地域评分作为观点，融合基线先验，
    用更高风险厌恶(防御)优化 → 地域权重，并报告对股票sleeve波动的影响（服务降股票风险目标）。
    """
    p = _bl_params()
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        bl_cfg = yaml.safe_load(f).get("bl", {})
    stock_delta = bl_cfg.get("stock_risk_aversion", 5.0)
    stock_max_w = bl_cfg.get("stock_max_weight", 0.50)

    # M2 地域评分
    dpath = OUTPUTS_DIR / "directions.json"
    region_scores = {}
    if dpath.exists():
        region_scores = json.loads(dpath.read_text(encoding="utf-8"))["final"].get("regions", {})

    rets, base_w = _region_returns(lookback_days)
    regions = list(rets.columns)
    scores = {r: region_scores.get(r, {}).get("strength", 0) for r in regions}
    print(f"[V2.3②] 股票地域 M2 评分：{scores}")

    cov = _annual_cov(rets)
    w_base = pd.Series([base_w[r] for r in regions], index=regions)
    pi = black_litterman.market_implied_prior_returns(w_base, p["delta"], cov, p["risk_free"])

    abs_views, confidences = {}, []
    for r in regions:
        s = scores.get(r, 0)
        if s == 0:
            continue
        abs_views[r] = float(pi[r] + s * p["step_return"])
        confidences.append(min(abs(s) / 2.0, 1.0) * p["confidence_scale"])

    if abs_views:
        bl = BlackLittermanModel(cov, pi=pi, absolute_views=abs_views,
                                 omega="idzorek", view_confidences=confidences)
        post_ret = bl.bl_returns()
    else:
        post_ret = pi

    # 防御性优化：max_quadratic_utility(高风险厌恶) → 偏向低波地域
    ef = EfficientFrontier(post_ret, cov, weight_bounds=(0.0, stock_max_w))
    ef.max_quadratic_utility(risk_aversion=stock_delta)
    w_bl = ef.clean_weights()

    # 风险影响：股票sleeve在 基线 vs BL 权重下的年化波动
    def _sleeve_vol(weights: dict) -> float:
        wv = np.array([weights[r] for r in regions])
        Sig = cov.values
        return float(np.sqrt(wv @ Sig @ wv))

    vol_base = _sleeve_vol(base_w)
    vol_bl = _sleeve_vol(w_bl)

    result = {
        "sleeve": "stock_region",
        "regions": regions,
        "scores": {r: scores.get(r, 0) for r in regions},
        "region_volatility": {r: round(float(np.sqrt(cov.loc[r, r])), 4) for r in regions},
        "baseline_weight": {r: round(base_w[r], 4) for r in regions},
        "bl_weight": {r: round(float(w_bl[r]), 4) for r in regions},
        "stock_sleeve_vol": {"baseline": round(vol_base, 4), "bl": round(vol_bl, 4),
                             "change": round(vol_bl - vol_base, 4)},
        "params": {"step_return": p["step_return"], "stock_risk_aversion": stock_delta,
                   "max_weight": stock_max_w},
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "bl_stock_region.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "bl_stock_region.md").write_text(_render_stock(result), encoding="utf-8")
    print("[V2.3②] ✅ 已写入 outputs/bl_stock_region.json 和 .md")
    return result


def _render_stock(r: dict) -> str:
    cn = {"US": "美国", "CN": "中国", "Asia": "新兴亚洲", "EU": "欧洲", "JP": "日本"}
    regs = r["regions"]
    lines = [f"# Black-Litterman 股票地域权重（V2.3 ②）", ""]
    lines.append(f"> 风险厌恶={r['params']['stock_risk_aversion']}(防御)｜每分偏移={r['params']['step_return']}｜单地域上限={int(r['params']['max_weight']*100)}%")
    lines.append("")
    lines.append("| 地域 | M2评分 | 地域年化波动 | 基线权重 | **BL权重** | 变动 |")
    lines.append("|------|-------|------------|---------|-----------|------|")
    for r2 in regs:
        base = r["baseline_weight"][r2] * 100
        bl = r["bl_weight"][r2] * 100
        lines.append(f"| {cn.get(r2,r2)} | {r['scores'][r2]:+d} | {r['region_volatility'][r2]*100:.1f}% | "
                     f"{base:.0f}% | **{bl:.0f}%** | {bl-base:+.0f}pp |")
    lines.append("")
    sv = r["stock_sleeve_vol"]
    lines.append("## 对股票 sleeve 波动的影响（服务「降股票风险」目标）")
    lines.append(f"- 基线权重下股票波动：**{sv['baseline']*100:.1f}%**")
    lines.append(f"- BL 权重下股票波动：**{sv['bl']*100:.1f}%**")
    arrow = "↓ 降低" if sv["change"] < 0 else ("↑ 升高" if sv["change"] > 0 else "持平")
    lines.append(f"- 变化：**{sv['change']*100:+.1f}pp（{arrow}）** → {'有助于' if sv['change']<0 else '未降低'}股票风险贡献")
    return "\n".join(lines)


def _render(r: dict) -> str:
    labs = list(r["assets"].keys())
    lines = [f"# Black-Litterman 目标权重（V2.3）- {r['sleeve']} sleeve", ""]
    lines.append(f"> δ={r['params']['delta']}｜每分偏移={r['params']['step_return']}｜权重界={r['params']['bounds']}")
    lines.append("")
    lines.append("| 资产 | M2评分 | 先验收益 | 后验收益 | 等权基准 | **BL权重** | 对比基准 |")
    lines.append("|------|-------|---------|---------|---------|-----------|---------|")
    for lab in labs:
        base = r["baseline_weight"][lab] * 100
        bl = r["bl_weight"][lab] * 100
        lines.append(f"| {r['assets'][lab]} | {r['scores'][lab]:+d} | "
                     f"{r['prior_implied_return'][lab]*100:.1f}% | {r['posterior_return'][lab]*100:.1f}% | "
                     f"{base:.0f}% | **{bl:.0f}%** | {bl-base:+.0f}pp |")
    lines.append("")
    lines.append("> BL vs A1线性倾斜：BL 的权重综合了相关性+置信度，分歧小则贴近基准、高置信才倾斜，且不会出极端解。")
    return "\n".join(lines)
