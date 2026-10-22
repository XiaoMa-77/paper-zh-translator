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

from papertrans import build, paginate, extract  # noqa: E402
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
    rep = json.load(open(os.path.join(wd, "report.json"), encoding="utf-8"))
    check(rep["coverage"] >= 0.99, f"译文覆盖率 {rep['coverage']}")
    check(rep["pages_output"] >= 1, f"页数 {rep['pages_output']}")
    check(not rep.get("overflow_pages"), "无版心溢出")


if __name__ == "__main__":
    structural()
    sample = os.environ.get("PAPERTRANS_SAMPLE")
    if sample:
        e2e(sample)
    else:
        print("[2] 端到端：跳过（设置 PAPERTRANS_SAMPLE=<pdf 路径> 可开启）")
    print("\n全部通过")
