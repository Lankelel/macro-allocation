"""研报抓取 CLI(确定性前端)。给关键词 → 抓行业深度 + 荐标的 + 个股深度 → 落 inbox。
双门(行业内容门 + 个股营收占比门)与决策弹药卡由 .claude/skills/研报 接力。

用法:
  py -3.13 -m uv run python -m report_fetcher --theme 储能 --keywords 储能,大储,户储,工商储,构网
"""
import argparse
import datetime
import os
import sys

from .business_mix import business_mix
from .eastmoney import EastMoneyReports
from .screen import in_whitelist, is_deep_industry, make_keyword_filter, pick_deep_stock_reports, rank_targets


def _window(months):
    end = datetime.date.today()
    begin = end - datetime.timedelta(days=int(months * 30.5))
    return begin.isoformat(), end.isoformat()


def _safe(name):
    for ch in '/\\:：*?"<>|':
        name = name.replace(ch, "_")
    return name


def _dedup_industry(deep):
    seen, pick = set(), []
    for it in sorted(deep, key=lambda x: x.get("publishDate", ""), reverse=True):
        key = (it.get("orgSName", ""), it.get("title", "")[:20])
        if key in seen:
            continue
        seen.add(key)
        pick.append(it)
    return pick


def main(argv=None):
    ap = argparse.ArgumentParser(description="研报自动抓取前端(行业深度 + 荐标的 + 个股深度)")
    ap.add_argument("--theme", required=True, help="主题名,如 储能")
    ap.add_argument("--keywords", required=True, help="逗号分隔关键词,如 储能,大储,户储,工商储,构网")
    ap.add_argument("--window-months", type=int, default=6)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--top-stocks", type=int, default=10)
    ap.add_argument("--per-stock", type=int, default=2, help="每只荐标的下载几篇个股深度")
    ap.add_argument("--min-pages", type=int, default=15, help="个股深度的页数阈值")
    ap.add_argument("--top-industry", type=int, default=20, help="最多下载几篇行业深度")
    ap.add_argument("--out", default=None, help="输出目录,默认 outputs/report_fetch/<theme>")
    args = ap.parse_args(argv)

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    begin, end = _window(args.window_months)
    out = args.out or os.path.join("outputs", "report_fetch", args.theme)
    ind_dir, stk_dir = os.path.join(out, "行业"), os.path.join(out, "个股")
    os.makedirs(ind_dir, exist_ok=True)
    os.makedirs(stk_dir, exist_ok=True)

    em = EastMoneyReports()
    kwf = make_keyword_filter(keywords)

    # ① 行业深度(标题含深度/专题 + 头部券商)
    print(f"=== [{args.theme}] 抓取 {begin}~{end} | 关键词 {keywords} ===", flush=True)
    ind = em.list_reports(1, begin, end, max_pages=args.max_pages, keyword_filter=kwf)
    deep_ind = _dedup_industry([it for it in ind if is_deep_industry(it) and in_whitelist(it.get("orgSName", ""))])
    print(f"\n[行业深度] 命中 {len(ind)} 篇,深度 {len(deep_ind)} 篇,下载 Top{args.top_industry}:", flush=True)
    for it in deep_ind[:args.top_industry]:
        fn = _safe(f"{it.get('publishDate','')[:10]}-{it.get('orgSName','')}-{it.get('title','')[:24]}.pdf")
        kb = em.download_pdf(it.get("infoCode", ""), os.path.join(ind_dir, fn)) // 1024
        print(f"  {'✓' if kb else '✗'} {kb:>5}KB {fn}", flush=True)

    # ② 荐标的(个股研报 metadata 聚合)
    stk = em.list_reports(0, begin, end, max_pages=args.max_pages, keyword_filter=kwf)
    targets = rank_targets(stk, top_n=args.top_stocks)
    print(f"\n[荐标的] 个股研报命中 {len(stk)} 篇 → Top{len(targets)}(覆盖家数排序):", flush=True)
    for t in targets:
        print(f"  {t['code']} {t['name']} 覆盖{t['coverage']} 买{t['buy']}/增{t['hold']} "
              f"目标价{t['target_price_avg']} PE{t['pe_avg']} {t['latest']}", flush=True)

    # ③ 对荐标的逐只抓个股深度(页数≥min,有则抓无则跳)
    print(f"\n[个股深度] 逐只抓(页≥{args.min_pages},每只Top{args.per_stock}):", flush=True)
    for t in targets:
        reps = em.stock_reports(t["code"], begin, end)
        deep = pick_deep_stock_reports(reps, per_stock=args.per_stock, min_pages=args.min_pages)
        if not deep:
            print(f"  {t['code']} {t['name']}: — 无深度个股报告(跳过)", flush=True)
            continue
        for r in deep:
            fn = _safe(f"{t['code']}-{t['name']}-{r.get('publishDate','')[:10]}-{r.get('orgSName','')}-{r.get('title','')[:18]}.pdf")
            kb = em.download_pdf(r.get("infoCode", ""), os.path.join(stk_dir, fn)) // 1024
            print(f"  {'✓' if kb else '✗'} {kb:>5}KB 页{r.get('attachPages')} {fn}", flush=True)

    print(f"\n完成 → {out}\n下一步(SKILL 接力):行业内容门 + 个股营收占比门(business_mix 取客观底)→ 决策弹药卡。", flush=True)


if __name__ == "__main__":
    sys.exit(main())
