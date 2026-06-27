"""个股选择层 纯函数单测（不联网）。联网部分(datasource)手动验证。"""
from stock_selector.recall import merge_candidates
from stock_selector.verify import apply_verify_rules
from stock_selector.score import score_pool
import numpy as np
import pandas as pd
from diagnostic.analyzer import stock_rc_with_satellite
from stock_selector.basket import build_basket, greedy_decorrelate
from stock_selector.cache import CachedSource
from stock_selector.datasource import DataSource


def test_merge_dedup_and_source_tag():
    llm = [{"code": "300124", "name": "汇川技术"}, {"code": "688017", "name": "绿的谐波"}]
    board = [{"code": "300124", "name": "汇川技术", "mktcap_yi": 1800.0, "board": "人形机器人"},
             {"code": "002472", "name": "双环传动", "mktcap_yi": 300.0, "board": "人形机器人"}]
    out = merge_candidates(llm, board)
    by = {c["code"]: c for c in out}
    assert by["300124"]["source"] == "both"
    assert by["688017"]["source"] == "llm"
    assert by["002472"]["source"] == "board"
    assert by["300124"]["mktcap_yi"] == 1800.0
    assert len(out) == 3


def test_verify_rules_filter():
    basics = {
        "300124": {"name": "汇川技术", "mktcap_yi": 1800.0, "list_years": 13.0, "concepts": ["人形机器人"], "is_st": False},
        "000001": {"name": "平安银行", "mktcap_yi": 2000.0, "list_years": 20.0, "concepts": [], "is_st": False},
        "300XXX": None,
        "002STX": {"name": "ST某某", "mktcap_yi": 20.0, "list_years": 5.0, "concepts": [], "is_st": True},
    }
    cands = [{"code": c, "name": "", "source": "llm"} for c in basics]
    verified, rejected = apply_verify_rules(cands, basics, theme_concepts=["人形机器人"])
    vcodes = {v["code"] for v in verified}
    rmap = {r["code"]: r["reason"] for r in rejected}
    assert "300124" in vcodes
    assert rmap["300XXX"] == "查无此股"
    assert rmap["002STX"] == "ST"
    assert "000001" in rmap   # 不沾主题概念 → 剔


def test_verify_unknown_list_years_not_rejected():
    # 上市年限取数失败(None/0=未知)→不拒(缺数据不惩罚);真新股(0.5)才拒
    basics = {
        "AAA": {"name": "甲", "mktcap_yi": 100, "list_years": None, "concepts": [], "is_st": False},
        "BBB": {"name": "乙", "mktcap_yi": 100, "list_years": 0, "concepts": [], "is_st": False},
        "CCC": {"name": "丙", "mktcap_yi": 100, "list_years": 0.5, "concepts": [], "is_st": False},
    }
    cands = [{"code": c, "name": "", "source": "llm"} for c in basics]
    v, r = apply_verify_rules(cands, basics, theme_concepts=[])
    vc = {x["code"] for x in v}
    rc = {x["code"]: x["reason"] for x in r}
    assert "AAA" in vc and "BBB" in vc          # 未知(None/0)不拒
    assert rc.get("CCC") == "上市<1年"            # 已知真新股拒


def test_verify_relaxes_when_no_theme_concepts():
    basics = {"300124": {"name": "汇川技术", "mktcap_yi": 1800.0, "list_years": 13.0, "concepts": [], "is_st": False}}
    cands = [{"code": "300124", "name": "", "source": "llm"}]
    verified, rejected = apply_verify_rules(cands, basics, theme_concepts=[])
    assert {v["code"] for v in verified} == {"300124"}   # 无主题概念 → 不按概念筛(数据源降级时的回退)


def test_verify_skips_concept_filter_when_no_concept_data():
    # 数据源降级：所有候选 concepts 都为空 → 即使传 theme_concepts 也不按概念拒(缺数据不惩罚)
    basics = {
        "300124": {"name": "汇川技术", "mktcap_yi": 1800.0, "list_years": 13.0, "concepts": [], "is_st": False},
        "002472": {"name": "双环传动", "mktcap_yi": 300.0, "list_years": 10.0, "concepts": [], "is_st": False},
    }
    cands = [{"code": c, "name": "", "source": "llm"} for c in basics]
    verified, rejected = apply_verify_rules(cands, basics, theme_concepts=["人形机器人"])
    assert {v["code"] for v in verified} == {"300124", "002472"}   # 全留，不误拒
    assert rejected == []


