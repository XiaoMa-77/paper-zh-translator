"""文档模型：抽出来的内容块与整篇文档。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Kind = Literal["title", "authors", "abstract", "heading1", "heading2", "body", "caption", "table", "figure", "equation", "refs", "unknown"]


@dataclass
class Block:
    id: str
    page: int
    kind: Kind
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    col: int = 0                 # 0=左/单栏 1=右栏
    size: float = 10.0
    bold: bool = False
    zh: str = ""                 # 译文，空表示未译
    image: str = ""              # 图片相对路径（figure/table 用）
    full_width: bool = False     # 是否跨栏
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Doc:
    source: str
    page_size: tuple[float, float] = (612.0, 792.0)
    columns: int = 2
    blocks: list[Block] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "page_size": list(self.page_size),
            "columns": self.columns,
            "assets": self.assets,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> Doc:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        doc = cls(source=data["source"], page_size=tuple(data["page_size"]),
                  columns=data.get("columns", 2), assets=data.get("assets", {}))
        for b in data["blocks"]:
            doc.blocks.append(Block(**b))
        return doc
