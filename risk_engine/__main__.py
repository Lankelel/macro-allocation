"""独立运行入口：python -m risk_engine（默认演示商品 sleeve）。"""
from pathlib import Path

import yaml

from . import build_risk_matrix, format_report

BASE = Path(__file__).resolve().parent.parent

with open(BASE / "config" / "holdings.yaml", encoding="utf-8") as f:
    holdings = yaml.safe_load(f)
comm = holdings["sleeves"]["commodity"]
assets = {label: comm[label]["code"] for label in comm}
print(f"[V2.1] 测试资产：{assets}")
risk = build_risk_matrix(assets)
print("\n" + format_report(risk))
