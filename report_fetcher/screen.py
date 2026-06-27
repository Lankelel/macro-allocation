"""研报机械筛选(确定性、泛用、与主题无关):头部券商白名单、深度信号、荐标的聚合。

精度的"主题相关"部分不在这里(那靠 SKILL 层的双门:行业内容门 + 个股营收占比门)。
这里只做与关键词无关的机械过滤,换任何主题都复用。
"""
import collections

# 头部券商白名单(质量优先,过滤咨询机构与小券商噪声)
WHITELIST = {
    "中信证券", "中信建投", "中金公司", "国泰君安", "华泰证券", "招商证券", "广发证券", "海通证券",
    "东吴证券", "兴业证券", "国信证券", "天风证券", "东方证券", "光大证券", "民生证券", "申万宏源",
    "中泰证券", "国金证券", "华西证券", "浙商证券", "长江证券", "西部证券", "平安证券", "国联证券",
    "方正证券", "信达证券", "东兴证券", "开源证券", "国元证券", "华源证券", "中邮证券",
}
BUY_RATINGS = {"买入", "增持"}


def in_whitelist(org):
    return any(w in (org or "") for w in WHITELIST)


def make_keyword_filter(keywords):
    """关键词粗筛器:标题命中任一关键词即保留(高召回,精度交给双门)。"""
    kws = tuple(keywords)
    return lambda title: any(k in (title or "") for k in kws)


def is_deep_industry(item):
    """行业研报深度信号 = 标题含 深度/专题(周报/月报即便长也排除)。"""
    t = item.get("title", "")
    return ("深度" in t) or ("专题" in t)


def is_deep_stock(item, min_pages=15):
    """个股研报深度信号 = 附件页数 >= min_pages(点评2-5页,深度15-40页;深度常不带"深度"二字)。"""
    try:
        return int(item.get("attachPages") or 0) >= min_pages
    except (TypeError, ValueError):
        return False


def rank_targets(stock_reports, top_n=10):
    """从个股研报 metadata 聚合荐标的:白名单 + 买入/增持,按覆盖家数→买入数→最近日期排序。"""
    agg = {}
    for it in stock_reports:
        if not in_whitelist(it.get("orgSName", "")):
            continue
        if it.get("emRatingName", "") not in BUY_RATINGS:
            continue
        code = it.get("stockCode", "")
        if not code:
            continue
        a = agg.setdefault(code, {"name": it.get("stockName", ""), "orgs": set(),
                                  "ratings": collections.Counter(), "tp": [], "pe": [], "latest": ""})
        a["orgs"].add(it.get("orgSName", ""))
        a["ratings"][it.get("emRatingName", "")] += 1
        for fld, key in (("indvAimPriceT", "tp"), ("predictThisYearPe", "pe")):
            v = it.get(fld)
            try:
                if v not in (None, ""):
                    a[key].append(float(v))
            except (TypeError, ValueError):
                pass
        a["latest"] = max(a["latest"], it.get("publishDate", "")[:10])
    ranked = sorted(
        agg.items(),
        key=lambda kv: (len(kv[1]["orgs"]), kv[1]["ratings"]["买入"], kv[1]["latest"]),
        reverse=True,
    )
    out = []
    for code, a in ranked[:top_n]:
        out.append({
            "code": code, "name": a["name"], "coverage": len(a["orgs"]),
            "orgs": sorted(a["orgs"]), "buy": a["ratings"]["买入"], "hold": a["ratings"]["增持"],
            "target_price_avg": round(sum(a["tp"]) / len(a["tp"]), 1) if a["tp"] else None,
            "pe_avg": round(sum(a["pe"]) / len(a["pe"]), 1) if a["pe"] else None,
            "latest": a["latest"],
        })
    return out


def pick_deep_stock_reports(stock_reports, per_stock=2, min_pages=15):
    """某只票的个股深度:白名单 + 页数>=min,按页数降序取 per_stock 篇(无则返回空=该股无深度)。"""
    deep = [r for r in stock_reports
            if is_deep_stock(r, min_pages) and in_whitelist(r.get("orgSName", ""))]
    return sorted(deep, key=lambda z: int(z.get("attachPages") or 0), reverse=True)[:per_stock]
