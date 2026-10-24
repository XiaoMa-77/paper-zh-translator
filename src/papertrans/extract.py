"""从 PDF 抽取内容块：文本、标题层级、图、表。

只用 PyMuPDF，不依赖 OCR。对扫描件会在 detect() 里明确报错，而不是悄悄产出空文档。
"""

from __future__ import annotations

import os
import re
from collections import Counter

import pymupdf

from .model import Block, Doc

CAP_FIG = re.compile(r"^(fig\.?|figure)\s*\d+", re.IGNORECASE)
CAP_TAB = re.compile(r"^(table|tab\.)\s*([ivxlcdm]+|\d+)", re.IGNORECASE)
HEAD_NUM = re.compile(r"^(\d+(\.\d+)*\.?|[IVXLC]+\.)\s+\S")
REF_HEAD = re.compile(r"^(references|bibliography|参考文献|r\s*e\s*f\s*e\s*r\s*e\s*n\s*c\s*e\s*s)\s*$", re.IGNORECASE)
JUNK = [
    re.compile(r"^(arxiv:\s*\d)", re.IGNORECASE),
    re.compile(r"^doi[:\s]", re.IGNORECASE),
    re.compile(r"^\d{4}-\d{4}\s*©", re.IGNORECASE),
    re.compile(r"^authorized licensed", re.IGNORECASE),
    re.compile(r"^downloaded on", re.IGNORECASE),
    re.compile(r"^\d{3,4}\s+(ieee|proceedings|journal)", re.IGNORECASE),
    re.compile(r"^[A-Z][A-Z\s\.]{3,}\bet al\.", re.IGNORECASE),
    re.compile(r"^proceedings of the", re.IGNORECASE),
    re.compile(r"^published in", re.IGNORECASE),
    re.compile(r"^\d{1,4}$"),
]
MATH_HINT = set("∈∑∏≤≥→←↔πσ∇·±×÷∞≈≠∪∩⊂⊆ℝθταβλμΔ∂√∫")
MATH_NUM = re.compile(r"\(\s*\d+[a-z]?\s*\)\s*[,.]?$")
RUNIN = re.compile(r"^\d+\)\s+[A-Z]")
INLINE_HEAD = re.compile(r"^((?:[IVXLC]+\.))\s+([A-Z][A-Z\s\-]{2,58}?)\s+(?=[A-Z][a-z])")
ABS_HEAD = re.compile(r"^abstract\b[—\-–:]?", re.IGNORECASE)


def _norm(text: str) -> str:
    """合并断行、去掉行尾连字符、压缩空白。"""
    t = text.replace("\u00ad", "")
    t = re.sub(r"-\n(?=[a-z])", "", t)          # object-\nnavigation -> objectnavigation
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _columns_of(page: pymupdf.Page, blocks: list[tuple]) -> int:
    """判断页面是 1 栏还是 2 栏。"""
    w = page.rect.width
    mid = w / 2
    left = [b for b in blocks if b[2] < mid - 4 and (b[2] - b[0]) < 0.46 * w]
    right = [b for b in blocks if b[0] > mid + 4 and (b[2] - b[0]) < 0.46 * w]
    wide = [b for b in blocks if (b[2] - b[0]) > 0.72 * w]
    crossing = [b for b in blocks if b[0] < mid - 6 and b[2] > mid + 6 and b[1] > 0.3 * page.rect.height]
    if len(left) >= 2 and len(right) >= 2 and len(wide) <= 2 and len(crossing) <= 1:
        return 2
    return 1


def _body_size(spans: list[dict]) -> float:
    c: Counter[float] = Counter()
    for s in spans:
        c[round(s["size"], 1)] += len(s["text"].strip())
    return c.most_common(1)[0][0] if c else 10.0


def _is_bold(span: dict) -> bool:
    name = span.get("font", "").lower()
    return any(k in name for k in ("bold", "black", "semibold", "medi"))


def detect_columns(path: str) -> int:
    with pymupdf.open(path) as doc:
        votes = []
        for page in doc:
            blocks = [b for b in page.get_text("blocks") if b[6] == 0]
            if len(blocks) >= 6:
                votes.append(_columns_of(page, blocks))
        return Counter(votes).most_common(1)[0][0] if votes else 1


def _graphic_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """页面上的位图与矢量图形外框。"""
    rects: list[pymupdf.Rect] = []
    for info in page.get_images(full=True):
        try:
            for r in page.get_image_rects(info[0]):
                if r.width > 20 and r.height > 20:
                    rects.append(r)
        except Exception:
            pass
    try:
        for d in page.get_drawings():
            r = d["rect"]
            if r.width > 12 and r.height > 12:
                rects.append(r)
    except Exception:
        pass
    return rects



