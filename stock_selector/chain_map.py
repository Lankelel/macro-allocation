# -*- coding: utf-8 -*-
"""产业链全景图生成器(chain_segment_ranker 的可视化产出)。

输入:一份 JSON「环节谱」(上中下游分层 + 各环节 产品/作用/龙头/大订单 + 环节评分)。
输出:自包含单页 HTML(无外部依赖,浏览器直接打开)。

铁律:本工具只做确定性渲染,不含任何选股/取数判断。环节谱由 SKILL 层(Claude+iFinD)产出。

用法:
  py -3.13 -m uv run python -m stock_selector.chain_map --spec spec.json --out outputs/AI算力产业链全景图.html
  # 或从 stdin 读 spec:  ... --spec - --out ...
"""
from __future__ import annotations

import argparse
import json
import sys

_CSS = """
:root{--up:#2563eb;--up-bg:#eff6ff;--up-bd:#bfdbfe;--mid:#ea580c;--mid-bg:#fff7ed;--mid-bd:#fed7aa;
--down:#16a34a;--down-bg:#f0fdf4;--down-bd:#bbf7d0;--star:#dc2626;--star-bg:#fef2f2;
--ink:#1e293b;--sub:#64748b;--line:#e2e8f0;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;color:var(--ink);
background:linear-gradient(180deg,#f8fafc,#f1f5f9);padding:28px;line-height:1.5}
.wrap{max-width:1280px;margin:0 auto}
header{text-align:center;margin-bottom:22px}
header h1{font-size:26px;letter-spacing:.5px}
header .flow{display:inline-flex;gap:8px;align-items:center;margin-top:10px;font-size:14px;color:var(--sub);
background:#fff;padding:7px 16px;border-radius:99px;border:1px solid var(--line)}
header .flow b{color:var(--ink)} header .meta{margin-top:8px;font-size:12px;color:#94a3b8}
.band{border-radius:16px;padding:16px 18px;margin-bottom:14px;border:1px solid}
.band.up{background:var(--up-bg);border-color:var(--up-bd)}
.band.mid{background:var(--mid-bg);border-color:var(--mid-bd)}
.band.down{background:var(--down-bg);border-color:var(--down-bd)}
.band-head{display:flex;align-items:baseline;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.band-head .tag{font-size:13px;font-weight:700;color:#fff;padding:3px 12px;border-radius:8px}
.up .tag{background:var(--up)} .mid .tag{background:var(--mid)} .down .tag{background:var(--down)}
.band-head .desc{font-size:13px;color:var(--sub)} .band-head .desc b{color:var(--ink)}
.grid{display:grid;gap:12px}
.g5{grid-template-columns:repeat(5,1fr)} .g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)} .g2{grid-template-columns:repeat(2,1fr)} .g1{grid-template-columns:1fr}
@media(max-width:1100px){.g5,.g4{grid-template-columns:repeat(3,1fr)}.g3{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.g5,.g4,.g3,.g2{grid-template-columns:1fr}}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:13px 14px;
box-shadow:0 1px 2px rgba(15,23,42,.04);position:relative}
.card.star{border:2px solid var(--star);background:var(--star-bg);box-shadow:0 6px 18px rgba(220,38,38,.12)}
.card .seg{font-size:15px;font-weight:700;display:flex;align-items:center;gap:6px;margin-bottom:7px}
.card.star .seg{color:var(--star)}
.badge{font-size:10px;font-weight:700;color:#fff;background:var(--star);padding:2px 7px;border-radius:6px}
.row{font-size:12.5px;margin:5px 0;display:flex;gap:6px}
.row .k{color:var(--sub);flex:0 0 42px;font-weight:600} .row .v{color:var(--ink);flex:1}
.lead{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}
.chip{font-size:11px;background:#f1f5f9;color:#334155;padding:2px 7px;border-radius:6px;border:1px solid #e2e8f0;white-space:nowrap}
.chip.hot{background:#fff1e6;color:#c2410c;border-color:#fed7aa}
.chip.gov{background:#eef2ff;color:#4338ca;border-color:#c7d2fe}
.code{color:#94a3b8;font-weight:400}
.conn{text-align:center;color:#94a3b8;font-size:18px;margin:-6px 0 8px}
.foot{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;margin-top:18px}
@media(max-width:760px){.foot{grid-template-columns:1fr}}
.panel{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.panel h3{font-size:15px;margin-bottom:10px;display:flex;gap:7px;align-items:center}
.panel h3 .dot{width:9px;height:9px;border-radius:99px;background:var(--star)}
.vtable{width:100%;border-collapse:collapse;font-size:12.5px}
.vtable th,.vtable td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
.vtable th{color:var(--sub);font-weight:600;font-size:11.5px}
.vtable .win{color:var(--star);font-weight:700} .vtable .bad{color:#94a3b8}
ul.why{list-style:none;font-size:13px}
ul.why li{padding:5px 0 5px 22px;position:relative}
ul.why li::before{content:"▸";position:absolute;left:4px;color:var(--star)}
.note{font-size:11px;color:#94a3b8;margin-top:14px;text-align:center}
"""

