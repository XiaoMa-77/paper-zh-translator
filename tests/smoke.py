"""冒烟测试：不依赖 pytest，直接 python tests/smoke.py 就能跑。

分两级：
1. 结构级（总是跑）：模块可导入、栏数判断、块分类、CSS 与分页器自洽。
2. 端到端（设置 PAPERTRANS_SAMPLE=某篇.pdf 才跑）：抽取 → 排版 → 打印 → 质检。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from papertrans import build, paginate  # noqa: E402 -- bootstrap local src before importing
from papertrans.model import Block  # noqa: E402


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def structural() -> None:
    print("[1] 结构检查")
    # 分页器：空输入不崩
    pages = paginate.paginate([], [])
    check(pages == [] or pages == [[]], "空文档分页不报错")
    # 分页器：强制换页正确
    blocks = ['<p>a</p>'] * 4 + ['<div class="full">span</div>'] + ['<p>b</p>'] * 4
    heights = [200.0] * 4 + [300.0] + [200.0] * 4
    pages = paginate.paginate(blocks, heights)
    check(len(pages) >= 1, "跨栏块能触发分页")
    # 构建：块转 HTML 覆盖主要类型
    doc_blocks = [
        Block(id="t", page=0, kind="title", text="T", x0=0, y0=0, x1=10, y1=10),
        Block(id="a", page=0, kind="abstract", text="A", x0=0, y0=0, x1=10, y1=10, zh="甲"),
        Block(id="h", page=0, kind="heading1", text="1. I", x0=0, y0=0, x1=10, y1=10, zh="一"),
        Block(id="p", page=0, kind="body", text="P", x0=0, y0=0, x1=10, y1=10, zh="乙"),
    ]
    html = build.to_html_blocks(type("D", (), {"blocks": doc_blocks})())
    check(any('class="head"' in h for h in html), "题名进 head")
    check(any("<h2" in h for h in html), "一级标题成 h2")
    check("Noto Serif CJK" in build.CSS, "CSS 用可分发的中文字体")
    # 表格重建：带 table_data 的表块渲染为 HTML 表格而非图片
    tb = Block(id="tb", page=0, kind="table", text="Table 1: x", x0=0, y0=0, x1=10, y1=10,
               zh="Table 1: 甲", meta={"table_data": [["A", "B"], ["1", "2"]]})
    th = build._table(tb, "")
    check("<table>" in th and "<th>A</th>" in th and "<td>1</td>" in th, "结构化表格渲染为 HTML")
    doc_blocks.append(tb)
    html2 = build.to_html_blocks(type("D", (), {"blocks": doc_blocks})())
    check(any("<table>" in h for h in html2), "表格块进入输出流")
    # MCP 层：实现函数可直接调用（不经 stdio），server 可构造
    try:
        from papertrans import mcp_server
        r = json.loads(mcp_server._doctor_impl())
        check(r["ok"], "MCP doctor 自检通过")
        server = mcp_server.create_server()
        check(server is not None, "MCP server 可构造")
    except ImportError:
        print("  skip  mcp 未安装，跳过 MCP 层检查")


def e2e(pdf: str) -> None:
    print(f"[2] 端到端：{os.path.basename(pdf)}")
    exe = sys.executable
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    wd = tempfile.mkdtemp(prefix="pt_")
    out = os.path.join(wd, "out.pdf")
    r = subprocess.run([exe, "-m", "papertrans", "run", pdf, "-o", wd, "--output", out],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    print("  " + (r.stdout or r.stderr).strip()[:300])
    check(os.path.exists(out), "产出 PDF")
    with open(os.path.join(wd, "report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    check(rep["passed"], "原文覆盖与最终打印检查通过")
    check(rep["source_audit"]["passed"], "直接对照原始 PDF 未发现遗漏/重复裁剪")
    check(rep["printed_audit"]["passed"], "文字和保护图片完整打印")
    check(rep["coverage"] >= 0.99, f"译文覆盖率 {rep['coverage']}")
    check(rep["pages_output"] >= 1, f"页数 {rep['pages_output']}")
    check(not rep.get("overflow_pages"), "无版心溢出")
    with open(os.path.join(wd, "doc.json"), encoding="utf-8") as f:
        doc = json.load(f)
    n_html_tables = sum(1 for b in doc["blocks"] if b.get("meta", {}).get("table_data"))
    n_tables = sum(1 for b in doc["blocks"] if b["kind"] == "table")
    check(n_tables == len(rep["source_audit"]["inventory_expected"]["tables"]), f"识别表格 {n_tables} 张")
    n_image_tables = sum(1 for b in doc["blocks"] if b["kind"] == "table" and b.get("image"))
    check(n_html_tables + n_image_tables == n_tables,
          f"表格完整保留：HTML {n_html_tables}，图片回退 {n_image_tables}")
    with open(os.path.join(wd, "final.html"), encoding="utf-8") as f:
        fh = f.read()
    if n_html_tables:
        check("<table><thead>" in fh, "输出 PDF 含结构化表格")


if __name__ == "__main__":
    structural()
    sample = os.environ.get("PAPERTRANS_SAMPLE")
    if sample:
        e2e(sample)
    else:
        print("[2] 端到端：跳过（设置 PAPERTRANS_SAMPLE=<pdf 路径> 可开启）")
    print("\n全部通过")