def _is_math(text: str) -> bool:
    """公式块的启发式判定：宁可漏判成正文，也不要把正文误判成公式。"""
    t = text.strip()
    if len(t) < 2 or len(t) > 220:
        return False
    if RUNIN.match(t):
        return False
    if t.count("·") >= 3 or t.count(".") == len(t) - t.count(" "):
        return False                      # 图里的点阵/装饰，不是公式
    if any(ch in MATH_HINT for ch in t):
        return True
    if MATH_NUM.search(t):
        return True
    return len(t) < 60 and bool(re.search(r"[=:]", t)) and not t.endswith(".")


def box_height(g) -> float:
    return max(b.y1 for b in g) - min(b.y0 for b in g)


def _extract_equations(result: Doc, doc, out_dir: str, dpi: int, boxes: dict | None = None) -> None:
    """把连续的公式碎片并成一张图，避免它们散落成正文段落。"""
    def _in_box(b) -> bool:
        if not boxes:
            return False
        cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
        return any(r.x0 - 2 <= cx <= r.x1 + 2 and r.y0 - 2 <= cy <= r.y1 + 2
                   for r in boxes.get(b.page, []))

    math_blocks = [b for b in result.blocks
                   if _is_math(b.text) and not b.image and b.width < 0.78 * result.page_size[0]
                   and len(b.text.strip()) < 90 and not _in_box(b)]
    groups: list[list[Block]] = []
    cur: list[Block] = []
    for b in sorted(math_blocks, key=lambda x: (x.page, x.col, x.y0)):
        if cur and cur[-1].page == b.page and cur[-1].col == b.col and b.y0 - cur[-1].y1 < 26:
            cur.append(b)
        else:
            if cur:
                groups.append(cur)
            cur = [b]
    if cur:
        groups.append(cur)

    # 公式常被 PDF 拆成"符号块 + 极短文字块"，把紧邻的短块一并并入图片
    def _absorb(g):
        ext = list(g)
        changed = True
        while changed:
            changed = False
            top, bot = min(x.y0 for x in ext), max(x.y1 for x in ext)
            for b in result.blocks:
                if b in ext or b.image or b.page != g[0].page or b.col != g[0].col:
                    continue
                if len(b.text.strip()) > 28:
                    continue
                if b.y1 > top - 14 and b.y1 < top + 2 or b.y0 < bot + 14 and b.y0 > bot - 2:
                    ext.append(b)
                    changed = True
        return ext

    groups = [_absorb(g) for g in groups]

    n = 0
    for g in groups:
        txt = " ".join(b.text for b in g)
        strong = (any(any(ch in MATH_HINT for ch in b.text) for b in g)
                  or bool(MATH_NUM.search(g[-1].text))
                  or (len(txt) < 42 and "=" in txt and len(txt.split()) <= 6))
        if box_height(g) < 9:
            strong = False
        if not strong and len(g) < 2:
            continue
        box = pymupdf.Rect(g[0].x0, g[0].y0, g[0].x1, g[0].y1)
        for b in g[1:]:
            box |= pymupdf.Rect(b.x0, b.y0, b.x1, b.y1)
        box = pymupdf.Rect(box.x0 - 2, box.y0 - 2, box.x1 + 2, box.y1 + 2) & doc[g[0].page].rect
        if box.height < 8:
            continue
        n += 1
        rel = f"fig/eq{n}.png"
        doc[g[0].page].get_pixmap(clip=box, dpi=dpi).save(os.path.join(out_dir, rel))
        first = g[0]
        eqb = Block(id=first.id, page=first.page, kind="equation", text="", x0=box.x0, y0=box.y0,
                    x1=box.x1, y1=box.y1, col=first.col, image=rel)
        idx = result.blocks.index(first)
        for b in g:
            result.blocks.remove(b)
        result.blocks.insert(idx, eqb)
        result.assets[eqb.id] = rel


def _span_size(page_spans, rect) -> float:
    box = pymupdf.Rect(rect[:4])
    sizes = [s["size"] for r, s in page_spans if r.intersects(box)]
    return max(sizes) if sizes else 0.0


