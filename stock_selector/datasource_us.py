"""美股数据源(yfinance)。DataSource 的 US 适配——四个上层工具(verify/score/basket/风险)零改动即可跑美股。
需运行时 `--with yfinance`(非默认依赖);Yahoo 在本环境可达(见 PROBE)。
yfinance `.info` 一站给齐:PE/PB/市值/ROE/营收增速/利润增速/成交量;`.history` 出日收益。
概念板块(腿2)美股无对应 → 返回空,发现层全靠 Claude 产业链点名。
口径对齐 A 股:ROE/增速转成 %(yfinance 返回小数);估值/流动性单位为美元(仅池内相对排序,不跨市场混池)。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .datasource import DataSource, _with_timeout

_TODAY = date(2026, 6, 17)


def _pct(x):
    """yfinance 比率(小数)→ %,对齐 A 股财务字段口径。"""
    return float(x) * 100 if (x is not None and x == x) else None


def _num(x):
    return float(x) if (x is not None and x != "" and x == x) else float("nan")


class UsSource(DataSource):
    """美股实现。.info 取一次缓存到实例(basics/valuation/liquidity/financials 共用);外层再套 CachedSource 落盘。"""

    def __init__(self):
        import yfinance as yf  # 延迟导入:A 股路径无需安装 yfinance
        self._yf = yf
        self._info_cache: dict = {}

    def _info(self, code: str) -> dict:
        if code not in self._info_cache:
            self._info_cache[code] = _with_timeout(lambda: self._yf.Ticker(code).info, 25.0, {}) or {}
        return self._info_cache[code]

    # 美股无东财式概念板块 → 腿2 留空,发现靠 Claude 点名
    def list_boards(self) -> list[str]:
        return []

    def board_constituents(self, board: str) -> list[dict]:
        return []

    def basics(self, code: str) -> dict | None:
        info = self._info(code)
        name = info.get("longName") or info.get("shortName")
        if not name:
            return None
        ly = None
        ep = info.get("firstTradeDateEpochUtc")
        if ep:
            try:
                ly = round((_TODAY - date.fromtimestamp(int(ep))).days / 365.0, 1)
            except Exception:
                ly = None
        mc = info.get("marketCap")
        return {"name": name, "mktcap_yi": round(mc / 1e8, 1) if mc else None,
                "list_years": ly, "concepts": [], "is_st": False}

    def daily_returns(self, code: str, lookback: int = 504) -> pd.Series:
        period = "3y" if lookback > 252 else "2y"

        def _f():
            h = self._yf.Ticker(code).history(period=period)
            s = h["Close"].astype(float).pct_change().dropna()
            if getattr(s.index, "tz", None) is not None:   # yfinance 索引带时区 → 去 tz 对齐 A 股(tz-naive),否则风险并入拼接报错
                s.index = s.index.tz_localize(None)
            return s

        s = _with_timeout(_f, 25.0, pd.Series(dtype=float))
        return s.iloc[-lookback:]

    def valuation(self, code: str) -> dict:
        info = self._info(code)
        return {"pe": _num(info.get("trailingPE")), "pb": _num(info.get("priceToBook"))}

    def liquidity(self, code: str) -> dict:
        info = self._info(code)
        vol = info.get("averageVolume")
        px = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        amt = (vol * px / 1e4) if (vol and px) else None   # 万美元(仅池内相对)
        return {"amount_wan_avg": round(amt, 1) if amt else None}

    def financials(self, code: str) -> dict:
        info = self._info(code)
        roe = _pct(info.get("returnOnEquity"))
        return {"roe_annual": roe, "roe_latest": roe,                # yfinance 只给 TTM,两口径同值
                "rev_growth": _pct(info.get("revenueGrowth")),
                "profit_growth": _pct(info.get("earningsGrowth")),
                "report_annual": "ttm", "report_latest": "ttm"}
