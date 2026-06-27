"""选基模块（券商分析师角色，A方案 MVP）：定向筛选——主题→召回→硬筛→打分排序。"""

from .selector import select_funds

__all__ = ["select_funds"]