def test_score_pool_percentile_and_redflag():
    pool = [
        {"code": "A", "fin_raw": 0.9, "pe_pct": 0.2, "amount_wan_avg": 5000, "vol": 0.3},
        {"code": "B", "fin_raw": 0.5, "pe_pct": 0.9, "amount_wan_avg": 200,  "vol": 0.6},  # 流动性差+贵
        {"code": "C", "fin_raw": 0.7, "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4},
    ]
    out = {r["code"]: r for r in score_pool(pool)}
    assert 0 <= out["A"]["total"] <= 1
    assert out["A"]["total"] > out["B"]["total"]
    assert "流动性差" in out["B"]["red_flags"]
    assert all("percentile" in v for v in out.values())


def test_score_fin_tracks_roe_loss_maker_ranks_low():
    # P1: fin_raw 现为真 ROE(%)。亏损股(负ROE)财务分应垫底,且与估值(pe_pct)解耦——
    # LOSS 虽最便宜(pe_pct最低),财务分仍应最低。
    pool = [
        {"code": "GOOD", "fin_raw": 25.0, "pe_pct": 0.9, "amount_wan_avg": 3000, "vol": 0.4},  # 高ROE但贵
        {"code": "MID",  "fin_raw": 8.0,  "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4},
        {"code": "LOSS", "fin_raw": -8.0, "pe_pct": 0.1, "amount_wan_avg": 3000, "vol": 0.4},  # 亏损但便宜
    ]
    out = {r["code"]: r for r in score_pool(pool)}
    assert out["GOOD"]["fin"] > out["MID"]["fin"] > out["LOSS"]["fin"]  # 财务分严格按ROE排
    assert out["LOSS"]["fin"] < 0.5                                     # 负ROE → 财务分低于中性


def test_score_growth_lifts_total():
    # A2: 其余维度相同,只差成长 → 高增长 grw 维度更高、total 更高
    pool = [
        {"code": "HG", "fin_raw": 10.0, "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4,
         "rev_growth": 40.0, "profit_growth": 50.0},
        {"code": "LG", "fin_raw": 10.0, "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4,
         "rev_growth": -10.0, "profit_growth": -20.0},
    ]
    out = {r["code"]: r for r in score_pool(pool)}
    assert out["HG"]["grw"] > out["LG"]["grw"]        # 成长维度按增速排
    assert out["HG"]["total"] > out["LG"]["total"]    # 高成长抬高综合分


def test_score_growth_absent_is_neutral():
    # 无成长字段(旧 pool) → grw 中性 0.5,不报错(向后兼容)
    pool = [{"code": "A", "fin_raw": 0.5, "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4}]
    out = score_pool(pool)
    assert out[0]["grw"] == 0.5


def test_score_warnflags_soft_not_hard():
    # A5两档: PE>150估值极端/年度ROE<0亏损 = 软警示(warn_flags),不进硬red_flags(不排除); 正常股双空; 缺字段不报错
    pool = [
        {"code": "PE", "fin_raw": 5, "pe_pct": 0.5, "amount_wan_avg": 5000, "vol": 0.4, "_pe": 300.0},
        {"code": "LOSS", "fin_raw": -5, "pe_pct": 0.5, "amount_wan_avg": 5000, "vol": 0.4, "roe_annual": -8.0},
        {"code": "OK", "fin_raw": 10, "pe_pct": 0.5, "amount_wan_avg": 5000, "vol": 0.4, "_pe": 30.0, "roe_annual": 15.0},
    ]
    out = {r["code"]: r for r in score_pool(pool)}
    assert "估值极端" in out["PE"]["warn_flags"] and out["PE"]["red_flags"] == []   # 软警示,不硬排除
    assert "亏损" in out["LOSS"]["warn_flags"] and out["LOSS"]["red_flags"] == []
    assert out["OK"]["warn_flags"] == [] and out["OK"]["red_flags"] == []


def test_build_basket_keeps_warnflag_stock():
    # 软警示股(亏损/估值极端)仍可入篮,只是带标注——不误伤未盈利潜力标的
    scored = [{"code": "A", "name": "A", "total": 0.9, "red_flags": [], "warn_flags": ["亏损"]},
              {"code": "B", "name": "B", "total": 0.8, "red_flags": [], "warn_flags": []}]
    b = build_basket(scored, amount_wan=2.0, n=4, single_cap=0.4)
    codes = {p["code"] for p in b["picks"]}
    assert "A" in codes                                            # 软警示不排除
    assert any(p["code"] == "A" and "亏损" in p["warn_flags"] for p in b["picks"])  # 带标注


def test_score_liquidity_floor_3000wan():
    # A4: 个股流动性线上调到 3000万 → 2500万触发流动性差,4000万不触发
    pool = [{"code": "L", "fin_raw": 5, "pe_pct": 0.5, "amount_wan_avg": 2500, "vol": 0.4},
            {"code": "H", "fin_raw": 5, "pe_pct": 0.5, "amount_wan_avg": 4000, "vol": 0.4}]
    out = {r["code"]: r for r in score_pool(pool)}
    assert "流动性差" in out["L"]["red_flags"]
    assert "流动性差" not in out["H"]["red_flags"]


def test_score_missing_field_no_nan():
    pool = [{"code": "A", "fin_raw": None, "pe_pct": None, "amount_wan_avg": None, "vol": None},
            {"code": "B", "fin_raw": 0.5, "pe_pct": 0.5, "amount_wan_avg": 3000, "vol": 0.4}]
    out = {r["code"]: r for r in score_pool(pool)}
    assert out["A"]["total"] == out["A"]["total"]   # 非 NaN


def test_satellite_raises_stock_rc():
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    rng = np.random.default_rng(0)
    base = pd.DataFrame({"stock": rng.normal(0, 0.01, 300), "bond": rng.normal(0, 0.002, 300),
                         "commodity": rng.normal(0, 0.008, 300)}, index=idx)
    # 个股与股票大类高度相关、且更高波动(高beta个股)——贴近现实
    sat = pd.DataFrame({"sat": base["stock"] * 1.6 + rng.normal(0, 0.012, 300)}, index=idx)
    w = {"stock": 0.37, "bond": 0.30, "commodity": 0.15}
    base_rc = stock_rc_with_satellite(base, w, sat_returns=None, sat_weight=0.0)
    with_sat = stock_rc_with_satellite(base, w, sat_returns=sat, sat_weight=0.03)
    assert with_sat["stock_rc"] >= base_rc["stock_rc"]   # 高beta个股并入抬高股票(含卫星)风险贡献
    assert "stock_rc" in with_sat and "pass" in with_sat


def test_build_basket_cap_and_size():
    scored = [{"code": f"{i}", "name": f"S{i}", "total": 1.0 - i*0.1, "red_flags": []} for i in range(6)]
    b = build_basket(scored, amount_wan=2.0, n=4, single_cap=0.4)
    assert len(b["picks"]) == 4
    allocs = [p["alloc_wan"] for p in b["picks"]]
    assert abs(sum(allocs) - 2.0) < 1e-6           # 4只等权25%<40%，金额守恒
    assert max(allocs) <= 2.0 * 0.4 + 1e-9


def test_build_basket_skips_redflag():
    scored = [{"code": "A", "name": "A", "total": 0.9, "red_flags": ["流动性差"]},
              {"code": "B", "name": "B", "total": 0.8, "red_flags": []},
              {"code": "C", "name": "C", "total": 0.7, "red_flags": []},
              {"code": "D", "name": "D", "total": 0.6, "red_flags": []},
              {"code": "E", "name": "E", "total": 0.5, "red_flags": []}]
    b = build_basket(scored, amount_wan=2.0, n=4, single_cap=0.4)
    assert "A" not in {p["code"] for p in b["picks"]}   # 红旗股不进篮子


def test_greedy_decorrelate_drops_high_corr_and_refills():
    # B 与 A 高相关(0.92≥0.8,同质)→剔B,从候选池补 C、D 凑满 n=3
    scored = [{"code": "A", "total": 0.9, "red_flags": []}, {"code": "B", "total": 0.8, "red_flags": []},
              {"code": "C", "total": 0.7, "red_flags": []}, {"code": "D", "total": 0.6, "red_flags": []}]
    corr = {"A": {"A": 1.0, "B": 0.92, "C": 0.1, "D": 0.2}, "B": {"A": 0.92, "B": 1.0, "C": 0.15, "D": 0.1},
            "C": {"A": 0.1, "B": 0.15, "C": 1.0, "D": 0.0}, "D": {"A": 0.2, "B": 0.1, "C": 0.0, "D": 1.0}}
    res = greedy_decorrelate(scored, corr, n=3, rho_threshold=0.8)
    assert [p["code"] for p in res["picks"]] == ["A", "C", "D"]      # B 被去同质,补位凑满3只
    assert res["dropped"][0]["code"] == "B" and res["dropped"][0]["conflict_with"] == "A"


def test_greedy_decorrelate_segment_cap():
    # F: 同环节≤1 → 同"光模块"的 B 被剔(纯靠环节,相关性放宽到0.9不触发),PCB 的 C 保留补位
    scored = [{"code": "A", "total": 0.9, "red_flags": [], "segment": "光模块"},
              {"code": "B", "total": 0.8, "red_flags": [], "segment": "光模块"},
              {"code": "C", "total": 0.7, "red_flags": [], "segment": "PCB"}]
    corr = {c: {c2: (1.0 if c == c2 else 0.0) for c2 in "ABC"} for c in "ABC"}
    res = greedy_decorrelate(scored, corr, n=3, rho_threshold=0.9, max_per_segment=1)
    assert [p["code"] for p in res["picks"]] == ["A", "C"]          # 同环节只留一只,跨环节保留
    assert res["dropped"][0]["code"] == "B" and res["dropped"][0]["segment"] == "光模块"


class _FakeSource(DataSource):
    """B 缓存测试用:计数调用次数,其余桩。basics 永远返回 None(模拟瞬时失败)。"""
    def __init__(self): self.calls = 0; self.basics_calls = 0
    def list_boards(self): return []
    def board_constituents(self, board): return []
    def basics(self, code): self.basics_calls += 1; return None
    def daily_returns(self, code, lookback=504):
        self.calls += 1
        return pd.Series([0.01, -0.02, 0.03])
    def valuation(self, code): return {"pe": float("nan"), "pb": float("nan")}
    def liquidity(self, code): return {"amount_wan_avg": None}
    def financials(self, code): return {"roe_annual": None}


def test_cached_source_reuses(tmp_path):
    # B: 第二次取同一只走缓存,不再打到 inner
    fake = _FakeSource()
    c = CachedSource(fake, cache_dir=str(tmp_path), ttl=1000)
    a = c.daily_returns("X")
    b = c.daily_returns("X")
    assert fake.calls == 1                       # 命中缓存,inner 只被调一次
    assert list(a) == list(b)


def test_cached_source_skips_empty_result(tmp_path):
    # B 修复: 空/失败结果(None)不缓存,下次仍重试(防瞬时失败毒化缓存,曾致 verify 全判查无)
    fake = _FakeSource()
    c = CachedSource(fake, cache_dir=str(tmp_path), ttl=1000)
    c.basics("X")
    c.basics("X")
    assert fake.basics_calls == 2                 # None 未缓存,两次都打到 inner


def test_greedy_decorrelate_keeps_negative_corr():
    # 高负相关=对冲,应保留(不是冗余押注)
    scored = [{"code": "A", "total": 0.9, "red_flags": []}, {"code": "B", "total": 0.8, "red_flags": []}]
    corr = {"A": {"A": 1.0, "B": -0.9}, "B": {"A": -0.9, "B": 1.0}}
    res = greedy_decorrelate(scored, corr, n=2, rho_threshold=0.8)
    assert [p["code"] for p in res["picks"]] == ["A", "B"]           # 负相关不剔


def test_greedy_decorrelate_missing_corr_not_dropped():
    # 缺该对相关数据(None)→视为不冲突,不惩罚(缺数据降级回退)
    scored = [{"code": "A", "total": 0.9, "red_flags": []}, {"code": "B", "total": 0.8, "red_flags": []}]
    corr = {"A": {"A": 1.0}, "B": {"B": 1.0}}                        # 无 A-B 项
    res = greedy_decorrelate(scored, corr, n=2, rho_threshold=0.8)
    assert len(res["picks"]) == 2


def test_build_basket_cap_binds_small_basket():
    scored = [{"code": "A", "name": "A", "total": 0.9, "red_flags": []},
              {"code": "B", "name": "B", "total": 0.8, "red_flags": []}]
    b = build_basket(scored, amount_wan=2.0, n=4, single_cap=0.4)   # 仅2只→等权50%>40%上限
    assert all(p["alloc_wan"] <= 2.0 * 0.4 + 1e-9 for p in b["picks"])
    assert b["used_wan"] < 2.0 and b["note"]            # 触发上限，余量未分配+提示
