"""
选基模块（券商分析师角色）- A 方案 MVP：定向筛选

给定一个主题（关键词）→ 在全市场召回候选 → 硬筛 → 自算风险指标 → 同类百分位打分排序 →
输出排序清单（标注未过硬筛/不可购买占位）。详见 PRD 第十一章。

铁律：关键词只做"粗筛召回"，最终靠数据定夺（不靠名字）；输出是建议，需人工 review。
数据：fund_open_fund_rank_em(阶段收益+手续费) + fund_individual_basic_info_xq(成立/规模/类型/评级)
     + risk_engine 自算(夏普/回撤/波动)。晨星星级/风格箱(OpenCLI)作可选增强，本 MVP 暂不接。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

from risk_engine.fetcher import fetch_fund_returns
from style_tilt.rbsa import fetch_factor_returns, run_rbsa

from .blocklist import load_blocklist
from .ratings import get_ratings, is_low_rated, load_ratings_table, rating_summary
from .tracking import TE_HIGH, tracking_error

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"
TRADING_DAYS = 252
RISK_FREE = 0.02

# 两层过滤（见 PRD 11.5）：
# 强制层 MANDATORY——必满足，不满足直接剔除（清盘红线 + 可算指标 + 股票主题非债货）。
# 弹性层 ELASTIC——偏好但可不满足，未达只标注 + 轻罚分（不剔除），让小众品种(原油/油气等天生规模小、成立晚)也能入榜。
MANDATORY = {"min_aum_yi": 0.5}          # 清盘红线：规模过低有清盘风险，必剔
ELASTIC = {"min_years": 3.0, "min_aum_yi": 2.0}   # 成熟度偏好：未达每项 score×0.9
ELASTIC_PENALTY = 0.9                    # 每违反一项弹性条件的打分折扣
# 打分权重（百分位加权；低波主题侧重低波动/小回撤，可按主题调）
WEIGHTS = {"sharpe": 0.35, "neg_maxdd": 0.30, "neg_vol": 0.25, "ann_ret": 0.10}
# 主题关键词 → RBSA 验证因子（A股风格因子，csindex）。目标风格载荷越高越名副其实。
# 仅对 A股 基金有效；海外/港股对 A股因子回归 R² 低 → 标"不适用"而非误杀。
# 匹配按"关键词包含概念词"推断（如 关键词含"低波"或"红利"→验证因子"红利低波"），不要求精确等于。
FACTOR_HINTS = {"红利低波": ["低波", "红利"], "成长": ["成长"], "价值": ["价值"]}


def _infer_verify_factor(keywords: list[str], override: str | None = None) -> str | None:
    if override:
        return override
    joined = "".join(keywords)
    for factor, hints in FACTOR_HINTS.items():
        if any(h in joined for h in hints):
            return factor
    return None
STYLE_MATCH_MIN = 0.40    # 目标风格载荷阈值（R²足够时，低于此判"风格不符"）
STYLE_R2_MIN = 0.30       # R² 低于此 → 风格验证不适用（多为海外/港股）


# 概念维度图谱：概念 → (维度, 召回同义词)。召回策略——
#   组内OR：同一概念/同一维度的词撒大网（红利低波→红利|低波|高股息|股息）；
#   跨组AND：不同维度间取交集（美股低波 = 美股维度 AND 风格维度），精准锁定跨维度品种、不混榜。
# 同义词解决"名字写法不一"（石油↔原油↔油气↔石化、美股↔标普↔纳指）。精度仍靠末端 RBSA/指标/评级。
CONCEPTS = {
    # —— 风格维度 ——
    "红利低波": ("风格", ["红利", "低波", "高股息", "股息"]),
    "成长":    ("风格", ["成长"]),
    "价值":    ("风格", ["价值"]),
    "质量":    ("风格", ["质量"]),
    "动量":    ("风格", ["动量"]),
    "等权":    ("风格", ["等权"]),
    "ESG":     ("风格", ["ESG", "可持续", "社会责任"]),
    # —— 属性维度（与风格/行业正交，可 AND，如 国企红利）——
    "央国企":  ("属性", ["央企", "国企", "国资", "央国企"]),
    # —— 地域维度 ——
    "美股":    ("地域", ["标普", "纳斯达克", "纳指", "道琼斯", "美国"]),
    "港股":    ("地域", ["港股", "恒生", "H股", "港股通"]),
    "中概互联": ("地域", ["中概", "中国互联网", "中国互联", "海外互联"]),
    "欧洲":    ("地域", ["欧洲", "德国", "法国", "英国"]),
    "日本":    ("地域", ["日本", "日经"]),
    "越南":    ("地域", ["越南"]),
    "印度":    ("地域", ["印度"]),
    "亚太":    ("地域", ["亚太", "亚洲", "大中华"]),
    "沙特":    ("地域", ["沙特", "沙特阿拉伯", "中东"]),
    # —— 宽基维度（A股宽基）——
    "沪深300":  ("宽基", ["沪深300"]),
    "上证50":   ("宽基", ["上证50"]),
    "中证500":  ("宽基", ["中证500"]),
    "中证1000": ("宽基", ["中证1000"]),
    "中证800":  ("宽基", ["中证800"]),
    "中证A500": ("宽基", ["中证A500", "A500"]),
    "中证A50":  ("宽基", ["中证A50", "A50"]),
    "创业板":   ("宽基", ["创业板"]),
    "科创":     ("宽基", ["科创", "科创板"]),
    "北证50":   ("宽基", ["北证50", "北交所"]),
    "微盘":     ("宽基", ["微盘"]),
    # —— 行业维度 ——
    "石油":    ("行业", ["石油", "原油", "油气", "石化"]),
    "煤炭":    ("行业", ["煤炭"]),
    "黄金":    ("行业", ["黄金", "贵金属"]),
    "有色":    ("行业", ["有色", "金属"]),
    "钢铁":    ("行业", ["钢铁"]),
    "化工":    ("行业", ["化工"]),
    "医药":    ("行业", ["医药", "医疗", "生物医药"]),
    "创新药":  ("行业", ["创新药"]),
    "中药":    ("行业", ["中药"]),
    "医疗器械": ("行业", ["医疗器械"]),
    "半导体":  ("行业", ["半导体", "芯片", "集成电路"]),
    "科技":    ("行业", ["科技", "信息技术", "TMT"]),
    "人工智能": ("行业", ["人工智能", "AI"]),
    "计算机":  ("行业", ["计算机", "软件", "云计算"]),
    "通信":    ("行业", ["通信", "5G"]),
    "传媒":    ("行业", ["传媒", "游戏", "动漫"]),
    "新能源车": ("行业", ["新能源车", "新能源汽车", "电动车", "智能驾驶"]),
    "新能源":  ("行业", ["新能源", "光伏", "锂电", "储能", "风电", "氢能"]),
    "电力":    ("行业", ["电力", "公用事业"]),
    "汽车":    ("行业", ["汽车"]),
    "家电":    ("行业", ["家电"]),
    "消费":    ("行业", ["消费"]),
    "白酒":    ("行业", ["白酒"]),
    "食品饮料": ("行业", ["食品饮料", "食品", "饮料"]),
    "农业":    ("行业", ["农业", "农牧", "养殖", "畜牧"]),
    "军工":    ("行业", ["军工", "国防", "航天", "航空"]),
    "银行":    ("行业", ["银行"]),
    "证券":    ("行业", ["证券", "券商"]),
    "保险":    ("行业", ["保险"]),
    "金融":    ("行业", ["金融"]),
    "地产":    ("行业", ["地产", "房地产"]),
    "基建":    ("行业", ["基建", "基础建设"]),
    "建材":    ("行业", ["建材"]),
    "机器人":  ("行业", ["机器人"]),
    "环保":    ("行业", ["环保"]),
    "旅游":    ("行业", ["旅游", "休闲"]),
    "稀土":    ("行业", ["稀土"]),
    "高端制造": ("行业", ["高端制造", "智能制造", "先进制造"]),
    "REITs":   ("行业", ["REITs", "REIT", "不动产"]),
}
# 回退断词词表（未命中任何概念时用，单组 OR）
CONCEPT_TOKENS = sorted({t for _, syns in CONCEPTS.values() for t in syns}, key=len, reverse=True)


def _split_tokens(keywords: list[str]) -> list[str]:
    """回退：长关键词断成成分词（无概念命中时用）。无可拆则原样保留。"""
    out = []
    for kw in keywords:
        toks = [t for t in CONCEPT_TOKENS if t in kw and t != kw]
        out.extend(toks if toks else [kw])
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return uniq


def _build_recall_plan(keywords: list[str]):
    """解析主题 → 召回计划：list[(维度, [召回词])]。同维度的概念合并为一个 OR 组，跨维度间 AND。
    最长匹配去重：若某概念命中的词是另一命中词的子串（如 新能源⊂新能源车），丢弃较短的那个。
    未命中任何概念则回退到单组 OR（断词）。返回 (plan, matched_concepts)。"""
    joined = "".join(keywords)
    hits = []   # (concept, dim, syns, 命中的trigger)
    for concept, (dim, syns) in CONCEPTS.items():
        trig = next((t for t in ([concept] + syns) if t in joined), None)
        if trig:
            hits.append((concept, dim, syns, trig))
    # 去掉"命中trigger被另一命中trigger包含"的较短概念（新能源车在场→丢新能源）
    trigs = [h[3] for h in hits]
    hits = [h for h in hits if not any(h[3] != o and h[3] in o for o in trigs)]
    groups: dict[str, set] = {}
    matched = []
    for concept, dim, syns, _ in hits:
        groups.setdefault(dim, set()).update(syns)
        matched.append(concept)
    if not groups:
        return [("关键词", _split_tokens(keywords))], matched
    return [(dim, sorted(terms)) for dim, terms in groups.items()], matched


def _recall(plan: list, deep_budget: int) -> pd.DataFrame:
    """按召回计划取候选：组内 OR、跨组 AND（基金名须每个维度组都命中≥1词）。
    自适应预过滤：召回数 > 深挖预算时才砍掉近3年为空(成立<3年)以聚焦预算；
    小众主题(召回≤预算)则全量深挖、不预过滤——否则弹性层放进来的年轻品种会在深挖前就被杀。"""
    rank = ak.fund_open_fund_rank_em(symbol="全部")
    names = rank["基金简称"].astype(str)
    mask = pd.Series(True, index=rank.index)
    desc = []
    for dim, terms in plan:
        pat = "|".join(terms)
        mask &= names.str.contains(pat, na=False)
        desc.append(f"{dim}({pat})")
    df = rank[mask].copy()
    n0 = len(df)
    plan_str = " AND ".join(desc)
    if n0 > deep_budget:
        df = df[df["近3年"].notna()]   # 召回过多→聚焦成立≥3年（近3年收益为空≈成立<3年，零成本）
        print(f"[选基] 召回计划 {plan_str} → {n0} 只 > 深挖预算 {deep_budget} → 预过滤(成立≥3年) 后 {len(df)} 只")
    else:
        print(f"[选基] 召回计划 {plan_str} → {n0} 只 ≤ 深挖预算 {deep_budget} → 全量深挖(不预过滤,纳入年轻品种)")
    return df[["基金代码", "基金简称", "近1年", "近3年", "手续费"]]


def _parse_aum_yi(s: str) -> float | None:
    """'25.08亿' -> 25.08；'5000.00万' -> 0.5（亿）。"""
    if not s or s == "<NA>":
        return None
    s = str(s)
    m = re.search(r"([\d.]+)", s)
    if not m:
        return None
    v = float(m.group(1))
    if "万" in s:
        v /= 10000.0
    return v


def _years_since(date_str: str) -> float | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(date_str))
    if not m:
        return None
    d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return round((datetime.now() - d).days / 365.25, 1)


def _basic_info(code: str) -> dict:
    d = ak.fund_individual_basic_info_xq(symbol=code)
    return dict(zip(d["item"], d["value"]))


def _metrics_from_returns(r, lookback: int) -> dict | None:
    """从日收益序列算 年化收益/波动/夏普/最大回撤（与 RBSA 共用同一份净值，避免重复拉取）。"""
    r = r.dropna()
    if len(r) < 60:
        return None
    r = r.iloc[-lookback:]
    ann_ret = float(r.mean() * TRADING_DAYS)
    vol = float(r.std() * np.sqrt(TRADING_DAYS))
    sharpe = (ann_ret - RISK_FREE) / vol if vol > 0 else 0.0
    nav = (1 + r).cumprod()
    mdd = float((nav / nav.cummax() - 1).min())
    return {"ann_ret": round(ann_ret, 4), "vol": round(vol, 4),
            "sharpe": round(sharpe, 3), "max_drawdown": round(mdd, 4), "n_obs": int(len(r))}


def _style_verdict(loadings, r2, target_factor):
    """RBSA 风格判定：R²低→海外/不适用；否则看目标风格载荷是否达标。"""
    if target_factor is None:
        return None, None, "未配置验证因子"
    load = round(float(loadings.get(target_factor, 0)), 3)
    if r2 < STYLE_R2_MIN:
        return load, round(r2, 2), "海外/港股,验证不适用"
    if load >= STYLE_MATCH_MIN:
        return load, round(r2, 2), "✓名副其实"
    top = max(loadings, key=loadings.get)
    return load, round(r2, 2), f"✗偏{top}"


def select_funds(keywords: list[str], lookback: int = 504, max_deep: int = 120,
                 verify: bool = True, verify_factor: str | None = None) -> dict:
    raw_keywords = keywords
    plan, matched = _build_recall_plan(keywords)   # 概念图谱：组内OR + 跨组AND + 同义词
    if matched:
        kind = "跨维度AND" if len(plan) > 1 else "单维OR"
        print(f"[选基] 主题解析：{raw_keywords} → 命中概念 {matched}（{kind}，{len(plan)}个维度组）")
    else:
        print(f"[选基] 主题解析：{raw_keywords} 未命中概念图谱 → 回退断词单组OR {plan[0][1]}")
    recall = _recall(plan, deep_budget=max_deep)
    # RBSA 验证因子（按原始主题词概念推断，可显式覆盖）
    target_factor = _infer_verify_factor(raw_keywords, verify_factor)
    if verify and target_factor:
        print(f"[选基] RBSA 风格验证因子：{target_factor}")
    factor_ret = None
    if verify and target_factor:
        try:
            factor_ret = fetch_factor_returns({"红利低波": "H30269", "成长": "000918", "价值": "000919"},
                                              lookback_days=lookback)
        except Exception as e:
            print(f"[选基] 风格因子拉取失败，跳过 RBSA 验证：{str(e)[:50]}")
    # 外部评级表（增量4）：一次拉全市场四家评级（含晨星星级），失败不阻断主流程
    try:
        ratings_table = load_ratings_table()
    except Exception as e:
        print(f"[选基] 评级表拉取失败，跳过外部评级增强：{str(e)[:50]}")
        ratings_table = {}
    rows = []
    for i, (_, row) in enumerate(recall.iterrows(), 1):
        code = row["基金代码"]
        if i > max_deep:
            print(f"[选基] 已达深挖上限 {max_deep}，剩余 {len(recall)-max_deep} 只未深挖")
            break
        try:
            kv = _basic_info(code)
        except Exception as e:
            print(f"[选基] {code} 基本信息失败：{str(e)[:50]}")
            continue
        # 净值只拉一次，供 风险指标 + RBSA 共用
        try:
            r = fetch_fund_returns(code)
        except Exception:
            r = None
        rm = _metrics_from_returns(r, lookback) if r is not None else None
        style_load, style_r2, style_verdict = (None, None, None)
        if factor_ret is not None and r is not None:
            try:
                rb = run_rbsa(r.iloc[-lookback:], factor_ret)
                style_load, style_r2, style_verdict = _style_verdict(rb["loadings"], rb["r2"], target_factor)
            except Exception:
                pass
        years = _years_since(kv.get("成立时间", ""))
        aum = _parse_aum_yi(kv.get("最新规模", ""))
        fee = None
        m = re.search(r"([\d.]+)", str(row.get("手续费", "")))
        if m:
            fee = float(m.group(1))
        rat = get_ratings(code, ratings_table)
        # 跟踪误差（仅指数基金；按业绩比较基准解析基准指数，复用同一份净值）
        te_info = None
        if r is not None:
            try:
                te_info = tracking_error(r, lookback, kv.get("业绩比较基准", ""), kv.get("基金类型", ""))
            except Exception:
                te_info = None
        rows.append({
            "code": code, "name": kv.get("基金名称", row["基金简称"]),
            "type": kv.get("基金类型", ""), "rating": kv.get("基金评级", ""),
            "years": years, "aum_yi": aum, "buy_fee_pct": fee,
            "ann_ret": rm["ann_ret"] if rm else None,
            "vol": rm["vol"] if rm else None,
            "sharpe": rm["sharpe"] if rm else None,
            "max_drawdown": rm["max_drawdown"] if rm else None,
            "n_obs": rm["n_obs"] if rm else None,
            "style_load": style_load, "style_r2": style_r2, "style_verdict": style_verdict,
            "rating_ms": rat.get("晨星评级"), "rating_5star_n": rat.get("5星家数", 0),
            "rating_summary": rating_summary(rat), "rating_low": is_low_rated(rat),
            "te": te_info.get("te") if te_info else None,
            "te_bench": te_info.get("bench") if te_info else None,
        })
        if i % 10 == 0:
            print(f"[选基] 已深挖 {i}/{min(len(recall), max_deep)} 只")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("无候选可处理")

    # 两层过滤。股票风格主题(有验证因子)时，排除债券/货币类——否则债券基金借"红利"名+低波动刷分(钻"R²低=不适用"后门)
    equity_theme = target_factor is not None

    def _mandatory_fail(r):
        """强制层：不满足直接剔除（清盘红线 + 可算指标 + 股票主题非债货）。"""
        bad = []
        if r["sharpe"] is None:
            bad.append("无净值/风险指标")
        if r["aum_yi"] is None or r["aum_yi"] < MANDATORY["min_aum_yi"]:
            bad.append(f"规模<{MANDATORY['min_aum_yi']}亿(清盘红线)")
        if equity_theme and any(x in str(r.get("type", "")) for x in ["债券", "货币", "短债", "纯债"]):
            bad.append("非股票类(债/货币)")
        return "；".join(bad)

    def _elastic_unmet(r):
        """弹性层：未达不剔除、只标注（后续按项数轻罚分）。"""
        soft = []
        if r["years"] is None or r["years"] < ELASTIC["min_years"]:
            soft.append(f"成立<{ELASTIC['min_years']}年")
        if r["aum_yi"] is None or r["aum_yi"] < ELASTIC["min_aum_yi"]:
            soft.append(f"规模<{ELASTIC['min_aum_yi']}亿")
        return soft

    df["fail_reason"] = df.apply(_mandatory_fail, axis=1)
    df["elastic_unmet"] = df.apply(_elastic_unmet, axis=1)
    hard_ok = df[df["fail_reason"] == ""].copy()
    failed = df[df["fail_reason"] != ""].copy()

    # RBSA 风格验证：把"高R²但非目标风格(✗偏…)"的剔出主榜（名不副实），其余进打分池
    if "style_verdict" in hard_ok.columns:
        style_bad = hard_ok[hard_ok["style_verdict"].astype(str).str.startswith("✗")].copy()
        passed = hard_ok[~hard_ok["style_verdict"].astype(str).str.startswith("✗")].copy()
    else:
        style_bad = hard_ok.iloc[0:0].copy()
        passed = hard_ok

    # 同类百分位打分（仅在通过硬筛+风格验证的池内）
    if not passed.empty:
        passed["pct_sharpe"] = passed["sharpe"].rank(pct=True)
        passed["pct_neg_maxdd"] = (-passed["max_drawdown"]).rank(pct=True)   # 回撤小→分高
        passed["pct_neg_vol"] = (-passed["vol"]).rank(pct=True)              # 波动小→分高
        passed["pct_ann_ret"] = passed["ann_ret"].rank(pct=True)
        passed["score"] = (WEIGHTS["sharpe"] * passed["pct_sharpe"]
                           + WEIGHTS["neg_maxdd"] * passed["pct_neg_maxdd"]
                           + WEIGHTS["neg_vol"] * passed["pct_neg_vol"]
                           + WEIGHTS["ann_ret"] * passed["pct_ann_ret"])
        # 弹性层轻罚：每违反一项弹性条件 ×0.9，确保全达标的优先、但未达标的仍留在榜内
        passed["score"] = passed["score"] * passed["elastic_unmet"].apply(lambda u: ELASTIC_PENALTY ** len(u))
        passed = passed.sort_values("score", ascending=False)
        passed["score"] = (passed["score"] * 100).round(1)

    # 不可购买回流：在「已打分」的池子上分流——标记过的挪出主榜（同类下一只自动补位），
    # 单列展示让你看到它们曾被考虑、为何被排除。打分在分流之前，故主榜名次连续、不留空洞。
    blocked_map = load_blocklist()
    if not passed.empty and blocked_map:
        is_blk = passed["code"].astype(str).isin(blocked_map)
        blocked = passed[is_blk].copy()
        passed = passed[~is_blk].copy()
        blocked["block_reason"] = blocked["code"].astype(str).map(
            lambda c: blocked_map.get(c, {}).get("reason", ""))
    else:
        blocked = passed.iloc[0:0].copy()
        blocked["block_reason"] = None

    result = {
        "theme_keywords": keywords,
        "recall_plan": [{"dim": d, "terms": t} for d, t in plan],
        "matched_concepts": matched,
        "lookback_days": lookback,
        "n_recalled": int(len(recall)),
        "n_deep": int(len(df)),
        "n_passed": int(len(passed)),
        "n_style_bad": int(len(style_bad)),
        "n_blocked": int(len(blocked)),
        "mandatory": MANDATORY,
        "elastic": ELASTIC,
        "weights": WEIGHTS,
        "verify_factor": target_factor,
        "ranked": passed.replace({np.nan: None}).to_dict("records") if not passed.empty else [],
        "blocked_out": blocked.replace({np.nan: None}).to_dict("records"),
        "style_mismatch": style_bad.replace({np.nan: None}).to_dict("records"),
        "filtered_out": failed.replace({np.nan: None}).to_dict("records"),
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "_".join(keywords)
    (OUTPUTS_DIR / f"fund_select_{safe}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / f"fund_select_{safe}.md").write_text(_render(result), encoding="utf-8")
    print(f"[选基] ✅ 已写入 outputs/fund_select_{safe}.{{json,md}}")
    return result


def _render(r: dict) -> str:
    lines = [f"# 选基排序清单（A方案 MVP）- 主题：{' / '.join(r['theme_keywords'])}", ""]
    man, ela = r.get("mandatory", {}), r.get("elastic", {})
    plan = r.get("recall_plan", [])
    if plan:
        conj = " AND " if len(plan) > 1 else "｜"
        plan_str = conj.join(f"{g['dim']}组OR({'|'.join(g['terms'])})" for g in plan)
        lines.append(f"> 召回计划：{plan_str}{'（跨维度AND）' if len(plan) > 1 else ''}")
    lines.append(f"> 召回 {r['n_recalled']} 只 → 深挖 {r['n_deep']} → 过强制层 {r['n_passed']}｜窗口 {r['lookback_days']}日")
    lines.append(f"> 两层过滤：强制层(必满足)规模>{man.get('min_aum_yi')}亿(清盘红线)+可算指标+股票主题非债货；"
                 f"弹性层(可不满足,未达每项×{ELASTIC_PENALTY})成立≥{ela.get('min_years')}年 & 规模≥{ela.get('min_aum_yi')}亿")
    lines.append(f"> 打分权重(百分位)：夏普{r['weights']['sharpe']}／-最大回撤{r['weights']['neg_maxdd']}／-波动{r['weights']['neg_vol']}／年化收益{r['weights']['ann_ret']}")
    vf = r.get("verify_factor")
    lines.append(f"> RBSA风格验证：{'对「'+vf+'」载荷做名实核对(剔除高R²却偏离的)' if vf else '本主题未配置验证因子,跳过'}")
    lines.append("> ⚠️ 关键词 OR 粗筛召回、数据定夺；输出是建议需人工 review。")
    lines.append("> 🔁 不可购买回流：买不到的标 `python -m fund_selector --block <代码> [原因]`，下次自动排除、同类下一只补位。")
    lines.append("")
    lines.append("## 🎯 入选排序（过强制层 + 风格名副其实）")
    if r["ranked"]:
        lines.append("| 排名 | 代码 | 简称 | 成立(年) | 规模(亿) | 年化收益 | 波动 | 夏普 | 最大回撤 | 风格载荷/R² | 风格判定 | 外部评级(沪/招/济/晨) | 跟踪误差 | 弹性 | **综合分** | 可购买 |")
        lines.append("|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|")
        for i, f in enumerate(r["ranked"], 1):
            sl = f"{f['style_load']}/{f['style_r2']}" if f.get('style_load') is not None else "—"
            rs = (f.get("rating_summary") or "—") + (" ⚠️避雷" if f.get("rating_low") else "")
            unmet = f.get("elastic_unmet") or []
            el = "✓" if not unmet else "⚠" + "/".join(unmet)
            te = f.get("te")
            te_str = ("—" if te is None else f"{te*100:.1f}%" + (" ⚠偏大" if te > TE_HIGH else "")
                      + (f"·{f.get('te_bench')}" if f.get("te_bench") else ""))
            lines.append(f"| {i} | {f['code']} | {f['name'][:14]} | {f['years']} | {f['aum_yi']} | "
                         f"{f['ann_ret']*100:.1f}% | {f['vol']*100:.1f}% | {f['sharpe']} | {f['max_drawdown']*100:.1f}% | "
                         f"{sl} | {f.get('style_verdict') or '—'} | {rs} | {te_str} | {el} | **{f['score']}** | ☐ |")
    else:
        lines.append("（无候选通过强制层+风格验证）")
    lines.append("")
    if r.get("blocked_out"):
        lines.append(f"## 🚫 已标记不可购买（{len(r['blocked_out'])} 只，自动排除主榜——名次已由同类下一只补位）")
        lines.append("| 代码 | 简称 | 综合分 | 标记原因 |")
        lines.append("|------|------|------|------|")
        for f in r["blocked_out"]:
            lines.append(f"| {f['code']} | {str(f['name'])[:14]} | {f.get('score')} | {f.get('block_reason') or '—'} |")
        lines.append("> 撤销：`python -m fund_selector --unblock <代码>`")
        lines.append("")
    if r.get("style_mismatch"):
        lines.append(f"## ⚠️ 风格不符（{len(r['style_mismatch'])} 只，被 RBSA 剔出主榜：名字像但实际偏离）")
        lines.append("| 代码 | 简称 | 风格载荷/R² | 判定 |")
        lines.append("|------|------|------|------|")
        for f in r["style_mismatch"]:
            sl = f"{f['style_load']}/{f['style_r2']}" if f.get('style_load') is not None else "—"
            lines.append(f"| {f['code']} | {str(f['name'])[:14]} | {sl} | {f.get('style_verdict')} |")
        lines.append("")
    lines.append(f"## 未过强制层（{len(r['filtered_out'])} 只，被强制层剔除：清盘红线/无指标/债货）")
    lines.append("| 代码 | 简称 | 原因 |")
    lines.append("|------|------|------|")
    for f in r["filtered_out"][:30]:
        lines.append(f"| {f['code']} | {str(f['name'])[:14]} | {f['fail_reason']} |")
    if len(r["filtered_out"]) > 30:
        lines.append(f"| … | （余 {len(r['filtered_out'])-30} 只略） | |")
    lines.append("")
    lines.append("> 外部评级源 akshare(上海证券/招商/济安/晨星星级)，避雷不追星；⚠️避雷=有机构≤2星或晨星<3。")
    lines.append("> 召回：概念图谱(组内OR+跨组AND+同义词)。")
    lines.append("> 跟踪误差：仅指数基金,真TE vs策库基准(中证/国证),未接标'—',>4%标⚠偏大。"
                 "⚠️口径局限:基准为**价格指数**、基金净值含分红→**高股息主题(红利)TE被除息抬高、绝对值偏大**;同基准内横向比'谁跟得紧'仍有效,勿跨主题硬比。")
    lines.append("> 下一步可叠加：TE改用全收益指数(消除分红偏差)、TE策库扩指数家族(标普/恒生)、晨星风格箱(待后端恢复)、概念图谱扩词。")
    return "\n".join(lines)
