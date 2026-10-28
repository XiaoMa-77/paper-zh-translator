import argparse
import json

import pymupdf
import pytest

from papertrans import audit, cli, mcp_server, qa
from papertrans.model import Block, Doc
from papertrans.translate import Provider


@pytest.fixture
def paper(tmp_path):
    path = tmp_path/'source.pdf'
    source = pymupdf.open()
    page = source.new_page()
    for y, text in [(80, 'First English paragraph 123.'), (140, 'Second paragraph 456.'),
                    (400, 'REFERENCES'), (420, '[1] Author. First paper, 2024.'),
                    (450, '[2] Author. Second paper, 2025.')]:
        page.insert_text((54, y), text)
    source.save(path)
    blocks = []
    for i, raw in enumerate(page.get_text('blocks')):
        text = raw[4].strip()
        blocks.append(Block(id=f'b{i}', page=0, kind='refs' if i >= 2 else 'body',
                            text=text, zh=text if i < 2 else '',
                            x0=raw[0], y0=raw[1], x1=raw[2], y1=raw[3]))
    source.close()
    return Doc(source=str(path), blocks=blocks, meta={'provider': 'none'}), tmp_path


class Reviewer:
    model = 'review-test'
    base_url = 'https://example.invalid/v1'

    def __init__(self, issue=False, incomplete=False):
        self.calls = 0
        self.issue = issue
        self.incomplete = incomplete

    def _post(self, payload):
        self.calls += 1
        items = json.loads(payload['messages'][1]['content'])
        if items and 'issue_index' in items[0]:
            return {'choices': [{'message': {'content': json.dumps({'decisions': [
                {'issue_index': i['issue_index'], 'confirmed': True, 'reason': '确认实质遗漏'}
                for i in items]})}}]}
        ids = [item['id'] for item in items]
        data = {'checked_ids': ids[:-1] if self.incomplete else ids,
                'issues': [{'id': ids[0], 'type': 'omission', 'detail': '遗漏重要条件',
                            'source': items[0]['english'],
                            'translation_quote': items[0]['chinese']}] if self.issue else []}
        return {'choices': [{'message': {'content': json.dumps(data)}}]}


def translated(doc):
    doc.meta['provider'] = 'openai'
    doc.blocks[0].zh = '第一段英文 123。'
    return doc


def test_original_pdf_is_checked_even_when_existing_blocks_are_filled(paper):
    doc, _ = paper
    doc.blocks.pop(0)
    result = audit.source_check(doc)
    assert not result['passed']
    assert result['missing_source_blocks'][0]['page'] == 1
    assert 'First English paragraph' in result['missing_source_blocks'][0]['text']


def test_complete_source_inventory_passes(paper):
    doc, _ = paper
    result = audit.source_check(doc)
    assert result['passed']
    assert result['inventory_actual']['references'] == ['1', '2']


def test_missing_reference_fails_independent_inventory(paper):
    doc, _ = paper
    doc.blocks.pop()
    assert not audit.source_check(doc)['passed']


def test_merged_reference_entries_are_flagged_even_if_all_words_exist(paper):
    doc, _ = paper
    doc.blocks[-2].text += ' ' + doc.blocks[-1].text
    doc.blocks.pop()
    result = audit.source_check(doc)
    assert result['merged_reference_blocks']
    assert not result['passed']


def test_missing_source_cannot_pass(paper):
    doc, tmp = paper
    doc.source = str(tmp/'missing.pdf')
    assert not audit.source_check(doc)['passed']


def test_semantic_omission_fails_and_is_cached(paper):
    doc, tmp = paper
    reviewer = Reviewer(issue=True)
    result = audit.review_translations(translated(doc), reviewer, str(tmp/'doc.json'))
    assert result['status'] == 'failed'
    assert result['issues'][0]['id'] == 'b0'
    assert audit.review_translations(doc, reviewer)['status'] == 'failed'
    assert reviewer.calls == 2
    assert Doc.load(str(tmp/'doc.json')).meta['translation_review']['status'] == 'failed'


