"""把 Doc 组装成双栏 HTML。版式参数与已交付成品保持一致，不在此处做任何"创意"。"""

from __future__ import annotations

import html
import os
import re

from .model import Block, Doc

CSS = r"""
@page { size: letter; margin: 60pt 49pt 56pt 49pt; }
html, body { margin:0; padding:0; }
body { font-family:"Noto Serif CJK SC","Source Han Serif SC","Times New Roman","SimSun","Songti SC",serif;
       font-size:10pt; line-height:1.30; text-align: justify; text-justify: inter-ideograph; }
.page { height:676pt; position:relative; break-after:page; overflow:hidden; }
.page.last { break-after:auto; }
.flow { column-count:2; column-gap:13pt; column-fill:balance; }
.full { width:514pt; }
.page > .full { display:flow-root; }
p { margin:0 0 4.2pt 0; text-indent:2em; }
p.noind { text-indent:0; }
.head { text-align:center; margin-bottom:8pt; }
h1.title { font-size:19pt; font-weight:bold; line-height:1.30; margin:0 0 10pt 0; text-align:center; }
.authors { font-size:10.5pt; margin-bottom:4pt; text-align:center; }
.affil { font-size:8.5pt; text-align:center; margin-bottom:2pt; }
.abstract { font-size:9pt; line-height:1.28; margin:0 0 8pt 0; }
.abstract p { text-indent:0; margin-bottom:5pt; }
.abstract .lead { font-weight:bold; font-style:italic; }
.footnote { font-size:7.4pt; line-height:1.24; border-top:0.5pt solid #999; padding-top:4pt; margin:6pt 0 8pt 0; }
.footnote p { text-indent:0; margin-bottom:3pt; }
h2.sec { font-size:10.5pt; font-weight:bold; margin:9pt 0 4pt 0; break-after:avoid; }
h3.sub { font-size:10pt; font-weight:bold; font-style:italic; margin:8pt 0 3.5pt 0; break-after:avoid; }
figure { margin:7pt 0 8pt 0; break-inside:avoid; }
figure img { width:100%; display:block; }
figcaption { font-size:8pt; line-height:1.26; margin-top:4pt; text-align:justify; text-indent:0; }
figcaption .lab { font-weight:bold; }
.tabwrap { margin:7pt 0 8pt 0; font-size:7.6pt; line-height:1.2; break-inside:avoid; }
.tcap { text-align:center; margin-bottom:3pt; }
.tcap .lab { font-size:8pt; font-weight:bold; display:block; }
.tcap .ttl { font-size:7.8pt; display:block; margin-top:1pt; }
table { width:100%; border-collapse:collapse; font-size:7.4pt; }
table th, table td { padding:1.4pt 2pt; text-align:center; white-space:normal; }
table th { font-weight:bold; }
thead tr:first-child th { border-top:1pt solid #000; }
thead tr:last-child th { border-bottom:0.6pt solid #000; }
tbody tr:last-child td { border-bottom:1pt solid #000; }
tbody tr.last td { border-bottom:1pt solid #000; }
tbody tr.top td { border-top:0.6pt solid #000; }
.b { font-weight:bold; }
.u { text-decoration: underline; }
.l { text-align:left !important; }
.eq { margin:6pt 0; font-size:10pt; position:relative; break-inside:avoid; }
.eq .mathline { text-align:center; }
.eq .num { position:absolute; right:0; top:50%; transform:translateY(-50%); }
math { font-size:10.2pt; font-family:"Latin Modern Math","Cambria Math","Times New Roman",serif; }
p.refitem { font-size:8pt; line-height:1.2; text-indent:-16pt; margin:0 0 1.5pt 16pt; text-align:left; break-inside:avoid; overflow-wrap:anywhere; }
h2.reftitle { font-size:9pt; font-weight:bold; margin:12pt 0 5pt 0; letter-spacing:1pt; break-after:avoid; }
"""


def _e(text: str) -> str:
    return html.escape(text, quote=False)


def _figure(b: Block, alt: str) -> str:
    cls = "full" if (b.full_width or b.width > 300) else ""
    cap = _e(b.zh or b.text)
    m = re.match(r"^((?:fig\.?|figure)\s*\d+[.:]?)\s*(.*)$", cap, re.IGNORECASE)
    lab, body = (m.group(1), m.group(2)) if m else ("", cap)
    return (
        f'<figure class="{cls}">\n<img src="{alt}" alt="">\n'
        f'<figcaption><span class="lab">{lab}</span> {body}</figcaption>\n</figure>'
    )


