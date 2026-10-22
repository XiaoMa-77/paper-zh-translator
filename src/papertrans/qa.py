"""质检：没有证据的"看起来对"一律不算通过。"""

from __future__ import annotations

import re
from collections import Counter

import pymupdf

from .model import Doc

NUM = re.compile(r"\d+(?:[.,]\d+)*%?")
TRANSLATABLE = {"title", "abstract", "heading1", "heading2", "body", "caption", "table"}
CJK = re.compile(r"[\u4e00-\u9fff]")


def check_doc(doc: Doc, source_pdf: str | None = None, rendered_pdf: str | None = None) -> dict:
    tr = [b for b in doc.blocks if b.kind in TRANSLATABLE and b.text.strip()]
    untranslated = [b.id for b in tr if not b.zh.strip()]
    zh_chars = sum(len(b.zh) for b in tr)
    src_chars = sum(len(b.text) for b in tr)
    cjk_ratio = (len(CJK.findall("".join(b.zh for b in tr))) / zh_chars) if zh_chars else 0.0

    # 数字一致性：原文出现过的数字，译文中必须都在
    num_src = Counter()
    num_missing: list[str] = []
    for b in tr:
        for n in NUM.findall(b.text):
            num_src[n] += 1
        if b.zh:
            for n in NUM.findall(b.text):
                if n not in b.zh:
                    num_missing.append(f"{b.id}:{n}")

    report: dict = {
        "blocks_total": len(doc.blocks),
        "blocks_translatable": len(tr),
        "blocks_untranslated": len(untranslated),
        "untranslated_ids": untranslated[:20],
        "coverage": round(1 - len(untranslated) / max(1, len(tr)), 4),
        "zh_char_ratio": round(zh_chars / max(1, src_chars), 3),
        "cjk_ratio": round(cjk_ratio, 3),
        "numbers_missing": num_missing[:50],
        "figures": sum(1 for b in doc.blocks if b.kind == "caption" and b.image),
        "tables": sum(1 for b in doc.blocks if b.kind == "table"),
        "headings": sum(1 for b in doc.blocks if b.kind in ("heading1", "heading2")),
    }

    if source_pdf and rendered_pdf:
        try:
            src = pymupdf.open(source_pdf)
            out = pymupdf.open(rendered_pdf)
            report["pages_source"] = src.page_count
            report["pages_output"] = out.page_count
            over = []
            for i, page in enumerate(out):
                blocks = [b for b in page.get_text("blocks") if b[1] > 45]
                if blocks and max(b[3] for b in blocks) > 740:
                    over.append(f"p{i + 1}")
            report["overflow_pages"] = over
        except Exception as exc:                      # 渲染前的调用不阻断
            report["layout_check_error"] = str(exc)

    report["passed"] = (
        report["coverage"] >= 0.99
        and not report["numbers_missing"]
        and not report.get("overflow_pages")
    )
    return report
