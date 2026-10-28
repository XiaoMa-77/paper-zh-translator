import pytest

from papertrans import paginate


def test_complete_flows_are_measured_before_packing_pages(monkeypatch):
    measured = iter([[], [400, 800], [400]])
    monkeypatch.setattr(paginate, "measure_blocks", lambda *args: next(measured))

    html, pages = paginate.build_pages(["a", "b"], "", ".")

    assert pages == 2
    assert html.count('height:402.0pt') == 2


def test_longest_fitting_prefix_fills_space_below_a_heading(monkeypatch):
    measured = iter([[100], [250, 500, 750], [250]])
    monkeypatch.setattr(paginate, "measure_blocks", lambda *args: next(measured))

    html, pages = paginate.build_pages(['<div class="head">T</div>', "a", "b", "c"], "", ".")

    assert pages == 2
    first_page, second_page = html.split('<div class="page last">')
    assert "ab" in first_page
    assert "c" in second_page


def test_one_oversized_block_errors_instead_of_silently_clipping(monkeypatch):
    measured = iter([[], [800]])
    monkeypatch.setattr(paginate, "measure_blocks", lambda *args: next(measured))

    with pytest.raises(RuntimeError, match="超过整页高度"):
        paginate.build_pages(["a"], "", ".")
