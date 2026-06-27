"""
V2.4 再平衡纪律（决策 D：阈值 5% + 季度强制）

逻辑链末端、纯逻辑（不调 API）：读"当前各大类金额 vs 目标权重"，
偏离超阈值即生成调仓信号；事先写死、机械执行（NBIM/Swensen 式纪律）。

设计要点：
- 保险锁定（holdings.locked），排除在再平衡之外；只对"可投资池"(总额-保险)再平衡。
- 目标权重 = SAA 的非保险类，按可投资池归一化。
- 触发：某大类实际权重 vs 目标偏离 ≥ 阈值(默认5个百分点) → 生成 buy/sell 信号。
- 季度强制：force_quarterly=True 时，即使未超阈值也提示季度例行检查。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"

# 大类中文名
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金",
      "high_risk": "高风险", "cash": "现金", "insurance": "保险"}


def check_rebalance() -> dict:
    """V2.4 主入口：算偏离、出调仓信号。"""
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    with open(BASE / "config" / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    threshold = settings["rebalance"]["threshold"]            # 0.05
    force_quarterly = settings["rebalance"]["force_quarterly"]
    cash_floor = settings["rebalance"].get("cash_floor_wan", 0.0)  # 最低现金缓冲

    total = holdings["total_assets_wan"]
    insurance = holdings["locked"]["insurance_wan"]
    investable = total - insurance                            # 可投资池

    saa = holdings["saa_target"]
    cur = holdings["current"]

    # 当前各大类金额（排除保险）
    cur_amt = {
        "stock": cur["stock_wan"], "bond": cur["bond_wan"],
        "commodity": cur["commodity_wan"], "gold": cur.get("gold_wan", 0.0),
        "high_risk": cur["high_risk_wan"], "cash": cur["cash_wan"],
    }
    classes = list(cur_amt.keys())

    # 目标权重 = 非保险 SAA 归一化；并应用现金下限(cash floor)
    saa_noins = {c: saa[c] for c in classes}
    s = sum(saa_noins.values())
    # 先算未加下限的现金目标金额
    raw_cash_amt = saa_noins["cash"] / s * investable
    # 现金目标 = max(SAA现金, 现金下限)；刚性现金不被再平衡清掉
    cash_target = max(raw_cash_amt, cash_floor)
    # 剩余资金按非现金类的 SAA 比例再分配
    non_cash = [c for c in classes if c != "cash"]
    s_nc = sum(saa_noins[c] for c in non_cash)
    remaining = investable - cash_target
    target_amt = {c: round(saa_noins[c] / s_nc * remaining, 2) for c in non_cash}
    target_amt["cash"] = round(cash_target, 2)
    target_w = {c: target_amt[c] / investable for c in classes}

    # 当前权重（占可投资池）
    cur_sum = sum(cur_amt.values())
    cur_w = {c: cur_amt[c] / cur_sum for c in classes}

    # 偏离 + 信号
    signals = []
    for c in classes:
        dev_pp = (cur_w[c] - target_w[c])                     # 权重偏离（小数）
        dev_amt = round(cur_amt[c] - target_amt[c], 2)        # 金额偏离
        triggered = abs(dev_pp) >= threshold
        if triggered:
            signals.append({
                "class": c, "name": CN[c],
                "current_w": round(cur_w[c], 4), "target_w": round(target_w[c], 4),
                "dev_pp": round(dev_pp, 4),
                "action": "卖出/转出" if dev_amt > 0 else "买入/转入",
                "amount_wan": abs(dev_amt),
            })

    result = {
        "total_wan": total, "insurance_locked_wan": insurance, "investable_wan": investable,
        "threshold_pp": threshold, "force_quarterly": force_quarterly,
        "classes": classes,
        "current_weight": {c: round(cur_w[c], 4) for c in classes},
        "target_weight": {c: round(target_w[c], 4) for c in classes},
        "current_amount_wan": cur_amt,
        "target_amount_wan": target_amt,
        "triggered": len(signals) > 0,
        "signals": signals,
    }

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "rebalance_plan.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "rebalance_plan.md").write_text(_render(result), encoding="utf-8")
    print("[V2.4] ✅ 已写入 outputs/rebalance_plan.json 和 rebalance_plan.md")
    return result


def _render(r: dict) -> str:
    lines = ["# 再平衡计划（V2.4）", ""]
    lines.append(f"> 总资产 {r['total_wan']}w｜保险锁定 {r['insurance_locked_wan']}w（排除）"
                 f"｜可投资池 {r['investable_wan']}w｜触发阈值 {int(r['threshold_pp']*100)}个百分点")
    lines.append("")
    lines.append("## 当前 vs 目标（占可投资池）")
    lines.append("| 大类 | 当前权重 | 目标权重 | 当前金额 | 目标金额 |")
    lines.append("|------|---------|---------|---------|---------|")
    for c in r["classes"]:
        lines.append(f"| {CN[c]} | {r['current_weight'][c]*100:.1f}% | {r['target_weight'][c]*100:.1f}% | "
                     f"{r['current_amount_wan'][c]}w | {r['target_amount_wan'][c]}w |")
    lines.append("")
    if r["triggered"]:
        lines.append(f"## ⚠️ 触发再平衡信号（{len(r['signals'])} 项偏离超阈值）")
        lines.append("| 大类 | 当前→目标 | 偏离 | 操作 | 金额 |")
        lines.append("|------|----------|------|------|------|")
        for s in r["signals"]:
            lines.append(f"| {s['name']} | {s['current_w']*100:.1f}%→{s['target_w']*100:.1f}% | "
                         f"{s['dev_pp']*100:+.1f}pp | **{s['action']}** | {s['amount_wan']}w |")
    else:
        lines.append("## ✅ 未触发：所有大类偏离均在阈值内")
    lines.append("")
    if r["force_quarterly"]:
        lines.append("> 📌 季度强制：即使未超阈值，每季度也应例行检查一次（决策D）。")
    lines.append("> ⚠️ 本计划为**建议**，需人工 review 后执行；执行后同步 Finance.md 调整日志。")
    return "\n".join(lines)
