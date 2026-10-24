"""Tests for grouping OCR lines into paragraphs and translating them whole."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.ocr.ocr_service import OcrLine
from core.translate.base import BatchTranslator
from core.translate.text_blocks import group_text_blocks
from ui.translation_worker import TranslationWorker


def _line(text: str, x: int, y: int, width: int, height: int = 18) -> OcrLine:
    return OcrLine(text, 0.99, QRect(x, y, width, height))


def test_wrapped_lines_become_one_paragraph_split_at_wider_gaps() -> None:
    lines = (
        _line("Cause: the area the editing view could cover was set from", 21, 64, 690),
        _line("changed. A screenshot started on one screen only got that", 21, 83, 699),
        _line("only tested screenshots that started across screens.", 21, 102, 451),
        _line("Fix: the editing view now covers every screen with the", 22, 132, 694),
        _line("whether you start on one screen or across several.", 21, 150, 660),
    )

    blocks = group_text_blocks(lines)

    assert [block.text for block in blocks] == [
        "Cause: the area the editing view could cover was set from changed. "
        "A screenshot started on one screen only got that only tested "
        "screenshots that started across screens.",
        "Fix: the editing view now covers every screen with the whether you "
        "start on one screen or across several.",
    ]
    assert blocks[0].bounds == QRect(21, 64, 699, 56)
    assert blocks[0].line_height == 18


def test_short_heading_line_ends_its_paragraph() -> None:
    lines = (
        _line("Checks:", 21, 197, 57, 17),
        _line("On your four screens I took a small screenshot and dragged it", 21, 216, 657),
    )

    assert [block.text for block in group_text_blocks(lines)] == [
        "Checks:",
        "On your four screens I took a small screenshot and dragged it",
    ]


def test_fragments_of_one_row_are_joined_and_columns_stay_apart() -> None:
    lines = (
        _line("Tip: you can pin", 560, 70, 150),
        _line("The editor lets", 30, 70, 140),
        _line("you annotate", 176, 70, 120),
        _line("a screenshot", 560, 89, 130),
    )

    assert [block.text for block in group_text_blocks(lines)] == [
        "The editor lets you annotate",
        "Tip: you can pin a screenshot",
    ]


def test_text_list_markers_start_items_and_are_kept_aside() -> None:
    lines = (
        _line("• Press F1 to capture a region.", 30, 20, 300),
        _line("• Drag the corners to resize the", 30, 39, 310),
        _line("selection before you confirm it.", 48, 58, 300),
    )

    blocks = group_text_blocks(lines)

    assert [(block.prefix, block.text) for block in blocks] == [
        ("• ", "Press F1 to capture a region."),
        ("• ", "Drag the corners to resize the selection before you confirm it."),
    ]


def test_drawn_bullet_dots_start_new_list_items() -> None:
    _app = QApplication.instance() or QApplication([])
    image = QImage(400, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("#151515"))
    painter = QPainter(image)
    painter.fillRect(QRect(31, 33, 4, 4), QColor("#e0e0e0"))
    painter.fillRect(QRect(31, 74, 4, 4), QColor("#e0e0e0"))
    painter.end()
    lines = (
        _line("On your four screens I took a small screenshot and the", 50, 26, 340),
        _line("editing view covered all four screens.", 50, 46, 300),
        _line("I added tests for starting on one screen.", 50, 67, 330),
    )

    blocks = group_text_blocks(lines, image)

    assert [block.text for block in blocks] == [
        "On your four screens I took a small screenshot and the editing view "
        "covered all four screens.",
        "I added tests for starting on one screen.",
    ]


def test_chinese_lines_join_without_spaces_and_hyphens_rejoin_words() -> None:
    lines = (
        _line("编辑画面现在从一开始就覆盖", 20, 20, 300),
        _line("所有缩放相同的屏幕。", 20, 39, 200),
        _line("A screen-", 20, 80, 300),
        _line("shot is ready.", 20, 99, 140),
    )

    assert [block.text for block in group_text_blocks(lines)] == [
        "编辑画面现在从一开始就覆盖所有缩放相同的屏幕。",
        "A screenshot is ready.",
    ]


def test_nearly_equal_left_edges_are_aligned() -> None:
    lines = (
        _line("First paragraph.", 50, 20, 300),
        _line("Second paragraph.", 48, 80, 300),
    )

    assert {block.bounds.left() for block in group_text_blocks(lines)} == {48}


class _RecordingTranslator(BatchTranslator):
    def __init__(self) -> None:
        self.requests: list[tuple[str, ...]] = []

    def translate_many_to_chinese(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        self.requests.append(texts)
        return tuple(f"译文{index}" for index, _text in enumerate(texts))


def test_worker_translates_whole_paragraphs_and_restores_list_markers() -> None:
    _app = QApplication.instance() or QApplication([])
    blocks = group_text_blocks(
        (
            _line("The editor lets you annotate screenshots with", 20, 20, 400),
            _line("arrows, shapes and text.", 20, 39, 200),
            _line("- Press F1 to capture.", 20, 80, 200),
        )
    )
    translator = _RecordingTranslator()

    translations = TranslationWorker(QImage())._translate_all(translator, blocks)

    assert translator.requests == [
        ("The editor lets you annotate screenshots with arrows, shapes and text.", "Press F1 to capture.")
    ]
    assert [item.text for item in translations] == ["译文0", "- 译文1"]
    assert translations[0].line_height == 18
