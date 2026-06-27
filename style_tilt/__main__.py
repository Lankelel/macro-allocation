"""独立运行入口：python -m style_tilt"""
from .analyzer import run_style_tilt, _render

result = run_style_tilt()
print("\n" + _render(result))