def _group_rects(rects: list[pymupdf.Rect], gap: float = 14.0) -> list[pymupdf.Rect]:
    """把图形按纵向邻接聚成组，一组通常就是一张图或一张表。"""
    rs = sorted([r for r in rects if r.get_area() > 0], key=lambda r: (r.y0, r.x0))
    groups: list[pymupdf.Rect] = []
    for r in rs:
        placed = False
        for g in groups:
            if r.y0 <= g.y1 + gap and r.y1 >= g.y0 - gap:
                g |= r
                placed = True
                break
        if not placed:
            groups.append(pymupdf.Rect(r))
    # 合并后可能产生新的邻接，做一轮收敛
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                if a.y0 <= b.y1 + gap and a.y1 >= b.y0 - gap:
                    groups[i] = a | b
                    groups.pop(j)
                    changed = True
                    break
            if changed:
                break
    return groups


def _figure_box(rects: list[pymupdf.Rect], clip: pymupdf.Rect,
                page_rect: pymupdf.Rect) -> pymupdf.Rect:
    """在给定带内找图形区域：过滤页面级背景框，并裁剪回带内。"""
    cand: list[pymupdf.Rect] = []
    for r in rects:
        if r.get_area() <= 0:
            continue
        if r.width > 0.97 * page_rect.width and r.height > 0.25 * page_rect.height:
            continue                      # 背景/外框
        inter = r & clip
        if inter.is_empty or inter.get_area() <= 0:
            continue
        if inter.get_area() < 0.25 * r.get_area():
            continue                      # 只是擦边
        cand.append(inter)
    if not cand:
        return clip
    box = cand[0]
    for r in cand[1:]:
        box |= r
    box = box & clip & page_rect
    return box if box.height > 24 and box.width > 40 else clip


def _table_rows(page_pl, box: pymupdf.Rect) -> list[list[str]] | None:
    """pdfplumber 重建表格结构，多策略尝试、按非空格子数择优。

    严格置信度：至少 2 行 2 列、非空格子过半，否则返回 None 回退为整图。
    宁可保留图片，也不要把正文误判成表格。
    """
    if page_pl is None:
        return None
    try:
        region = page_pl.crop((box.x0, box.y0, box.x1, box.y1))
        candidates: list[list] = []
        for cfg in ({"vertical_strategy": "text", "horizontal_strategy": "lines"},   # booktabs 首选
                    {"vertical_strategy": "text", "horizontal_strategy": "text"}):   # 无线表的兜底
            candidates.extend(region.extract_tables(cfg))
        if not candidates:
            return None
        best = max(candidates, key=lambda t: sum(1 for r in t for c in r if c and c.strip()))
        rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in best]
        rows = [r for r in rows if any(r)]
        n_cells = sum(len(r) for r in rows)
        filled = sum(1 for r in rows for c in r if c)
        if len(rows) < 2 or min(len(r) for r in rows) < 2 or n_cells < 6:
            return None
        if filled / n_cells < 0.5:
            return None
        width = max(len(r) for r in rows)
        return [r + [""] * (width - len(r)) for r in rows]
    except Exception:
        return None


