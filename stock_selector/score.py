"""同类百分位打分(同主题候选池内)+红旗避雷。延续选基模块同类百分位 + 淘汰器 fillna(0.5) 防 nan。
铁律: 历史裸收益排名只用于避雷,不用于追星(Carhart)——本层不把裸收益计入 total。"""
from __future__ import annotations

import pandas as pd

# 质量大类(fin+grw)=0.35 内拆 ROE水平/成长趋势。A3(2026-06-17)经单因子IC抽查校验:
# 维持质量倾斜的原则权重,刻意不照搬 IC(2024-25 IC 偏向高波/主题股,与系统降风险使命冲突;小样本易过拟合)。详见 PROBE.md。
WEIGHTS = {"fin": 0.20, "grw": 0.15, "val": 0.25, "liq": 0.20, "risk": 0.20}  # ROE/成长/估值/流动性/风险
# A4: 1000万借自ETF散户规则,对个股太低(几乎全过)→个股口径上调3000万(微盘/流动性差风险线)。
# 全市场成交额分位精校属可选后续(警示红旗,低风险,不为它再跑全市场)。
AMOUNT_FLOOR_WAN = 3000.0   # 日均成交额 < 3000万 → 流动性差红旗(个股口径)
# 红旗两档:硬红旗(red_flags)→basket/去相关自动排除;软警示(warn_flags)→保留入篮,仅标注供人工review。
# 流动性差/微盘=真不可投→硬;估值极端/亏损=卫星仓高风险博弈常态(未盈利潜力股/暂亏反转)→软,避免误伤。
PE_EXTREME = 150.0          # A5: PE > 此值 → 估值极端(软警示,人工可调)


def _pr(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").rank(pct=True).fillna(0.5)


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """取列;缺列→全 None Series(经 _pr fillna 中性 0.5,向后兼容旧 pool)。"""
    return df[name] if name in df.columns else pd.Series([None] * len(df), index=df.index)


def score_pool(pool: list[dict]) -> list[dict]:
    """pool 每项需含 fin_raw / pe_pct / amount_wan_avg / vol(缺失→fillna中性)。出 total 降序清单。"""
    if not pool:
        return []
    df = pd.DataFrame(pool)
    fin = _pr(df["fin_raw"])                       # 财务质量=年度ROE同类百分位(越高越好;负ROE→垫底)
    grw = (_pr(_col(df, "rev_growth")) + _pr(_col(df, "profit_growth"))) / 2  # 成长=营收+净利增速百分位均值
    val = 1 - _pr(df["pe_pct"])                    # PE 行业分位越低越好 → 反向
    liq = _pr(df["amount_wan_avg"])                # 流动性越高越好
    risk = 1 - _pr(df["vol"])                      # 波动越低越好 → 反向
    total = (WEIGHTS["fin"]*fin + WEIGHTS["grw"]*grw + WEIGHTS["val"]*val
             + WEIGHTS["liq"]*liq + WEIGHTS["risk"]*risk)
    tpr = total.rank(pct=True)
    out = []
    for i in range(len(df)):
        red_flags = list(pool[i].get("red_flags", []) or [])      # 硬:排除
        warn_flags = list(pool[i].get("warn_flags", []) or [])    # 软:仅标注
        amt = pd.to_numeric(pd.Series([pool[i].get("amount_wan_avg")]), errors="coerce").iloc[0]
        if pd.notna(amt) and amt < AMOUNT_FLOOR_WAN and "流动性差" not in red_flags:
            red_flags.append("流动性差")                          # 硬红旗:真不可投/微盘
        pe = pd.to_numeric(pd.Series([pool[i].get("_pe")]), errors="coerce").iloc[0]
        if pd.notna(pe) and pe > PE_EXTREME and "估值极端" not in warn_flags:
            warn_flags.append("估值极端")                         # 软警示:不排除,人工review
        roe = pd.to_numeric(pd.Series([pool[i].get("roe_annual")]), errors="coerce").iloc[0]
        if pd.notna(roe) and roe < 0 and "亏损" not in warn_flags:
            warn_flags.append("亏损")                             # 软警示:未盈利潜力股不误伤
        out.append({**pool[i], "fin": round(float(fin.iloc[i]), 3), "grw": round(float(grw.iloc[i]), 3),
                    "val": round(float(val.iloc[i]), 3), "liq": round(float(liq.iloc[i]), 3),
                    "risk": round(float(risk.iloc[i]), 3), "percentile": round(float(tpr.iloc[i]), 3),
                    "red_flags": red_flags, "warn_flags": warn_flags, "total": round(float(total.iloc[i]), 3)})
    out.sort(key=lambda x: -x["total"])
    return out