def test_incomplete_semantic_review_cannot_pass(paper):
    doc, _ = paper
    result = audit.review_translations(translated(doc), Reviewer(incomplete=True))
    assert result['status'] == 'error'


def test_changing_translation_invalidates_cached_review(paper):
    doc, _ = paper
    reviewer = Reviewer()
    audit.review_translations(translated(doc), reviewer)
    doc.blocks[0].zh += ' 修改。'
    audit.review_translations(doc, reviewer)
    assert reviewer.calls == 2


def test_changing_source_invalidates_cached_review(paper):
    doc, _ = paper
    reviewer = Reviewer()
    audit.review_translations(translated(doc), reviewer)
    with open(doc.source, 'ab') as stream:
        stream.write(b'\n% source changed\n')
    audit.review_translations(doc, reviewer)
    assert reviewer.calls == 2


def test_without_key_semantic_review_is_unavailable_and_qa_fails(paper, monkeypatch):
    doc, _ = paper
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    result = audit.review_translations(translated(doc))
    assert result['status'] == 'unavailable'
    assert not qa.check_doc(doc, doc.source)['passed']


def test_changed_text_cannot_reuse_a_previous_pass_flag(paper):
    doc, _ = paper
    audit.review_translations(translated(doc), Reviewer())
    doc.blocks[0].zh += ' 新改动。'
    result = qa.check_doc(doc, doc.source)
    assert not result['passed']
    assert result['translation_review']['status'] == 'stale'


def test_layout_mode_does_not_claim_a_semantic_review(paper):
    doc, _ = paper
    assert audit.review_translations(doc)['status'] == 'not_applicable'


def test_reviewer_cannot_ground_an_issue_in_invented_chinese_text(paper):
    doc, _ = paper

    class InventedQuote(Reviewer):
        def _post(self, payload):
            data = json.loads(super()._post(payload)['choices'][0]['message']['content'])
            data['issues'][0]['translation_quote'] = '这句话实际不存在'
            return {'choices': [{'message': {'content': json.dumps(data)}}]}

    result = audit.review_translations(translated(doc), InventedQuote(issue=True))
    assert result['status'] == 'error'


def test_equivalent_wording_is_dismissed_by_confirmation(paper):
    doc, _ = paper

    class Equivalent(Reviewer):
        def _post(self, payload):
            items = json.loads(payload['messages'][1]['content'])
            if items and 'issue_index' in items[0]:
                return {'choices': [{'message': {'content': json.dumps({'decisions': [
                    {'issue_index': 0, 'confirmed': False, 'reason': '译文已经表达该内容'}]})}}]}
            return super()._post(payload)

    result = audit.review_translations(translated(doc), Equivalent(issue=True))
    assert result['status'] == 'passed'
    assert not result['issues']
    assert len(result['dismissed_issues']) == 1


def test_reconstructed_table_cannot_silently_drop_numeric_cells():
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((54, 100), 'A 12.3 45.6')
    page.insert_text((54, 120), 'B 78.9 10.0')
    assert audit.missing_table_tokens(page, pymupdf.Rect(50, 80, 300, 130),
                                      [['A', '12.3', '45.6'], ['B', '78.9', '10.0']]) == []
    assert audit.missing_table_tokens(page, pymupdf.Rect(50, 80, 300, 130),
                                      [['A', '12.3', '45.6'], ['B', '78.9']]) == ['10.0']


def test_asset_pixels_are_compared_to_the_original_pdf(paper):
    doc, tmp = paper
    source = pymupdf.open(doc.source)
    box = pymupdf.Rect(54, 200, 299, 240)
    pix = source[0].get_pixmap(clip=box, dpi=72)
    pix.save(tmp/'asset.png')
    doc.meta.update(asset_root=str(tmp), asset_dpi=72)
    doc.blocks.append(Block(id='picture', page=0, kind='figure', text='',
                            x0=54, y0=200, x1=299, y1=240, image='asset.png', meta={'bbox':list(box)}))
    assert audit.source_check(doc)['passed']
    pix.set_pixel(10, 10, (0, 0, 0))
    pix.save(tmp/'asset.png')
    result = audit.source_check(doc)
    assert not result['passed']
    assert result['changed_source_images'][0]['id'] == 'picture'


