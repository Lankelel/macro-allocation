"""把 verified 候选补齐 score 所需字段：fin_raw / pe_pct / amount_wan_avg / vol。
fin_raw = 真 ROE(加权净资产收益率, 年度口径)，来自财务比率主干 source.financials(见 datasource)。
  P1: 已弃用 1/PE 占位 → 解除 PE 双算(fin 与 val 不再同源)；亏损股(负ROE)财务分自然垫底。
缺失一律 None → score 的 fillna(0.5) 兜底，不 nan 污染。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd


def _progress(stage: str, i: int, n: int, code: str) -> None:
    """逐只进度 → stderr(不污染 stdout 的 JSON)。供外部 grep 计数估算完成百分比。"""
    print(f"[progress] {stage} {i}/{n} ({round(i / n * 100)}%) {code}", file=sys.stderr, flush=True)


def enrich(verified: list[dict], source) -> list[dict]:
    """source: DataSource。逐只取估值/收益/流动性，pe 在池内取行业近似分位(pe_pct)。"""
    n = len(verified)
    pes = []
    for i, c in enumerate(verified, 1):
        try:
            c["_pe"] = source.valuation(c["code"]).get("pe")
        except Exception:
            c["_pe"] = float("nan")
        pes.append(c["_pe"])
        _progress("valuation", i, n, c["code"])
    pe_pct = pd.to_numeric(pd.Series(pes), errors="coerce").rank(pct=True).fillna(0.5).tolist()
    for i, c in enumerate(verified):
        try:
            ret = source.daily_returns(c["code"], lookback=252)
            c["vol"] = float(ret.std() * np.sqrt(252)) if len(ret) > 30 else None
        except Exception:
            c["vol"] = None
        try:
            c["amount_wan_avg"] = source.liquidity(c["code"]).get("amount_wan_avg")
        except Exception:
            c["amount_wan_avg"] = None
        c["pe_pct"] = pe_pct[i]
        try:                                          # 财务主干一次调用,ROE+成长同源取出(后续指标继续复用)
            f = source.financials(c["code"])
            c["roe_annual"] = f.get("roe_annual")
            c["roe_latest"] = f.get("roe_latest")
            c["roe_report"] = f.get("report_annual")
            c["rev_growth"] = f.get("rev_growth")      # 营收增速(年度)
            c["profit_growth"] = f.get("profit_growth")  # 净利润增速(年度)
        except Exception:
            c["roe_annual"] = c["roe_latest"] = c["roe_report"] = None
            c["rev_growth"] = c["profit_growth"] = None
        c["fin_raw"] = c["roe_annual"]                 # 打分用年度口径(用户定); 缺失→score fillna 中性
        _progress("ret+liq", i + 1, n, c["code"])
    return verified
