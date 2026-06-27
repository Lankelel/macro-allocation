"""
M1 资讯模块 - collector

职责：
  1. （可选）触发 Horizon 生成最新日报
  2. 读取 Horizon 产出的 markdown 简报
  3. 包装成 M2 可直接消费的结构（briefing markdown + 元信息）

设计说明：
  Horizon 输出是 markdown 日报（horizon/data/summaries/horizon-{date}-{lang}.md），
  不是结构化 JSON。M1 不强行解析成 per-item JSON，而是直接把日报正文传给 M2，
  由 M2 的 4 位大师阅读。结构化是 M2 的输出（directions.json）才需要做的事。
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# 路径解析（相对本文件，跨机器稳定）
BASE = Path(__file__).resolve().parent.parent          # macro-allocation/
HORIZON_DIR = BASE.parent / "horizon"                   # ../horizon/
SUMMARIES_DIR = HORIZON_DIR / "data" / "summaries"
OUTPUTS_DIR = BASE / "outputs"

# 语言偏好：优先中文，其次英文
LANG_PREFERENCE = ["zh", "en"]


def run_horizon(hours: int = 24, timeout: int = 1200) -> bool:
    """
    触发 Horizon 生成一份新日报。

    通过 horizon 自己的 uv 环境运行（与本项目 venv 隔离）。
    需要 horizon/.env 里已填入真实 ANTHROPIC_API_KEY。

    Returns:
        True 表示运行成功，False 表示失败（打印 stderr 供排查）。
    """
    if not HORIZON_DIR.exists():
        raise FileNotFoundError(f"未找到 Horizon 目录：{HORIZON_DIR}")

    cmd = ["python", "-m", "uv", "run", "horizon", "--hours", str(hours)]
    print(f"[M1] 运行 Horizon：{' '.join(cmd)}（cwd={HORIZON_DIR}）")
    try:
        result = subprocess.run(
            cmd,
            cwd=HORIZON_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"[M1] ⛔ Horizon 运行超时（>{timeout}s）")
        return False

    if result.returncode != 0:
        print("[M1] ⛔ Horizon 运行失败：")
        print(result.stderr[-2000:] if result.stderr else "(无 stderr)")
        return False

    print("[M1] ✅ Horizon 运行完成")
    return True


def read_latest_briefing(lang_preference: list[str] | None = None) -> dict | None:
    """
    读取 summaries 目录下最新的 markdown 简报。

    Returns:
        dict（含 markdown 正文 + 元信息），或 None（没有任何简报时）。
    """
    langs = lang_preference or LANG_PREFERENCE
    if not SUMMARIES_DIR.exists():
        print(f"[M1] ⚠️ summaries 目录不存在：{SUMMARIES_DIR}（Horizon 还没跑过？）")
        return None

    md_files = sorted(SUMMARIES_DIR.glob("horizon-*.md"), reverse=True)
    if not md_files:
        print(f"[M1] ⚠️ 未找到任何 horizon-*.md 简报")
        return None

    # 按语言偏好挑：先按文件名里的日期降序，再在同一天里挑首选语言
    chosen = None
    for lang in langs:
        for f in md_files:
            if f.stem.endswith(f"-{lang}"):
                chosen = f
                break
        if chosen:
            break
    if chosen is None:
        chosen = md_files[0]  # 没匹配到偏好语言，退回最新一份

    markdown = chosen.read_text(encoding="utf-8")
    print(f"[M1] ✅ 读取简报：{chosen.name}（{len(markdown)} 字符）")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "horizon",
        "source_file": chosen.name,
        "briefing_md": markdown,
    }


def _merge_manual_sources(briefing: dict, manual_file: str | None) -> dict:
    """⑪ 人工资讯源：把手动粘贴的公众号等内容追加到简报正文（供 M2 阅读）。"""
    if not manual_file:
        return briefing
    path = (BASE / manual_file) if not Path(manual_file).is_absolute() else Path(manual_file)
    if not path.exists():
        return briefing
    raw = path.read_text(encoding="utf-8")
    cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()   # 先剥离 HTML 注释块
    # 去掉标题/引用后还有实质内容才合并（纯模板→跳过）
    meaningful = [ln for ln in cleaned.splitlines() if ln.strip() and not ln.strip().startswith(("#", ">"))]
    if not meaningful:
        print("[M1] ℹ️ 人工资讯源文件为空（仅模板/注释），跳过合并")
        return briefing
    briefing["briefing_md"] += f"\n\n---\n\n## 人工补充资讯（公众号等，{path.name}）\n\n{cleaned}\n"
    briefing["manual_sources"] = path.name
    print(f"[M1] ✅ 已合并人工资讯源：{path.name}（{len(meaningful)} 行实质内容）")
    return briefing


def collect(run_fresh: bool = False, hours: int = 24, manual_sources_file: str | None = None) -> dict | None:
    """
    M1 主入口。

    Args:
        run_fresh: True 则先触发 Horizon 生成新日报，再读取；False 则直接读已有简报（调试常用）。
        hours: 传给 Horizon 的时间窗口（⑩：低频宏观源需更长，季度建议 720）。
        manual_sources_file: ⑪ 人工资讯源文件（公众号手动粘贴），合并进简报。

    Returns:
        M1 输出 dict（写入 outputs/m1_briefing.json），或 None。
    """
    if run_fresh:
        ok = run_horizon(hours=hours)
        if not ok:
            print("[M1] ⛔ 生成新日报失败，尝试读取已有简报作为兜底")

    briefing = read_latest_briefing()
    if briefing is None:
        return None

    briefing = _merge_manual_sources(briefing, manual_sources_file)

    # 落盘供 M2 / 调试使用
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUTS_DIR / "m1_briefing.json"
    out_path.write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[M1] ✅ 已写入 {out_path}")
    return briefing


if __name__ == "__main__":
    # 独立运行：python -m m1_news.collector
    # 默认只读取已有简报；加 --fresh 触发 Horizon 重新生成
    import sys

    fresh = "--fresh" in sys.argv
    result = collect(run_fresh=fresh)
    if result:
        print("\n--- 简报预览（前 500 字）---")
        print(result["briefing_md"][:500])
    else:
        print("\n[M1] 没有可用简报。请先填好 horizon/.env 的 API key，再用 --fresh 运行。")
