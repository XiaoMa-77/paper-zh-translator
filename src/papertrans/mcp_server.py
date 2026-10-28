"""MCP Server：把 papertrans 暴露给 AI 助手（Claude Desktop 等）。

安装：pip install papertrans[mcp]
运行：papertrans-mcp        （stdio 传输，写进客户端的 MCP 配置即可）

工具设计原则与 CLI 一致：每个阶段可单独调用，结果以 JSON 字符串返回，
退出码语义折算成 JSON 里的 ok/passed 字段，错误信息直接可读。
"""

from __future__ import annotations

import json
import os
import time

from . import __version__, audit, build, extract, qa, render, review, translate
from .model import Doc


def _d(arg: str | None, pdf: str) -> str:
    return arg or os.path.join("build", os.path.splitext(os.path.basename(pdf))[0])


def _json(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _translate_paper_impl(pdf_path: str, out_dir: str = "", provider: str = "none",
                          model: str = "", glossary: str = "", style: str = "academic",
                          tables: str = "auto") -> str:
    """一条龙：抽取 → 翻译 → 排版 → 打印 → 质检。返回结果 JSON。"""
    wd = _d(out_dir or None, pdf_path)
    os.makedirs(wd, exist_ok=True)
    doc = extract.extract(pdf_path, wd, tables=tables)
    doc.save(os.path.join(wd, "doc.json"))
    gl = {}
    if glossary:
        if not os.path.exists(glossary):
            return _json(ok=False, error=f"术语表不存在：{glossary}")
        import yaml
        with open(glossary, encoding="utf-8") as f:
            gl = yaml.safe_load(f) or {}
    provider_obj = translate.get_provider(provider, model=model or None)
    translate.translate_doc(doc, provider_obj, gl, style)
    doc.save(os.path.join(wd, "doc.json"))
    out_pdf, pages = _build(wd, doc, "")
    report = qa.check_doc(doc, pdf_path, out_pdf)
    report["pages"] = pages
    with open(os.path.join(wd, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return _json(ok=report["passed"], pdf=out_pdf, workdir=wd, pages=pages,
                 coverage=report["coverage"], passed=report["passed"])


def _build(wd: str, doc: Doc | None, output: str) -> tuple[str, int]:
    from . import paginate
    if doc is None:
        doc = Doc.load(os.path.join(wd, "doc.json"))
    doc.meta["asset_root"] = os.path.abspath(wd)
    doc.blocks = extract._merge_refs(doc.blocks)
    audit.review_translations(doc, checkpoint=os.path.join(wd, "doc.json"))
    doc.save(os.path.join(wd, "doc.json"))
    blocks = build.to_html_blocks(doc)
    body, pages = paginate.build_pages(blocks, build.CSS, wd)
    html_path = os.path.join(wd, "final.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build.document([body], os.path.basename(doc.source)))
    out_pdf = output or os.path.join(wd, os.path.splitext(os.path.basename(doc.source))[0] + ".zh.pdf")
    render.print_pdf(html_path, out_pdf)
    return out_pdf, pages


def _extract_impl(pdf_path: str, out_dir: str = "", tables: str = "auto",
                  review_page: bool = False) -> str:
    """只抽取结构（doc.json + fig/）。先用它检查抽取质量，再决定是否翻译。"""
    wd = _d(out_dir or None, pdf_path)
    os.makedirs(wd, exist_ok=True)
    doc = extract.extract(pdf_path, wd, tables=tables)
    doc.save(os.path.join(wd, "doc.json"))
    if review_page:
        review.write_review(doc, wd)
    return _json(ok=True, workdir=wd, blocks=len(doc.blocks), assets=len(doc.assets),
                 tables_html=sum(1 for b in doc.blocks if b.meta.get("table_data")),
                 columns=doc.columns)


def _translate_impl(workdir: str, provider: str = "openai", model: str = "",
                    glossary: str = "", style: str = "academic") -> str:
    """翻译已抽取的 doc.json（需要 LLM_API_KEY 环境变量，或 provider=none 验版面）。"""
    p = os.path.join(workdir, "doc.json")
    if not os.path.exists(p):
        return _json(ok=False, error=f"没有 {p}，请先 extract")
    doc = Doc.load(p)
    gl = {}
    if glossary:
        if not os.path.exists(glossary):
            return _json(ok=False, error=f"术语表不存在：{glossary}")
        import yaml
        with open(glossary, encoding="utf-8") as f:
            gl = yaml.safe_load(f) or {}
    provider_obj = translate.get_provider(provider, model=model or None)
    t0 = time.time()
    stats = translate.translate_doc(doc, provider_obj, gl, style)
    stats["translation_review"] = audit.review_translations(
        doc, provider=provider_obj if provider == "openai" else None, checkpoint=p)
    stats["source_audit"] = audit.source_check(doc)
    doc.save(p)
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    stats["ok"] = (not stats["missing"] and stats["source_audit"]["passed"]
                   and stats["translation_review"]["status"] in ("passed", "not_applicable"))
    return _json(**stats)


def _build_impl(workdir: str, output: str = "") -> str:
    """排版打印已翻译的工作目录，并写质检报告。"""
    out_pdf, pages = _build(workdir, None, output)
    doc = Doc.load(os.path.join(workdir, "doc.json"))
    report = qa.check_doc(doc, doc.source, out_pdf)
    report["pages"] = pages
    with open(os.path.join(workdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return _json(ok=report["passed"], pdf=out_pdf, pages=pages,
                 coverage=report["coverage"], passed=report["passed"])


def _report_impl(workdir: str) -> str:
    p = os.path.join(workdir, "report.json")
    if not os.path.exists(p):
        return _json(ok=False, error="没有 report.json，请先 build")
    return open(p, encoding="utf-8").read()


def _doctor_impl() -> str:
    """环境自检：pymupdf / Chromium / 中文字体 / pdfplumber。"""
    rows: dict[str, object] = {}
    ok = True
    try:
        import pymupdf
        rows["pymupdf"] = getattr(pymupdf, "VersionBind", "ok")
    except Exception as exc:
        rows["pymupdf"] = str(exc)
        ok = False
    try:
        rows["chromium"] = render.find_browser()
    except Exception as exc:
        rows["chromium"] = str(exc)
        ok = False
    try:
        import pdfplumber  # noqa: F401
        rows["pdfplumber"] = "ok（表格重建可用）"
    except Exception:
        rows["pdfplumber"] = "未安装（表格将保留为图片）"
    fonts = []
    for d in ("C:/Windows/Fonts", "/usr/share/fonts", "/System/Library/Fonts"):
        if os.path.isdir(d):
            fonts = [f for f in os.listdir(d)
                     if any(k in f.lower() for k in ("simsun", "noto", "sourcehan", "songti"))]
            if fonts:
                break
    rows["cjk_fonts"] = ", ".join(fonts[:3]) or "未发现（输出可能方框）"
    return _json(ok=ok, **rows)


def create_server():
    """兼容 mcp 1.x（FastMCP）与 2.x（MCPServer，FastMCP 改名而来）。"""
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x

    server = Server("papertrans", instructions=(
        f"papertrans {__version__}：英文论文 PDF → 保留双栏版式的中文 PDF。"
        "推荐流程：先 doctor 检查环境 → extract 检查抽取 → translate（openai，需 LLM_API_KEY）"
        "→ build 出 PDF。只想快速出片用 translate_paper 一条龙；provider=none 不翻译只验版面。"
    ))

    for tool in (doctor, translate_paper, extract_structure, translate_workdir, build_pdf, qa_report):
        server.tool()(tool)
    return server


# ---- 工具薄封装：实现函数可被直接 import 测试，装饰只做注册 ----

def doctor() -> str:
    """环境自检：依赖、浏览器、中文字体是否齐备。"""
    return _doctor_impl()


def translate_paper(pdf_path: str, out_dir: str = "", provider: str = "none",
                    model: str = "", glossary: str = "", style: str = "academic",
                    tables: str = "auto") -> str:
    """一条龙翻译整篇论文 PDF，返回结果 JSON（pdf 路径、覆盖率、质检）。"""
    return _translate_paper_impl(pdf_path, out_dir, provider, model, glossary, style, tables)


def extract_structure(pdf_path: str, out_dir: str = "", tables: str = "auto",
                      review_page: bool = False) -> str:
    """只抽取 PDF 结构（文本块/图/表），产出 doc.json 与 fig/，先检查再翻译。"""
    return _extract_impl(pdf_path, out_dir, tables, review_page)


def translate_workdir(workdir: str, provider: str = "openai", model: str = "",
                      glossary: str = "", style: str = "academic") -> str:
    """翻译已抽取工作目录里的 doc.json（openai 需环境变量 LLM_API_KEY）。"""
    return _translate_impl(workdir, provider, model, glossary, style)


def build_pdf(workdir: str, output: str = "") -> str:
    """把工作目录排版打印成中文 PDF 并质检。"""
    return _build_impl(workdir, output)


def qa_report(workdir: str) -> str:
    """读取质检报告 report.json。"""
    return _report_impl(workdir)


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
