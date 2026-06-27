"""候选召回：合并 LLM 点名 ∪ 概念板块兜底(best-effort)，按代码去重并打 source 标签。
merge_candidates 是纯逻辑(可单测)；build_board_candidates 联网取板块成分(best-effort)。"""
from __future__ import annotations


def merge_candidates(llm: list[dict], board: list[dict]) -> list[dict]:
    """llm: [{code,name}], board: [{code,name,mktcap_yi?,board?}] → 合并去重，source∈{llm,board,both}。"""
    by: dict[str, dict] = {}
    for c in board:
        by[c["code"]] = {**c, "source": "board"}
    for c in llm:
        if c["code"] in by:
            by[c["code"]]["source"] = "both"
        else:
            by[c["code"]] = {"code": c["code"], "name": c.get("name", c["code"]), "source": "llm"}
    return list(by.values())


def build_board_candidates(boards: list[str], source) -> list[dict]:
    """对 Claude 选定的概念板块名列表，逐个拉成分股(best-effort)，合并去重(代码)。source: DataSource。"""
    by: dict[str, dict] = {}
    for b in boards:
        try:
            for c in source.board_constituents(b):
                by.setdefault(c["code"], c)
        except Exception as e:
            print(f"[recall] 板块 {b} 拉取失败，跳过：{str(e)[:60]}")
    return list(by.values())
