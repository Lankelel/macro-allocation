from holdings_screener.screener import _composite_scores, _mark_bottom, _protect_reason


def test_composite_scores_ranks_within_group():
    # 三只同类基金：A 最优(高夏普/低回撤/低波/低费)，C 最差
    group = [
        {"code": "A", "sharpe": 1.5, "max_drawdown": -0.10, "vol": 0.12, "ann_ret": 0.15, "buy_fee_pct": 0.1, "rating_low": False},
        {"code": "B", "sharpe": 0.8, "max_drawdown": -0.20, "vol": 0.18, "ann_ret": 0.10, "buy_fee_pct": 0.5, "rating_low": False},
        {"code": "C", "sharpe": 0.2, "max_drawdown": -0.35, "vol": 0.28, "ann_ret": 0.03, "buy_fee_pct": 1.2, "rating_low": False},
    ]
    scored = _composite_scores(group)
    by = {f["code"]: f["score"] for f in scored}
    assert by["A"] > by["B"] > by["C"]          # 排序正确
    assert 0 <= by["C"] <= 100 and 0 <= by["A"] <= 100


def test_composite_scores_rating_low_penalized():
    group = [
        {"code": "A", "sharpe": 1.0, "max_drawdown": -0.15, "vol": 0.15, "ann_ret": 0.10, "buy_fee_pct": 0.3, "rating_low": False},
        {"code": "B", "sharpe": 1.0, "max_drawdown": -0.15, "vol": 0.15, "ann_ret": 0.10, "buy_fee_pct": 0.3, "rating_low": True},
    ]
    by = {f["code"]: f["score"] for f in _composite_scores(group)}
    assert by["B"] < by["A"]                     # 同指标下，避雷的分更低


def test_mark_bottom_floor_and_min_group():
    scored = [{"code": c, "score": s} for c, s in
              [("A", 90), ("B", 70), ("C", 50), ("D", 30), ("E", 10)]]
    # 5 只 × 20% = 1 只 → 只标最末 E
    elim = _mark_bottom(scored, pct=20, min_group=5)
    assert [f["code"] for f in elim] == ["E"]


def test_mark_bottom_skips_small_group():
    scored = [{"code": c, "score": s} for c, s in [("A", 90), ("B", 10)]]
    assert _mark_bottom(scored, pct=20, min_group=5) == []   # 组内<5 不淘汰


def test_protect_recently_bought():
    assert _protect_reason({"name": "招商招悦纯债A ⬆️ 已加仓", "sharpe": 1.0}) == "刚买入"
    assert _protect_reason({"name": "XX新建仓", "sharpe": 1.0}) == "刚买入"


def test_protect_no_metrics():
    assert _protect_reason({"name": "次新基金", "sharpe": None}) == "数据不足"


def test_protect_none_for_normal():
    assert _protect_reason({"name": "易方达沪深300", "sharpe": 0.8}) is None


def test_protect_prescription_locked():
    # 处方锁定标的(低波替换目标/黄金)即便质量分低也不淘汰
    locked = {"007751", "513400", "002610"}
    assert _protect_reason({"code": "007751", "name": "景顺长城沪港深红利低波", "sharpe": 0.3}, locked) == "处方锁定"
    assert _protect_reason({"code": "888888", "name": "某基金", "sharpe": 0.3}, locked) is None  # 不在锁定集→正常评


def test_composite_scores_missing_fee_no_nan():
    # 真实持仓无费率字段(全 None)→ 分数不应为 nan，且仍按其余指标排序
    group = [
        {"code": "A", "sharpe": 1.5, "max_drawdown": -0.10, "vol": 0.12, "ann_ret": 0.15, "buy_fee_pct": None, "rating_low": False},
        {"code": "B", "sharpe": 0.3, "max_drawdown": -0.30, "vol": 0.25, "ann_ret": 0.05, "buy_fee_pct": None, "rating_low": False},
    ]
    by = {f["code"]: f["score"] for f in _composite_scores(group)}
    assert by["A"] == by["A"] and by["B"] == by["B"]   # 非 nan(nan!=nan)
    assert by["A"] > by["B"]
