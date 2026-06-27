"""独立运行入口：python -m diagnostic"""
from .analyzer import diagnose, _render

result = diagnose()
print("\n" + _render(result))
