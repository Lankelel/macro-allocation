"""调仓结论汇总（一份就够）：把散在 risk_diagnostic / theme_decision / rebalance_fund 的结论，
合并成单一 outputs/调仓结论.md —— 核心目标状态 + 大类调整 + 主题决策 + 单只买卖清单 + 资金配平 + 下一步。

动机：之前要在 4-5 个文件间来回翻才能拼出"该怎么调仓"。本模块读已有产物 JSON 汇成一页。
铁律：输出是建议，需人工 review 后执行。先跑 fund_rebalancer(最好带 --swap/--fill) 再跑本模块。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUTS = BASE / "outputs"
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金",
      "high_risk": "高风险", "cash": "现金"}


def _load(name: str):
    p = OUTPUTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def summarize() -> str:
    diag = _load("risk_diagnostic.json") or {}
    theme = _load("theme_decision.json") or {}
    rb = _load("rebalance_fund.json")
    if rb is None:
        raise RuntimeError("缺 outputs/rebalance_fund.json，请先运行 python -m fund_rebalancer [--swap --fill ...]")

    L = ["# 调仓结论（汇总·一份就够）"]
    L.append(f"> 生成于 {datetime.now():%Y-%m-%d %H:%M}｜⚠️ 建议，需人工 review 后执行")
    L.append("> 汇总自 risk_diagnostic + theme_decision + rebalance_fund"
             f"（{'已带低波替换处方' if rb.get('swap_enabled') else '未带--swap'}）")
    L.append("")

    # 1 核心目标
    L.append("## 1️⃣ 核心目标：股票风险贡献")
    rc = diag.get("risk_contribution_pct", {})
    if rc:
        cap = diag.get("risk_cap", 0.6)
        ok = "✅ 达标" if rc.get("stock", 1) <= cap else "❌ 未达标"
        L.append(f"- 股票风险贡献 **{rc.get('stock', 0)*100:.1f}%**（上限 {cap*100:.0f}%）{ok}"
                 f"｜组合波动 {diag.get('portfolio_vol', 0)*100:.1f}%")
        L.append("- 其余：" + "、".join(f"{CN.get(c, c)}{p*100:.0f}%" for c, p in rc.items() if c != "stock"))
    else:
        L.append("- （无 risk_diagnostic.json，先跑 python -m diagnostic）")
    L.append("")

    # 2 大类调整
    L.append("## 2️⃣ 大类调整（当前 → 目标）")
    cur, tgt, gaps = rb["class_current_wan"], rb["class_target_wan"], rb["gaps_wan"]
    L.append("| 大类 | 当前(w) | 目标(w) | 差额(w) | 方向 |")
    L.append("|------|------|------|------|------|")
    for c in ["stock", "bond", "commodity", "gold", "high_risk", "cash"]:
        if c not in tgt:
            continue
        g = gaps.get(c, round(tgt.get(c, 0) - cur.get(c, 0), 2))
        d = "🟢买入" if g > 0.05 else ("🔴卖出" if g < -0.05 else "维持")
        L.append(f"| {CN.get(c, c)} | {cur.get(c, 0)} | {tgt.get(c, 0)} | {g:+.1f} | {d} |")
    L.append("")

    # 3 主题决策
    dec = theme.get("decisions", {})
    buy_dec = {c: d for c, d in dec.items() if d.get("buy_this_period")}
    if buy_dec:
        L.append("## 3️⃣ 主题决策（要加仓的大类配什么主题）")
        L.append(f"> 美林时钟：{theme.get('quadrant', '—')}")
        L.append("| 大类 | 主题 | 加仓 | 打分构成 |")
        L.append("|------|------|------|------|")
        for c, d in buy_dec.items():
            warn = " ⚠️张力" if d.get("low_vol_tension") else ""
            L.append(f"| {CN.get(c, c)} | **{d['theme']}**{warn} | +{d['gap_wan']}w | {d['reason']} |")
        if any(d.get("low_vol_tension") for d in buy_dec.values()):
            L.append("> ⚠️张力=该主题与「降股票风险」目标冲突，若优先降风险可手动改红利低波。")
        L.append("")

    # 4 单只买卖清单
    L.append("## 4️⃣ 单只买卖清单（照此执行）")
    trades = rb.get("trades", [])
    sells = [t for t in trades if "卖" in t["action"] or "转出" in t["action"]]
    buys = [t for t in trades if "买" in t["action"]]
    if rb.get("stock_trim_wan", 0) > 0.05:
        L.append(f"- 🔻 股票减持（配平用）：约 {rb['stock_trim_wan']}w")
    swaps = rb.get("swap_actions", [])
    if swaps:
        L.append("\n**① 低波替换（降股票波动，等额对换）**")
        L.append("| 卖出 | → 买入 | 金额(w) |")
        L.append("|------|------|------|")
        for s in swaps:
            tag = "（新建）" if s.get("buy_is_new") else ""
            L.append(f"| {s['sell_code']} {s['sell_name'][:10]} | {s['buy_code']} {s['buy_name'][:12]}{tag} | {s['amount_wan']} |")
    screen_sells = rb.get("screen_sells", [])
    if screen_sells:
        L.append("\n**🗑️ 末位淘汰卖出（驱动超配大类减持，额度内）**")
        L.append("| 代码 | 简称 | 大类 | 卖出(w) | 综合分 | 备注 |")
        L.append("|------|------|------|------|------|------|")
        for s in sorted(screen_sells, key=lambda x: x.get("score", 0)):
            note = "部分卖出（余下期清）" if s.get("partial") else "清仓"
            L.append(f"| {s['code']} | {s['name'][:14]} | {CN.get(s['class'], s['class'])} | "
                     f"{s['amount_wan']} | {s.get('score')} | {note} |")
    if sells:
        L.append("\n**卖出/转出**")
        L.append("| 代码 | 简称 | 大类 | 金额(w) |")
        L.append("|------|------|------|------|")
        for t in sells:
            L.append(f"| {t['code']} | {t['name'][:14]} | {CN.get(t['class'], t['class'])} | {t['amount_wan']} |")
    if buys:
        L.append("\n**买入（现有基金加仓）**")
        L.append("| 代码 | 简称 | 大类 | 金额(w) |")
        L.append("|------|------|------|------|")
        for t in buys:
            L.append(f"| {t['code']} | {t['name'][:14]} | {CN.get(t['class'], t['class'])} | {t['amount_wan']} |")
    for f in rb.get("selector_fills", []):
        rec = f["rec"]
        L.append(f"\n**② 选基填充：{CN.get(f['class'], f['class'])} 加 {f['amount_wan']}w → 主题「{f['theme']}」**")
        if not rec.get("picks"):
            L.append(f"- ⚠️ {rec.get('note', '无可买标的')}")
        for p in rec.get("picks", []):
            el = "" if not p.get("elastic_unmet") else f"，{'/'.join(p['elastic_unmet'])}"
            L.append(f"- 买入 **{p['code']} {p['name'][:14]}** {p['amount_wan']}w（综合分 {p.get('score')}{el}）")
        if rec.get("alternatives"):
            L.append("  备选：" + "、".join(f"{a['code']}({a.get('score')})" for a in rec["alternatives"]))
    for n in rb.get("new_positions", []):
        L.append(f"\n**新建仓位**：{CN.get(n['class'], n['class'])} 买入 {n['amount_wan']}w —— {n.get('note', '')}")
    L.append("")

    # 5 资金配平
    L.append("## 5️⃣ 资金配平")
    sf = rb.get("screen_freed_wan", 0)
    lo = rb.get("leftover_to_cash_wan", 0)
    if rb["balanced"]:
        status = "✅ 已配平"
    elif rb["fund_buys_wan"] <= rb["funding_wan"] + 1e-9:
        status = f"✅ 配平，余 {lo}w 转现金"   # 资金有余（非缺口）
    else:
        status = "⚠️ 资金不足"
    L.append(f"- 现金释放 {rb['cash_release_wan']}w"
             + (f" ＋淘汰卖出 {sf}w" if sf > 0 else "")
             + f"｜可用 {rb['funding_wan']}w｜实买 {rb['fund_buys_wan']}w｜{status}")
    uf = rb.get("underfunded", {})
    if uf:
        L.append("- ⚠️ 未填满（资金不足，按缺口优先级先满最缺的）："
                 + "、".join(f"{CN.get(c, c)}缺{v}w" for c, v in uf.items()))
        L.append("  - 补足：① `--trim-stock` 用股票超配补；② 动用现金缓冲；③ 下季继续")
    L.append("")

    # 6 下一步
    L.append("## 6️⃣ 下一步")
    L.append("1. 人工 review 本结论（尤其 ⚠️张力 / 未填满项）")
    L.append("2. 按「单只买卖清单」实际申赎")
    L.append("3. `python -m results_sync --apply` 生成提案并追加 Finance.md")
    L.append("4. 更新 Finance.md 调整日志（闭环）")

    out = "\n".join(L)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "调仓结论.md").write_text(out, encoding="utf-8")
    print("[汇总] ✅ 已写入 outputs/调仓结论.md")
    return out
