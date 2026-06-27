"""工具桥 CLI：Claude 经 Bash 调用，出确定性 JSON。
用法(工作目录 macro-allocation/，前缀 PYTHONIOENCODING=utf-8 py -3.13 -m uv run python -m stock_selector):
  recall  --theme 人形机器人 [--boards 人形机器人,减速器] [--llm 300124,688017]
  verify  --codes 300124,002472 [--theme-concepts 人形机器人]
  score   --codes 300124,002472
  basket  --codes 300124,002472 --amount 1.5 [--n 4 --cap 0.4] --total 50 [--segments 300124:机器人,002472:减速器]
  select  --codes ... --amount 1.5 --total 50 [--theme-concepts ..][--segments ..]  # 一站式 verify→score→去相关→basket→风险
通用：--market a|us(默认 a;us 需装可选依赖:`uv run --extra us ...`)、--no-cache 关闭磁盘缓存(默认开;.cache/ 不入库)。
铁律：所有数据走 Python 工具(守"不靠名字靠数据")；输出是建议、需人工 review。
"""
from __future__ import annotations

import argparse
import json
import sys

from stock_selector.datasource import AshareSource
from stock_selector.cache import CachedSource
from stock_selector import recall, verify, score, enrich, basket


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _parse_segments(s: str) -> dict:
    return {c.strip(): seg.strip() for kv in s.split(",") if ":" in kv
            for c, seg in [kv.split(":", 1)]}


def _make_basket(scored, src, amount, n, cap, total, segments):
    """共用：去相关(可环节感知)→ basket → 风险并入。"""
    sel = basket.select_decorrelated(scored, src, n=n, segments=segments or None)
    b = basket.build_basket(sel["picks"], amount_wan=amount, n=n, single_cap=cap)
    b["decorrelation"] = {"threshold": sel["threshold"], "dropped": sel["dropped"],
                          "degraded": sel["degraded"], "segment_mode": sel.get("segment_mode", False)}
    b["risk_check"] = basket.check_basket_risk(b["picks"], amount, src, total)
    return b


def _make_source(market: str, no_cache: bool):
    if market == "us":
        from stock_selector.datasource_us import UsSource   # 延迟导入,A 股路径不需 yfinance
        base = UsSource()
    else:
        base = AshareSource()
    return base if no_cache else CachedSource(base)


def main(argv=None):
    p = argparse.ArgumentParser(prog="stock_selector")
    p.add_argument("--market", choices=["a", "us"], default="a", help="a=A股(默认) us=美股(需--with yfinance)")
    p.add_argument("--no-cache", action="store_true", help="关闭磁盘缓存(默认开)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("recall")
    pr.add_argument("--theme"); pr.add_argument("--boards", default=""); pr.add_argument("--llm", default="")
    pv = sub.add_parser("verify")
    pv.add_argument("--codes", required=True); pv.add_argument("--theme-concepts", default="")
    ps = sub.add_parser("score"); ps.add_argument("--codes", required=True)
    pb = sub.add_parser("basket")
    pb.add_argument("--codes", required=True); pb.add_argument("--amount", type=float, required=True)
    pb.add_argument("--n", type=int, default=4); pb.add_argument("--cap", type=float, default=0.4)
    pb.add_argument("--total", type=float, required=True); pb.add_argument("--segments", default="")
    pse = sub.add_parser("select")   # C: 一站式 verify→score→去相关→basket→风险
    pse.add_argument("--codes", required=True); pse.add_argument("--theme", default="")
    pse.add_argument("--theme-concepts", default=""); pse.add_argument("--segments", default="")
    pse.add_argument("--amount", type=float, required=True); pse.add_argument("--total", type=float, required=True)
    pse.add_argument("--n", type=int, default=4); pse.add_argument("--cap", type=float, default=0.4)
    a = p.parse_args(argv)
    src = _make_source(a.market, a.no_cache)

    if a.cmd == "recall":
        boards = [b for b in a.boards.split(",") if b]
        llm = [{"code": c, "name": ""} for c in a.llm.split(",") if c]
        board_c = recall.build_board_candidates(boards, src) if boards else []
        _emit({"theme": a.theme, "board_recall_n": len(board_c),
               "candidates": recall.merge_candidates(llm, board_c)})
    elif a.cmd == "verify":
        cands = [{"code": c, "name": "", "source": "llm"} for c in a.codes.split(",") if c]
        tc = [t for t in a.theme_concepts.split(",") if t]
        v, r = verify.verify_candidates(cands, src, tc)
        _emit({"verified": v, "rejected": r})
    elif a.cmd == "score":
        cands = [{"code": c, "name": "", "source": "llm", "flags": []} for c in a.codes.split(",") if c]
        _emit({"scored": score.score_pool(enrich.enrich(cands, src))})
    elif a.cmd == "basket":
        codes = [c for c in a.codes.split(",") if c]
        cands = enrich.enrich([{"code": c, "name": "", "source": "llm", "flags": []} for c in codes], src)
        scored = score.score_pool(cands)
        _emit(_make_basket(scored, src, a.amount, a.n, a.cap, a.total, _parse_segments(a.segments)))
    elif a.cmd == "select":
        codes = [c for c in a.codes.split(",") if c]
        tc = [t for t in a.theme_concepts.split(",") if t]
        verified, rejected = verify.verify_candidates(
            [{"code": c, "name": "", "source": "llm"} for c in codes], src, tc)
        scored = score.score_pool(enrich.enrich(verified, src))
        b = _make_basket(scored, src, a.amount, a.n, a.cap, a.total, _parse_segments(a.segments))
        _emit({"theme": a.theme, "verified_n": len(verified), "rejected": rejected,
               "scored": scored, "basket": b})


if __name__ == "__main__":
    main(sys.argv[1:])
