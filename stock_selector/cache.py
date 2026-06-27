"""B: 网络取数磁盘缓存(开发/重复跑提速)。
CachedSource 包装任意 DataSource,按 (方法,参数) 缓存到 .cache/stock_selector/,TTL 控新鲜度。
pickle 统一序列化 Series/dict;.cache/ 已被 .gitignore 忽略,不入库。
日线/财务日频更新 → 默认 TTL 1 天,当天重复跑(测试/校准/同池)直接复用,把分钟级跑压到秒级。"""
from __future__ import annotations

import pickle
import time
from pathlib import Path

from .datasource import DataSource

BASE = Path(__file__).resolve().parent.parent
DEFAULT_TTL = 86400  # 1 天


def _safe(key: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in key)


def _worth_caching(v) -> bool:
    """不缓存"空/失败结果"(None/空容器/全None的dict/空Series)——这些多是瞬时网络失败,
    存了会毒化缓存(曾让 basics 失败的 None 被缓存→后续全判查无此股)。"""
    if v is None:
        return False
    if isinstance(v, dict):
        return bool(v) and not all(x is None or (isinstance(x, float) and x != x) for x in v.values())
    if isinstance(v, (list, tuple, set)):
        return len(v) > 0
    try:
        import pandas as pd
        if isinstance(v, pd.Series):
            return len(v) > 0
    except Exception:
        pass
    return True


class CachedSource(DataSource):
    """读穿缓存:命中且未过期→返回缓存;否则取真值并落盘。取数失败不写缓存(下次重试)。"""

    def __init__(self, inner: DataSource, cache_dir=None, ttl: int = DEFAULT_TTL):
        self._inner = inner
        self._dir = Path(cache_dir) if cache_dir else (BASE / ".cache" / "stock_selector")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl

    def _cached(self, key: str, fn):
        f = self._dir / f"{_safe(key)}.pkl"
        if f.exists() and (time.time() - f.stat().st_mtime) < self._ttl:
            try:
                return pickle.loads(f.read_bytes())
            except Exception:
                pass
        val = fn()
        if _worth_caching(val):                  # 不缓存空/失败结果(防瞬时失败毒化)
            try:
                f.write_bytes(pickle.dumps(val))
            except Exception:
                pass
        return val

    def basics(self, code):
        return self._cached(f"basics_{code}", lambda: self._inner.basics(code))

    def daily_returns(self, code, lookback=504):
        return self._cached(f"ret_{lookback}_{code}", lambda: self._inner.daily_returns(code, lookback))

    def valuation(self, code):
        return self._cached(f"val_{code}", lambda: self._inner.valuation(code))

    def liquidity(self, code):
        return self._cached(f"liq_{code}", lambda: self._inner.liquidity(code))

    def financials(self, code):
        return self._cached(f"fin_{code}", lambda: self._inner.financials(code))

    def list_boards(self):
        return self._cached("boards_all", lambda: self._inner.list_boards())

    def board_constituents(self, board):
        return self._cached(f"board_{board}", lambda: self._inner.board_constituents(board))
