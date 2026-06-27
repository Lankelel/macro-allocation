"""独立运行入口：
  python -m results_sync          只生成提案 outputs/finance_sync_proposal.md
  python -m results_sync --apply  额外把建议追加到 Finance.md（非破坏式，标注待确认）
"""
import sys

from .sync import sync

result = sync(apply="--apply" in sys.argv)
print(f"\n提案文件：{result['proposal_path']}")
print(f"是否已追加 Finance.md：{result['applied_to_finance']}")
