"""
M2 分析模块 - analyzer

流程：
  1. 读取 M1 简报 + 持仓背景
  2. 并行调用 4 位大师 Persona（背对背独立打分）
  3. Moderator 综合 → 输出 directions.json

模型：DeepSeek（OpenAI 兼容接口）。persona=deepseek-chat，moderator=deepseek-reasoner。
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .personas import (
    PERSONAS,
    build_moderator_messages,
    build_persona_messages,
)

BASE = Path(__file__).resolve().parent.parent      # macro-allocation/
OUTPUTS_DIR = BASE / "outputs"
HORIZON_ENV = BASE.parent / "horizon" / ".env"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _load_api_key() -> str:
    """优先读 macro-allocation/.env，缺失则回退 horizon/.env（复用同一个 key）。"""
    load_dotenv(BASE / ".env")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        load_dotenv(HORIZON_ENV)
        key = os.getenv("DEEPSEEK_API_KEY")
    if not key or "PLACEHOLDER" in key:
        raise RuntimeError(
            "未找到有效的 DEEPSEEK_API_KEY。请在 macro-allocation/.env 或 horizon/.env 填入。"
        )
    return key


def _extract_json(text: str) -> dict:
    """从模型输出里抽取 JSON（容错：去掉 ```json 包裹）。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start : end + 1]
    return json.loads(t)


async def _call_persona_once(client: AsyncOpenAI, model: str, key: str, temp: float,
                            briefing_md: str, holdings_summary: str) -> dict | None:
    """调用单个大师 1 次，返回打分 dict 或 None。"""
    messages = build_persona_messages(key, briefing_md, holdings_summary)
    try:
        resp = await client.chat.completions.create(
            model=model, messages=messages, temperature=temp,
            response_format={"type": "json_object"},
        )
        return _extract_json(resp.choices[0].message.content)
    except Exception as e:
        print(f"[M2] ⚠️ {PERSONAS[key]['name']} 单次调用失败：{e}")
        return None


def _median_int(values: list[int]) -> int:
    """整数中位数（偶数个时向 0 取整，保守）。"""
    if not values:
        return 0
    m = statistics.median(values)
    # 偶数个时 median 可能是 x.5，向 0 方向取整以保守
    return int(m) if m >= 0 else -int(-m)


def _aggregate_samples(samples: list[dict]) -> dict:
    """
    对同一位大师的 K 次打分做中位数投票（self-consistency）。
    每个维度取 K 次评分的中位数；reason 取最接近中位数的那次。
    """
    if not samples:
        return {}
    groups = ["directions", "regions", "commodities"]
    agg = {}
    for g in groups:
        agg[g] = {}
        keys = samples[0].get(g, {}).keys()
        for k in keys:
            scores = [s.get(g, {}).get(k, {}).get("strength", 0) for s in samples if s.get(g)]
            med = _median_int(scores)
            # reason 取评分==中位数的那次（否则取第一个）
            reason = ""
            for s in samples:
                item = s.get(g, {}).get(k, {})
                if item.get("strength") == med:
                    reason = item.get("reason", "")
                    break
            if not reason and samples:
                reason = samples[0].get(g, {}).get(k, {}).get("reason", "")
            agg[g][k] = {"strength": med, "reason": reason, "samples": scores}
    return agg


async def _call_persona_stable(client: AsyncOpenAI, model: str, key: str, temp: float,
                              k: int, briefing_md: str, holdings_summary: str) -> tuple[str, dict | None]:
    """调用单个大师 K 次并行 → 中位数聚合，返回 (key, 聚合dict 或 None)。"""
    tasks = [_call_persona_once(client, model, key, temp, briefing_md, holdings_summary)
             for _ in range(k)]
    samples = [s for s in await asyncio.gather(*tasks) if s is not None]
    if not samples:
        print(f"[M2] ⚠️ {PERSONAS[key]['name']} {k} 次全失败")
        return key, None
    print(f"[M2] ✅ {PERSONAS[key]['name']} 完成（{len(samples)}/{k} 次有效，已取中位数）")
    return key, _aggregate_samples(samples)


async def _analyze_async(briefing_md: str, holdings_summary: str, settings: dict) -> dict:
    api_key = _load_api_key()
    m2 = settings["m2"]
    persona_model = m2.get("persona_model", "deepseek-chat")
    moderator_model = m2.get("moderator_model", "deepseek-reasoner")
    k = m2.get("samples_per_persona", 3)
    persona_temp = m2.get("persona_temperature", 0.2)
    moderator_temp = m2.get("moderator_temperature", 0.0)

    client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    # 1) 并行调用 4 位大师，每位跑 K 次取中位数（self-consistency，决策3：parallel）
    print(f"[M2] 并行调用 {len(m2['masters'])} 位大师 × {k} 次（中位数投票）...")
    tasks = [
        _call_persona_stable(client, persona_model, mk, persona_temp, k,
                             briefing_md, holdings_summary)
        for mk in m2["masters"]
    ]
    results = await asyncio.gather(*tasks)
    persona_results = {mk: v for mk, v in results if v is not None}

    if not persona_results:
        raise RuntimeError("所有大师调用都失败了，无法综合。")

    # 2) Moderator 综合（低温度，尽量确定性）
    print(f"[M2] Moderator（{moderator_model}）综合 {len(persona_results)} 份观点...")
    mod_messages = build_moderator_messages(persona_results, briefing_md)
    mod_resp = await client.chat.completions.create(
        model=moderator_model, messages=mod_messages, temperature=moderator_temp,
    )
    final = _extract_json(mod_resp.choices[0].message.content)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": {"persona": persona_model, "moderator": moderator_model},
        "stability": {"samples_per_persona": k, "persona_temp": persona_temp,
                      "moderator_temp": moderator_temp},
        "personas_used": list(persona_results.keys()),
        "final": final,
        "raw_personas": persona_results,
    }


def analyze(briefing: dict, holdings: dict, settings: dict, clock: dict | None = None) -> dict:
    """
    M2 主入口（同步包装）。

    Args:
        briefing: M1 输出（含 briefing_md）
        holdings: holdings.yaml 内容（提供持仓背景）
        settings: settings.yaml 内容
        clock: ⑤ 美林时钟结果（可选）。给定则作为统一宏观锚点注入大师背景。

    Returns:
        directions 结果 dict，并写入 outputs/directions.json
    """
    briefing_md = briefing["briefing_md"]
    saa = holdings.get("saa_target", {})
    holdings_summary = (
        f"目标大类配置：股票 {saa.get('stock')}、债券 {saa.get('bond')}、"
        f"大宗商品 {saa.get('commodity')}、高风险 {saa.get('high_risk')}。"
        f"关注 6 大方向：{settings.get('directions')}。"
    )
    if clock:
        # 美林时钟统一锚点：告诉大师当前宏观象限 + 历史占优类（背景参考，非硬指令）
        g, i = clock["growth"], clock["inflation"]
        holdings_summary += (
            f"\n【宏观环境锚（美林时钟，{clock['data_month']}）】当前处于「{clock['quadrant']}」象限："
            f"增长({g['indicator']} {g['value']}, {'上行' if g['direction']=='up' else '下行'})、"
            f"通胀(CPI同比 {i['value']}%, {'上行' if i['direction']=='up' else '下行'})；"
            f"该象限历史占优资产为【{clock['favored_class_cn']}】。"
            f"请在此宏观背景下打分：方向与之一致可增强信心，明显相悖时应说明理由并偏保守。"
        )

    result = asyncio.run(_analyze_async(briefing_md, holdings_summary, settings))

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUTS_DIR / "directions.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[M2] ✅ 已写入 {out_path}")
    return result


if __name__ == "__main__":
    # 独立运行：python -m m2_analysis.analyzer
    import yaml

    cfg = BASE / "config"
    with open(cfg / "settings.yaml", encoding="utf-8") as f:
        _settings = yaml.safe_load(f)
    with open(cfg / "holdings.yaml", encoding="utf-8") as f:
        _holdings = yaml.safe_load(f)

    briefing_path = OUTPUTS_DIR / "m1_briefing.json"
    if not briefing_path.exists():
        print("[M2] 未找到 m1_briefing.json，请先运行 M1（python -m m1_news.collector）")
    else:
        _briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
        res = analyze(_briefing, _holdings, _settings)
        print("\n--- 最终方向判断（final）---")
        print(json.dumps(res["final"], ensure_ascii=False, indent=2))
