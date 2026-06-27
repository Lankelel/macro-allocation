"""V2.3 Black-Litterman：把 M2 评分作为观点，融合均衡先验 → sleeve 目标权重。"""

from .optimizer import run_bl_on_sleeve, run_bl_stock_regions

__all__ = ["run_bl_on_sleeve", "run_bl_stock_regions"]
