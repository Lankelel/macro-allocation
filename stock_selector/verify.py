"""校验落地(守铁律)：把候选逐只用 basics 数据验真，剔除查无/ST/上市过短/概念不符的。
apply_verify_rules 是纯逻辑(吃已取好的 basics dict)，便于单测；联网取 basics 在 verify_candidates。"""
from __future__ import annotations

MIN_LIST_YEARS = 1.0


def apply_verify_rules(cands: list[dict], basics: dict, theme_concepts: list[str]) -> tuple[list, list]:
    """cands:[{code,name,source}], basics:{code: {name,mktcap_yi,list_years,concepts,is_st} | None}。
    theme_concepts 为空时不做"概念不符"过滤(数据源无 concepts 时自动放宽)。"""
    verified, rejected = [], []
    tset = set(theme_concepts or [])
    # 缺数据不惩罚：若所有候选都拿不到 concepts(数据源降级)，跳过"概念不符"过滤
    if not any((basics.get(c["code"]) or {}).get("concepts") for c in cands):
        tset = set()
    for c in cands:
        b = basics.get(c["code"])
        if b is None:
            rejected.append({"code": c["code"], "reason": "查无此股"}); continue
        if b.get("is_st"):
            rejected.append({"code": c["code"], "reason": "ST"}); continue
        ly = b.get("list_years")     # 仅真·新股(已知正值且<1年)拒;未知/取数失败(None/0)放行(缺数据不惩罚)
        if ly is not None and 0 < ly < MIN_LIST_YEARS:
            rejected.append({"code": c["code"], "reason": "上市<1年"}); continue
        if tset and not (set(b.get("concepts", [])) & tset):
            rejected.append({"code": c["code"], "reason": "概念不符"}); continue
        verified.append({**c, "name": b["name"], "mktcap_yi": b.get("mktcap_yi"),
                         "list_years": b.get("list_years"), "concepts": b.get("concepts", []),
                         "flags": [], "verified": True})
    return verified, rejected


def verify_candidates(cands: list[dict], source, theme_concepts: list[str]) -> tuple[list, list]:
    """联网版：逐只取 basics 再套规则。source: DataSource。"""
    basics = {}
    for c in cands:
        try:
            basics[c["code"]] = source.basics(c["code"])
        except Exception:
            basics[c["code"]] = None
    return apply_verify_rules(cands, basics, theme_concepts)
