"""
⑦ 结果同步 Finance.md：把系统产出汇成"系统配置建议"块，对齐 Finance.md 调整日志

铁律（CLAUDE.md）：系统产出是**建议**，需人工 review 后才落地 Finance.md 调整日志。
故本模块：
  - 默认只生成提案 outputs/finance_sync_proposal.md（打印 + 写文件），不动 Finance.md
  - 仅 sync(apply=True)（`python -m results_sync --apply`）才**追加**到 Finance.md，
    且放在清晰标注「🤖 系统配置建议（待人工确认）」的区块、非破坏式（只 append 不覆盖）

汇总来源（读 outputs/*.json，缺失则跳过）：
  - clock.json         宏观象限（美林时钟）
  - rebalance_fund.json 单只级调仓清单（与 ⑬ 调仓结论同源 → 一致 + 新鲜度统一）；缺失则兜底读 rebalance_plan.json（大类级）
  - vol_target.json    波动率目标动态削峰信号
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
FINANCE_MD = BASE.parent.parent.parent / "AI Freedom" / "Finance.md"
MARKER = "## 🤖 系统配置建议（待人工确认）"
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金", "high_risk": "高风险", "cash": "现金"}


def _load(name: str) -> dict | None:
    p = OUTPUTS_DIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_proposal(today: str) -> str:
    clock = _load("clock.json")
    rf = _load("rebalance_fund.json")       # 单只级（与 ⑬ 调仓结论同源）
    reb = _load("rebalance_plan.json")       # 大类级（rf 缺失时兜底）
    vt = _load("vol_target.json")

    lines = [f"### {today} 系统建议", ""]

    if clock:
        g, i = clock["growth"], clock["inflation"]
        lines.append(f"- **宏观环境（美林时钟 {clock['data_month']}）**：{clock['quadrant']} → 历史占优 **{clock['favored_class_cn']}**"
                     f"（增长 {g['indicator']} {g['value']} {'↑' if g['direction']=='up' else '↓'}、"
                     f"通胀 CPI {i['value']}% {'↑' if i['direction']=='up' else '↓'}）")

    if vt:
        if vt.get("regime") == "calm":
            lines.append(f"- **波动率目标**：🟢 平静期，股票满仓不削（近期波动 {vt['realized_vol']*100:.1f}% ≤ 基准 {vt['target_vol']*100:.1f}%）")
        else:
            lines.append(f"- **波动率目标**：⚠️ 近期股票波动 {vt['realized_vol']*100:.1f}% > 基准 {vt['target_vol']*100:.1f}%"
                         f" → 建议股票 {vt['saa_stock_weight']*100:.0f}%→{vt['stock_target_weight']*100:.0f}%、"
                         f"转入现金约 **{vt['derisk_to_cash_wan']:.1f}w**（临时削峰，回落自动满仓）")

    single_level = False
    if rf:
        single_level = True
        cur, tgt, gaps = rf.get("class_current_wan", {}), rf.get("class_target_wan", {}), rf.get("gaps_wan", {})
        lines.append("- **大类调整**（当前→目标）：")
        lines.append("")
        lines.append("  | 大类 | 当前(w) | 目标(w) | 差额(w) |")
        lines.append("  |------|------|------|------|")
        for c in ["stock", "bond", "commodity", "gold", "high_risk", "cash"]:
            if c not in tgt:
                continue
            g = gaps.get(c, round(tgt.get(c, 0) - cur.get(c, 0), 2))
            lines.append(f"  | {CN.get(c, c)} | {cur.get(c, 0)} | {tgt.get(c, 0)} | {g:+.1f} |")
        lines.append("")
        for s in rf.get("swap_actions", []):
            tag = "(新建)" if s.get("buy_is_new") else ""
            lines.append(f"- **低波替换**：卖 {s['sell_code']} {s['sell_name'][:10]} → 买 {s['buy_code']} {s['buy_name'][:12]}{tag} {s['amount_wan']}w")
        screen_sells = rf.get("screen_sells", [])
        if screen_sells:
            ss = "；".join(
                f"{s['code']} {s['name'][:10]} {s['amount_wan']}w"
                f"({'部分卖出' if s.get('partial') else '清仓'}，分{s.get('score')})"
                for s in sorted(screen_sells, key=lambda x: x.get("score", 0)))
            lines.append(f"- **🗑️ 末位淘汰卖出（同类内综合分末位，驱动超配大类减持，额度内）**：{ss}")
        trades = rf.get("trades", [])
        buys = [t for t in trades if "买" in t["action"]]
        sells = [t for t in trades if "卖" in t["action"] or "转出" in t["action"]]
        if buys:
            lines.append("- **买入（现有基金加仓）**：" + "；".join(f"{t['code']} {t['name'][:10]} +{t['amount_wan']}w" for t in buys))
        if sells:
            lines.append("- **卖出/转出**：" + "；".join(f"{t['code']} {t['name'][:10]} {t['amount_wan']}w" for t in sells))
        for f in rf.get("selector_fills", []):
            picks = f["rec"].get("picks", [])
            buy_str = "、".join(f"{p['code']} {p['name'][:10]} {p['amount_wan']}w(分{p.get('score')})" for p in picks) or f["rec"].get("note", "无可买标的")
            lines.append(f"- **选基填充**：{CN.get(f['class'], f['class'])} 加 {f['amount_wan']}w → 主题「{f['theme']}」→ {buy_str}")
        for n in rf.get("new_positions", []):
            lines.append(f"- **新建仓位**：{CN.get(n['class'], n['class'])} 买入 {n['amount_wan']}w —— {n.get('note', '')}")
        sf = rf.get("screen_freed_wan", 0) or 0
        lo = rf.get("leftover_to_cash_wan", 0) or 0
        if rf.get("balanced"):
            status = "✅已配平"
        elif rf.get("fund_buys_wan", 0) <= rf.get("funding_wan", 0) + 1e-9:
            status = f"✅配平，余 {lo}w 转现金"   # 资金有余（非缺口）
        else:
            status = "⚠️资金不足"
        lines.append(f"- **资金配平**：现金释放 {rf.get('cash_release_wan')}w"
                     + (f" ＋淘汰卖出 {sf}w" if sf > 0 else "")
                     + f"｜可用 {rf.get('funding_wan')}w｜实买 {rf.get('fund_buys_wan')}w｜{status}")
        uf = rf.get("underfunded", {})
        if uf:
            lines.append("  - ⚠️ 未填满（资金不足，按缺口优先级先满最缺）：" + "、".join(f"{CN.get(c, c)}缺{v}w" for c, v in uf.items()))
    elif reb and reb.get("signals"):
        lines.append("- **大类再平衡信号**（偏离≥阈值或季度强制）：")
        lines.append("")
        lines.append("  | 大类 | 当前% | 目标% | 动作 | 金额(w) |")
        lines.append("  |------|------|------|------|------|")
        for s in reb["signals"]:
            lines.append(f"  | {s['name']} | {s['current_w']*100:.1f}% | {s['target_w']*100:.1f}% | "
                         f"{s['action']} | {s['amount_wan']:.1f} |")
        lines.append("")

    if len(lines) <= 2:
        lines.append("- （无可用产出，请先运行 main.py / fund_rebalancer 生成 outputs/*.json）")

    lines.append("")
    caveat = "" if single_level else "大类信号尚未细化到单只基金（先跑 fund_rebalancer 生成单只清单）。"
    lines.append("> ⚠️ 以上为系统建议，**需人工 review** 后再摘录进上方「调整日志」表并执行。" + caveat)
    return "\n".join(lines)


def sync(apply: bool = False, today: str | None = None) -> dict:
    today = today or datetime.now().strftime("%Y-%m-%d")
    proposal = _build_proposal(today)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    prop_path = OUTPUTS_DIR / "finance_sync_proposal.md"
    prop_path.write_text(f"# 系统配置建议提案\n\n{proposal}\n", encoding="utf-8")
    print(f"[⑦] ✅ 提案已写入 {prop_path}")

    applied = False
    if apply:
        if not FINANCE_MD.exists():
            print(f"[⑦] ⚠️ 未找到 Finance.md：{FINANCE_MD}，仅生成提案")
        else:
            text = FINANCE_MD.read_text(encoding="utf-8")
            block = f"\n\n{MARKER}\n\n> 由 macro-allocation 自动追加，待人工确认后并入正式调整日志。\n\n{proposal}\n"
            # 非破坏式：直接 append 到文件末尾（若已有同日建议则提示，不重复）
            if f"### {today} 系统建议" in text:
                print(f"[⑦] ℹ️ Finance.md 已存在 {today} 的系统建议，跳过追加（避免重复）")
            else:
                FINANCE_MD.write_text(text + block, encoding="utf-8")
                applied = True
                print(f"[⑦] ✅ 已追加「{MARKER}」到 Finance.md 末尾（非破坏式，待你 review）")

    return {"date": today, "proposal_path": str(prop_path), "applied_to_finance": applied}
