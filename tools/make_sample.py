"""生成一个合成的双栏"论文"样本，用于演示与回归测试。

为什么不直接放真实论文的译文：整篇翻译属于演绎作品，放进公开仓库有版权风险。
这个样本是自己画的，可以随便分发，也正好当 extract.py 的回归基准。

用法：python tools/make_sample.py
产出：samples/toy-paper.pdf
"""

from __future__ import annotations

import os

import pymupdf

W, H = 612, 792
LEFT, RIGHT = 54, 306          # 两栏的起始 x
COLW = 236
BODY = 9.2
LEAD = 12.4

TITLE = "A Toy Study of Layout-Preserving PDF Translation"
AUTHORS = "Ada Example, Bo Sample and Cy Demo"

ABSTRACT = (
    "Translating an academic paper is easy; keeping its layout is not. Columns, floating "
    "figures, tables and numbered equations all move when the text changes length. This "
    "toy paper exists so that a layout-preserving translation pipeline can be exercised "
    "end to end without shipping anyone else's copyrighted work. It contains two columns, "
    "one full-width caption, one table and one numbered equation."
)

INTRO = [
    "Object navigation and document translation look unrelated, yet both are exercises in "
    "keeping a structured representation consistent while its contents change. In this "
    "paper we describe a deliberately small example that stresses the parts of a PDF that "
    "a naive text-replacement pipeline usually breaks: column order, figure anchoring, and "
    "table cell counts.",

    "Our pipeline treats layout as code and language as data. The renderer never asks a "
    "language model where a paragraph should go, and the translator never sees a "
    "coordinate. Keeping that separation makes failures diagnosable: a wrong crop is a "
    "geometry bug, a wrong sentence is a prompting bug, and the two never hide each other.",

    "The second reason is regression testing. Once the geometry is deterministic, a change "
    "to the extractor either reproduces the same boxes or it does not, and that difference "
    "can be reviewed in seconds instead of by reading a diff of coordinates.",
]

METHOD = [
    "We extract text blocks together with their bounding boxes, classify each block as "
    "title, heading, body, caption or table, and then rebuild the page in HTML. Every "
    "block is measured in a real browser before pagination, because estimating line breaks "
    "from character counts is wrong often enough to matter.",

    "Figures are anchored to their captions: the graphic group that sits closest above a "
    "caption is almost always the figure that caption describes. Tables are anchored the "
    "other way, since table captions sit above the table in most venues.",
]

RESULTS = (
    "On the toy sample the pipeline reproduces both columns, keeps the figure above its "
    "caption, preserves the table's three columns, and leaves the equation as an image so "
    "that its indices cannot be mistyped."
)


