import re

from papertrans import build, extract
from papertrans.model import Block, Doc


def ref(id, text):
    return Block(id=id, page=0, kind='refs', text=text, x0=54, y0=50, x1=299, y1=100)


def test_reference_start_inside_pdf_block_becomes_a_separate_item():
    blocks = [ref('h', 'REFERENCES'), ref('a', '[1] A. First title'),
              ref('b', 'continued, 2024. [2] B. Second title, 2025.')]

    result = extract._merge_refs(blocks)

    assert [b.text for b in result] == ['REFERENCES', '[1] A. First title continued, 2024.',
                                      '[2] B. Second title, 2025.']


def test_legacy_merged_references_render_as_individual_hanging_paragraphs():
    doc = Doc(source='sample.pdf', blocks=[ref('h', 'REFERENCES'),
              ref('a', '[1] A. First, 2024. [2] B. Second, 2025.')])
    html = ''.join(build.to_html_blocks(doc))

    assert html.count('class="refitem"') == 2
    assert re.search(r'<p class="refitem">\[2\]', html)


def test_first_reference_is_not_mistaken_for_the_section_heading():
    doc = Doc(source='sample.pdf', blocks=[ref('a', '[1] A. First, 2024.')])
    html = ''.join(build.to_html_blocks(doc))

    assert '<p class="refitem">[1]' in html


def test_reference_processing_preserves_protected_image_blocks():
    panel = Block(id='a', page=0, kind='algorithm', text='',
                  x0=54, y0=50, x1=299, y1=100, image='fig/algorithm1.png')
    assert extract._merge_refs([panel, ref('r', '[1] Author, 2024.')])[0] is panel


def test_reference_ids_remain_stable_when_rebuilding_again():
    blocks = [ref('a', '[1] First, 2024.'), ref('b', '[2] Second, 2025.')]
    once = extract._merge_refs(blocks)
    twice = extract._merge_refs(once)
    assert [b.id for b in once] == [b.id for b in twice] == ['a', 'b']
