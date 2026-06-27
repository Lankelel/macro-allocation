"""
⑤ E1 美林投资时钟（决策 E：M1→M2 之间的"环境定位"统一锚点）

思想：用「增长」×「通胀」两个方向把宏观环境定到四象限，每个象限历史上有一类资产占优，
作为大师评分 + 倾斜的统一锚点（让 M2 在同一个宏观框架下打分，而非各说各话）。

四象限（增长↑↓ × 通胀↑↓）与占优资产：
  复苏 Recovery   增长↑ 通胀↓ → 超配【股票】（盈利改善、利率仍低）
  过热 Overheat   增长↑ 通胀↑ → 超配【商品】（需求旺、涨价）
  滞胀 Stagflation 增长↓ 通胀↑ → 超配【现金】（资产普跌、避险）
  衰退 Recession  增长↓ 通胀↓ → 超配【债券】（降息、避险买债）

指标选择（务实）：
  - 增长轴：制造业 PMI（月度、最及时；>50 扩张）。方向 = 近 3 月动量（最新 vs 3 月前）。
  - 通胀轴：CPI 同比（YoY，月度）。方向 = 近 3 月动量。
  - GDP 同比（季度、较滞后）仅作增长方向的旁证。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import akshare as ak
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"

QUADRANTS = {
    ("up", "down"):   {"name": "复苏 Recovery",    "favor": "stock",     "favor_cn": "股票"},
    ("up", "up"):     {"name": "过热 Overheat",    "favor": "commodity", "favor_cn": "商品"},
    ("down", "up"):   {"name": "滞胀 Stagflation", "favor": "cash",      "favor_cn": "现金"},
    ("down", "down"): {"name": "衰退 Recession",   "favor": "bond",      "favor_cn": "债券"},
}


def _parse_month(s: str) -> pd.Timestamp:
    m = re.match(r"(\d{4})年(\d{1,2})月", str(s))
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1) if m else pd.NaT


def _monthly(fn: str, val_col: str) -> pd.Series:
    """取某 NBS 月度指标，按月份升序的 Series。"""
    df = getattr(ak, fn)()
    df = df[["月份", val_col]].copy()
    df["dt"] = df["月份"].map(_parse_month)
    s = df.dropna(subset=["dt"]).set_index("dt")[val_col].sort_index()
    return pd.to_numeric(s, errors="coerce").dropna()


def _direction(s: pd.Series, lag: int = 3) -> tuple[str, float, float]:
    """近 lag 月动量方向：最新 vs lag 月前。返回(up/down, 最新值, 变化)。"""
    latest = float(s.iloc[-1])
    prev = float(s.iloc[-1 - lag]) if len(s) > lag else float(s.iloc[0])
    chg = latest - prev
    return ("up" if chg >= 0 else "down"), latest, chg


def run_clock(lag: int = 3) -> dict:
    pmi = _monthly("macro_china_pmi", "制造业-指数")
    cpi = _monthly("macro_china_cpi", "全国-同比增长")
    try:
        gdp_df = getattr(ak, "macro_china_gdp")()[["季度", "国内生产总值-同比增长"]].copy()
        gdp_val = float(pd.to_numeric(gdp_df["国内生产总值-同比增长"], errors="coerce").dropna().iloc[0])
        gdp_q = str(gdp_df["季度"].iloc[0])
    except Exception:
        gdp_val, gdp_q = None, None

    g_dir, pmi_latest, pmi_chg = _direction(pmi, lag)
    i_dir, cpi_latest, cpi_chg = _direction(cpi, lag)
    quad = QUADRANTS[(g_dir, i_dir)]

    # 给 M2 的倾斜锚：占优类 +1，其余 0（温和、只表方向）
    anchor = {c: 0 for c in ["stock", "bond", "commodity", "cash"]}
    anchor[quad["favor"]] = 1

    result = {
        "data_month": str(pmi.index[-1].date())[:7],
        "growth": {"indicator": "制造业PMI", "value": round(pmi_latest, 1),
                   "change_3m": round(pmi_chg, 2), "direction": g_dir,
                   "expanding": pmi_latest >= 50},
        "inflation": {"indicator": "CPI同比", "value": round(cpi_latest, 2),
                      "change_3m": round(cpi_chg, 2), "direction": i_dir},
        "gdp_yoy_ref": {"value": gdp_val, "quarter": gdp_q},
        "quadrant": quad["name"],
        "favored_class": quad["favor"],
        "favored_class_cn": quad["favor_cn"],
        "m2_anchor": anchor,
        "lag_months": lag,
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "clock.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "clock.md").write_text(_render(result), encoding="utf-8")
    print(f"[E1] ✅ 美林时钟：{quad['name']} → 占优{quad['favor_cn']}（已写入 outputs/clock.*）")
    return result


def _render(r: dict) -> str:
    g, i = r["growth"], r["inflation"]
    arrow = lambda d: "↑上行" if d == "up" else "↓下行"
    lines = ["# 美林投资时钟 - 宏观环境定位（⑤ E1）", ""]
    lines.append(f"> 数据月份 **{r['data_month']}**｜方向取近 {r['lag_months']} 月动量")
    lines.append("")
    lines.append("## 两轴读数")
    lines.append("| 轴 | 指标 | 最新值 | 近3月变化 | 方向 |")
    lines.append("|----|------|------|------|------|")
    lines.append(f"| 增长 | {g['indicator']} | {g['value']}{'（扩张）' if g['expanding'] else '（收缩<50）'} "
                 f"| {g['change_3m']:+.2f} | {arrow(g['direction'])} |")
    lines.append(f"| 通胀 | {i['indicator']} | {i['value']}% | {i['change_3m']:+.2f}pp | {arrow(i['direction'])} |")
    if r["gdp_yoy_ref"]["value"] is not None:
        lines.append(f"\n> 旁证：最新 GDP 同比 {r['gdp_yoy_ref']['value']}%（{r['gdp_yoy_ref']['quarter']}，季度滞后仅参考）")
    lines.append("")
    lines.append(f"## 定位：**{r['quadrant']}** → 历史占优资产：**{r['favored_class_cn']}**")
    lines.append("")
    lines.append("| 象限 | 增长 | 通胀 | 占优资产 |")
    lines.append("|------|------|------|------|")
    for (gd, idr), q in QUADRANTS.items():
        mark = " ←**当前**" if q["name"] == r["quadrant"] else ""
        lines.append(f"| {q['name']}{mark} | {arrow(gd)} | {arrow(idr)} | {q['favor_cn']} |")
    lines.append("")
    lines.append(f"## 给 M2 的统一锚点")
    lines.append(f"- `m2_anchor` = {r['m2_anchor']}（占优类 +1，作为大师打分/倾斜的宏观背景，非硬性指令）")
    lines.append("> 用法：M2 四位大师在此宏观象限下打分，倾斜方向与时钟一致时增强信心、相悖时提示降置信度。"
                 "美林时钟可解释、与「宏观配置」定位契合（决策E：E1先做）。")
    return "\n".join(lines)