def wrap(text: str, width: float, size: float) -> list[str]:
    """按可用宽度断行（Helvetica 用 get_text_length 精确测量）。"""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if pymupdf.get_text_length(trial, fontname="helv", fontsize=size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_par(page, x, y, text, size=BODY, width=COLW, lead=LEAD, font="helv"):
    for line in wrap(text, width, size):
        page.insert_text((x, y), line, fontname=font, fontsize=size)
        y += lead
    return y


def build() -> str:
    os.makedirs("samples", exist_ok=True)
    doc = pymupdf.open()
    p1 = doc.new_page(width=W, height=H)

    p1.insert_text((W / 2 - pymupdf.get_text_length(TITLE, "hebo", 16) / 2, 92), TITLE,
                   fontname="hebo", fontsize=16)
    p1.insert_text((W / 2 - pymupdf.get_text_length(AUTHORS, "helv", 9.5) / 2, 112), AUTHORS,
                   fontname="helv", fontsize=9.5)

    y = draw_par(p1, LEFT, 150, "Abstract— " + ABSTRACT, size=8.6, lead=11.4, font="heit")
    y += 8
    y = draw_par(p1, LEFT, y, "1. Introduction", size=10.5, font="hebo", lead=14)
    for para in INTRO:
        y += 2
        y = draw_par(p1, LEFT, y, para)
    y += 2
    y += 6
    p1.insert_text((LEFT + 42, y), "C = (1/N) * SUM p_i * d_i", fontname="helv", fontsize=9.2)
    p1.insert_text((LEFT + COLW - 22, y), "(1)", fontname="helv", fontsize=9.2)

    # 右栏：方法 + 图
    ry = draw_par(p1, RIGHT, 150, "2. Method", size=10.5, font="hebo", lead=14)
    for para in METHOD:
        ry += 2
        ry = draw_par(p1, RIGHT, ry, para)

    fig = pymupdf.Rect(RIGHT, ry + 10, RIGHT + COLW, ry + 118)
    p1.draw_rect(fig, color=(0.25, 0.3, 0.35), width=1)
    p1.draw_rect(pymupdf.Rect(fig.x0 + 16, fig.y0 + 52, fig.x0 + 96, fig.y0 + 96),
                 color=(0.45, 0.5, 0.55), fill=(0.93, 0.94, 0.95), width=0.8)
    p1.draw_rect(pymupdf.Rect(fig.x0 + 118, fig.y0 + 30, fig.x0 + 200, fig.y0 + 96),
                 color=(0.45, 0.5, 0.55), fill=(0.9, 0.93, 0.95), width=0.8)
    p1.draw_line(pymupdf.Point(fig.x0 + 96, fig.y0 + 74), pymupdf.Point(fig.x0 + 118, fig.y0 + 74),
                 color=(0.2, 0.2, 0.2), width=1.2)
    p1.insert_text((fig.x0 + 8, fig.y0 + 16), "agent", fontname="helv", fontsize=7.5)
    p1.insert_text((fig.x0 + 126, fig.y0 + 22), "memory", fontname="helv", fontsize=7.5)
    draw_par(p1, RIGHT, fig.y1 + 12,
             "Fig. 1: A schematic figure that must stay above its own caption after "
             "reflowing.", size=7.8, lead=9.6, font="heit")

    # 第二页：表格 + 公式 + 结果 + 参考文献
    p2 = doc.new_page(width=W, height=H)
    y2 = draw_par(p2, LEFT, 80, "3. Results", size=10.5, font="hebo", lead=14)
    y2 = draw_par(p2, LEFT, y2 + 2, RESULTS)

    y2 = draw_par(p2, LEFT, y2 + 10, "Table 1: Toy results.", size=7.8, font="hebo", lead=9.6)
    rows = [("Method", "SPL", "Success"), ("Baseline", "31.2", "48.5"),
            ("Ours", "37.4", "55.8")]
    ty = y2 + 6
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            p2.insert_text((LEFT + j * 78, ty), cell,
                           fontname="hebo" if i == 0 else "helv", fontsize=8.4)
        p2.draw_line(pymupdf.Point(LEFT, ty + 6), pymupdf.Point(LEFT + 228, ty + 6),
                     color=(0, 0, 0), width=0.6 if i == 0 else 0.3)
        ty += 18
    p2.draw_line(pymupdf.Point(LEFT, ty + 6), pymupdf.Point(LEFT + 228, ty + 6),
                 color=(0, 0, 0), width=1.0)

    ey = draw_par(p2, RIGHT, 80, "The expected cost of a visit order is", width=COLW)
    p2.insert_text((RIGHT + 30, ey + 8), "E = sum p_i * d(o_i-1, o_i)          (2)",
                   fontname="helv", fontsize=9.2)

    draw_par(p2, RIGHT, ey + 40, "Equation (2) is kept as a picture so that subscripts "
                                 "cannot be mistyped during translation.", width=COLW)

    ref_y = draw_par(p2, RIGHT, 300, "References", size=10.5, font="hebo", lead=14)
    for i, ref in enumerate([
        "[1] A. Example. Layout as code, language as data. In Proc. Toy Conf., 2026.",
        "[2] B. Sample. Measuring blocks before pagination. arXiv:0000.00000, 2026.",
    ]):
        ref_y = draw_par(p2, RIGHT, ref_y + 2, ref, size=7.8, lead=9.6)

    out = os.path.join("samples", "toy-paper.pdf")
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    print(build())
