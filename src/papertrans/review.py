"""人工兜底：把裁出来的图/表/公式摊开给人看，30 秒内能发现裁错的那几张。

用法：
    papertrans extract paper.pdf -o build/x --review
    # 打开 build/x/review/index.html，对不满意的裁剪框写进 build/x/overrides.json
    # {"b0123": [x0, y0, x1, y1]}  坐标单位 pt，原点在页面左上
    papertrans extract paper.pdf -o build/x     # 重跑即生效
"""

from __future__ import annotations

import json
import os
import shutil

from .model import Doc


def write_review(doc: Doc, workdir: str) -> str:
    rdir = os.path.join(workdir, "review")
    os.makedirs(rdir, exist_ok=True)
    items = [b for b in doc.blocks if b.image]
    cards = []
    for b in items:
        src = os.path.join(workdir, b.image)
        dst = os.path.join(rdir, os.path.basename(b.image))
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copyfile(src, dst)
        bbox = b.meta.get("bbox", [])
        cards.append(
            f'<figure><img src="{os.path.basename(b.image)}">'
            f'<figcaption><b>{b.id}</b> · p{b.page + 1} · {b.kind}'
            f'{" · " + str([round(v) for v in bbox]) if bbox else ""}'
            f'<br><span class="cap">{b.text[:110]}</span></figcaption></figure>'
        )
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>裁剪复核 · {os.path.basename(doc.source)}</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#222}}
h1{{font-size:18px;font-weight:500}} p{{color:#555;font-size:13px;line-height:1.7}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
figure{{margin:0;border:1px solid #ddd;border-radius:8px;padding:8px;background:#fff}}
img{{width:100%;display:block;border-radius:4px}}
figcaption{{font-size:12px;color:#444;margin-top:6px;line-height:1.5}}
.cap{{color:#888}} code{{background:#f4f4f2;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>裁剪复核（{len(items)} 处）</h1>
<p>逐张看：图形是否完整、有没有把正文/图注带进来。不满意的，把坐标写进
<code>overrides.json</code>（格式 <code>{{"b0123": [x0,y0,x1,y1]}}</code>，单位 pt），
再跑一次 <code>papertrans extract</code> 即生效。</p>
<div class="grid">{''.join(cards)}</div></body></html>"""
    path = os.path.join(rdir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    tpl = os.path.join(workdir, "overrides.json")
    if not os.path.exists(tpl):
        with open(tpl, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=1)
    return path
