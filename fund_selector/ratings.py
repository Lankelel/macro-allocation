"""外部评级增强（增量4）：akshare fund_rating_all 一次拉全市场四家评级。

晨星新站详情页(星级/风格箱)后端当前不稳定(504/维护)，且需逐只浏览器抓取——
改用 akshare `fund_rating_all`：一次 API 拿全市场，含 上海证券/招商证券/济安金信/**晨星评级**(1-5星) + 5星家数。
晨星星级正是用户最初想要的外部参考；风格箱缺失由 RBSA 风格验证覆盖。无浏览器依赖、离线稳。

用法：外部参考、避雷不追星——某只基金若多家机构给低星(或晨星<3)，是负面信号。
不并入核心打分（评级与自算风险指标同源、会双重计数），只作展示列 + 避雷标注。
"""
from __future__ import annotations

import akshare as ak
import pandas as pd

# 四家评级机构列名（akshare fund_rating_all 输出）
AGENCIES = ["上海证券", "招商证券", "济安金信", "晨星评级"]
_CACHE: dict | None = None


def load_ratings_table() -> dict:
    """拉全市场评级表 → {代码: {上海证券, 招商证券, 济安金信, 晨星评级, 5星评级家数}}。进程内缓存（一次 API）。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    df = ak.fund_rating_all()
    out = {}
    for _, r in df.iterrows():
        code = str(r["代码"]).strip()
        rec = {}
        for a in AGENCIES:
            v = r.get(a)
            rec[a] = int(v) if pd.notna(v) else None
        n5 = r.get("5星评级家数")
        rec["5星家数"] = int(n5) if pd.notna(n5) else 0
        out[code] = rec
    _CACHE = out
    print(f"[选基] 评级表加载 {len(out)} 只（上海证券/招商/济安/晨星）")
    return out


def get_ratings(code: str, table: dict | None = None) -> dict:
    """取单只基金四家评级。table 可传入已加载的表避免重复拉取。"""
    table = table if table is not None else load_ratings_table()
    return table.get(str(code).strip(), {a: None for a in AGENCIES} | {"5星家数": 0})


def rating_summary(rec: dict) -> str:
    """紧凑展示：'沪2 招2 济2 晨2 ·0家5星'。无评级显示 —。"""
    def s(v):
        return str(v) if v is not None else "—"
    return (f"沪{s(rec.get('上海证券'))} 招{s(rec.get('招商证券'))} "
            f"济{s(rec.get('济安金信'))} 晨{s(rec.get('晨星评级'))} ·{rec.get('5星家数', 0)}家5星")


def is_low_rated(rec: dict) -> bool:
    """避雷信号：有评级的机构里，任一给≤2星 或 晨星<3 → 提示。全无评级不算雷。"""
    rated = [v for k, v in rec.items() if k in AGENCIES and v is not None]
    if not rated:
        return False
    ms = rec.get("晨星评级")
    return any(v <= 2 for v in rated) or (ms is not None and ms < 3)
