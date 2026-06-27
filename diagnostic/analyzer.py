"""
V2.2 风险贡献诊断 + 处方

用 V2.1 风险引擎的协方差矩阵，算出各大类对组合总风险的**贡献占比**（而非资金占比），
看清"假分散"，并给出无杠杆约束下的调整处方。

概念科普（边际风险贡献 MCR / 风险贡献 RC）：
- 组合波动 σ_p = sqrt(w'Σw)，w=权重向量，Σ=协方差矩阵
- 资产 i 的边际风险贡献 MCR_i = (Σw)_i / σ_p  （多持有一点 i，组合波动变化多少）
- 资产 i 的风险贡献 RC_i = w_i × MCR_i，且 ΣRC_i = σ_p（各资产风险贡献之和=组合总波动）
- 风险贡献占比 RC%_i = RC_i / σ_p （加总=100%）
- 核心洞察：资金占 40% 的股票，风险占比可能高达 70%+ → "假分散"

无杠杆处方（决策C，按"每降一单位风险损失收益从小到大"排序）：
  ①低波/红利替换 → ②加黄金等真分散器 → ③设风险上限 → ④波动率目标 → ⑤最后才加债/现金
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from risk_engine.engine import compute_risk
from risk_engine.fetcher import fetch_returns

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"

RISK_CAP = 0.60  # 单一大类风险贡献上限（超过即提示"假分散"/需处方）


def _build_class_returns(reps: dict, lookback_days: int) -> pd.DataFrame:
    """
    构造各大类的日收益序列，支持两种代表形式：
    - 单只代表：直接用该基金收益（bond/commodity）
    - 篮子代表：拉篮子内各基金，按篮子权重合成一条"大类收益"（stock 用方案A地域权重）

    Returns: DataFrame，列=大类(stock/bond/commodity)，值=日收益率
    """
    underlying, spec = {}, {}     # underlying: {唯一标签: 代码}; spec: {大类: ("single",标签) | ("basket",[(标签,w)])}
    for c, r in reps.items():
        if "basket" in r:
            legs = []
            for leg in r["basket"]:
                lab = f"{c}__{leg['code']}"
                underlying[lab] = leg["code"]
                legs.append((lab, float(leg["w"])))
            spec[c] = ("basket", legs)
        else:
            underlying[c] = r["code"]
            spec[c] = ("single", c)

    rets = fetch_returns(underlying, lookback_days=lookback_days)  # 所有底层基金对齐

    class_df = pd.DataFrame(index=rets.index)
    for c, (kind, info) in spec.items():
        if kind == "single":
            if info in rets.columns:
                class_df[c] = rets[info]
        else:  # 篮子：按权重合成（缺失的腿自动剔除并重新归一）
            avail = [(lab, w) for lab, w in info if lab in rets.columns]
            tot = sum(w for _, w in avail)
            if tot > 0:
                class_df[c] = sum(rets[lab] * (w / tot) for lab, w in avail)
    return class_df.dropna()


def compute_risk_contribution(weights: dict[str, float], cov: dict[str, dict[str, float]],
                              classes: list[str]) -> dict:
    """
    给定权重和年化协方差矩阵，计算各类的风险贡献占比。

    weights 会被归一化到和为 1（只在有数据的风险类之间分配）。
    """
    w = np.array([weights[c] for c in classes], dtype=float)
    w = w / w.sum()  # 归一化
    Sigma = np.array([[cov[a][b] for b in classes] for a in classes], dtype=float)

    port_var = float(w @ Sigma @ w)
    port_vol = float(np.sqrt(port_var))
    mcr = (Sigma @ w) / port_vol          # 边际风险贡献
    rc = w * mcr                           # 风险贡献（绝对，加总=port_vol）
    rc_pct = rc / port_vol                 # 风险贡献占比（加总=1）

    return {
        "classes": classes,
        "weight_normalized": {c: round(float(w[i]), 4) for i, c in enumerate(classes)},
        "portfolio_vol": round(port_vol, 4),
        "risk_contribution_pct": {c: round(float(rc_pct[i]), 4) for i, c in enumerate(classes)},
    }


def diagnose(lookback_days: int = 504) -> dict:
    """V2.2 主入口：跑诊断，输出双视图 + 处方。"""
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)

    reps = holdings["class_representatives"]
    classes = list(reps.keys())
    cap_weights = {c: reps[c]["weight"] for c in classes}  # SAA 资金权重

    # 构造各大类收益（stock 用篮子合成）→ 算协方差
    print(f"[V2.2] 构造大类代表收益（stock 用篮子按地域权重合成）...")
    class_returns = _build_class_returns(reps, lookback_days)
    risk = compute_risk(class_returns)

    # 防御：只用实际拉到数据的大类（某只基金拉取失败时不崩）
    fetched = risk["assets"]
    if set(fetched) != set(classes):
        missing = set(classes) - set(fetched)
        print(f"[V2.2] ⚠️ 以下大类数据缺失，已从诊断中排除：{missing}")
        classes = fetched
        cap_weights = {c: cap_weights[c] for c in classes}

    rc = compute_risk_contribution(cap_weights, risk["cov_annual"], classes)

    # 资金权重（在三类间归一，便于和风险贡献对比）
    total_w = sum(cap_weights.values())
    cap_norm = {c: cap_weights[c] / total_w for c in classes}

    # 找风险主导的类
    rc_pct = rc["risk_contribution_pct"]
    dominant = max(rc_pct, key=rc_pct.get)
    flagged = {c: p for c, p in rc_pct.items() if p > RISK_CAP}

    result = {
        "classes": classes,
        "names": {c: reps[c]["name"] for c in classes},
        "annual_volatility": {c: risk["annual_volatility"][c] for c in classes},
        "capital_weight": {c: round(cap_norm[c], 4) for c in classes},
        "risk_contribution_pct": rc_pct,
        "portfolio_vol": rc["portfolio_vol"],
        "dominant_class": dominant,
        "flagged": flagged,
        "risk_cap": RISK_CAP,
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "risk_diagnostic.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "risk_diagnostic.md").write_text(
        _render(result), encoding="utf-8")
    print("[V2.2] ✅ 已写入 outputs/risk_diagnostic.json 和 risk_diagnostic.md")
    return result


def _render(r: dict) -> str:
    cls = r["classes"]
    cn = {"stock": "股票", "bond": "债券", "commodity": "大宗商品"}
    lines = ["# 风险贡献诊断 + 处方（V2.2）", ""]
    lines.append(f"> 组合年化波动率（三大风险类）：**{r['portfolio_vol']*100:.1f}%**"
                 f"｜风险上限阈值：{int(r['risk_cap']*100)}%")
    lines.append("> 注：cash/insurance 波动≈0、high_risk(虚拟货币)无数据，诊断聚焦股/债/商品三类。")
    lines.append("")

    # 双视图对比
    lines.append("## 双视图：资金权重 vs 风险贡献")
    lines.append("| 大类 | 年化波动率 | 资金权重 | **风险贡献** | 差距 |")
    lines.append("|------|-----------|---------|------------|------|")
    for c in cls:
        cw = r["capital_weight"][c] * 100
        rcp = r["risk_contribution_pct"][c] * 100
        gap = rcp - cw
        flag = " ⚠️" if r["risk_contribution_pct"][c] > r["risk_cap"] else ""
        lines.append(f"| {cn.get(c,c)} | {r['annual_volatility'][c]*100:.1f}% | "
                     f"{cw:.0f}% | **{rcp:.0f}%**{flag} | {gap:+.0f}pp |")
    lines.append("")

    # 诊断结论
    dom = r["dominant_class"]
    dom_rc = r["risk_contribution_pct"][dom] * 100
    lines.append("## 诊断结论")
    if r["flagged"]:
        lines.append(f"- ⚠️ **{cn.get(dom,dom)}风险主导**：资金占比不高，但贡献了 **{dom_rc:.0f}%** 的组合风险，"
                     f"超过 {int(r['risk_cap']*100)}% 上限——典型的**「假分散」**：你以为分散了，实则组合命运被它决定。")
    else:
        lines.append(f"- ✅ 无单一大类风险贡献超过 {int(r['risk_cap']*100)}%，风险分布相对均衡。")
    lines.append("")

    # 处方
    if r["flagged"]:
        lines.append("## 处方（无杠杆，按「每降一单位风险损失收益从小到大」排序）")
        lines.append("> 目标：降低{}的风险主导。**加债券是最低效的，放最后。**".format(cn.get(dom,dom)))
        lines.append("")
        lines.append("1. **低波/红利替换**（最高效，几乎不损收益）：在股票内部转向红利低波/防御股，降低 sleeve 自身波动。依据低波动异象。*你已持 007751 红利低波，可提高其比重。*")
        lines.append("2. **加真分散器**（不是加债）：优先加黄金（既分散、长期又有正收益）。*你已持 002610 黄金。*")
        lines.append("3. **设风险上限**：不追求风险相等，只把主导类削到 ≤60% 即停（无杠杆友好）。")
        lines.append("4. **波动率目标（E3）**：股票波动飙升时机械减仓转现金，动态削峰。")
        lines.append("5. **加债/现金**：最贵的杠杆，兜底用，非首选。")
    return "\n".join(lines)
