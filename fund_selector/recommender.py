"""买入建议桥（N6-A）：给定主题 + 金额 → 选基选出可买标的 + 分配金额。

这是"选基 ↔ 再平衡"价值闭环的可复用核心：再平衡器算出"某大类该加 X 万"，
本桥把它落到"买哪只、各多少万"。复用 select_funds 的完整漏斗（召回→两层→风格验真→打分→评级→回流）。
ranked 已是"过强制层+风格名副其实+可购买(不可购买已分流走)"，直接取 top-N 即可。

缓存复用：select_funds 较慢(深挖)，默认优先读 outputs/fund_select_<主题>.json；--refresh 强制重跑。
分配策略 split：top1=全押第一(默认,集中)；even=top-N 均分；score=按综合分加权。
"""
from __future__ import annotations

import json
from pathlib import Path

from .selector import OUTPUTS_DIR, _build_recall_plan, select_funds


def _load_cached(theme_keywords: list[str]) -> dict | None:
    """读已有选基结果（按主题原词的文件名）。无则 None。"""
    safe = "_".join(theme_keywords)
    p = OUTPUTS_DIR / f"fund_select_{safe}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def recommend_buy(theme_keywords: list[str], amount_wan: float, top_n: int = 1,
                  split: str = "top1", lookback: int = 504, max_deep: int = 40,
                  refresh: bool = False) -> dict:
    """主题 + 金额 → 买入建议（top-N 标的 + 分配金额）。"""
    res = None if refresh else _load_cached(theme_keywords)
    used_cache = res is not None
    if res is None:
        res = select_funds(theme_keywords, lookback=lookback, max_deep=max_deep)

    ranked = res.get("ranked", [])
    picks = ranked[:top_n]
    if not picks:
        return {"theme": theme_keywords, "amount_wan": amount_wan, "used_cache": used_cache,
                "picks": [], "alternatives": [], "note": "无可买标的（榜单为空，放宽条件或换主题）"}

    if split == "even":
        weights = [1.0 / len(picks)] * len(picks)
    elif split == "score":
        s = sum(p.get("score", 0) or 0 for p in picks) or 1.0
        weights = [(p.get("score", 0) or 0) / s for p in picks]
    else:  # top1：全押第一
        weights = [1.0] + [0.0] * (len(picks) - 1)

    allocs = []
    for p, w in zip(picks, weights):
        amt = round(amount_wan * w, 2)
        if amt <= 0:
            continue
        allocs.append({
            "code": p["code"], "name": p["name"], "amount_wan": amt,
            "score": p.get("score"), "style_verdict": p.get("style_verdict"),
            "rating_summary": p.get("rating_summary"), "rating_low": p.get("rating_low"),
            "te": p.get("te"), "te_bench": p.get("te_bench"),
            "elastic_unmet": p.get("elastic_unmet") or [],
        })
    return {
        "theme": theme_keywords, "amount_wan": amount_wan, "split": split,
        "used_cache": used_cache, "picks": allocs,
        "alternatives": [{"code": a["code"], "name": a["name"], "score": a.get("score")}
                         for a in ranked[top_n:top_n + 3]],
    }


def render_buy(rec: dict) -> str:
    lines = [f"## 🎯 买入建议：主题「{' / '.join(rec['theme'])}」加 {rec['amount_wan']}w"]
    src = "复用缓存" if rec.get("used_cache") else "实时选基"
    lines.append(f"> 来源：{src}｜分配：{rec.get('split', 'top1')}")
    if not rec["picks"]:
        lines.append(f"> ⚠️ {rec.get('note', '无可买标的')}")
        return "\n".join(lines)
    lines.append("")
    lines.append("| 代码 | 简称 | 买入(w) | 综合分 | 风格 | 外部评级 | 跟踪误差 | 弹性 |")
    lines.append("|------|------|------|------|------|------|------|------|")
    for p in rec["picks"]:
        rs = (p.get("rating_summary") or "—") + (" ⚠️避雷" if p.get("rating_low") else "")
        te = p.get("te")
        te_str = "—" if te is None else f"{te*100:.1f}%"
        el = "✓" if not p.get("elastic_unmet") else "⚠" + "/".join(p["elastic_unmet"])
        lines.append(f"| {p['code']} | {p['name'][:14]} | **{p['amount_wan']}** | {p.get('score')} | "
                     f"{p.get('style_verdict') or '—'} | {rs} | {te_str} | {el} |")
    if rec["alternatives"]:
        alt = "、".join(f"{a['code']} {a['name'][:10]}(分{a.get('score')})" for a in rec["alternatives"])
        lines.append("")
        lines.append(f"> 备选：{alt}")
    lines.append("> ⚠️ 建议需人工 review；买不到可 `--block <代码>` 后重选。")
    return "\n".join(lines)
