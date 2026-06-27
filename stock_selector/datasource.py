"""数据源抽象：A股用确认可用的源(见 PROBE.md)，美股(yfinance)后扩只加适配器，上层工具零改动。
所有方法出"纯结构"(dict/Series/list)，不含任何选股判断逻辑。

A股 AshareSource 采用的源(因 akshare 东财 _em 封装在本环境不可用):
  - 名称/ST  : 新浪实时 hq.sinajs.cn
  - 收益/流动性: ak.stock_zh_a_daily(新浪)
  - 估值/市值 : ak.stock_value_em(datacenter)
  - 概念列表  : ak.stock_board_concept_name_ths(同花顺)
  - 概念成分  : best-effort 直连 push2(失败则跳过，仅用 LLM 点名)
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from datetime import date
from urllib.parse import quote

import akshare as ak
import pandas as pd
import requests

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}
_TODAY = date(2026, 6, 15)


def _with_timeout(fn, timeout_s: float, default):
    """在 daemon 线程里跑可能挂死的网络调用：超时即返回 default(优雅降级，不阻塞整批)。
    akshare 的东财 _em 封装无超时控制，单只挂死会拖垮整批；daemon 线程超时后被进程退出时丢弃，不卡退出。"""
    box = {"v": default}

    def _run():
        try:
            box["v"] = fn()
        except Exception:
            pass

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout_s)
    return box["v"]


class DataSource(ABC):
    @abstractmethod
    def list_boards(self) -> list[str]: ...
    @abstractmethod
    def board_constituents(self, board: str) -> list[dict]: ...   # [{code,name,board}]
    @abstractmethod
    def basics(self, code: str) -> dict | None: ...               # {name,mktcap_yi,list_years,concepts,is_st}
    @abstractmethod
    def daily_returns(self, code: str, lookback: int = 504) -> pd.Series: ...
    @abstractmethod
    def valuation(self, code: str) -> dict: ...                   # {pe,pb}
    @abstractmethod
    def liquidity(self, code: str) -> dict: ...                   # {amount_wan_avg}
    @abstractmethod
    def financials(self, code: str) -> dict: ...                  # 财务比率主干 {roe_annual,roe_latest,...}


def _sina_symbol(code: str) -> str:
    """A股代码 → 新浪前缀。6/9→sh, 688→sh, 0/3→sz, 4/8(北交)→bj。"""
    c = str(code).zfill(6)
    if c[0] in "69":
        return "sh" + c
    if c[0] in "03":
        return "sz" + c
    return "bj" + c


class AshareSource(DataSource):
    """A股实现。接口取舍见 stock_selector/PROBE.md。"""

    def __init__(self):
        self._sess = requests.Session()
        self._sess.headers.update(_UA)

    # ---- 概念板块（同花顺列表 + best-effort 东财成分） ----
    def list_boards(self) -> list[str]:
        """best-effort：同花顺概念列表在本环境间歇可用，失败返回 []（腿2 降级为仅 LLM 点名）。"""
        try:
            df = ak.stock_board_concept_name_ths()
        except Exception as e:
            print(f"[datasource] 概念板块列表暂不可用({type(e).__name__})，腿2 降级为仅 LLM 点名")
            return []
        col = "name" if "name" in df.columns else df.columns[0]
        return df[col].astype(str).tolist()

    def _em_push2(self, fs: str, fields: str, pz: int = 100, retries: int = 2):
        url = (f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz={pz}&po=1&fid=f3"
               f"&fs={quote(fs, safe=':')}&fields={fields}")
        for _ in range(retries):
            try:
                j = self._sess.get(url, timeout=12).json()
                return (j.get("data") or {}).get("diff") or []
            except Exception:
                time.sleep(1.0)
        return None

    def board_constituents(self, board: str) -> list[dict]:
        """best-effort：经东财 push2 取概念成分；本环境板块列表常不稳 → 失败返回 []，调用方应优雅降级。"""
        boards = self._em_push2("m:90 t:3", "f12,f14", pz=400)
        if not boards:
            print(f"[datasource] 概念成分兜底不可用(东财push2受限)，跳过板块「{board}」，仅用 LLM 点名")
            return []
        match = [b for b in boards if board in b.get("f14", "") or b.get("f14", "") in board]
        if not match:
            return []
        bk = match[0]["f12"]
        cons = self._em_push2(f"b:{bk}", "f12,f14", pz=300)
        if not cons:
            return []
        return [{"code": str(c["f12"]), "name": str(c["f14"]), "board": board} for c in cons]

    # ---- 个股基本面（新浪实时名称 + 新浪日线上市年限 + value_em 市值） ----
    def basics(self, code: str) -> dict | None:
        name = self._sina_name(code)
        if not name:
            return None
        try:
            d = ak.stock_zh_a_daily(symbol=_sina_symbol(code))
            first = pd.to_datetime(d["date"]).min().date()
            list_years = round((_TODAY - first).days / 365.0, 1)
        except Exception:
            list_years = None         # 取数失败=未知(非0),verify 不据此误拒(缺数据不惩罚)
        try:
            mktcap_yi = round(self._value_last(code).get("总市值", 0) / 1e8, 1)
        except Exception:
            mktcap_yi = None
        return {"name": name, "mktcap_yi": mktcap_yi, "list_years": list_years,
                "concepts": [], "is_st": ("ST" in name)}

    def _sina_name(self, code: str) -> str | None:
        try:
            r = self._sess.get(f"https://hq.sinajs.cn/list={_sina_symbol(code)}",
                               headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
            r.encoding = "gbk"
            if '="' not in r.text:
                return None
            payload = r.text.split('="', 1)[1].split('"')[0]
            name = payload.split(",")[0].strip()
            return name or None
        except Exception:
            return None

    # ---- 估值 / 流动性 / 收益 ----
    def _value_last(self, code: str) -> dict:
        # 东财 value_em 无超时、本环境间歇挂死 → 8s 守门，超时降级为空 dict(上层取不到 PE/市值 → 中性兜底)
        def _fetch():
            df = ak.stock_value_em(symbol=str(code).zfill(6))
            return df.iloc[-1].to_dict()

        return _with_timeout(_fetch, 8.0, {})

    def valuation(self, code: str) -> dict:
        try:
            row = self._value_last(code)
            pe = row.get("PE(TTM)")
            pb = row.get("市净率")
            return {"pe": float(pe) if pe not in (None, "") else float("nan"),
                    "pb": float(pb) if pb not in (None, "") else float("nan")}
        except Exception:
            return {"pe": float("nan"), "pb": float("nan")}

    def daily_returns(self, code: str, lookback: int = 504) -> pd.Series:
        d = ak.stock_zh_a_daily(symbol=_sina_symbol(code))
        s = d.set_index(pd.to_datetime(d["date"]))["close"].astype(float).pct_change().dropna()
        return s.iloc[-lookback:]

    def liquidity(self, code: str) -> dict:
        d = ak.stock_zh_a_daily(symbol=_sina_symbol(code)).tail(60)
        amt_wan = float(pd.to_numeric(d["amount"], errors="coerce").mean()) / 1e4  # 新浪 amount 单位元
        return {"amount_wan_avg": round(amt_wan, 1)}

    # ---- 财务比率主干（新浪 stock_financial_analysis_indicator，86字段，见 PROBE.md）----
    # 一站覆盖 ROE/成长/偿债/现金流/营运，后续加指标只从同一行多读一列，不换源(避免返工)。
    def financials(self, code: str) -> dict:
        """取 加权净资产收益率(ROE)，年度口径(最近12-31年报)+最新一期都留。
        超时/缺失 → None(上层 fillna 中性兜底，不污染打分)。"""
        def _fetch():
            return ak.stock_financial_analysis_indicator(
                symbol=str(code).zfill(6), start_year=str(_TODAY.year - 2))

        df = _with_timeout(_fetch, 15.0, None)
        empty = {"roe_annual": None, "roe_latest": None, "rev_growth": None, "profit_growth": None,
                 "report_annual": None, "report_latest": None}
        if df is None or len(df) == 0:
            return empty
        roe_col = next((c for c in ("加权净资产收益率(%)", "净资产收益率(%)") if c in df.columns), None)
        dcol = "日期" if "日期" in df.columns else df.columns[0]
        d = df.copy()
        d["_dt"] = pd.to_datetime(d[dcol], errors="coerce")
        d = d.dropna(subset=["_dt"]).sort_values("_dt")
        if d.empty:
            return empty

        def _num(row, col) -> float | None:
            if not col or col not in df.columns:
                return None
            v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
            return float(v) if v == v else None

        latest = d.iloc[-1]
        annual_rows = d[(d["_dt"].dt.month == 12) & (d["_dt"].dt.day == 31)]
        annual = annual_rows.iloc[-1] if len(annual_rows) else latest  # 无年报则退最新一期
        return {"roe_annual": _num(annual, roe_col), "roe_latest": _num(latest, roe_col),
                "rev_growth": _num(annual, "主营业务收入增长率(%)"),     # 成长(年度,与ROE同源同行)
                "profit_growth": _num(annual, "净利润增长率(%)"),
                "report_annual": str(annual["_dt"].date()), "report_latest": str(latest["_dt"].date())}
