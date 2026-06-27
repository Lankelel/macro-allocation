"""G1 主题自动决策层：宏观方向观点(M2 directions + 美林时钟) → 选基主题，补"方向→主题"翻译层。"""

from .decider import decide_themes

__all__ = ["decide_themes"]
