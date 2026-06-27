"""G1 主题自动决策：python -m theme_decider
读 M2 directions + 美林时钟 + 再平衡缺口 → 各大类选定选基主题（建议，需人工 review）。
输出 outputs/theme_decision.{json,md} + 现成 --fill 命令。"""
from .decider import _render, decide_themes

result = decide_themes()
print("\n" + _render(result))
