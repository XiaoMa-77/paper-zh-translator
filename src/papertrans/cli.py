"""命令行入口：一条命令出 PDF，也是 AI 助手最直接的调用方式。

退出码：0 成功 / 2 输入非法 / 3 需人工复核 / 4 渲染失败
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__, build, extract, paginate, qa, render, review, translate
from .model import Doc


def _workdir(arg: str | None, pdf: str) -> str:
    return arg or os.path.join("build", os.path.splitext(os.path.basename(pdf))[0])


def _load_glossary(path: str | None) -> dict:
    if not path:
        return {}
    if not os.path.exists(path):
        raise RuntimeError(f"术语表不存在：{path}（路径写错时不静默跳过，否则术语约束会悄悄失效）")
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _finish_pdf(doc: Doc, blocks: list[str], wd: str, output: str | None) -> tuple[str, int]:
    """分页 → 写 final.html → 打印 PDF。run 与 build 共用，正文只组装一次。"""
    body, pages = paginate.build_pages(blocks, build.CSS, wd)
    html_path = os.path.join(wd, "final.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build.document([body], os.path.basename(doc.source)))
    out_pdf = output or os.path.join(wd, os.path.splitext(os.path.basename(doc.source))[0] + ".zh.pdf")
    render.print_pdf(html_path, out_pdf)
    return out_pdf, pages


def cmd_extract(args) -> int:
    wd = _workdir(args.out, args.pdf)
    os.makedirs(wd, exist_ok=True)
    doc = extract.extract(args.pdf, wd, dpi=args.dpi, columns=args.columns, tables=args.tables)
    doc.save(os.path.join(wd, "doc.json"))
    out = {"workdir": wd, "blocks": len(doc.blocks), "assets": len(doc.assets),
           "columns": doc.columns}
    if args.review:
        out["review"] = review.write_review(doc, wd)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_translate(args) -> int:
    wd = args.workdir
    doc = Doc.load(os.path.join(wd, "doc.json"))
    glossary = _load_glossary(args.glossary)
    provider = translate.get_provider(args.provider, model=args.model)
    t0 = time.time()
    stats = translate.translate_doc(doc, provider, glossary, args.style)
    doc.save(os.path.join(wd, "doc.json"))
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    print(json.dumps(stats, ensure_ascii=False))
    return 0 if not stats["missing"] else 3


def cmd_build(args) -> int:
    wd = args.workdir
    doc = Doc.load(os.path.join(wd, "doc.json"))
    blocks = build.to_html_blocks(doc)
    if args.preview_only:
        print(build.write_preview(doc, wd, blocks))
        return 0
    out_pdf, pages = _finish_pdf(doc, blocks, wd, args.output)
    report = qa.check_doc(doc, doc.source, out_pdf)
    report["pages"] = pages
    with open(os.path.join(wd, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({"pdf": out_pdf, "pages": pages, "passed": report["passed"],
                      "coverage": report["coverage"]}, ensure_ascii=False))
    return 0 if report["passed"] else 3


def cmd_run(args) -> int:
    wd = _workdir(args.out, args.pdf)
    os.makedirs(wd, exist_ok=True)
    doc = extract.extract(args.pdf, wd, dpi=args.dpi, columns=args.columns, tables=args.tables)
    doc.save(os.path.join(wd, "doc.json"))
    if getattr(args, "review", False):
        review.write_review(doc, wd)
    glossary = _load_glossary(args.glossary)
    provider = translate.get_provider(args.provider, model=args.model)
    translate.translate_doc(doc, provider, glossary, args.style)
    doc.save(os.path.join(wd, "doc.json"))

    out_pdf, pages = _finish_pdf(doc, build.to_html_blocks(doc), wd, args.output)
    report = qa.check_doc(doc, args.pdf, out_pdf)
    report["pages"] = pages
    with open(os.path.join(wd, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({"pdf": out_pdf, "pages": pages, "passed": report["passed"],
                      "coverage": report["coverage"], "workdir": wd}, ensure_ascii=False))
    return 0 if report["passed"] else 3


def cmd_doctor(args) -> int:
    """环境自检：缺什么就直说，别等跑到一半才报错。"""
    import platform
    import shutil

    rows = []
    rows.append(("python", platform.python_version(), True))
    try:
        import pymupdf
        ver = getattr(pymupdf, "VersionBind", "") or (pymupdf.__doc__.split()[1] if pymupdf.__doc__ else "ok")
        rows.append(("pymupdf", ver, True))
    except Exception as exc:
        rows.append(("pymupdf", str(exc), False))
    try:
        import yaml  # noqa: F401
        rows.append(("pyyaml", "ok", True))
    except Exception:
        rows.append(("pyyaml", "缺失（仅 glossary 用，可选）", False))
    try:
        exe = render.find_browser()
        rows.append(("chromium", exe, True))
    except Exception as exc:
        rows.append(("chromium", str(exc), False))
    fonts = []
    for d in ("C:/Windows/Fonts", "/usr/share/fonts", "/System/Library/Fonts"):
        if os.path.isdir(d):
            fonts = [f for f in os.listdir(d) if any(k in f.lower() for k in ("simsun", "noto", "sourcehan", "songti"))]
            if fonts:
                break
    rows.append(("CJK 字体", ", ".join(fonts[:3]) or "未发现（输出可能方框）", bool(fonts)))
    rows.append(("磁盘剩余", f"{shutil.disk_usage('.').free // (1 << 30)} GB", True))

    ok = True
    for name, val, good in rows:
        print(f"{'✓' if good else '✗'} {name:<10} {val}")
        ok = ok and (good or name in ("pyyaml",))
    print()
    print("结论：" + ("可以开工" if ok else "先修上面标 ✗ 的项"))
    return 0 if ok else 2


def cmd_report(args) -> int:
    path = os.path.join(args.workdir, "report.json")
    if not os.path.exists(path):
        print("没有 report.json，请先 build", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        print(f.read())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="papertrans", description="PDF 论文中文翻译（保持双栏版式）")
    p.add_argument("--version", action="version", version=f"papertrans {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="只抽取内容与图，便于检查")
    e.add_argument("pdf")
    e.add_argument("-o", "--out")
    e.add_argument("--dpi", type=int, default=320)
    e.add_argument("--columns", type=int, choices=[1, 2])
    e.add_argument("--tables", choices=["auto", "image"], default="auto",
                   help="auto=尝试重建可编辑表格（失败回退图片），image=一律保留为图")
    e.add_argument("--review", action="store_true", help="导出裁剪复核页 review/index.html")
    e.set_defaults(func=cmd_extract)

    t = sub.add_parser("translate", help="翻译已抽取的 doc.json")
    t.add_argument("workdir")
    t.add_argument("--provider", default="none")
    t.add_argument("--model")
    t.add_argument("--glossary")
    t.add_argument("--style", default="academic")
    t.set_defaults(func=cmd_translate)

    b = sub.add_parser("build", help="排版并打印 PDF")
    b.add_argument("workdir")
    b.add_argument("-o", "--output")
    b.add_argument("--preview-only", action="store_true")
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("run", help="抽取 + 翻译 + 排版 一条龙")
    r.add_argument("pdf")
    r.add_argument("-o", "--out", help="工作目录")
    r.add_argument("--output", help="输出 PDF 路径")
    r.add_argument("--provider", default="none")
    r.add_argument("--model")
    r.add_argument("--glossary")
    r.add_argument("--style", default="academic")
    r.add_argument("--dpi", type=int, default=320)
    r.add_argument("--columns", type=int, choices=[1, 2])
    r.add_argument("--tables", choices=["auto", "image"], default="auto")
    r.add_argument("--review", action="store_true", help="额外导出裁剪复核页")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("doctor", help="检查运行环境")
    d.set_defaults(func=cmd_doctor)

    q = sub.add_parser("report", help="打印质检报告")
    q.add_argument("workdir")
    q.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
