"""渲染后端：优先用本机 Chromium 内核的 --headless 打印，找不到再退回 Playwright。

之所以不用 WeasyPrint：它做不出跨栏浮动与实测高度分页，输出会退化成单栏。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str:
    env = os.environ.get("PAPERTRANS_BROWSER")
    if env and os.path.exists(env):
        return env
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "找不到 Chromium 内核浏览器。请设置 PAPERTRANS_BROWSER 指向 msedge/chrome 可执行文件。"
    )


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="ignore", timeout=timeout)


def print_pdf(html_path: str, pdf_path: str, timeout: int = 180) -> str:
    exe = find_browser()
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    args = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={os.path.abspath(pdf_path)}", url]
    r = _run(args, timeout=timeout)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"打印失败：{r.stderr[:400]}")
    return pdf_path


def dump_dom(html_path: str, timeout: int = 120) -> str:
    exe = find_browser()
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    r = _run([exe, "--headless=new", "--disable-gpu", "--virtual-time-budget=10000",
              "--dump-dom", url], timeout=timeout)
    return r.stdout


def is_full_width(block_html: str) -> bool:
    return re.search(r'class="[^"]*\b(?:full|head)\b', block_html[:160]) is not None


def measure_blocks(blocks: list[str], css: str, workdir: str,
                   span_width: str = "514pt", col_width: str = "250.5pt") -> list[float]:
    """在浏览器里真实排一遍，取每个块的高度（pt）。这是全流程精度的地基。"""
    parts = [f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>']
    for i, b in enumerate(blocks):
        w = span_width if is_full_width(b) else col_width
        parts.append(f'<div id="m{i}" style="width:{w};"><div>{b}</div></div>')
    parts.append(
        f'<pre id="out"></pre><script>window.addEventListener("load",function(){{'
        f'var r=[];for(var i=0;i<{len(blocks)};i++){{var el=document.getElementById("m"+i).firstElementChild;'
        f'var cs=getComputedStyle(el);r.push([i,el.getBoundingClientRect().height+parseFloat(cs.marginTop)+parseFloat(cs.marginBottom)]);}}'
        f'document.getElementById("out").textContent=JSON.stringify(r);}});</script></body></html>'
    )
    tmp = os.path.join(workdir, "_measure.html")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    dom = dump_dom(tmp)
    m = re.search(r'<pre id="out">(.*?)</pre>', dom, re.DOTALL)
    if not m:
        raise RuntimeError("测高失败：浏览器未返回测量结果")
    import json
    data = json.loads(m.group(1))
    return [h * 0.75 for _, h in data]      # 屏幕 px → 打印 pt
