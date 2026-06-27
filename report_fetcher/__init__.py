"""研报自动抓取前端(方案B:本模块做确定性数据,.claude/skills/研报 做相关性门与决策弹药卡推理)。

流程:关键词粗筛(eastmoney+screen) → 下载深度PDF(行业+个股) → 抽文字(extract)
     → 个股门客观底(business_mix) → 交 SKILL 做双门精筛与决策弹药卡。
"""
from .eastmoney import EastMoneyReports
from .screen import (
    WHITELIST, BUY_RATINGS, in_whitelist, make_keyword_filter,
    is_deep_industry, is_deep_stock, rank_targets, pick_deep_stock_reports,
)
from .extract import pdf_to_text
from .business_mix import business_mix, market_prefix

__all__ = [
    "EastMoneyReports", "WHITELIST", "BUY_RATINGS", "in_whitelist", "make_keyword_filter",
    "is_deep_industry", "is_deep_stock", "rank_targets", "pick_deep_stock_reports",
    "pdf_to_text", "business_mix", "market_prefix",
]
