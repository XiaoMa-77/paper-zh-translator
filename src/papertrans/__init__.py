"""PaperTrans —— 论文 PDF 中文翻译流水线（确定性排版 + LLM 只负责语言）。

设计原则（来自实际交付经验）：
1. 版面必须由代码决定，LLM 不参与任何坐标、字号、断页决策。
2. 每个阶段都可落盘、可断言、可单独重跑。
3. 任何"看起来对"的产物都要有质检证据（report.json），否则视为失败。
"""

__version__ = "0.3.1"

from .model import Block, Doc  # noqa: F401
