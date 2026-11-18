"""边界与异常场景：空/近空 PDF、模型坏结果、漏译重试、公式越界、版心溢出与数字格式。

全部离线运行：不访问网络、不下载模型；模型调用一律通过替换 _post 或本地 Provider mock。
"""

from __future__ import annotations

import json

import pymupdf
import pytest

from papertrans import extract, qa, translate
from papertrans.model import Block, Doc
from papertrans.translate import OpenAIProvider


def _blank_pdf(tmp_path, text: str):
    path = tmp_path / "blank.pdf"
    source = pymupdf.open()
    source.new_page(width=612, height=792).insert_text((72, 100), text)
    source.save(path)
    source.close()
    return path


def test_pdf_without_text_layer_is_rejected(tmp_path):
    """空 PDF / 扫描件：extract 必须明确报错，不能产出空译文。"""
    path = _blank_pdf(tmp_path, "short")

    with pytest.raises(RuntimeError, match="扫描件"):
        extract.extract(str(path), str(tmp_path / "work"))


def test_text_layer_below_threshold_is_also_rejected(tmp_path):
    """文字层不足 400 字符同样拒绝，避免把残缺文本当完整论文翻译。"""
    path = _blank_pdf(tmp_path, "word " * 20)

    with pytest.raises(RuntimeError, match="扫描件"):
        extract.extract(str(path), str(tmp_path / "work"))


@pytest.mark.parametrize(
    "content",
    ['{"translations": []}', '{"unexpected": []}'],
)
def test_empty_or_malformed_translation_result_yields_no_translations(monkeypatch, content):
    """模型返回空列表或缺字段时解析为空映射，交给上层重试，而不是编造译文。"""
    provider = OpenAIProvider(api_key="test-key")
    monkeypatch.setattr(
        provider, "_post",
        lambda payload: {"choices": [{"message": {"content": content}}]},
    )

    assert provider.translate([("b1", "Memory tokens")], {}) == {}


def test_non_string_translation_result_is_stringified(monkeypatch):
    """模型把数字等非字符串塞进 zh 时不静默丢失，按字符串回填。"""
    provider = OpenAIProvider(api_key="test-key")
    answer = json.dumps({"translations": [{"id": "b1", "zh": 123}]})
    monkeypatch.setattr(
        provider, "_post",
        lambda payload: {"choices": [{"message": {"content": answer}}]},
    )

    assert provider.translate([("b1", "x")], {}) == {"b1": "123"}


class _FlakyProvider(translate.Provider):
    name = "openai"

    def __init__(self):
        self.rounds: list[list[str]] = []

    def translate(self, items, glossary, style="academic"):
        ids = [i for i, _ in items]
        self.rounds.append(ids)
        if len(self.rounds) == 1:
            return {i: f"译-{i}" for i in ids[:-1]}   # 第一轮故意漏掉最后一块
        return {i: f"译-{i}" for i in ids}


def test_translate_doc_retries_only_the_missing_blocks():
    """模型漏译时只补空缺块，已译块不重复消耗。"""
    blocks = [Block(id=f"b{i}", page=0, kind="body", text=f"text {i}",
                    x0=0, y0=0, x1=10, y1=10) for i in range(3)]
    doc = Doc(source="paper.pdf", blocks=blocks)
    provider = _FlakyProvider()

    stats = translate.translate_doc(doc, provider, retries=1)

    assert stats["missing"] == []
    assert [b.zh for b in blocks] == ["译-b0", "译-b1", "译-b2"]
    assert [len(r) for r in provider.rounds] == [3, 1]


def test_equation_crop_is_clamped_inside_the_page(tmp_path):
    """公式碎片贴近页面右/下边界时，裁剪框不得越出页面。"""
    source = pymupdf.open()
    page = source.new_page(width=612, height=792)
    formula = Block(id="f", page=0, kind="body", text="y=θ",
                    x0=560, y0=770, x1=700, y1=790)
    heading = Block(id="h", page=0, kind="heading2", text="A. Next",
                    x0=54, y0=100, x1=180, y1=112)
    doc = Doc(source="paper.pdf", blocks=[heading, formula])
    (tmp_path / "fig").mkdir()
    extract._extract_equations(doc, source, str(tmp_path), 72, {})

    equations = [b for b in doc.blocks if b.kind == "equation"]
    assert len(equations) == 1
    box = pymupdf.Rect(equations[0].meta["bbox"])
    assert box.x1 <= page.rect.x1 and box.y1 <= page.rect.y1
    source.close()


def test_qa_flags_printed_overflow_and_tolerates_number_formatting(tmp_path):
    """渲染页底越界必须被标出；千分位/百分号形态差异不能误报数字缺失。"""
    src = pymupdf.open()
    src.new_page(width=612, height=792).insert_text((54, 100), "Values 1,000 and 85% remain.")
    src_path = tmp_path / "source.pdf"
    src.save(src_path)
    src.close()

    out = pymupdf.open()
    page = out.new_page(width=612, height=792)
    page.insert_text((54, 100), "Values 1000 and 85 % remain.")
    page.insert_text((54, 760), "overflow at page bottom")
    out_path = tmp_path / "out.pdf"
    out.save(out_path)
    out.close()

    doc = Doc(source=str(src_path), blocks=[
        Block(id="b1", page=0, kind="body", text="Values 1,000 and 85% remain.",
              zh="Values 1000 and 85 % remain.", x0=54, y0=100, x1=300, y1=112),
    ], meta={"provider": "none"})

    report = qa.check_doc(doc, str(src_path), str(out_path))

    assert "p1" in report["overflow_pages"]
    assert report["numbers_missing"] == []