def test_duplicate_printed_image_is_detected(paper):
    doc, tmp = paper
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 30), False)
    pix.clear_with(255)
    pix.set_pixel(10, 10, (0, 0, 0))
    pix.save(tmp/'asset.png')
    doc.meta['asset_root'] = str(tmp)
    doc.blocks.append(Block(id='picture', page=0, kind='figure', text='',
                            x0=54, y0=200, x1=299, y1=240, image='asset.png'))
    output = pymupdf.open()
    page = output.new_page()
    page.insert_image(pymupdf.Rect(54, 100, 154, 150), filename=str(tmp/'asset.png'))
    page.insert_image(pymupdf.Rect(54, 200, 154, 250), filename=str(tmp/'asset.png'))
    path = tmp/'output.pdf'
    output.save(path)
    output.close()
    result = audit.printed_check(doc, str(path))
    assert result['duplicated_image_blocks'] == [['picture']]


def test_missing_printed_content_is_detected(paper):
    doc, tmp = paper
    output = pymupdf.open()
    output.new_page().insert_text((54, 80), doc.blocks[1].text)
    path = tmp/'output.pdf'
    output.save(path)
    output.close()
    result = audit.printed_check(doc, str(path))
    assert not result['passed']
    assert 'b0' in result['missing_text_blocks']


class Translator(Provider):
    name = 'openai'
    model = 'test-model'

    def translate(self, items, glossary, style='academic'):
        return {id: '中文 ' + text for id, text in items}


@pytest.mark.parametrize('entry', ['cli', 'mcp'])
def test_translation_commands_run_review_by_default_and_propagate_failure(paper, monkeypatch, entry):
    doc, tmp = paper
    for b in doc.blocks:
        b.zh = ''
    doc.save(str(tmp/'doc.json'))
    monkeypatch.setattr(cli.translate, 'get_provider', lambda *args, **kwargs: Translator())
    calls = []

    def review(doc, **kwargs):
        calls.append(doc)
        return {'status': 'failed', 'issues': [{'id': 'b0', 'detail': 'omission'}]}

    monkeypatch.setattr(audit, 'review_translations', review)
    if entry == 'cli':
        args = argparse.Namespace(workdir=str(tmp), provider='openai', model=None,
                                  glossary=None, style='academic')
        assert cli.cmd_translate(args) == 3
    else:
        assert not json.loads(mcp_server._translate_impl(str(tmp)))['ok']
    assert len(calls) == 1


@pytest.mark.parametrize('entry', ['cli', 'mcp'])
def test_build_commands_run_review_by_default(paper, monkeypatch, entry):
    doc, tmp = paper
    translated(doc).save(str(tmp/'doc.json'))
    calls = []

    def review(doc, **kwargs):
        calls.append(doc)
        result = {'status': 'failed', 'fingerprint': audit.translation_fingerprint(doc), 'issues': []}
        doc.meta['translation_review'] = result
        return result

    monkeypatch.setattr(audit, 'review_translations', review)
    monkeypatch.setattr(cli.paginate, 'build_pages', lambda *args: ('<p>test</p>', 1))
    monkeypatch.setattr(cli.render, 'print_pdf', lambda *args: str(tmp/'output.pdf'))
    if entry == 'cli':
        cli._finish_pdf(doc, ['<p>test</p>'], str(tmp), None)
    else:
        mcp_server._build(str(tmp), doc, '')
    assert len(calls) == 1
    assert Doc.load(str(tmp/'doc.json')).meta['translation_review']['status'] == 'failed'