_GRID = {1: "g1", 2: "g2", 3: "g3", 4: "g4", 5: "g5"}


def _leaders(items):
    out = []
    for it in items or []:
        cls = it.get("cls", "")
        code = it.get("code", "")
        code_html = f' <span class="code">{code}</span>' if code else ""
        out.append(f'<span class="chip{(" " + cls) if cls else ""}">{it.get("t", "")}{code_html}</span>')
    return '<span class="v lead">' + "".join(out) + "</span>"


def _row(r):
    k = r.get("k", "")
    if "leaders" in r:
        return f'<div class="row"><span class="k">{k}</span>{_leaders(r["leaders"])}</div>'
    return f'<div class="row"><span class="k">{k}</span><span class="v">{r.get("v", "")}</span></div>'


def _card(seg):
    star = seg.get("star")
    badge = f'<span class="badge">{seg.get("badge", "最可挖掘")}</span>' if star else ""
    rows = "".join(_row(r) for r in seg.get("rows", []))
    cls = "card star" if star else "card"
    return f'<div class="{cls}"><div class="seg">{seg.get("name", "")}{badge}</div>{rows}</div>'


def _band(b):
    cls = b.get("cls", "mid")
    cols = _GRID.get(int(b.get("cols", 3)), "g3")
    cards = "".join(_card(s) for s in b.get("segments", []))
    return (f'<div class="band {cls}"><div class="band-head">'
            f'<span class="tag">{b.get("layer", "")}</span>'
            f'<span class="desc">{b.get("desc", "")}</span></div>'
            f'<div class="grid {cols}">{cards}</div></div>')


def _footer(spec):
    why = spec.get("why") or {}
    sc = spec.get("scorecard") or {}
    why_items = "".join(f"<li>{x}</li>" for x in why.get("items", []))
    left = (f'<div class="panel"><h3><span class="dot"></span>{why.get("title", "为什么选定本环节")}</h3>'
            f'<ul class="why">{why_items}</ul></div>') if why_items else ""
    rows = ""
    for r in sc.get("rows", []):
        cls = r.get("cls", "")
        tr = f'<tr class="{cls}">' if cls else "<tr>"
        rows += (f'{tr}<td>{r.get("seg", "")}</td><td>{r.get("pe", "")}</td>'
                 f'<td>{r.get("roe", "")}</td><td>{r.get("peg", "")}</td></tr>')
    leaders = f'<p style="font-size:12px;color:#64748b;margin-top:10px"><b>环节龙头：</b>{sc.get("leaders", "")}</p>' if sc.get("leaders") else ""
    right = (f'<div class="panel"><h3><span class="dot"></span>{sc.get("title", "环节估值×盈利速览(TTM)")}</h3>'
             f'<table class="vtable"><tr><th>环节</th><th>PE</th><th>ROE</th><th>PEG</th></tr>'
             f'{rows}</table>{leaders}</div>') if rows else ""
    if not (left or right):
        return ""
    return f'<div class="foot">{left}{right}</div>'


def render(spec: dict) -> str:
    bands = "".join(
        _band(b) + (f'<div class="conn">{b["conn"]}</div>' if b.get("conn") else "")
        for b in spec.get("bands", [])
    )
    meta = spec.get("meta", "PE/ROE 为 TTM ｜ 红框=本轮选定「最可挖掘环节」")
    note = spec.get("note", "本图为投研分析辅助，非投资建议 · 个股仍需过「个股门 + 决策弹药卡」")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{spec.get("theme", "")}产业链全景图 · 主题→环节→标的</title>
<style>{_CSS}</style></head><body><div class="wrap">
<header><h1>{spec.get("theme", "")}产业链全景图</h1>
<div class="flow">三级漏斗 &nbsp;<b>主题</b> → <b>环节</b> → <b>标的</b></div>
<div class="meta">{spec.get("date", "")} ｜ {meta}</div></header>
{bands}{_footer(spec)}
<div class="note">{note}</div>
</div></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="产业链全景图生成器(JSON环节谱→HTML)")
    ap.add_argument("--spec", required=True, help="环节谱 JSON 路径;'-' 表示从 stdin 读")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    args = ap.parse_args(argv)
    raw = sys.stdin.read() if args.spec == "-" else open(args.spec, encoding="utf-8").read()
    spec = json.loads(raw)
    html = render(spec)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[chain_map] 已生成 {args.out} ({len(html)} 字节)")


if __name__ == "__main__":
    sys.exit(main())
