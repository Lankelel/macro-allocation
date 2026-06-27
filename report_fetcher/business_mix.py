"""个股相关性门的"客观底":主营业务构成占比(akshare stock_zygc_em,东财)。

用法纪律(口径隐藏是常态):
- 主营构成常把主题 bundle 进大类(安克"充电储能类"、鹏辉"锂离子电池")。
- 所以本函数给的是"客观分部占比" = 第一步;真·主题占比常需 SKILL 层结合个股深度报告拆细。
"""


def market_prefix(code):
    """6→SH(沪) 0/3→SZ(深) 其它(8/4/920…)→BJ(北交所)。"""
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    return "BJ"


def business_mix(code, market=None, by="按产品分类"):
    """返回最近一期主营构成:[{segment, share, revenue}],share 为 0-1 小数。
    market 不传则自动判断;by 可选 '按产品分类'/'按行业分类'(无产品口径时自动回退)。"""
    import akshare as ak

    mkt = market or market_prefix(code)
    df = ak.stock_zygc_em(symbol=f"{mkt}{code}")
    if df is None or len(df) == 0:
        return []

    def _col(*names):
        for n in names:
            for c in df.columns:
                if n in c:
                    return c
        return None

    dcol = _col("报告日期", "报告期") or df.columns[1]
    tcol = _col("分类")
    ncol = _col("主营构成", "构成")
    rcol = _col("收入比例", "比例")
    icol = _col("主营收入")

    periods = sorted([p for p in df[dcol].dropna().unique()], reverse=True)
    if not periods:
        return []
    latest = periods[0]
    sub = df[df[dcol] == latest]
    types = [by, "按行业分类"] if tcol else [None]
    for typ in types:
        s2 = sub if typ is None or not tcol else sub[sub[tcol] == typ]
        if len(s2) == 0:
            continue
        rows = []
        for _, r in s2.iterrows():
            share = r.get(rcol)
            try:
                share = float(share)
            except (TypeError, ValueError):
                share = None
            rows.append({"segment": str(r.get(ncol, "")), "share": share, "revenue": r.get(icol)})
        if rows:
            return rows
    return []
