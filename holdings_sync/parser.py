"""
⑥ 持仓自动同步：解析 AI Freedom/Finance.md 的「持仓明细分类表」→ 单只基金明细 + 聚合

为什么要这一步：holdings.yaml 只记到**大类/地域**级（如美股合计 16w），没有"513100 多少、
513500 多少"的**单只**数据。要产出"精确加减仓哪只基金、各多少万"的清单，必须先有单只持仓。
本模块从 Finance.md 同步出单只明细，是后续"再平衡器扩到基金级"的数据地基。

设计（不破坏手工维护的 holdings.yaml）：
  - 输出独立文件 config/holdings_current.json（机读单只明细 + 大类/地域聚合 + 数据日期）
  - 并与 holdings.yaml 的 current 块比对，报告大类金额是否漂移（提示需人工核对）

解析要点（Finance.md 表格的坑）：
  - 类别表头行（如「**股票/股票基金类（合计约40w）**」）→ 切换当前大类
  - 删除线 ~~代码~~ / 金额「~~7.0~~ → 2.0」→ 取箭头后的最终值；已清仓→0
  - 地域含 emoji → 归一到 US/CN/Asia 桶（与项目 stock_region 对齐）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FINANCE_MD = BASE.parent.parent.parent / "AI Freedom" / "Finance.md"
CONFIG = BASE / "config"
OUTPUTS_DIR = BASE / "outputs"

CLASS_KEYWORDS = [("股票", "stock"), ("债券", "bond"), ("偏债", "bond"), ("大宗商品", "commodity")]

# 处方S5：黄金=真分散器，从「大宗商品」段内拆出为独立大类，单列追踪（与诊断/SAA口径一致）
GOLD_CODES = {"002610"}


def _maybe_gold(cls: str | None, code: str, name: str) -> str | None:
    if cls == "commodity" and (code in GOLD_CODES or "黄金" in name):
        return "gold"
    return cls


def _strip_marks(s: str) -> str:
    return s.replace("~~", "").replace("**", "").strip()


def _parse_amount(cell: str) -> float:
    """金额单元格 → 最终持仓(万)。处理「~~7.0~~ → 2.0」取箭头后值；纯删除线/→0 为 0。"""
    c = cell.replace("~~", "").replace("**", "")
    if "→" in c:
        c = c.split("→")[-1]
    m = re.search(r"-?\d+\.?\d*", c)
    return float(m.group()) if m else 0.0


def _region_bucket(region_raw: str) -> str:
    """地域原文 → US/CN/Asia 桶（与 Finance.md 自身地域聚合口径一致）。"""
    r = region_raw
    if "全球" in r or "发达" in r or "美国" in r:
        return "US"          # 含"全球(含中)/全球发达"，与 Finance 把它们计入美/发达一致
    if any(k in r for k in ["越南", "印度", "沙特", "亚太", "大中华", "亚洲"]):
        return "Asia"
    if "中国" in r or "港" in r or "香港" in r:
        return "CN"
    return "其他"


def _extract_as_of(text: str) -> str | None:
    m = re.search(r"当前持仓梳理（(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def parse_finance(path: Path = FINANCE_MD) -> dict:
    text = path.read_text(encoding="utf-8")
    as_of = _extract_as_of(text)

    # 定位「持仓明细分类表」到下一个 ### 或 --- 之间的表格
    start = text.find("持仓明细分类表")
    if start == -1:
        raise RuntimeError("未找到「持仓明细分类表」")
    body = text[start:]
    end = min((p for p in [body.find("\n### ", 5), body.find("\n---", 5)] if p > 0), default=len(body))
    table = body[:end]

    funds, current_class = [], None
    for line in table.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        first = cells[0]
        rest_empty = all(not c for c in cells[1:6])
        # 表头分隔行 |---|---| 跳过
        if set(first.replace("-", "").replace(":", "")) == set() and rest_empty:
            continue
        # 类别表头行：第一格有字、其余为空
        if rest_empty and first:
            label = _strip_marks(first)
            for kw, cls in CLASS_KEYWORDS:
                if kw in label:
                    current_class = cls
                    break
            continue
        # 列名行
        if first == "代码":
            continue
        # 数据行
        code = _strip_marks(cells[0])
        if not re.fullmatch(r"\d{6}", code):   # 必须是 6 位基金代码
            continue
        amount = _parse_amount(cells[5])
        funds.append({
            "code": code,
            "name": _strip_marks(cells[1]),
            "asset_attr": cells[2],
            "region_raw": cells[3],
            "region": _region_bucket(cells[3]) if current_class == "stock" else None,
            "sector": cells[4],
            "class": _maybe_gold(current_class, code, _strip_marks(cells[1])),
            "amount_wan": round(amount, 4),
            "active": amount > 0,
        })

    active = [f for f in funds if f["active"]]
    by_class = {}
    for f in active:
        by_class[f["class"]] = round(by_class.get(f["class"], 0) + f["amount_wan"], 4)
    stock_by_region = {}
    for f in active:
        if f["class"] == "stock":
            stock_by_region[f["region"]] = round(stock_by_region.get(f["region"], 0) + f["amount_wan"], 4)

    return {
        "source": "AI Freedom/Finance.md",
        "as_of": as_of,
        "n_funds_active": len(active),
        "n_funds_total": len(funds),
        "by_class": by_class,
        "stock_by_region": stock_by_region,
        "funds": funds,
    }


def sync(write: bool = True) -> dict:
    import yaml
    parsed = parse_finance()

    # 与 holdings.yaml current 块比对（报漂移，不自动覆盖手工配置）
    with open(CONFIG / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    cur = holdings.get("current", {})
    drift = {}
    for cls, key in [("stock", "stock_wan"), ("bond", "bond_wan"), ("commodity", "commodity_wan"), ("gold", "gold_wan")]:
        synced = parsed["by_class"].get(cls, 0)
        recorded = cur.get(key)
        if recorded is not None and abs(synced - recorded) > 0.05:
            drift[cls] = {"finance_md": synced, "holdings_yaml": recorded, "diff": round(synced - recorded, 2)}
    parsed["drift_vs_holdings_yaml"] = drift

    if write:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG / "holdings_current.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUTPUTS_DIR / "holdings_current.md").write_text(_render(parsed), encoding="utf-8")
        print(f"[⑥] ✅ 已写入 config/holdings_current.json 和 outputs/holdings_current.md")
    return parsed


def _render(p: dict) -> str:
    cn = {"stock": "股票", "bond": "债券", "commodity": "大宗商品", "gold": "黄金"}
    lines = [f"# 当前持仓单只明细（自动同步自 Finance.md）", ""]
    lines.append(f"> 数据日期 **{p['as_of']}**｜活跃基金 {p['n_funds_active']} 只（表内共 {p['n_funds_total']} 行）")
    lines.append("")
    lines.append("## 大类聚合")
    lines.append("| 大类 | 金额(w) |")
    lines.append("|------|------|")
    for c, v in p["by_class"].items():
        lines.append(f"| {cn.get(c,c)} | {v:.1f} |")
    lines.append("")
    lines.append("## 股票地域聚合")
    lines.append("| 地域 | 金额(w) |")
    lines.append("|------|------|")
    for r, v in p["stock_by_region"].items():
        lines.append(f"| {r} | {v:.1f} |")
    lines.append("")
    if p.get("drift_vs_holdings_yaml"):
        lines.append("## ⚠️ 与 holdings.yaml 的大类金额漂移（需人工核对）")
        for c, d in p["drift_vs_holdings_yaml"].items():
            lines.append(f"- {cn.get(c,c)}：Finance.md {d['finance_md']}w vs holdings.yaml {d['holdings_yaml']}w（差 {d['diff']:+.2f}w）")
    else:
        lines.append("## ✅ 与 holdings.yaml 大类金额一致（无漂移）")
    lines.append("")
    lines.append("## 单只明细")
    lines.append("| 代码 | 简称 | 大类 | 地域 | 金额(w) |")
    lines.append("|------|------|------|------|------|")
    for f in p["funds"]:
        if not f["active"]:
            continue
        lines.append(f"| {f['code']} | {f['name']} | {cn.get(f['class'],f['class'])} | "
                     f"{f['region'] or f['region_raw']} | {f['amount_wan']:.1f} |")
    lines.append("")
    lines.append("> 用途：这是「精确加减仓清单」的数据地基——后续把再平衡器从大类级扩到基金级即可生成。")
    return "\n".join(lines)
