"""独立运行入口：
  python -m fund_selector 红利低波              单关键词
  python -m fund_selector 红利低波 低波红利       多关键词(或关系召回)
  --lookback 504    风险指标回看交易日(默认504≈2年)
  --max-deep 120    最多深挖几只候选(默认120)

不可购买回流（人在回路）：
  python -m fund_selector --block 007466 平台无此基金   标记不可购买(原因可选)
  python -m fund_selector --unblock 007466             撤销标记
  python -m fund_selector --list-blocked               查看当前清单

买入建议桥（N6，给主题+金额选标的）：
  python -m fund_selector --buy 石油 5                   主题加5万→选基选标的+分配
  python -m fund_selector --buy 红利低波 8 --top 2 --split even   top2均分
  （--refresh 强制重跑选基；默认复用 outputs/fund_select_<主题>.json 缓存）
"""
import sys

from .blocklist import add_block, load_blocklist, remove_block
from .recommender import recommend_buy, render_buy
from .selector import select_funds, _render

argv = sys.argv[1:]

# 不可购买清单管理（与选基互斥，先处理）
if argv and argv[0] in ("--block", "--unblock", "--list-blocked"):
    cmd = argv[0]
    if cmd == "--list-blocked":
        bl = load_blocklist()
        if not bl:
            print("不可购买清单为空。")
        else:
            print(f"不可购买清单（{len(bl)} 只）：")
            for code, info in bl.items():
                print(f"  {code}  {info.get('reason') or '—'}  (标记于 {info.get('marked_at')})")
        sys.exit(0)
    if len(argv) < 2:
        print(f"用法：python -m fund_selector {cmd} <基金代码> [原因]")
        sys.exit(1)
    code = argv[1]
    if cmd == "--block":
        reason = " ".join(argv[2:])
        add_block(code, reason)
        print(f"✅ 已标记不可购买：{code}" + (f"（{reason}）" if reason else ""))
    else:  # --unblock
        remove_block(code)
        print(f"✅ 已撤销标记：{code}")
    sys.exit(0)

# 买入建议桥：--buy <主题> <金额> [--top N] [--split S] [--refresh]
if argv and argv[0] == "--buy":
    rest = argv[1:]
    top_n, split, refresh = 1, "top1", False
    pos = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--top":
            top_n = int(rest[i + 1]); i += 2
        elif a == "--split":
            split = rest[i + 1]; i += 2
        elif a == "--refresh":
            refresh = True; i += 1
        else:
            pos.append(a); i += 1
    if len(pos) < 2:
        print("用法：python -m fund_selector --buy <主题> <金额万> [--top N] [--split top1|even|score] [--refresh]")
        sys.exit(1)
    theme, amount = pos[0], float(pos[1])
    rec = recommend_buy([theme], amount, top_n=top_n, split=split, refresh=refresh)
    print("\n" + render_buy(rec))
    sys.exit(0)

lookback, max_deep = 504, 120
kws = []
i = 0
while i < len(argv):
    a = argv[i]
    if a == "--lookback":
        lookback = int(argv[i + 1]); i += 2
    elif a == "--max-deep":
        max_deep = int(argv[i + 1]); i += 2
    else:
        kws.append(a); i += 1

if not kws:
    print("用法：python -m fund_selector <主题关键词> [更多关键词] [--lookback N] [--max-deep N]")
    print("     管理不可购买：--block <代码> [原因] / --unblock <代码> / --list-blocked")
    sys.exit(1)

result = select_funds(kws, lookback=lookback, max_deep=max_deep)
print("\n" + _render(result))