def extract(path: str, out_dir: str, dpi: int = 320, columns: int | None = None,
            tables: str = "auto") -> Doc:
    """抽取整篇 PDF。图片写入 out_dir/fig，返回 Doc。"""
    os.makedirs(os.path.join(out_dir, "fig"), exist_ok=True)
    doc = pymupdf.open(path)

    text_chars = sum(len(p.get_text().strip()) for p in doc)
    if text_chars < 400:
        raise RuntimeError(
            "该 PDF 几乎没有文字层，可能是扫描件。请先 OCR（v2 计划接入 PaddleOCR），"
            "不要用本工具硬跑——输出的空译文比报错更危险。"
        )

    cols = columns or detect_columns(path)
    result = Doc(source=os.path.abspath(path), page_size=(doc[0].rect.width, doc[0].rect.height), columns=cols)
    ov_path = os.path.join(out_dir, "overrides.json")
    overrides = {}
    if os.path.exists(ov_path):
        import json as _json
        with open(ov_path, encoding="utf-8") as f:
            overrides = _json.load(f)

    # 全篇正文字号
    all_spans: list[dict] = []
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b["type"] == 0:
                for line in b["lines"]:
                    all_spans.extend(line["spans"])
    body = _body_size(all_spans)

    bid = 0
    in_refs = False
    fig_no = 0
    tab_no = 0
    boxes: dict[int, list[pymupdf.Rect]] = {}
    plumber = None          # pdfplumber 句柄，首次遇到表格时才懒加载
    for pno, page in enumerate(doc):
        pw = page.rect.width
        mid = pw / 2
        raw = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        raw.sort(key=lambda b: (0 if (cols == 1 or b[0] < mid) else 1, b[1], b[0]))
        graphics = _graphic_rects(page)
        page_spans = [(pymupdf.Rect(line["bbox"]), s) for blk in page.get_text("dict")["blocks"]
                      if blk["type"] == 0 for line in blk["lines"] for s in line["spans"]]

        # 页面上的文字块按阅读顺序排好后，逐块判断类型
        for i, b in enumerate(raw):
            x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], _norm(b[4])
            if not txt:
                continue
            box0 = pymupdf.Rect(x0, y0, x1, y1)
            spans = [s for r, s in page_spans if r.intersects(box0)]
            size = max((s["size"] for s in spans), default=body)
            bold = any(_is_bold(s) for s in spans)
            wide = (x1 - x0) > 0.72 * pw
            col = 0 if (cols == 1 or (x0 + x1) / 2 < mid) else 1

            kind = "body"
            if CAP_FIG.match(txt):
                kind = "caption"
            elif CAP_TAB.match(txt):
                kind = "table"
            elif REF_HEAD.match(txt):
                in_refs = True
                kind = "refs"
            elif pno == 0 and size >= body * 1.6 and y0 < page.rect.height * 0.3:
                kind = "title"
            elif ABS_HEAD.match(txt) and len(txt) < 40:
                kind = "abstract"
            elif HEAD_NUM.match(txt) and len(txt) < 120 and (bold or size > body * 1.05):
                kind = "heading1" if re.match(r"^(\d+\.?|[IVXLC]+\.)\s", txt) else "heading2"
            elif bold and len(txt) < 90 and size >= body * 0.95:
                kind = "heading2"
            if in_refs and kind == "body":
                kind = "refs"

            blk = Block(id=f"b{bid:04d}", page=pno, kind=kind, text=txt,
                        x0=x0, y0=y0, x1=x1, y1=y1, col=col, size=size, bold=bold,
                        full_width=wide)
            bid += 1

            # 图：题注上方最近的一组图形就是这张图（题注常被跨栏合并，不能作依据）
            if kind == "caption":
                groups = [g for g in _group_rects(graphics) if g.y1 <= y0 + 6 and g.height > 24]
                above = [g for g in groups if y0 - 30 <= g.y1 <= y0 + 6]
                if above:
                    box = max(above, key=lambda g: g.y1)
                    # 向上吸附到相邻组，拼回被切开的整图
                    for g in sorted([x for x in groups if x.y1 < box.y0 + 4], key=lambda x: -x.y1):
                        if box.y0 - g.y1 <= 24:
                            box |= g
                        else:
                            break
                else:
                    top = max(40, y0 - 300)
                    body_above = [r[3] for r in raw if r[3] < y0 - 2 and r[3] > top
                                  and len(r[4].strip()) > 60 and _span_size(page_spans, r) >= body * 0.9]
                    if body_above:
                        top = max(body_above) + 3
                    box = pymupdf.Rect(45, top, pw - 45, y0 - 2)
                if box.height > 340:
                    box = pymupdf.Rect(box.x0, y0 - 340, box.x1, y0 - 2)
                if blk.id in overrides:
                    box = pymupdf.Rect(*overrides[blk.id])
                if box.width > 0.55 * pw:                     # 宽图统一给整幅页宽
                    box = pymupdf.Rect(45, box.y0, pw - 45, box.y1)
                    blk.full_width = True
                fig_no += 1
                rel = f"fig/fig{fig_no}.png"
                pix = page.get_pixmap(clip=box, dpi=dpi)
                pix.save(os.path.join(out_dir, rel))
                result.assets[blk.id] = rel
                blk.image = rel
                blk.meta["bbox"] = [round(v, 1) for v in box]
                boxes.setdefault(pno, []).append(pymupdf.Rect(box))

            # 表：题注下方区域。auto 模式先尝试 pdfplumber 重建为可编辑表格，
            # 置信度不足（无横线/行列太少/格子太空）则回退为整图
            if kind == "table":
                groups = [g for g in _group_rects(graphics) if g.height > 24]
                below = [g for g in groups if y1 - 2 <= g.y0 <= y1 + 26]
                if below:                                     # 只接受紧贴题注下方的成组图形
                    box = min(below, key=lambda g: g.y0)
                    if box.height > 420:
                        box = pymupdf.Rect(box.x0, box.y0, box.x1, box.y0 + 420)
                    if box.width > 0.55 * pw:
                        box = pymupdf.Rect(45, box.y0, pw - 45, box.y1)
                        blk.full_width = True
                else:                                         # 无矢量线时退到"题注到下一段正文"的带状区域
                    nxt = [r[1] for r in raw[i + 1:] if r[1] > y1 + 4
                           and _span_size(page_spans, r) >= body * 0.9]
                    bottom = (min(nxt) - 2) if nxt else min(y1 + 220, page.rect.height - 40)
                    narrow = (x1 - x0) < 0.55 * pw
                    x_lo, x_hi = ((45, mid) if (narrow and x0 < mid) else (mid, pw - 45)) if narrow else (45, pw - 45)
                    box = pymupdf.Rect(x_lo, y1 + 2, x_hi, bottom if bottom - y1 > 28 else min(y1 + 200, page.rect.height - 40))
                tab_no += 1
                rows = None
                if tables == "auto":
                    if plumber is None:
                        try:
                            import pdfplumber
                            plumber = pdfplumber.open(path)
                        except ImportError:
                            plumber = False    # 未安装：一直走图片回退
                    page_pl = plumber.pages[pno] if plumber else None
                    rows = _table_rows(page_pl, box)
                if rows:
                    blk.meta["table_data"] = rows
                    blk.meta["bbox"] = [round(v, 1) for v in box]
                    # 格子文字已在结构里，同样要剔除区域内的原文本块，避免与表格重复
                    boxes.setdefault(pno, []).append(pymupdf.Rect(box))
                elif box is not None and box.height > 24:
                    rel = f"fig/tab{tab_no}.png"
                    page.get_pixmap(clip=box, dpi=dpi).save(os.path.join(out_dir, rel))
                    result.assets[blk.id] = rel
                    blk.image = rel
                    blk.meta["bbox"] = [round(v, 1) for v in box]
                    boxes.setdefault(pno, []).append(pymupdf.Rect(box))

            result.blocks.append(blk)

    _extract_equations(result, doc, out_dir, dpi, boxes)
    result.blocks = _postprocess(result.blocks, body, boxes)
    for n, b in enumerate(result.blocks):
        b.id = f"b{n:04d}"
    if plumber:
        plumber.close()
    return result


