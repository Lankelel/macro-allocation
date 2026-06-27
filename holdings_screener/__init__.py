"""持仓末位淘汰器：同类内复合质量标准排序 → 末位淘汰 → 腾现金 + 替代建议提示。"""
from .screener import screen

__all__ = ["screen"]
