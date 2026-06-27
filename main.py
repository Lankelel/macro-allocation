"""
宏观配置 - 主编排入口

两段式流水线：
  阶段一（定性）：M1 资讯 → M2 分析 → M3 决策   （需 API + Horizon 简报）
  阶段二（量化 V2）：风险诊断 → Black-Litterman → 再平衡   （需 akshare 网络）

用法：
  python main.py                # 全流程（定性 + 量化）
  python main.py --quant-only   # 只跑量化层 V2（读已有 directions.json）
  python main.py --qual-only    # 只跑定性 M1→M2→M3
"""
import sys
from pathlib import Path

import yaml

from m1_news import collect as m1_collect
from clock import run_clock
from m2_analysis import analyze as m2_analyze
from m3_decision import decide as m3_decide
from diagnostic import diagnose
from black_litterman import run_bl_on_sleeve, run_bl_stock_regions
from style_tilt import run_style_tilt
from vol_target import run_vol_target
from rebalancer import check_rebalance
from theme_decider import decide_themes

BASE = Path(__file__).parent
CONFIG = BASE / "config"


def load_config():
    with open(CONFIG / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    with open(CONFIG / "holdings.yaml", encoding="utf-8") as f:
        holdings = yaml.safe_load(f)
    return settings, holdings


def run_qualitative(settings, holdings):
    """阶段一：M1→M2→M3（定性方向倾斜）。"""
    print("\n========== 阶段一：定性方向倾斜（M1→M2→M3）==========")
    print("[M1] 收集资讯...")
    m1cfg = settings.get("m1", {})
    briefing = m1_collect(
        run_fresh=m1cfg.get("run_fresh", False),
        hours=m1cfg.get("hours", 24),
        manual_sources_file=m1cfg.get("manual_sources_file"),
    )
    if briefing is None:
        print("[M1] 暂无简报（需先配 horizon/.env 的 key 并运行 Horizon）")
        return None
    print("\n[E1] 美林时钟（宏观环境定位，M1→M2 统一锚点）...")
    try:
        clock = run_clock()
    except Exception as e:
        print(f"[E1] ⚠️ 时钟失败（不阻塞 M2）：{e}")
        clock = None
    print("\n[M2] 分析方向（含宏观锚）...")
    directions = m2_analyze(briefing, holdings, settings, clock=clock)
    print("\n[M3] 计算二级权重（线性倾斜，对照基准）...")
    m3_decide(directions, holdings, settings)
    return directions


def run_quant_layer():
    """阶段二：V2 量化层（诊断 → BL → 再平衡）。"""
    print("\n========== 阶段二：量化层 V2（诊断→BL→再平衡）==========")
    print("[V2.2] 风险贡献诊断...")
    diagnose()
    print("\n[处方①] 低波红利替换（风格体检+替换测算）...")
    run_style_tilt()
    print("\n[V2.3] Black-Litterman（商品 sleeve）...")
    run_bl_on_sleeve("commodity")
    print("\n[V2.3②] Black-Litterman（股票地域）...")
    run_bl_stock_regions()
    print("\n[E3] 波动率目标（动态削峰）...")
    run_vol_target()
    print("\n[V2.4] 再平衡检查...")
    check_rebalance()
    print("\n[G1] 主题自动决策（方向观点→选基主题建议）...")
    try:
        decide_themes()   # 出 theme_decision.{json,md} + 现成 --fill 命令；铁律：仅建议，不自动执行 --fill
    except Exception as e:
        print(f"[G1] ⚠️ 主题决策失败（不阻塞）：{e}")

    print("\n[⑪末位淘汰] 持仓质量末位淘汰（同类内综合分）...")
    use_screen = False
    try:
        from holdings_screener import screen as screen_holdings
        screen_holdings()     # 出 holdings_screen.{json,md}（建议，人工 review）
        use_screen = True
    except Exception as e:
        print(f"[末位淘汰] ⚠️ 跳过（不阻塞，--use-screen 失效）：{str(e)[:70]}")

    print("\n[⑫⑬] 单只调仓清单（基础版）+ 一页调仓结论汇总...")
    try:
        from fund_rebalancer import plan_fund_level
        from decision_summary import summarize
        # 接法A：淘汰名单在「超配大类额度内」执行具体卖出，卖出现金计入可用资金
        plan_fund_level(use_screen=use_screen)
        summarize()           # 合并 诊断+主题+单只(含淘汰卖出) → outputs/调仓结论.md
        print("    （如需低波替换/选基填充：python -m fund_rebalancer --use-screen --swap --fill <大类>=<主题> 再 python -m decision_summary）")
    except Exception as e:
        print(f"[⑫⑬] ⚠️ 跳过（需先跑 ⑥ holdings_sync 生成 holdings_current.json）：{str(e)[:70]}")


def run_pipeline(quant_only=False, qual_only=False):
    settings, holdings = load_config()
    print("[OK] 配置加载成功")
    print(f"  - 关注方向：{settings['directions']}")
    print(f"  - SAA 锚：{holdings['saa_target']}")

    if not quant_only:
        directions = run_qualitative(settings, holdings)
        if directions is None and qual_only:
            return
    if not qual_only:
        run_quant_layer()

    print("\n========== 完成 ==========")
    print("定性产出：outputs/{m1_briefing,directions,allocations}.*")
    print("量化产出：outputs/{risk_diagnostic,bl_commodity,rebalance_plan}.*")
    print("决策产出：outputs/theme_decision.{json,md}（G1 主题建议 + 现成 --fill 命令）")
    print("⚠️ 所有建议需人工 review 后执行；主题确认后用 fund_rebalancer --fill 出单只调仓清单，再同步 Finance.md。")


if __name__ == "__main__":
    run_pipeline(
        quant_only="--quant-only" in sys.argv,
        qual_only="--qual-only" in sys.argv,
    )