def _postprocess(blocks: list[Block], body: float, boxes: dict | None = None) -> list[Block]:
    """清洗：去页眉页脚/arXiv 戳/版权行，拆出内联标题，识别摘要与题名。"""
    kept: list[Block] = []
    for b in blocks:
        if b.kind in ("equation", "figure"):
            kept.append(b)
            continue
        t = b.text
        if any(p.match(t) for p in JUNK):
            continue
        if len(t) < 3:
            continue
        # 落在图/表裁剪框内的文字，已经进了图片，必须剔除，否则与图重复
        if boxes and b.kind not in ("caption", "table"):
            cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
            if any((r.x0 - 2 <= cx <= r.x1 + 2 and r.y0 - 2 <= cy <= r.y1 + 2) for r in boxes.get(b.page, [])):
                continue
        # 摘要：去掉前缀单独成块
        if ABS_HEAD.match(t):
            body_text = ABS_HEAD.sub("", t).strip(" —-–:")
            b.kind = "abstract"
            b.text = body_text
            kept.append(b)
            continue
        # 标题与正文被 PyMuPDF 合成一个块时拆开
        m = INLINE_HEAD.match(t)
        if m and b.kind in ("body", "heading1", "heading2"):
            head = f"{m.group(1)} {m.group(2)}".strip()
            rest = t[m.end():].strip()
            hb = Block(id=b.id + "h", page=b.page, kind="heading1" if m.group(1)[0] in "IVXLC" else "heading2",
                       text=head, x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y0 + b.size * 1.6,
                       col=b.col, size=b.size, bold=True, full_width=b.full_width)
            kept.append(hb)
            if rest:
                b.text = rest
                b.y0 = b.y0 + b.size * 1.6
                kept.append(b)
            continue
        kept.append(b)

    # 题名：首页最大字号、且位于页面上部
    first = [b for b in kept if b.page == 0]
    cand = [b for b in first if b.size >= body * 1.35 and b.y0 < 260]
    if cand:
        top = max(b.size for b in cand)
        title_blocks = [b for b in cand if abs(b.size - top) < 0.6]
        title_blocks.sort(key=lambda b: b.y0)
        merged = title_blocks[0]
        merged.text = " ".join(b.text for b in title_blocks)
        merged.kind = "title"
        merged.full_width = True
        for b in title_blocks[1:]:
            kept.remove(b)
        # 题名之后紧跟的作者行
        idx = kept.index(merged)
        if idx + 1 < len(kept):
            nxt = kept[idx + 1]
            if nxt.size >= body * 0.95 and len(nxt.text) < 300 and not nxt.text.endswith("."):
                nxt.kind = "authors"
    return kept
