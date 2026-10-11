"""Resizable screenshot annotation frame."""

from __future__ import annotations

from ui.image_canvas import ImageCanvas


class ResizableFrame(ImageCanvas):
    """An editable image canvas with a WeChat-style draggable resize border."""

    def __init__(self) -> None:
        super().__init__(resizable=True)
