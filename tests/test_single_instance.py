"""Tests for running only one copy of the app."""

import subprocess
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.single_instance import InstanceServer, notify_running_instance, server_name


def _unique_name() -> str:
    # Never the real pipe, so the developer's running copy is not disturbed.
    return f"MengRenDesktop-test-{uuid.uuid4().hex}"


def _wait_for(condition, seconds: float = 5.0) -> bool:
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_without_a_running_copy_the_app_starts_normally() -> None:
    _app = QApplication.instance() or QApplication([])

    assert not notify_running_instance(_unique_name(), timeout_ms=200)


def test_a_second_launch_asks_the_running_copy_to_show_itself() -> None:
    _app = QApplication.instance() or QApplication([])
    name = _unique_name()
    server = InstanceServer(name)
    requests: list[bool] = []
    server.show_requested.connect(lambda: requests.append(True))

    assert server.listening
    assert notify_running_instance(name)
    assert _wait_for(lambda: requests == [True])
    server.close()


def test_a_second_process_is_turned_away(tmp_path: Path) -> None:
    _app = QApplication.instance() or QApplication([])
    name = _unique_name()
    server = InstanceServer(name)
    requests: list[bool] = []
    server.show_requested.connect(lambda: requests.append(True))
    script = tmp_path / "second_copy.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "from app.single_instance import notify_running_instance\n"
        "app = QCoreApplication([])\n"
        f"sys.exit(0 if notify_running_instance({name!r}, 3000) else 1)\n",
        encoding="utf-8",
    )

    second = subprocess.Popen([sys.executable, str(script)])

    assert _wait_for(lambda: second.poll() is not None, 20)
    assert second.returncode == 0
    assert _wait_for(lambda: requests == [True])
    server.close()


def test_every_version_shares_one_name_per_user() -> None:
    assert server_name().startswith("MengRenDesktop-")
    assert "18." not in server_name()
