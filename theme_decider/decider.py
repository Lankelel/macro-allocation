"""G1 主题自动决策层：把宏观信号翻译成「选基主题」，补上"方向观点 → 主题"这段原本人工脑补的环节。

数据流（输入都已存在）：
  ① M2 directions.json   行业方向打分(AI/energy/military/consumer/finance/medical，-2~+2)
  ② clock.json           美林时钟象限 + 每大类 m2_anchor
  ③ 再平衡 gaps_wan       本期哪些大类要加仓（复用 fund_rebalancer，不重算）
        ↓  大类候选主题池 ×（基础优先级 + M2方向打分 + 时钟避险加成）取最高
  输出  {commodity: 石油, high_risk: AI, …} + 理由 → theme_decision.{json,md} + 现成 --fill 命令

铁律：输出是**建议**，需人工 review；主题最终裁量权保留在人。默认不自动执行 --fill。
设计选择（用户定）：股票主题**由 M2 方向打分决定**（低波红利作中性默认；方向强时让位给赛道，并提示与降股票风险目标的张力）。
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "high_risk": "高风险", "cash": "现金"}

# 大类 → 候选主题。每候选 =（主题词, [关联的M2方向keys], 基础优先级）。
# 基础优先级=无方向信号时的默认排序；M2方向打分 + 时钟加成叠加其上。沿用"策库"哲学，可扩展。
CLASS_THEMES = {
    "commodity": [
        ("石油", ["energy"], 0.5),
        ("黄金", [], 0.8),            # 避险默认略高；energy 强时石油反超；滞胀/衰退象限黄金再加成
        ("有色", ["energy"], 0.3),
    ],
    "stock": [                        # 用户定：由方向打分决定；红利低波作中性默认
        ("红利低波", [], 1.0),
        ("科技", ["AI"], 0.0),
        ("半导体", ["AI"], 0.0),
        ("军工", ["military"], 0.0),
        ("消费", ["consumer"], 0.0),
        ("金融", ["finance"], 0.0),
        ("医药", ["medical"], 0.0),
    ],
    "high_risk": [                    # 高风险/卫星仓（接受高波搏收益；用户实际持仓含加密货币[无对应公募]，
                                      # 科技/AI/半导体作"公募可买的高波卫星"代理——what-if实测它们做股票主仓会破≤60%，归宿正是这里）
        ("AI", ["AI"], 0.5),
        ("科技", ["AI"], 0.4),
        ("半导体", ["AI"], 0.3),
        ("军工", ["military"], 0.2),
    ],
}
# 时钟象限 → 防御主题加成（滞胀/衰退避险偏黄金）
QUADRANT_BONUS = {"滞胀": {"黄金": 1.0}, "衰退": {"黄金": 0.5}}
# 低波股票主题（被方向打分选成其它=与降股票风险目标存在张力，提示）
LOW_VOL_STOCK = {"红利低波", "低波", "高股息"}


def _load(name: str):
    p = OUTPUTS_DIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def decide_themes() -> dict:
    directions = (_load("directions.json") or {}).get("final", {}).get("directions", {})
    clock = _load("clock.json") or {}
    quadrant = str(clock.get("quadrant", ""))
    # 本期哪些大类要加仓——复用再平衡器（无 swap/fill 时纯逻辑、不联网）
    gaps = {}
    try:
        from fund_rebalancer.planner import plan_fund_level
        gaps = plan_fund_level().get("gaps_wan", {})
    except Exception as e:
        print(f"[G1] 读再平衡缺口失败（缺 holdings_current.json？）：{str(e)[:60]}；将不标注本期加仓")

    def dstr(k):
        return directions.get(k, {}).get("strength", 0) or 0

    decisions = {}
    for cls, candidates in CLASS_THEMES.items():
        scored = []
        for theme, dir_keys, base in candidates:
            ds = sum(dstr(k) for k in dir_keys)
            qb = next((b.get(theme, 0) for q, b in QUADRANT_BONUS.items() if q in quadrant), 0)
            scored.append({"theme": theme, "score": round(base + ds + qb, 2),
                           "base": base, "dir_score": ds, "dir_keys": dir_keys, "q_bonus": qb})
        scored.sort(key=lambda x: -x["score"])
        top = scored[0]
        parts = [f"基础{top['base']}"]
        if top["dir_keys"]:
            parts.append(f"方向{'+'.join(top['dir_keys'])}={top['dir_score']:+g}")
        if top["q_bonus"]:
            parts.append(f"时钟{quadrant}避险+{top['q_bonus']}")
        gap = round(gaps.get(cls, 0.0), 2)
        decisions[cls] = {
            "theme": top["theme"], "score": top["score"], "reason": " ".join(parts),
            "runners_up": scored[1:3], "gap_wan": gap, "buy_this_period": gap > 0.05,
            "low_vol_tension": cls == "stock" and top["theme"] not in LOW_VOL_STOCK,
        }

    result = {
        "quadrant": quadrant,
        "directions": {k: v.get("strength") for k, v in directions.items()},
        "decisions": decisions,
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "theme_decision.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "theme_decision.md").write_text(_render(result), encoding="utf-8")
    print("[G1] ✅ 已写入 outputs/theme_decision.{json,md}")
    return result


def _render(r: dict) -> str:
    lines = ["# G1 主题自动决策（建议，需人工 review）", ""]
    ds = "、".join(f"{k}{v:+g}" for k, v in r["directions"].items()) or "（无 directions.json）"
    lines.append(f"> 美林时钟：{r['quadrant'] or '—'}｜M2 方向打分：{ds}")
    lines.append("> 规则：大类候选主题池 ×（基础优先级 + M2方向打分 + 时钟避险加成）取最高。股票主题由方向打分决定（你的设定）。")
    lines.append("")
    lines.append("| 大类 | 选定主题 | 综合分 | 打分构成 | 本期加仓 | 备选 |")
    lines.append("|------|------|------|------|------|------|")
    for cls, d in r["decisions"].items():
        ru = "、".join(f"{x['theme']}({x['score']})" for x in d["runners_up"]) or "—"
        gap = f"+{d['gap_wan']}w" if d["buy_this_period"] else "—"
        warn = " ⚠️张力" if d.get("low_vol_tension") else ""
        lines.append(f"| {CN.get(cls, cls)} | **{d['theme']}**{warn} | {d['score']} | {d['reason']} | {gap} | {ru} |")
    lines.append("")
    if any(d.get("low_vol_tension") for d in r["decisions"].values()):
        lines.append("> ⚠️ 张力提示：股票主题被方向打分选成了高波赛道，与「降股票风险贡献」核心目标存在张力。"
                     "**实测数据**：科技/AI 公募波动 36-40%(vs 红利低波 13%)，做股票主仓会把股票风险贡献顶到约 **75% > 60%**——"
                     "故其归宿是高风险卫星仓(本表已为 high_risk 选它)，**核心股票仓本期应手动改用 红利低波**。")
        lines.append("")
    fills = [f"--fill {cls}={d['theme']}" for cls, d in r["decisions"].items() if d["buy_this_period"]]
    lines.append("## 采纳方式（review 后手动执行）")
    if fills:
        lines.append("```")
        lines.append("python -m fund_rebalancer " + " ".join(fills))
        lines.append("```")
    else:
        lines.append("本期无大类需加仓（或缺口过小），无需选基填充。")
    lines.append("")
    # C: 高风险/卫星仓加仓 → 现成「选股」命令(下探到个股,仅建议,人工执行;类比 --fill)
    hr = r["decisions"].get("high_risk")
    if hr and hr.get("buy_this_period"):
        lines.append(f"### 高风险/卫星仓 → 个股选择（可选，下探到个股）")
        lines.append(f"高风险类本期 +{hr['gap_wan']}w、主题「{hr['theme']}」。如要选个股(卫星仓·小额)：")
        lines.append("```")
        lines.append(f"/选股 {hr['theme']} {hr['gap_wan']}")
        lines.append("```")
        lines.append("> 选股层=卫星仓个股(stock_selector)；仅建议、需人工 review；个股风险并入「股票含卫星 ≤60%」预算。")
        lines.append("")
    lines.append("> ⚠️ 本决策为**建议**；主题选择保留人工最终裁量（铁律：产出需人工 review）。策库可在 theme_decider/decider.py 的 CLASS_THEMES 调整。")
    return "\n".join(lines)
