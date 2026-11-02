"""Background update checks and the dark update window.

The checker asks GitHub 15 seconds after start and then every 12 hours; a
failed check stays silent. The window shows the release notes and, on
"立即更新", downloads, verifies and installs the new version on a background
thread, then starts it and quits this copy.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from app.branding import APP_DISPLAY_NAME
from app.update_handoff import launch_new_version
from core import update
from core.update import ReleaseInfo, UpdateCancelled, UpdateError
from ui import theme

_log = logging.getLogger(__name__)

FIRST_CHECK_MS = 15 * 1000
CHECK_INTERVAL_MS = 12 * 60 * 60 * 1000


class _CheckWorker(QObject):
    finished = Signal(object, str)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(update.check_for_update(), "")
        except UpdateError as error:
            self.finished.emit(None, str(error))
        except Exception as error:  # A check must never break the app.
            _log.exception("检查更新出现意外错误")
            self.finished.emit(None, f"检查更新失败：{error}")


class UpdateChecker(QObject):
    """Checks GitHub now and then; reports a newer release once found."""

    update_available = Signal(object)
    manual_check_finished = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _CheckWorker | None = None
        self._manual = False
        self.latest: ReleaseInfo | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_now)

    def start(self) -> None:
        QTimer.singleShot(FIRST_CHECK_MS, self.check_now)
        self._timer.start(CHECK_INTERVAL_MS)

    def check_now(self, manual: bool = False) -> None:
        if self._thread is not None:
            self._manual = self._manual or manual
            return
        self._manual = manual
        thread = QThread(self)
        worker = _CheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Keep the worker referenced until its thread has completely stopped:
        # dropping it earlier lets Python destroy it from this thread while the
        # worker thread is still running, which makes Qt abort the whole app.
        thread.finished.connect(self._release)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _release(self) -> None:
        self._thread = None
        self._worker = None

    def _finished(self, release: ReleaseInfo | None, error: str) -> None:
        if error:
            _log.info("检查更新没有成功：%s", error)
        if release is not None:
            self.latest = release
            self.update_available.emit(release)
        if self._manual:
            self.manual_check_finished.emit(release, error)
        self._manual = False


class _InstallWorker(QObject):
    progress = Signal(int, int)
    stage = Signal(str)
    installed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, release: ReleaseInfo, exe) -> None:
        super().__init__()
        self._release = release
        self._exe = exe
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            self.stage.emit("正在下载新版本……")
            archive = update.download(
                self._release,
                progress=lambda received, total: self.progress.emit(received, total),
                cancelled=self._cancel.is_set,
            )
            self.stage.emit("下载完成，正在安装……")
            self.installed.emit(update.install(archive, self._exe, self._release.version))
        except UpdateCancelled as error:
            self.failed.emit(str(error))
        except UpdateError as error:
            _log.warning("更新失败：%s", error, exc_info=error.__cause__ is not None)
            self.failed.emit(str(error))
        except Exception as error:
            _log.exception("更新出现意外错误")
            self.failed.emit(f"更新失败：{error}")
        finally:
            self.finished.emit()


_STYLE = f"""
QDialog {{ background: {theme.BACKGROUND}; }}
QLabel {{ color: {theme.TEXT}; font-family: {theme.FONT}; font-size: 13px; }}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#muted {{ color: {theme.MUTED}; font-size: 12px; }}
QTextBrowser {{
    color: {theme.TEXT};
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 10px;
    padding: 8px;
    font-family: {theme.FONT};
    font-size: 13px;
}}
QProgressBar {{
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: {theme.TEXT};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 5px; }}
QPushButton {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 8px;
    padding: 0 16px;
    min-height: 32px;
    font-family: {theme.FONT};
    font-size: 13px;
}}
QPushButton:hover {{ background: {theme.HOVER}; border-color: {theme.MUTED}; }}
QPushButton:disabled {{ color: {theme.DISABLED}; }}
QPushButton#primaryButton {{
    color: {theme.ACCENT_INK};
    background: {theme.ACCENT};
    border-color: {theme.ACCENT};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{ background: #7fd3aa; }}
"""


class UpdateDialog(QDialog):
    """Shows a new release and installs it on request."""

    def __init__(self, release: ReleaseInfo, parent=None) -> None:
        super().__init__(parent)
        self._release = release
        self._thread: QThread | None = None
        self._worker: _InstallWorker | None = None
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 软件更新")
        self.resize(560, 480)
        self.setStyleSheet(_STYLE)

        title = QLabel(f"发现新版本 v{release.version}")
        title.setObjectName("title")
        current = QLabel(f"当前版本 v{update.current_version()} · 来自 GitHub 正式发布")
        current.setObjectName("muted")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(release.notes or "这个版本没有写更新说明。")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.status = QLabel("点“立即更新”会自动下载、校验并安装新版本，完成后自动重启软件。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.update_button = QPushButton("立即更新")
        self.update_button.setObjectName("primaryButton")
        self.page_button = QPushButton("打开下载页")
        self.close_button = QPushButton("以后再说")
        self.update_button.clicked.connect(self.start_update)
        self.page_button.clicked.connect(self._open_page)
        self.close_button.clicked.connect(self._close_or_cancel)
        if update.running_exe() is None:
            self.update_button.setEnabled(False)
            self.status.setText("当前是从源码运行，不能自动更新；请点“打开下载页”下载新版本。")

        buttons = QHBoxLayout()
        buttons.addWidget(self.page_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.update_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(current)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        theme.dark_title_bar(self)

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release.page_url))

    def start_update(self) -> None:
        exe = update.running_exe()
        if exe is None or self._thread is not None:
            return
        self.update_button.setEnabled(False)
        self.page_button.setEnabled(False)
        self.close_button.setText("取消")
        self.progress.setValue(0)
        self.progress.show()
        thread = QThread(self)
        worker = _InstallWorker(self._release, exe)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._show_progress)
        worker.stage.connect(self.status.setText)
        worker.installed.connect(self._restart)
        worker.failed.connect(self._show_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._worker_done)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _show_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(received * 100 / total))
            self.status.setText(f"正在下载新版本…… {received / 1048576:.1f} / {total / 1048576:.1f} MB")

    def _restart(self, new_exe) -> None:
        self.status.setText("安装完成，正在启动新版本……")
        self.progress.setValue(100)
        old_exe = update.running_exe()
        try:
            launch_new_version(new_exe, old_exe)
        except OSError as error:
            self._show_failure(f"新版本已安装到 {new_exe.parent}，但没能自动启动：{error}")
            return
        _log.info("已启动新版本 %s，当前版本退出", new_exe)
        QTimer.singleShot(300, QApplication.quit)

    def _show_failure(self, message: str) -> None:
        self.status.setText(f"<span style='color:{theme.DANGER}'>{message}</span>")
        self.progress.hide()
        self.update_button.setEnabled(True)
        self.update_button.setText("重试")
        self.page_button.setEnabled(True)
        self.close_button.setText("以后再说")

    def _worker_done(self) -> None:
        self._thread = None
        self._worker = None

    def _close_or_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("正在取消……")
            return
        self.reject()

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            return
        super().reject()