def _img_style(b: Block) -> str:
    """图片按它在 PDF 里的物理宽度显示，别把窄公式拉满栏宽。

    截图是 320dpi 的位图，不给 width 时浏览器按内在尺寸排版，
    窄公式会被放大两三倍，"where a_t" 这种行内碎片能占掉四行。
    """
    cap = 514.0 if b.full_width else 250.5
    bbox = b.meta.get("bbox")
    image_width = bbox[2] - bbox[0] if bbox and len(bbox) == 4 else b.width
    w = min(image_width + 4, cap) if image_width > 1 else cap
    return f"width:{w:.1f}pt;max-width:100%;height:auto"


def _table(b: Block, alt: str) -> str:
    cls = "tabwrap" + (" full" if (b.full_width or b.width > 300) else "")
    cap = _e(b.zh or b.text)
    m = re.match(r"^((?:table|tab\.)\s*[ivxlcdm\d]+[.:]?)\s*(.*)$", cap, re.IGNORECASE)
    lab, body = (m.group(1), m.group(2)) if m else ("", cap)
    rows = b.meta.get("table_data") or []
    if rows:
        # 结构化表格：pdfplumber 重建的行列，单元格保留原文（数字与术语不译）
        thead = "".join(f"<th>{_e(c)}</th>" for c in rows[0])
        trs = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
        inner = f"<table><thead><tr>{thead}</tr></thead><tbody>{trs}</tbody></table>"
    else:
        inner = f'<img src="{alt}" alt="" style="{_img_style(b)}">' if alt else ""
    return (
        f'<div class="{cls}">\n<div class="tcap"><span class="lab">{lab}</span>'
        f'<span class="ttl">{body}</span></div>\n{inner}\n</div>'
    )


def to_html_blocks(doc: Doc) -> list[str]:
    """Doc -> 一串顶层 HTML 块（供分页器消费）。"""
    out: list[str] = []
    head_parts: list[str] = []
    ref_head_done = False

    for b in doc.blocks:
        text = b.zh or b.text
        if b.kind == "title":
            head_parts.append(f'<h1 class="title">{_e(text)}</h1>')
            continue
        if b.kind == "authors":
            head_parts.append(f'<div class="authors">{_e(text)}</div>')
            continue

        if b.kind == "abstract":
            has_cjk = bool(re.search(r"[\u4e00-\u9fff]", b.zh or ""))
            lead = "摘要——" if has_cjk else "Abstract—"
            out.append(f'<div class="abstract"><p><span class="lead">{lead}</span>{_e(text)}</p></div>')
        elif b.kind == "heading1":
            out.append(f'<h2 class="sec">{_e(text)}</h2>')
        elif b.kind == "heading2":
            out.append(f'<h3 class="sub">{_e(text)}</h3>')
        elif b.kind in ("equation", "algorithm") and b.image:
            out.append(f'<div class="eq"><div class="mathline"><img src="{b.image}" style="{_img_style(b)}"></div></div>')
        elif b.kind == "caption" and b.image:
            out.append(_figure(b, b.image))
        elif b.kind == "table" and (b.image or b.meta.get("table_data")):
            out.append(_table(b, b.image))
        elif b.kind == "refs":
            # 只有小节标题该用 h2；条目必须用小字悬挂缩进，否则每条参考文献
            # 都会带上标题的行间距，参考表会被撑成两倍长
            is_heading = bool(re.fullmatch(r"references|bibliography|参考文献", b.text.strip(), re.IGNORECASE))
            if not ref_head_done:
                heading = text if is_heading else "References"
                out.append(f'<h2 class="reftitle">{_e(heading)}</h2>')
                ref_head_done = True
            if not is_heading:
                for item in re.split(r"(?=\[\d+\](?:\s|$))", text):
                    if item.strip():
                        out.append(f'<p class="refitem">{_e(item.strip())}</p>')
        elif b.text.lstrip().startswith("•") or b.text.lstrip().startswith("-"):
            out.append(f'<p class="noind">{_e(text)}</p>')
        else:
            out.append(f"<p>{_e(text)}</p>")

    if head_parts:
        out.insert(0, '<div class="head">' + "".join(head_parts) + "</div>")
    return out


def document(blocks: list[str], title: str = "论文中文译文") -> str:
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body>\n"
        + "\n".join(blocks)
        + "\n</body></html>\n"
    )


def write_preview(doc: Doc, workdir: str, blocks: list[str]) -> str:
    """不分页的单页预览（调试用，能快速看出抽取/翻译对不对）。"""
    path = os.path.join(workdir, "preview.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(document(blocks, os.path.basename(doc.source)))
    return path
