"""
Fund-level 再平衡器：产出"该买卖哪只基金、各多少万"的精确清单

这是整条链路的终点——把"大类该怎么调"落到"每只基金买卖多少"。
两层组合，都可执行：
  1. 大类回 SAA：按 cash_floor 算各大类目标（与 V2.4 rebalancer 同口径）
  2. 下推到单只：每个大类目标按"现有基金当前占比"比例分配 → 单只目标 → 与当前 diff → 买卖
     （设最小交易额阈值 min_trade，过滤碎单噪音；大类已达标的类自然无动作）
  3. 低波处方叠加（可选）：叠加 style_tilt.swaps（卖纳指513100→买道指513400、卖沪深300→买红利低波007751）

数据：单只当前持仓来自 ⑥ 的 config/holdings_current.json；大类目标来自 holdings.yaml 的 SAA。
铁律：输出是**建议**，需人工 review 后执行。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config"
OUTPUTS_DIR = BASE / "outputs"
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金", "high_risk": "高风险", "cash": "现金"}


def _class_targets(holdings: dict, settings: dict) -> tuple[dict, float, float]:
    """大类目标金额（SAA + cash_floor），口径同 V2.4 rebalancer。返回(target_amt, investable, cash_target)。"""
    total = holdings["total_assets_wan"]
    insurance = holdings["locked"]["insurance_wan"]
    investable = total - insurance
    saa = holdings["saa_target"]
    classes = ["stock", "bond", "commodity", "gold", "high_risk", "cash"]
    saa_noins = {c: saa[c] for c in classes}
    s = sum(saa_noins.values())
    cash_floor = settings["rebalance"].get("cash_floor_wan", 0.0)
    raw_cash = saa_noins["cash"] / s * investable
    cash_target = max(raw_cash, cash_floor)
    non_cash = [c for c in classes if c != "cash"]
    s_nc = sum(saa_noins[c] for c in non_cash)
    remaining = investable - cash_target
    target = {c: round(saa_noins[c] / s_nc * remaining, 4) for c in non_cash}
    target["cash"] = round(cash_target, 4)
    return target, investable, cash_target


def plan_fund_level(swap: bool = False, theta: float = 1.0, min_trade: float = 0.3,
                    trim_stock: bool = False, fill_themes: dict | None = None,
                    use_screen: bool = False) -> dict:
    """fill_themes（N6-B）：{大类: 主题}。把该大类的买入额改由**选基**选出具体新标的（而非摊到现有基金），
    用于"给某大类加新主题敞口"。金额守恒（用该类已配资额）、不破坏配平。需 fund_selector 缓存或会实时选基。"""
    fill_themes = fill_themes or {}
    cur_path = CONFIG / "holdings_current.json"
    if not cur_path.exists():
        raise RuntimeError("缺 config/holdings_current.json，请先运行 ⑥：python -m holdings_sync")
    current = json.loads(cur_path.read_text(encoding="utf-8"))
    with open(CONFIG / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    with open(CONFIG / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    class_target, investable, cash_target = _class_targets(holdings, settings)

    cur_by_class = dict(current["by_class"])
    cur_cls = {
        "stock": cur_by_class.get("stock", 0.0),
        "bond": cur_by_class.get("bond", 0.0),
        "commodity": cur_by_class.get("commodity", 0.0),
        "gold": cur_by_class.get("gold", holdings["current"].get("gold_wan", 0.0)),
        "high_risk": holdings["current"].get("high_risk_wan", 0.0),
        "cash": holdings["current"].get("cash_wan", 0.0),
    }
    funds = [f for f in current["funds"] if f["active"]]
    by_cls_funds: dict[str, list] = {}
    for f in funds:
        by_cls_funds.setdefault(f["class"], []).append(f)

    # 各大类缺口（正=需买入，负=超配可卖）
    gaps = {c: round(class_target[c] - cur_cls[c], 4) for c in ["stock", "bond", "commodity", "gold", "high_risk"]}
    buy_gaps = {c: g for c, g in gaps.items() if g > 0.05}
    cash_release = round(cur_cls["cash"] - class_target["cash"], 4)

    # —— 接法A：末位淘汰驱动「超配大类」的卖出（额度内，卖出现金计入可用资金）——
    # 读 holdings_screen.json 的淘汰名单：每个超配大类内，按综合分升序（最差先卖），
    # 累计卖到该类「超配额」为止（不超卖、不破坏大类目标）；最后一只可能部分卖出，余量下期再清。
    screen_sells, screen_freed = [], 0.0
    if use_screen:
        sp = OUTPUTS_DIR / "holdings_screen.json"
        if sp.exists():
            elim = (json.loads(sp.read_text(encoding="utf-8")) or {}).get("eliminated", [])
            by_cls_elim: dict[str, list] = {}
            for e in elim:
                by_cls_elim.setdefault(e.get("class"), []).append(e)
            for c, items in by_cls_elim.items():
                over = round(-gaps.get(c, 0.0), 4)          # 该类超配额（正=可卖）
                if over <= 0.05:
                    continue                                  # 不超配的类：淘汰本期不在额度内执行
                budget = over
                for e in sorted(items, key=lambda x: x.get("score", 0)):  # 最差先卖
                    if budget <= 0.05:
                        break
                    sell = round(min(e.get("amount_wan", 0.0), budget), 2)
                    if sell < min_trade:
                        continue
                    amt = round(e.get("amount_wan", 0.0), 2)
                    screen_sells.append({
                        "code": e["code"], "name": e.get("name", e["code"]), "class": c,
                        "current_wan": amt, "target_wan": round(amt - sell, 2),
                        "action": "卖出", "amount_wan": sell, "score": e.get("score"),
                        "partial": sell < amt - 1e-9,
                    })
                    budget = round(budget - sell, 4)
            screen_freed = round(sum(s["amount_wan"] for s in screen_sells), 4)

    # —— ⑨ 配平核心：可用资金 = 现金释放 (+ 淘汰卖出 / 或可选股票超配减持) ——
    # use_screen 时由淘汰名单具体执行股票减持，故不再叠加 --trim-stock 的笼统减持（避免重复计资金）。
    stock_trim = 0.0
    stock_trim_line = None
    if trim_stock and not use_screen and gaps.get("stock", 0) < -0.05:
        stock_trim = round(-gaps["stock"], 2)   # 股票超配额
        stock_trim_line = {"class": "stock", "amount_wan": stock_trim,
                           "note": "整体减持以补足资金（建议从纳指等高波标的减持；若同时 --swap 则可经卖 513100 实现）"}
    funding = round(cash_release + stock_trim + screen_freed, 4)

    # 按缺口大小优先分配可用资金（最缺的先满）→ 每类实际可买额
    funded = {}
    budget = funding
    for c in sorted(buy_gaps, key=lambda x: -buy_gaps[x]):
        take = round(min(buy_gaps[c], max(0.0, budget)), 4)
        funded[c] = take
        budget = round(budget - take, 4)
    leftover_to_cash = round(max(0.0, budget), 2)

    # 单只买入 = 该类已配资额 × (按现有基金占比) ；不足额按 scale 缩放
    trades, new_positions, underfunded = [], [], {}
    fund_target = {}   # 供 swap 用：再平衡后股票各腿目标
    # 先记录股票各腿（不主动减持时维持现状，供 swap 计算基数）
    for f in by_cls_funds.get("stock", []):
        fund_target[f["code"]] = f["amount_wan"]
    for c, gap in buy_gaps.items():
        fc = funded.get(c, 0.0)
        if fc < gap - 0.05:
            underfunded[c] = round(gap - fc, 2)
        if c in fill_themes:   # 该类改由选基填新标的，跳过摊到现有基金/新建占位
            continue
        legs = by_cls_funds.get(c, [])
        cur_total = cur_cls[c]
        if not legs or cur_total <= 0:
            if fc > 0.05:
                new_positions.append({"class": c, "amount_wan": round(fc, 2),
                                      "note": "无现有基金，需新建（如虚拟货币 BTC/ETH）" if c == "high_risk" else ""})
            continue
        scale = fc / gap if gap > 0 else 0.0
        for f in legs:
            buy_full = class_target[c] * (f["amount_wan"] / cur_total) - f["amount_wan"]
            buy = buy_full * scale
            if buy >= min_trade:
                trades.append({
                    "code": f["code"], "name": f["name"], "class": c,
                    "current_wan": round(f["amount_wan"], 2), "target_wan": round(f["amount_wan"] + buy, 2),
                    "action": "买入", "amount_wan": round(buy, 2),
                })

    # 低波处方叠加（可选）：在股票现状目标上做风格替换
    swap_actions = []
    if swap:
        swaps = settings.get("style_tilt", {}).get("swaps", [])
        code_name = {f["code"]: f["name"] for f in funds}
        for sw in swaps:
            from_tgt = fund_target.get(sw["from_code"])
            if from_tgt is None:
                continue
            move = round(theta * from_tgt, 2)
            if move < min_trade:
                continue
            swap_actions.append({
                "sell_code": sw["from_code"], "sell_name": code_name.get(sw["from_code"], sw["from_code"]),
                "buy_code": sw["to"]["code"], "buy_name": sw["to"]["name"],
                "amount_wan": move, "buy_is_new": sw["to"]["code"] not in code_name,
            })

    # —— N6-B 选基填充：被 --fill 指定的大类，用选基为其主题选出具体新标的（金额=该类已配资额）——
    selector_fills = []
    if fill_themes:
        from fund_selector.recommender import recommend_buy
        for cls, theme in fill_themes.items():
            amt = round(funded.get(cls, 0.0), 2)
            if amt <= 0.05:
                continue
            try:
                rec = recommend_buy([theme], amt)
            except Exception as e:
                rec = {"theme": [theme], "amount_wan": amt, "picks": [], "note": f"选基失败：{str(e)[:50]}"}
            selector_fills.append({"class": cls, "theme": theme, "amount_wan": amt, "rec": rec})

    fills_total = round(sum(f["amount_wan"] for f in selector_fills), 2)
    buys = round(sum(t["amount_wan"] for t in trades) + sum(n["amount_wan"] for n in new_positions) + fills_total, 2)
    result = {
        "investable_wan": investable,
        "class_target_wan": {c: round(class_target[c], 2) for c in class_target},
        "class_current_wan": {c: round(cur_cls[c], 2) for c in cur_cls},
        "gaps_wan": {c: round(g, 2) for c, g in gaps.items()},
        "min_trade_wan": min_trade,
        "cash_release_wan": round(cash_release, 2),
        "trim_stock": trim_stock,
        "stock_trim_wan": stock_trim,
        "stock_trim_line": stock_trim_line,
        "use_screen": use_screen,
        "screen_sells": screen_sells,
        "screen_freed_wan": round(screen_freed, 2),
        "funding_wan": round(funding, 2),
        "fund_buys_wan": buys,
        "balanced": abs(buys - funding) <= 0.1 + 1e-9,
        "leftover_to_cash_wan": leftover_to_cash,
        "underfunded": underfunded,
        "trades": trades,
        "new_positions": new_positions,
        "selector_fills": selector_fills,
        "swap_enabled": swap, "swap_theta": theta if swap else None,
        "swap_actions": swap_actions,
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "rebalance_fund.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "rebalance_fund.md").write_text(_render(result), encoding="utf-8")
    print("[fund-rebalance] ✅ 已写入 outputs/rebalance_fund.{json,md}")
    return result


def _render(r: dict) -> str:
    lines = ["# 单只基金调仓清单（fund-level 再平衡）", ""]
    lines.append(f"> 可投资池 {r['investable_wan']}w｜单只目标=大类目标按现有基金占比下推｜"
                 f"最小交易额 {r['min_trade_wan']}w（碎单已过滤）｜买入已按可用资金配平")
    lines.append("")
    lines.append("## 大类对账（当前 → 目标）")
    lines.append("| 大类 | 当前(w) | 目标(w) | 差额(w) |")
    lines.append("|------|------|------|------|")
    for c in ["stock", "bond", "commodity", "high_risk", "cash"]:
        cu, tg = r["class_current_wan"][c], r["class_target_wan"][c]
        lines.append(f"| {CN[c]} | {cu:.1f} | {tg:.1f} | {tg-cu:+.1f} |")
    lines.append("")
    lines.append("## 🎯 单只基金调仓清单（核心产出，已配平）")
    if r["trades"]:
        lines.append("| 代码 | 简称 | 大类 | 当前(w) | 目标(w) | 动作 | 金额(w) |")
        lines.append("|------|------|------|------|------|------|------|")
        for t in sorted(r["trades"], key=lambda x: (-x["amount_wan"])):
            lines.append(f"| {t['code']} | {t['name']} | {CN[t['class']]} | {t['current_wan']:.1f} | "
                         f"{t['target_wan']:.1f} | **{t['action']}** | {t['amount_wan']:.1f} |")
    else:
        lines.append("（无超过最小交易额的调仓——各大类基本达标）")
    lines.append("")
    if r["new_positions"]:
        lines.append("## 新建仓位（当前无对应基金）")
        for n in r["new_positions"]:
            note = f"——{n['note']}" if n.get("note") else ""
            lines.append(f"- {CN[n['class']]}：买入 **{n['amount_wan']:.1f}w**{note}")
        lines.append("")
    if r.get("selector_fills"):
        lines.append("## 🎯 选基填充（--fill：该大类的买入额改由选基选出具体新标的）")
        lines.append("> 这些大类不摊到现有基金，而是用「选基」为指定主题选出最合适标的（金额=该类已配资额）。")
        for fl in r["selector_fills"]:
            rec = fl["rec"]
            lines.append(f"### {CN.get(fl['class'], fl['class'])} 加 {fl['amount_wan']:.1f}w → 主题「{fl['theme']}」")
            if not rec.get("picks"):
                lines.append(f"- ⚠️ {rec.get('note', '无可买标的（换主题或放宽条件）')}")
                continue
            lines.append("| 代码 | 简称 | 买入(w) | 综合分 | 风格 | 外部评级 | 弹性 |")
            lines.append("|------|------|------|------|------|------|------|")
            for p in rec["picks"]:
                rs = (p.get("rating_summary") or "—") + (" ⚠️避雷" if p.get("rating_low") else "")
                el = "✓" if not p.get("elastic_unmet") else "⚠" + "/".join(p["elastic_unmet"])
                lines.append(f"| {p['code']} | {p['name'][:14]} | **{p['amount_wan']}** | {p.get('score')} | "
                             f"{p.get('style_verdict') or '—'} | {rs} | {el} |")
            if rec.get("alternatives"):
                alt = "、".join(f"{a['code']} {a['name'][:10]}(分{a.get('score')})" for a in rec["alternatives"])
                lines.append(f"> 备选：{alt}")
        lines.append("")
    if r.get("stock_trim_line"):
        s = r["stock_trim_line"]
        lines.append(f"## 股票减持（--trim-stock）")
        lines.append(f"- 股票整体减持 **{s['amount_wan']:.1f}w**——{s['note']}")
        lines.append("")
    if r.get("screen_sells"):
        lines.append("## 🗑️ 末位淘汰卖出（接法A：驱动超配大类减持，额度内）")
        lines.append("| 代码 | 简称 | 大类 | 持仓(w) | 卖出(w) | 综合分 | 备注 |")
        lines.append("|------|------|------|------|------|------|------|")
        for s in sorted(r["screen_sells"], key=lambda x: x.get("score", 0)):
            note = "部分卖出（额度满，余下期清）" if s.get("partial") else "清仓"
            lines.append(f"| {s['code']} | {s['name'][:14]} | {CN.get(s['class'], s['class'])} | "
                         f"{s['current_wan']:.1f} | {s['amount_wan']:.1f} | {s.get('score')} | {note} |")
        lines.append(f"> 淘汰腾出现金 **{r['screen_freed_wan']:.1f}w** 已计入可用资金（在该大类超配额度内卖出，不破坏大类目标）。")
        lines.append("")
    lines.append("## 💰 资金配平（⑨：买入永不超过可用资金）")
    lines.append(f"- 现金释放：{r['class_current_wan']['cash']:.1f}w → {r['class_target_wan']['cash']:.1f}w，**{r['cash_release_wan']:.1f}w**"
                 + (f"　＋淘汰卖出 {r['screen_freed_wan']:.1f}w" if r.get("screen_freed_wan", 0) > 0 else "")
                 + (f"　＋股票减持 {r['stock_trim_wan']:.1f}w" if r["stock_trim_wan"] > 0 else ""))
    lines.append(f"- **可用资金合计 {r['funding_wan']:.1f}w**｜实际买入 {r['fund_buys_wan']:.1f}w｜"
                 f"{'✅ 已配平' if r['balanced'] else '剩余转现金 ' + format(r['leftover_to_cash_wan'], '.1f') + 'w'}")
    if r["underfunded"]:
        for c, amt in r["underfunded"].items():
            lines.append(f"  - ⚠️ {CN[c]} 仍缺 **{amt:.1f}w**未填满（资金不足，已按缺口优先级先满最缺的类）")
        lines.append(f"  - 💡 补足办法：① `--trim-stock` 用股票超配部分（约 {abs(r['gaps_wan'].get('stock',0)):.1f}w）补；② 或动用现金缓冲；③ 或下季度继续。")
    lines.append("")
    if r["swap_enabled"]:
        lines.append(f"## 低波处方叠加（可选，θ={r['swap_theta']}）")
        lines.append("> 在上面再平衡后的股票目标上做风格替换（保持股票占比不变，降 sleeve 波动）。")
        if r["swap_actions"]:
            lines.append("| 卖出 | 买入 | 金额(w) |")
            lines.append("|------|------|------|")
            for s in r["swap_actions"]:
                newtag = "（新建）" if s["buy_is_new"] else ""
                lines.append(f"| {s['sell_code']} {s['sell_name']} | {s['buy_code']} {s['buy_name']}{newtag} | {s['amount_wan']:.1f} |")
        else:
            lines.append("（无满足最小交易额的替换）")
        lines.append("")
    else:
        lines.append("> 💡 加 `--swap` 可叠加「低波处方」：卖纳指/沪深300宽基、买道指/红利低波（降股票波动）。")
    lines.append("")
    lines.append("> ⚠️ 本清单为**建议**，需人工 review 后执行；执行后同步 Finance.md 调整日志。"
                 "单只目标用「维持现有基金占比」的中性规则，可人工覆盖个别基金。")
    return "\n".join(lines)
