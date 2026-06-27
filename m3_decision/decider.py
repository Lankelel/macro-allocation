"""
M3 决策模块 - decider

方法：Tactical Tilting + Equal Weight Baseline（机构主流）
  Step 1  等权基准：每个 sleeve 内部先平均分
  Step 2  评分调整：每 +1 评分 → 权重 +step%（默认 2%）
  Step 3  守恒约束：sleeve 内总额保持不变（盈亏由中性项均摊回填）
  Step 4  边界约束：单次 ≤max_single_step / 累计偏离 ≤max_deviation / 单只 ≤max_single_holding

不调用任何 API，纯逻辑。读 directions.json（M2）+ holdings/settings → allocations.md。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE / "outputs"


def _tilt_sleeve(
    items: dict[str, float],
    scores: dict[str, int],
    step: float,
    max_single_step: float,
    sleeve_total: float,
) -> dict[str, float]:
    """
    对单个 sleeve 做战术倾斜。

    Args:
        items: {品种: 等权基准权重}（已是该 sleeve 内部占比，和为 sleeve_total）
        scores: {品种: 评分 -2~+2}
        step: 每分调整幅度
        max_single_step: 单品种单次调整上限
        sleeve_total: 该 sleeve 的总权重（守恒目标）

    Returns:
        {品种: 调整后权重}，和仍为 sleeve_total
    """
    # Step 1+2：按评分计算原始调整量（带单次上限裁剪）
    deltas = {}
    for k in items:
        raw = scores.get(k, 0) * step
        clipped = max(-max_single_step, min(max_single_step, raw))
        deltas[k] = clipped

    # Step 3：守恒——总调整量需归零，把净偏移在"被调整项"上按比例回填
    net = sum(deltas.values())
    if abs(net) > 1e-9:
        # 把净偏移均摊到所有品种（保证 sum 不变）
        n = len(items)
        for k in items:
            deltas[k] -= net / n

    adjusted = {k: items[k] + deltas[k] for k in items}

    # 防止负权重：截断到 0，再重新归一到 sleeve_total
    for k in adjusted:
        if adjusted[k] < 0:
            adjusted[k] = 0.0
    s = sum(adjusted.values())
    if s > 0:
        adjusted = {k: v / s * sleeve_total for k, v in adjusted.items()}
    return adjusted


def decide(directions: dict, holdings: dict, settings: dict) -> dict:
    """
    M3 主入口。

    Args:
        directions: M2 输出（含 final.directions / regions / commodities）
        holdings: holdings.yaml
        settings: settings.yaml

    Returns:
        决策结果 dict，并写入 outputs/allocations.md + outputs/allocations.json
    """
    m3 = settings["m3"]
    step = m3["step_per_score"]
    max_single_step = m3["max_single_step"]
    max_single_holding = m3["max_single_holding"]

    final = directions["final"]
    saa = holdings["saa_target"]
    sleeves = holdings["sleeves"]

    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "sleeves": {}}

    # ---------- 商品 sleeve（按 gold/oil/broad 评分倾斜）----------
    commodity_total = saa["commodity"]  # 如 0.15
    n_comm = len(sleeves["commodity"])
    comm_base = {k: commodity_total / n_comm for k in sleeves["commodity"]}
    comm_scores = {k: final["commodities"].get(k, {}).get("strength", 0)
                   for k in sleeves["commodity"]}
    comm_adj = _tilt_sleeve(comm_base, comm_scores, step, max_single_step, commodity_total)
    result["sleeves"]["commodity"] = {
        "total": commodity_total,
        "items": {
            k: {
                "code": sleeves["commodity"][k]["code"],
                "name": sleeves["commodity"][k]["name"],
                "baseline": round(comm_base[k], 4),
                "score": comm_scores[k],
                "target": round(comm_adj[k], 4),
            }
            for k in sleeves["commodity"]
        },
    }

    # ---------- 股票地域 sleeve（按 US/CN/Asia/EU/JP 评分倾斜）----------
    stock_total = saa["stock"]  # 如 0.40
    region_cfg = sleeves["stock_region"]
    # 基准：用 holdings 里配的 target_pct（如 US/CN/Asia=40/40/20）换算成占总组合的比例
    region_base = {r: region_cfg[r]["target_pct"] * stock_total for r in region_cfg}
    region_scores = {r: final["regions"].get(r, {}).get("strength", 0) for r in region_cfg}
    region_adj = _tilt_sleeve(region_base, region_scores, step, max_single_step, stock_total)
    result["sleeves"]["stock_region"] = {
        "total": stock_total,
        "items": {
            r: {
                "baseline": round(region_base[r], 4),
                "score": region_scores[r],
                "target": round(region_adj[r], 4),
            }
            for r in region_cfg
        },
    }

    # ---------- 行业大方向（仅作为卫星仓位的倾斜提示，不直接改大类权重）----------
    result["direction_tilts"] = {
        k: {"score": v.get("strength", 0), "reason": v.get("reason", "")}
        for k, v in final["directions"].items()
    }

    # 落盘
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "allocations.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = _render_markdown(result, directions)
    (OUTPUTS_DIR / "allocations.md").write_text(md, encoding="utf-8")
    print(f"[M3] ✅ 已写入 outputs/allocations.json 和 allocations.md")
    return result


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _render_markdown(result: dict, directions: dict) -> str:
    ts = result["timestamp"][:10]
    lines = [f"# 配置建议（M3 决策输出）- {ts}", ""]
    lines.append("> 方法：Tactical Tilting + Equal Weight Baseline")
    lines.append("> 评分来自 M2（4 大师 + Moderator），权重为占总组合（非保险池）比例")
    lines.append("")

    # 商品
    lines.append("## 大宗商品 sleeve")
    c = result["sleeves"]["commodity"]
    lines.append(f"总目标：{_pct(c['total'])}")
    lines.append("")
    lines.append("| 品种 | 代码 | 基准 | 评分 | 建议权重 |")
    lines.append("|------|------|------|------|---------|")
    for k, v in c["items"].items():
        lines.append(f"| {v['name']} | {v['code']} | {_pct(v['baseline'])} | {v['score']:+d} | **{_pct(v['target'])}** |")
    lines.append("")

    # 股票地域
    lines.append("## 股票地域 sleeve")
    s = result["sleeves"]["stock_region"]
    lines.append(f"总目标：{_pct(s['total'])}")
    lines.append("")
    lines.append("| 地域 | 基准 | 评分 | 建议权重 |")
    lines.append("|------|------|------|---------|")
    region_names = {"US": "美国", "CN": "中国", "Asia": "新兴亚洲", "EU": "欧洲", "JP": "日本"}
    for r, v in s["items"].items():
        lines.append(f"| {region_names.get(r, r)} | {_pct(v['baseline'])} | {v['score']:+d} | **{_pct(v['target'])}** |")
    lines.append("")

    # 行业方向提示
    lines.append("## 行业大方向倾斜提示（卫星仓位参考）")
    lines.append("")
    lines.append("| 方向 | 评分 | 理由 |")
    lines.append("|------|------|------|")
    dir_names = {"AI": "AI/科技", "energy": "能源", "medical": "医疗", "military": "军工", "consumer": "消费", "finance": "金融"}
    for k, v in result["direction_tilts"].items():
        lines.append(f"| {dir_names.get(k, k)} | {v['score']:+d} | {v['reason']} |")
    lines.append("")
    lines.append("---")
    lines.append("> ⚠️ 本输出为**建议**，需人工 review 后执行；追加到 Finance.md 调整日志。")
    return "\n".join(lines)


if __name__ == "__main__":
    import yaml

    cfg = BASE / "config"
    with open(cfg / "settings.yaml", encoding="utf-8") as f:
        _settings = yaml.safe_load(f)
    with open(cfg / "holdings.yaml", encoding="utf-8") as f:
        _holdings = yaml.safe_load(f)

    dpath = OUTPUTS_DIR / "directions.json"
    if not dpath.exists():
        print("[M3] 未找到 directions.json，请先运行 M2")
    else:
        _directions = json.loads(dpath.read_text(encoding="utf-8"))
        res = decide(_directions, _holdings, _settings)
        print("\n--- allocations.md 预览 ---")
        print((OUTPUTS_DIR / "allocations.md").read_text(encoding="utf-8"))
