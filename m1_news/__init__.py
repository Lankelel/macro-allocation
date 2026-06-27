"""M1 资讯模块：触发 Horizon 生成日报，读取最新 markdown 简报供 M2 使用。"""

from .collector import collect, read_latest_briefing, run_horizon

__all__ = ["collect", "read_latest_briefing", "run_horizon"]
