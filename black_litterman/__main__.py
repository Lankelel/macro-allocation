"""独立运行入口：python -m black_litterman（默认对商品 sleeve 跑 BL）。"""
from .optimizer import run_bl_on_sleeve, _render

result = run_bl_on_sleeve("commodity")
print("\n" + _render(result))
