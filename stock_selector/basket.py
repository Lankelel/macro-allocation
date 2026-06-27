"""组小篮子：相关性去重(去同质押注) → 取 top-n(跳过红旗股) → 等权分配并施加单股上限。
纯逻辑(可单测)：build_basket / greedy_decorrelate；联网：build_corr_matrix / select_decorrelated /
check_basket_risk(接 diagnostic.stock_rc_with_satellite)。"""
from __future__ import annotations

CORR_THRESHOLD = 0.60    # ρ ≥ 此值视作"同质押注"，择优留一；负相关=对冲，保留。
# 0.60 经 59只×6行业 校准(见 PROBE.md)：同环节ρ中位0.60/跨环节0.38/跨行业0.14；0.60=同环节中位锚点,
# 敢去重(recall 52%)又不误伤跨环节(误删~10%)。最初0.8/0.7太高(只抓7%/24%)。
CORR_LOOKBACK = 252      # 相关性回看交易日，与 vol/risk 口径一致
SEG_RELAXED_RHO = 0.90   # F: 有环节标签时,去重主力交给"同环节≤1",相关性放宽到只 catch 近重复(防误删跨环节)


def greedy_decorrelate(scored: list[dict], corr: dict, n: int = 4,
                       rho_threshold: float = CORR_THRESHOLD, max_per_segment: int | None = None) -> dict:
    """纯函数：scored 已按 total 降序。贪心选入篮，跳过(去同质)条件：
      ① 环节满(F)：s["segment"] 已选满 max_per_segment 只(同环节≤该数)；
      ② 相关(E)：与已入篮某只 ρ≥阈值。
    跳过后继续向下补位直到凑满 n。corr 缺该对→视为不冲突(缺数据不惩罚)；只惩罚高正相关,负相关(对冲)放行。"""
    selected: list[dict] = []
    dropped: list[dict] = []
    seg_count: dict = {}
    for s in scored:
        code, seg = s["code"], s.get("segment")
        if max_per_segment and seg and seg_count.get(seg, 0) >= max_per_segment:    # F 同环节已满
            dropped.append({"code": code, "reason": "同环节已满", "segment": seg})
            continue
        conflict = None
        for sel in selected:
            rho = (corr.get(code) or {}).get(sel["code"])
            if rho is not None and rho >= rho_threshold:     # 正相关同质;负相关(对冲)放行
                conflict = (sel["code"], float(rho))
                break
        if conflict:
            dropped.append({"code": code, "conflict_with": conflict[0], "rho": round(conflict[1], 3)})
            continue
        selected.append(s)
        if seg:
            seg_count[seg] = seg_count.get(seg, 0) + 1
        if len(selected) >= n:
            break
    return {"picks": selected, "dropped": dropped}


def build_corr_matrix(codes: list[str], source, lookback: int = CORR_LOOKBACK):
    """联网：逐只拉日收益→对齐→皮尔逊相关矩阵(dict)。不足2只可对齐或共同交易日<30→None(降级)。"""
    import pandas as pd
    rets = {}
    for c in codes:
        try:
            s = source.daily_returns(c, lookback=lookback)
            if len(s) > 30:
                rets[c] = s
        except Exception:
            pass
    if len(rets) < 2:
        return None
    df = pd.concat(rets, axis=1).dropna()
    if len(df) < 30:
        return None
    return df.corr().to_dict()


def select_decorrelated(scored: list[dict], source, n: int = 4, rho_threshold: float = CORR_THRESHOLD,
                        lookback: int = CORR_LOOKBACK, segments: dict | None = None,
                        max_per_segment: int = 1) -> dict:
    """编排：红旗预过滤 → 相关矩阵 → 贪心去同质补位。相关数据不足→降级取前n(同旧行为)。
    F: 传 segments({code:环节}) 则启用"同环节≤max_per_segment",并把相关阈值放宽到 SEG_RELAXED_RHO
    (去重主力交给环节,相关性只兜近重复)——解单一热门板块下全局0.60误删跨环节的问题。"""
    clean = [s for s in scored if not s.get("red_flags")]
    pool = clean or scored
    if segments:
        pool = [{**s, "segment": segments.get(s["code"])} for s in pool]
    corr = build_corr_matrix([s["code"] for s in pool], source, lookback)
    eff_rho = SEG_RELAXED_RHO if segments else rho_threshold
    cap = max_per_segment if segments else None
    if corr is None:
        return {"picks": pool[:n], "dropped": [], "degraded": True,
                "threshold": eff_rho, "segment_mode": bool(segments)}
    res = greedy_decorrelate(pool, corr, n, eff_rho, max_per_segment=cap)
    return {**res, "degraded": False, "threshold": eff_rho, "segment_mode": bool(segments)}


def build_basket(scored: list[dict], amount_wan: float, n: int = 4, single_cap: float = 0.4) -> dict:
    """scored: score_pool 产出(降序，含 red_flags/total)。取前 n 只无红旗股，等权+单股上限分配。"""
    clean = [s for s in scored if not s.get("red_flags")]
    picks_src = (clean or scored)[:n]
    k = len(picks_src)
    if k == 0:
        return {"picks": [], "amount_wan": amount_wan, "used_wan": 0.0, "note": "无可入篮候选"}
    cap_wan = amount_wan * single_cap
    alloc = min(amount_wan / k, cap_wan)           # 等权；超单股上限则截到上限
    picks = [{"code": s["code"], "name": s.get("name", s["code"]), "alloc_wan": round(alloc, 3),
              "total": s.get("total"), "warn_flags": s.get("warn_flags", [])} for s in picks_src]
    used = round(alloc * k, 3)
    note = "" if abs(used - amount_wan) < 1e-6 else \
        f"单股上限触发，{round(amount_wan - used, 3)}w 未分配(建议加只数或放宽上限)"
    return {"picks": picks, "amount_wan": amount_wan, "used_wan": used, "note": note}


def check_basket_risk(picks: list[dict], amount_wan: float, source, total_assets_wan: float) -> dict:
    """合成篮子日收益(按 alloc 权重)→ 调 diagnostic.stock_rc_with_satellite 检查股票(含卫星)风险贡献。"""
    import pandas as pd
    import yaml
    from pathlib import Path
    from diagnostic.analyzer import _build_class_returns, stock_rc_with_satellite
    base = Path(__file__).resolve().parent.parent
    holdings = yaml.safe_load((base / "config" / "holdings.yaml").read_text(encoding="utf-8"))
    reps = holdings["class_representatives"]
    class_ret = _build_class_returns(reps, lookback_days=504)
    class_w = {c: reps[c]["weight"] for c in reps}
    legs = {}
    for p in picks:
        try:
            legs[p["code"]] = source.daily_returns(p["code"], lookback=504) * (p["alloc_wan"] / amount_wan)
        except Exception:
            pass
    if not legs:
        return {"stock_rc": None, "pass": None, "remedies": ["个股收益拉取失败，无法评估"]}
    sat = pd.concat(legs.values(), axis=1).dropna().sum(axis=1).to_frame("sat")
    sat_weight = amount_wan / total_assets_wan
    res = stock_rc_with_satellite(class_ret, class_w, sat_returns=sat, sat_weight=sat_weight)
    remedies = [] if res["pass"] else [
        f"缩小卫星仓金额(当前 {amount_wan}w)", "换更低 beta/低相关个股", "篮子再分散(加只数/降单股上限)"]
    return {"stock_rc": res["stock_rc"], "pass": res["pass"], "remedies": remedies}
