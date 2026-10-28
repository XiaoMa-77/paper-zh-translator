import pymupdf
import re

from papertrans import extract
from papertrans.model import Block, Doc


def test_overlapping_short_superscript_is_included_in_equation_crop(tmp_path):
    source = pymupdf.open()
    source.new_page(width=612, height=792)
    label = Block(id='a', page=0, kind='body', text='aWj+1',
                  x0=54, y0=298, x1=80, y1=310)
    formula = Block(id='b', page=0, kind='body', text='y=Decoder(x)',
                    x0=60, y0=302, x1=290, y1=326)
    heading = Block(id='h', page=0, kind='heading2', text='C. Next section',
                    x0=54, y0=360, x1=180, y1=370)
    doc = Doc(source='sample.pdf', blocks=[label, formula, heading])
    (tmp_path/'fig').mkdir()

    extract._extract_equations(doc, source, str(tmp_path), 72, {})

    assert len(doc.blocks) == 2
    assert doc.blocks[0].kind == 'equation'
    assert doc.blocks[0].y0 <= 298
    assert doc.blocks[1] is heading


def test_complete_ruled_algorithm_is_one_panel_and_preserves_all_twelve_lines(tmp_path):
    source = pymupdf.open()
    page = source.new_page(width=612, height=792)
    page.draw_line((313, 90), (558, 90))
    page.draw_line((313, 260), (558, 260))
    for i in range(1, 13):
        page.insert_text((319, 90 + i * 13), f'{i}: step {i}')
    heading = Block(id='h', page=0, kind='heading2', text='Algorithm 1 Example',
                    x0=313, y0=72, x1=480, y1=84, col=1)
    fragments = [Block(id='c', page=0, kind='body', text='code fragments',
                       x0=319, y0=94, x1=550, y1=248, col=1)]
    following = Block(id='d', page=0, kind='heading2', text='D. Next section',
                      x0=313, y0=275, x1=480, y1=285, col=1)
    doc = Doc(source='sample.pdf', blocks=[heading, *fragments, following])
    (tmp_path/'fig').mkdir()

    extract._extract_algorithms(doc, source, str(tmp_path), 72, {})

    assert [b.kind for b in doc.blocks] == ['heading2', 'algorithm', 'heading2']
    panel = doc.blocks[1]
    assert re.findall(r'(\d+):', page.get_textbox(pymupdf.Rect(panel.meta['bbox']))) == [str(i) for i in range(1, 13)]


def test_figure_cut_through_a_photo_expands_to_its_whitespace_boundary():
    source = pymupdf.open()
    page = source.new_page(width=612, height=792)
    page.draw_rect(pymupdf.Rect(54, 54, 558, 200), fill=(0, 0, 0))
    box = extract._expand_figure_top(page, pymupdf.Rect(45, 100, 567, 205), 40)
    assert box.y0 < 54
