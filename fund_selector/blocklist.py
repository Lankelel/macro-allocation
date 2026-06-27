"""不可购买清单（人在回路闭环）：

你 review 排序清单后，把无法购买的基金代码标记下来 → 持久化到 config/unbuyable_funds.json。
下次选基时这些基金自动从主榜剔除（挪到「已标记不可购买」区块），空出的名次由同类下一只自动补上。

为什么单独成文件而非写死在 selector：标记是「人」的决策、跨主题复用（标了 007466 不能买，跑任何主题都该排除），
且要长期累积——配置数据，不属于算法逻辑。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BLOCK_PATH = BASE / "config" / "unbuyable_funds.json"


def load_blocklist() -> dict:
    """读不可购买清单：{code: {reason, marked_at}}。文件不存在→空。"""
    if not BLOCK_PATH.exists():
        return {}
    try:
        return json.loads(BLOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    BLOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLOCK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_block(code: str, reason: str = "") -> dict:
    """标记一只基金不可购买（已存在则更新原因）。返回更新后的整张清单。"""
    code = str(code).strip()
    data = load_blocklist()
    data[code] = {"reason": reason or data.get(code, {}).get("reason", ""),
                  "marked_at": datetime.now().strftime("%Y-%m-%d")}
    _save(data)
    return data


def remove_block(code: str) -> dict:
    """撤销标记（恢复可购买）。"""
    code = str(code).strip()
    data = load_blocklist()
    data.pop(code, None)
    _save(data)
    return data


def is_blocked(code: str) -> bool:
    return str(code).strip() in load_blocklist()
