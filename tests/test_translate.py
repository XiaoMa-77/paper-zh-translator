"""Translation responses from OpenAI-compatible reasoning models."""

import json

import pytest

from papertrans.translate import OpenAIProvider


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("", ""),
        ("```json\n", "\n```"),
        ("<think>Preserve {M0, . . . , Mj} in the translation.</think>\n", ""),
    ],
)
def test_translate_reads_final_json_after_reasoning(monkeypatch, prefix, suffix):
    expected = {"b1": "记忆 token {M0, . . . , Mj} <think>原文标签</think>"}
    answer = json.dumps(
        {"translations": [{"id": "b1", "zh": expected["b1"]}]}, ensure_ascii=False
    )
    provider = OpenAIProvider(api_key="test-key")
    monkeypatch.setattr(
        provider, "_post",
        lambda payload: {"choices": [{"message": {"content": prefix + answer + suffix}}]},
    )

    assert provider.translate([("b1", "Memory tokens")], {}) == expected


def test_translate_rejects_unfinished_reasoning(monkeypatch):
    provider = OpenAIProvider(api_key="test-key")
    content = '<think>Draft: {"translations":[{"id":"b1","zh":"未确认草稿"}]}'
    monkeypatch.setattr(
        provider, "_post",
        lambda payload: {"choices": [{"message": {"content": content}}]},
    )

    with pytest.raises(RuntimeError, match="思考"):
        provider.translate([("b1", "Memory tokens")], {})
