"""Keep one copy of the app running per Windows user.

The first copy listens on a local named pipe. A copy started later (for example
by double-clicking the desktop icon while the app already sits in the tray)
connects to it, asks it to show its main window and quits. The pipe name does
not contain the version, so different versions also find each other. Nothing is
written to disk, so a crash leaves nothing behind to clean up.
"""

from __future__ import annotations

import ctypes
import getpass
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger(__name__)

_SHOW_REQUEST = b"show"
_ASFW_ANY = -1


def server_name() -> str:
    """Return the pipe name shared by every version for the current user."""
    return f"MengRenDesktop-{getpass.getuser()}"


def notify_running_instance(name: str | None = None, timeout_ms: int = 800) -> bool:
    """Ask an already running copy to show itself; return whether one answered."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    try:
        # This copy was just started by the user, so it may hand the right to
        # bring a window to the front to the running copy.
        ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)
    except (AttributeError, OSError):
        pass
    socket.write(_SHOW_REQUEST)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Listens for later copies and reports when one asks to show the window."""

    show_requested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._name = name or server_name()
        self._server.newConnection.connect(self._accept)
        if not self._server.listen(self._name):
            # A pipe left by a crashed copy: remove it and listen again.
            QLocalServer.removeServer(self._name)
            if not self._server.listen(self._name):
                _log.warning("无法启用单实例检查：%s", self._server.errorString())

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        # Any connection is a later launch: the request text is not needed,
        # and a copy that quits quickly may close before it could be read.
        accepted = False
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.disconnected.connect(socket.deleteLater)
            socket.disconnectFromServer()
            accepted = True
        if accepted:
            _log.info("又打开了一次软件，已改为显示正在运行的主窗口")
            self.show_requested.emit()
