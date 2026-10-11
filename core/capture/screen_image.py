import mss

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPixmap


class ScreenImage:

    @staticmethod
    def grab(rect: QRect) -> QPixmap:

        monitor = {
            "left": rect.x(),
            "top": rect.y(),
            "width": rect.width(),
            "height": rect.height(),
        }

        with mss.mss() as sct:

            shot = sct.grab(monitor)

            image = QImage(
                shot.rgb,
                shot.width,
                shot.height,
                QImage.Format_RGB888,
            )

            return QPixmap.fromImage(image.copy())