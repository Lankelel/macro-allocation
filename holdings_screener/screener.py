"""持仓末位淘汰器：同类内复合质量标准排序 → 末位淘汰 → 腾现金 + 同类替代建议。
纯逻辑(打分/取整/保护)与联网(拉数/评级/选基)分离。详见 spec。铁律：建议，需人工 review。"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config"
OUTPUTS = BASE / "outputs"
CN = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金", "high_risk": "高风险"}

# 复合权重：风险调整收益为主(0.75) + 费率(0.15,文献最稳健预测器)；评级避雷另作乘法罚
WEIGHTS = {"sharpe": 0.30, "neg_maxdd": 0.25, "neg_vol": 0.20, "ann_ret": 0.10, "neg_fee": 0.15}
RATING_LOW_PENALTY = 0.85


def _composite_scores(group: list[dict]) -> list[dict]:
    """组内同类百分位综合分（0~100）。group 每项需含 sharpe/max_drawdown/vol/ann_ret/buy_fee_pct/rating_low。"""
    if not group:
        return []
    df = pd.DataFrame(group)
    # 强制数值化(None→NaN)；某指标缺失→该项百分位填 0.5 中性，避免 NaN 污染整体分
    num = {c: pd.to_numeric(df.get(c), errors="coerce")
           for c in ["sharpe", "max_drawdown", "vol", "ann_ret", "buy_fee_pct"]}

    def pr(s):
        return s.rank(pct=True).fillna(0.5)

    p_sharpe = pr(num["sharpe"])
    p_negdd = pr(-num["max_drawdown"])                    # 回撤小(绝对值小,值更接近0)→分高
    p_negvol = pr(-num["vol"])
    p_ann = pr(num["ann_ret"])
    p_negfee = pr(-num["buy_fee_pct"])                    # 费率缺失(持仓无此字段)→全0.5中性
    base = (WEIGHTS["sharpe"] * p_sharpe + WEIGHTS["neg_maxdd"] * p_negdd
            + WEIGHTS["neg_vol"] * p_negvol + WEIGHTS["ann_ret"] * p_ann + WEIGHTS["neg_fee"] * p_negfee)
    penalty = df["rating_low"].map(lambda x: RATING_LOW_PENALTY if x else 1.0)
    df["score"] = (base * penalty * 100).round(1)
    return df.to_dict("records")


def _mark_bottom(scored: list[dict], pct: int, min_group: int) -> list[dict]:
    """返回组内末位 pct% 的基金（按 score 升序、向下取整）；组内<min_group 则空。"""
    if len(scored) < min_group:
        return []
    n_cut = math.floor(len(scored) * pct / 100)
    if n_cut <= 0:
        return []
    return sorted(scored, key=lambda f: f["score"])[:n_cut]


RECENT_MARKERS = ("已加仓", "新建", "新增", "⬆️")


def _protect_reason(fund: dict, locked_codes: set | None = None) -> str | None:
    """返回保护原因(不淘汰)或 None。处方锁定(低波替换目标/黄金) / 刚买入(Finance.md标记) / 数据不足(无指标)。"""
    if locked_codes and str(fund.get("code", "")).strip() in locked_codes:
        return "处方锁定"
    name = str(fund.get("name", ""))
    if any(m in name for m in RECENT_MARKERS):
        return "刚买入"
    if fund.get("sharpe") is None:
        return "数据不足"
    return None


def _prescription_locked() -> set:
    """处方锁定标的：低波替换的目标基金(settings style_tilt.swaps 的 to) + 黄金代表(holdings)。质量榜不淘汰它们。"""
    import yaml
    locked = set()
    try:
        with open(CONFIG / "settings.yaml", encoding="utf-8") as f:
            st = (yaml.safe_load(f) or {}).get("style_tilt", {})
        for sw in st.get("swaps", []):
            code = (sw.get("to") or {}).get("code")
            if code:
                locked.add(str(code).strip())
    except Exception:
        pass
    try:
        with open(CONFIG / "holdings.yaml", encoding="utf-8") as f:
            reps = (yaml.safe_load(f) or {}).get("class_representatives", {})
        if "gold" in reps and reps["gold"].get("code"):
            locked.add(str(reps["gold"]["code"]).strip())
    except Exception:
        pass
    return locked


def screen(pct: int = 20, min_group: int = 5, lookback: int = 504) -> dict:
    """主入口：读持仓 → 拉指标+评级 → 同类分组打分 → 末位淘汰 + 保护 → 腾现金。"""
    from risk_engine.fetcher import fetch_fund_returns
    from fund_selector.selector import _metrics_from_returns
    from fund_selector.ratings import load_ratings_table, get_ratings, rating_summary, is_low_rated

    cur_path = CONFIG / "holdings_current.json"
    if not cur_path.exists():
        raise RuntimeError("缺 config/holdings_current.json，请先运行 ⑥：python -m holdings_sync")
    current = json.loads(cur_path.read_text(encoding="utf-8"))
    funds = [f for f in current["funds"] if f.get("active")]
    ratings = load_ratings_table()

    enriched = []
    for f in funds:
        code = f["code"]
        try:
            r = fetch_fund_returns(code)
            m = _metrics_from_returns(r, lookback)
        except Exception:
            m = None
        rat = get_ratings(code, ratings)
        enriched.append({
            "code": code, "name": f.get("name", code), "class": f.get("class"),
            "amount_wan": f.get("amount_wan", 0.0), "sector": f.get("sector", ""),
            "sharpe": m["sharpe"] if m else None, "max_drawdown": m["max_drawdown"] if m else None,
            "vol": m["vol"] if m else None, "ann_ret": m["ann_ret"] if m else None,
            "buy_fee_pct": f.get("buy_fee_pct"), "rating_summary": rating_summary(rat),
            "rating_low": is_low_rated(rat),
        })

    # 分组(按 class) → 保护过滤 → 组内打分 → 末位标记
    locked = _prescription_locked()
    groups: dict[str, list] = {}
    protected = []
    for f in enriched:
        reason = _protect_reason(f, locked)
        if reason:
            protected.append({**f, "protect": reason})
        else:
            groups.setdefault(f["class"], []).append(f)

    eliminated, kept = [], []
    for cls, g in groups.items():
        scored = _composite_scores(g)
        cut_codes = {c["code"] for c in _mark_bottom(scored, pct, min_group)}
        for f in scored:
            (eliminated if f["code"] in cut_codes else kept).append(f)

    freed_cash = round(sum(f["amount_wan"] for f in eliminated), 2)
    result = {
        "pct": pct, "min_group": min_group, "lookback": lookback,
        "n_funds": len(funds), "n_eliminated": len(eliminated), "freed_cash_wan": freed_cash,
        "eliminated": eliminated, "kept": kept, "protected": protected,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "holdings_screen.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS / "holdings_screen.md").write_text(_render(result), encoding="utf-8")
    print(f"[淘汰器] ✅ 已写入 outputs/holdings_screen.{{json,md}}（淘汰 {len(eliminated)} 只，腾出 {freed_cash}w）")
    return result


def _render(r: dict) -> str:
    L = ["# 持仓末位淘汰建议（同类内综合分排序）", ""]
    L.append(f"> 末位 {r['pct']}%｜组内<{r['min_group']}只不淘汰｜共 {r['n_funds']} 只持仓｜⚠️ 建议，需人工 review")
    L.append("> 标准：同类百分位(夏普0.30/-回撤0.25/-波动0.20/年化0.10/-费率0.15)+评级避雷×0.85")
    L.append("")
    L.append(f"## 🗑️ 建议淘汰（{r['n_eliminated']} 只，腾出现金 {r['freed_cash_wan']}w）")
    if r["eliminated"]:
        L.append("| 代码 | 名称 | 大类 | 持仓(w) | 综合分 | 外部评级 |")
        L.append("|------|------|------|------|------|------|")
        for f in sorted(r["eliminated"], key=lambda x: x["score"]):
            avoid = " ⚠️避雷" if f.get("rating_low") else ""
            L.append(f"| {f['code']} | {str(f['name'])[:16]} | {CN.get(f['class'], f['class'])} | "
                     f"{f['amount_wan']} | {f['score']}{avoid} | {f.get('rating_summary', '—')} |")
    else:
        L.append(f"（本期无淘汰：各组都不足 {r['min_group']} 只或无人达淘汰线）")
    L.append("")
    if r["protected"]:
        L.append(f"## 🛡️ 保护未评（{len(r['protected'])} 只）")
        L.append("| 代码 | 名称 | 原因 |")
        L.append("|------|------|------|")
        for f in r["protected"]:
            L.append(f"| {f['code']} | {str(f['name'])[:16]} | {f['protect']} |")
        L.append("")
    L.append("> 替代建议：对淘汰的基金，可用其 sector 主题跑选基补回（`python -m fund_selector --buy <主题> <金额>`）。")
    L.append("> ⚠️ 建议需人工 review；执行后更新 Finance.md。")
    return "\n".join(L)
