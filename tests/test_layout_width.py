import pytest

from papertrans import build, paginate, render
from papertrans.model import Block


@pytest.mark.parametrize("class_name", ["full", "tabwrap full", "head"])
def test_full_width_blocks_are_paginated_as_spans(class_name):
    assert paginate._is_span(f'<div class="{class_name}">table</div>')


def test_wide_table_is_measured_at_the_same_width_as_printing(monkeypatch, tmp_path):
    def dump(path):
        assert 'width:514pt;' in tmp_path.joinpath('_measure.html').read_text(encoding='utf-8')
        return '<pre id="out">[[0,100]]</pre>'

    monkeypatch.setattr(render, 'dump_dom', dump)
    assert render.measure_blocks(['<div class="tabwrap full">x</div>'], '', str(tmp_path)) == [75]


def test_table_uses_crop_width_instead_of_narrow_caption_width():
    block = Block(id='t', page=0, kind='table', text='TABLE I',
                  x0=200, y0=40, x1=400, y1=60, full_width=True,
                  meta={'bbox': [54, 80, 565, 450]})
    assert 'width:514.0pt;' in build._img_style(block)
