"""report_fetcher 纯逻辑测试(不联网):JSONP剥壳、关键词粗筛、深度信号、荐标的聚合、市场前缀。"""
from report_fetcher.eastmoney import _strip_jsonp
from report_fetcher.screen import (
    in_whitelist, is_deep_industry, is_deep_stock, make_keyword_filter,
    pick_deep_stock_reports, rank_targets,
)
from report_fetcher.business_mix import market_prefix


def test_strip_jsonp():
    assert _strip_jsonp('x({"a":1})') == '{"a":1}'
    assert _strip_jsonp('{"a":1}') == '{"a":1}'


def test_keyword_filter():
    f = make_keyword_filter(["储能", "构网"])
    assert f("工商储专题：储能商业模式")
    assert f("电网构网型变流器")
    assert not f("农化钾肥月度观察")
    assert not f("")


def test_is_deep_industry():
    assert is_deep_industry({"title": "锂电储能行业深度报告"})
    assert is_deep_industry({"title": "工商储专题：商业模式多样化"})
    assert not is_deep_industry({"title": "电力设备行业跟踪周报"})


def test_is_deep_stock():
    assert is_deep_stock({"attachPages": "30"})
    assert is_deep_stock({"attachPages": 15})
    assert not is_deep_stock({"attachPages": "5"})
    assert not is_deep_stock({"attachPages": None})
    assert not is_deep_stock({})


def test_in_whitelist():
    assert in_whitelist("东吴证券")
    assert in_whitelist("中信证券股份有限公司")  # 子串匹配
    assert not in_whitelist("头豹研究院")
    assert not in_whitelist("")


def test_rank_targets_filters_and_sorts():
    reps = [
        {"stockCode": "A", "stockName": "甲", "orgSName": "东吴证券", "emRatingName": "买入",
         "publishDate": "2026-06-01", "indvAimPriceT": "100", "predictThisYearPe": "20"},
        {"stockCode": "A", "stockName": "甲", "orgSName": "国信证券", "emRatingName": "增持", "publishDate": "2026-06-10"},
        {"stockCode": "B", "stockName": "乙", "orgSName": "国金证券", "emRatingName": "买入", "publishDate": "2026-05-01"},
        {"stockCode": "C", "stockName": "丙", "orgSName": "头豹研究院", "emRatingName": "买入", "publishDate": "2026-06-01"},
        {"stockCode": "D", "stockName": "丁", "orgSName": "东吴证券", "emRatingName": "中性", "publishDate": "2026-06-01"},
        {"stockCode": "", "stockName": "无码", "orgSName": "东吴证券", "emRatingName": "买入", "publishDate": "2026-06-01"},
    ]
    out = rank_targets(reps, top_n=10)
    assert [t["code"] for t in out] == ["A", "B"]  # A覆盖2家排前;非白名单/非买增/无码全剔
    a = out[0]
    assert a["coverage"] == 2 and a["buy"] == 1 and a["hold"] == 1
    assert a["target_price_avg"] == 100.0 and a["pe_avg"] == 20.0


def test_pick_deep_stock_reports():
    reps = [
        {"orgSName": "东吴证券", "attachPages": "30", "title": "深度A"},
        {"orgSName": "国信证券", "attachPages": "24", "title": "深度B"},
        {"orgSName": "东吴证券", "attachPages": "5", "title": "点评"},      # 页数不够
        {"orgSName": "头豹研究院", "attachPages": "40", "title": "非白名单"},  # 非白名单
    ]
    out = pick_deep_stock_reports(reps, per_stock=2, min_pages=15)
    assert [r["title"] for r in out] == ["深度A", "深度B"]  # 白名单+页够,按页数降序


def test_market_prefix():
    assert market_prefix("688411") == "SH"
    assert market_prefix("300866") == "SZ"
    assert market_prefix("000700") == "SZ"
    assert market_prefix("920533") == "BJ"
