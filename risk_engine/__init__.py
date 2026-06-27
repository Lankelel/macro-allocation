"""
V2.1 风险/相关性引擎：拉历史净值 → 日收益 → 波动率/相关性/协方差(Ledoit-Wolf)。

这是量化层的地基，输出 risk_matrix.json 供 V2.2(诊断)/V2.3(BL)/E3(波动目标) 消费。
"""
import json
from pathlib import Path

import yaml

from .engine import compute_risk, format_report
from .fetcher import fetch_returns

__all__ = ["compute_risk", "format_report", "fetch_returns", "build_risk_matrix"]

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"


def build_risk_matrix(assets: dict[str, str], lookback_days: int = 504) -> dict:
    """
    端到端：拉数据 → 算风险 → 落盘 risk_matrix.json + risk_report.md。

    Args:
        assets: {标签: 基金代码}
        lookback_days: 回溯交易日数（默认 ~2 年）
    """
    returns = fetch_returns(assets, lookback_days=lookback_days)
    risk = compute_risk(returns)
    risk["asset_codes"] = assets  # 记录标签→代码映射

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "risk_matrix.json").write_text(
        json.dumps(risk, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "risk_report.md").write_text(
        format_report(risk), encoding="utf-8")
    print(f"[V2.1] ✅ 已写入 outputs/risk_matrix.json 和 risk_report.md")
    return risk


if __name__ == "__main__":
    # 独立运行：默认用 holdings.yaml 的商品 sleeve（gold/oil/broad）做演示
    with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    comm = holdings["sleeves"]["commodity"]
    assets = {label: comm[label]["code"] for label in comm}
    print(f"[V2.1] 测试资产：{assets}")
    risk = build_risk_matrix(assets)
    print("\n" + format_report(risk))
