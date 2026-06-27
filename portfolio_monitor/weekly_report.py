"""每周持仓涨跌报告（手动验证版）。

口径：
- 取每只基金的「最新可得净值」与「约 7 自然日前同口径净值」，按净值日期对齐算周涨跌幅
  （不锁死日历周五；QDII 因 T+2+海外时区，最新净值常滞后到周三/周四，已逐只标注净值日期）。
- 组合周涨跌幅 = 各「有市价」基金按记录市值(amount_w)加权平均。
- 保险/养老金/现金/高风险无市价 → 不计涨跌，仅作总资产背景列出。

数据源：akshare（免费）。场外/联接走 fund_open_fund_info_em；场内 ETF 走 fund_etf_fund_info_em。
运行：PYTHONIOENCODING=utf-8 py -3.13 -m uv run python -m portfolio_monitor.weekly_report
（工作目录：macro-allocation/）
"""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path

import akshare as ak

HERE = Path(__file__).resolve().parent
CFG = HERE / "holdings.json"
WINDOW_DAYS = 7          # 周涨跌幅回看窗口（自然日）
LOOKBACK_FETCH = 25      # 拉多少天净值以覆盖窗口（含节假日缓冲）


def _nav_series(h: dict) -> list[tuple[dt.date, float]]:
    """返回 [(净值日期, 单位净值), ...] 升序；失败返回 []。"""
    code = h["code"]
    today = dt.date.today()
    start = (today - dt.timedelta(days=LOOKBACK_FETCH)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    def _from_open():
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        return [(r["净值日期"], float(r["单位净值"]))
                for _, r in df.iterrows() if r.get("单位净值") not in (None, "")]

    def _from_etf():
        df = ak.fund_etf_fund_info_em(fund=code, start_date=start, end_date=end)
        out = []
        for _, r in df.iterrows():
            d, v = r.get("净值日期"), r.get("单位净值")
            if d is None or v is None or (isinstance(v, float) and v != v):  # NaN
                continue
            out.append((d, float(v)))
        return out

    order = (_from_etf, _from_open) if h.get("etf") else (_from_open, _from_etf)
    for fn in order:
        try:
            ser = fn()
            if ser:
                # 统一日期为 date 对象
                norm = []
                for d, v in ser:
                    if isinstance(d, str):
                        d = dt.datetime.strptime(d[:10], "%Y-%m-%d").date()
                    elif isinstance(d, dt.datetime):
                        d = d.date()
                    norm.append((d, v))
                norm.sort(key=lambda x: x[0])
                return norm
        except Exception:
            continue
    return []


def _weekly_return(ser: list[tuple[dt.date, float]]):
    """返回 (周涨跌幅%, 最新日期, 最新净值, 对照日期, 对照净值) 或 None。"""
    if len(ser) < 2:
        return None
    last_d, last_v = ser[-1]
    target = last_d - dt.timedelta(days=WINDOW_DAYS)
    # 取 <= target 的最近一条；若没有则取最早一条
    prev = None
    for d, v in ser:
        if d <= target:
            prev = (d, v)
    if prev is None:
        prev = ser[0]
    pd_, pv = prev
    if pv == 0:
        return None
    ret = (last_v / pv - 1) * 100
    return ret, last_d, last_v, pd_, pv


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    rows = []
    fixed = []
    failed = []
    for h in cfg["holdings"]:
        if not h.get("market"):
            fixed.append(h)
            continue
        ser = _nav_series(h)
        wr = _weekly_return(ser)
        if wr is None:
            failed.append(h)
            rows.append({**h, "ret": None})
            continue
        ret, ld, lv, pdt, pv = wr
        rows.append({**h, "ret": ret, "last_d": ld, "prev_d": pdt})

    ok = [r for r in rows if r["ret"] is not None]
    mkt_w = sum(r["amount_w"] for r in ok)
    port_ret = sum(r["ret"] * r["amount_w"] for r in ok) / mkt_w if mkt_w else 0.0

    print("=" * 64)
    print(f"  每周持仓涨跌报告  |  生成日 {dt.date.today()}  (口径见文件头)")
    print("=" * 64)

    by_class = {}
    for r in ok:
        by_class.setdefault(r["klass"], []).append(r)

    for klass in ["股票", "债券", "商品"]:
        items = by_class.get(klass, [])
        if not items:
            continue
        cw = sum(r["amount_w"] for r in items)
        cret = sum(r["ret"] * r["amount_w"] for r in items) / cw
        print(f"\n【{klass}】 市值 {cw:.2f}w  周涨跌 {cret:+.2f}%")
        for r in sorted(items, key=lambda x: x["ret"], reverse=True):
            arrow = "🔺" if r["ret"] >= 0 else "🔻"
            print(f"  {arrow} {r['ret']:+6.2f}%  {r['code']} {r['name']:<22} "
                  f"({r['amount_w']:.2f}w, 净值{r['prev_d']}→{r['last_d']})")

    print("\n" + "-" * 64)
    print(f"  组合周涨跌幅(有市价 {mkt_w:.2f}w 加权)：{port_ret:+.2f}%")
    fixed_w = sum(h["amount_w"] for h in fixed)
    total_w = mkt_w + fixed_w
    print(f"  有市价 {mkt_w:.2f}w + 固定(保险/养老/现金) {fixed_w:.2f}w = 总资产 {total_w:.2f}w")
    if failed:
        print(f"  ⚠️ 取数失败 {len(failed)} 只(未计入)："
              + "，".join(f"{h['code']} {h['name']}" for h in failed))
    print("=" * 64)


if __name__ == "__main__":
    main()
