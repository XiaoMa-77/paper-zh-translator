import pytest

from papertrans.extract import CAP_TAB
from papertrans.extract import _ruled_table_box
import pymupdf


@pytest.mark.parametrize("label", ["I", "II", "III", "IV", "1"])
def test_ieee_table_caption_without_punctuation_is_recognized(label):
    assert CAP_TAB.match(f"TABLE {label} COMPARISON ON THE VALIDATION SET.")


@pytest.mark.parametrize("text", ["Table 1: Results", "TABLE II. RESULTS"])
def test_punctuated_table_caption_still_works(text):
    assert CAP_TAB.match(text)


@pytest.mark.parametrize("text", ["Table identification is difficult", "Table IIIa text"])
def test_ordinary_words_are_not_table_numbers(text):
    assert not CAP_TAB.match(text)


def test_horizontal_rules_bound_the_complete_table_without_the_next_table():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    for y in (80, 110, 210, 310, 450, 520, 560):
        page.draw_line((54, y), (565, y))

    box = _ruled_table_box(page, pymupdf.Rect(54, 50, 565, 70), -1, limit=500)

    assert box is not None
    assert box.y0 == 78
    assert box.y1 == 452
