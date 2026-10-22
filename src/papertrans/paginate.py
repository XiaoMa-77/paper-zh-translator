"""块级分页：实测高度 → 装满两栏 → 跨栏块放不下时挂起（类似浮动体）。

这套算法是四篇译文版式稳定的关键，不要用 CSS 多栏的 column-span 代替：
Chromium 在分页边界会把后续内容挤到下一页，留下大片空白。
"""

from __future__ import annotations

import os

from .render import measure_blocks

COLCAP = 676.0
EPS = 56.0


def _is_span(block_html: str) -> bool:
    head = block_html[:160]
    return 'class="full' in head or 'class="head' in head


def paginate(blocks: list[str], heights: list[float]) -> list[list[dict]]:
    pages: list[list[dict]] = [[]]
    used = 0.0
    pending: list[tuple[str, float]] = []
    cur = {"blocks": [], "cap": COLCAP, "total": 0.0}
    pages[0].append(cur)

    def flow_height() -> float:
        return min(cur["cap"], cur["total"] / 2 + 10)

    def close_flow() -> None:
        nonlocal used
        if cur["blocks"]:
            cur["h"] = flow_height()
            used += cur["h"]
        elif cur in pages[-1]:
            pages[-1].remove(cur)

    def start_flow() -> None:
        nonlocal cur
        cur = {"blocks": [], "cap": COLCAP - used, "total": 0.0}
        pages[-1].append(cur)

    def new_page(flush: bool = True) -> None:
        nonlocal used, cur
        if cur["blocks"]:
            close_flow()
        pages.append([])
        used = 0.0
        cur = {"blocks": [], "cap": COLCAP, "total": 0.0}
        pages[-1].append(cur)
        if flush and pending:
            b, h = pending.pop(0)
            pages[-1].append({"span": b, "h": h})
            used += h + 6
            start_flow()

    for b, h in zip(blocks, heights):
        if _is_span(b):
            y = used + (flow_height() if cur["blocks"] else 0.0)
            if y + h <= COLCAP - EPS:
                close_flow()
                pages[-1].append({"span": b, "h": h})
                used += h + 6
                start_flow()
            else:
                pending.append((b, h))
        else:
            cap2 = 2 * cur["cap"] - EPS
            if cur["total"] + h <= cap2:
                cur["blocks"].append(b)
                cur["total"] += h
            else:
                new_page()
                cur["blocks"].append(b)
                cur["total"] += h

    if cur["blocks"]:
        cur["h"] = flow_height()
    elif cur in pages[-1]:
        pages[-1].remove(cur)
    while pending:
        b, h = pending.pop(0)
        pages.append([{"span": b, "h": h}])

    out: list[list[dict]] = []
    for p in pages:
        p[:] = [r for r in p if r.get("span") or r["blocks"]]
        if p:
            out.append(p)
    return out


def render_pages(pages: list[list[dict]]) -> str:
    o: list[str] = []
    for i, p in enumerate(pages):
        cls = "page last" if i == len(pages) - 1 else "page"
        o.append(f'<div class="{cls}">')
        for ri, r in enumerate(p):
            if r.get("span"):
                o.append(f'<div class="full">{r["span"]}</div>')
            else:
                h = r["cap"] if ri == len(p) - 1 else r["h"]
                o.append(f'<div class="flow" style="height:{h:.1f}pt">' + "".join(r["blocks"]) + "</div>")
        o.append("</div>")
    return "\n".join(o)


def build_pages(blocks: list[str], css: str, workdir: str) -> tuple[str, int]:
    heights = measure_blocks(blocks, css, workdir)
    pages = paginate(blocks, heights)
    return render_pages(pages), len(pages)
