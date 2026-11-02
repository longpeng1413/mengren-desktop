"""Tests for finding, downloading, verifying and installing new versions."""

import hashlib
import io
import time
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel

from app.update_handoff import Handoff, parse_handoff
from core import update
from core.update import ReleaseInfo, UpdateCancelled, UpdateError
from ui import update_dialog
from ui.main_window import MainWindow
from ui.update_dialog import UpdateChecker, UpdateDialog


def _release(version: str = "18.40", sums: bool = True) -> ReleaseInfo:
    name = f"mengren-desktop-v{version}-windows-x64.zip"
    return ReleaseInfo(
        version=version,
        notes="- 新功能",
        page_url="https://github.com/longpeng1413/mengren-desktop/releases/tag/v" + version,
        zip_name=name,
        zip_url="https://example.invalid/" + name,
        zip_size=0,
        sums_url="https://example.invalid/SHA256SUMS.txt" if sums else "",
    )


class _Response:
    def __init__(self, data: bytes, status: int = 200, drop_after: int | None = None) -> None:
        self._stream = io.BytesIO(data)
        self._drop_after = drop_after
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size: int = -1) -> bytes:
        if self._drop_after is not None and (size < 0 or self._stream.tell() >= self._drop_after):
            # Like a real socket: reading past the cut raises instead of returning less.
            raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")
        if self._drop_after is not None:
            size = min(size, self._drop_after - self._stream.tell())
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _serve(monkeypatch, files: dict[str, bytes]) -> None:
    monkeypatch.setattr(update, "_open", lambda url, _timeout, _headers=None: _Response(files[url]))


def _zip_bytes(version: str, extra: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(f"猛人桌面助手v{version}正式版/猛人桌面助手v{version}.exe", b"exe")
        bundle.writestr(f"猛人桌面助手v{version}正式版/_internal/data.txt", b"data")
        if extra:
            bundle.writestr(extra, b"bad")
    return buffer.getvalue()


# ------------------------------------------------------------- versions ----


@pytest.mark.parametrize(
    ("remote", "local", "newer"),
    [("18.31", "18.30", True), ("v18.100", "18.99", True), ("19", "18.30", True), ("18.30", "18.30", False), ("18.2", "18.30", False)],
)
def test_versions_compare_as_numbers(remote, local, newer) -> None:
    assert update.is_newer(remote, local) is newer


def test_release_json_is_read_and_unusable_releases_are_skipped() -> None:
    body = {
        "html_url": "https://github.com/x/releases/tag/v18.40",
        "body": "说明",
        "assets": [
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/sums"},
            {"name": "mengren-desktop-v18.40-windows-x64.zip", "browser_download_url": "https://x/zip", "size": 9},
        ],
    }

    release = update.parse_release(body)

    assert (release.version, release.zip_url, release.sums_url, release.zip_size) == ("18.40", "https://x/zip", "https://x/sums", 9)
    assert update.parse_release({**body, "prerelease": True}) is None
    assert update.parse_release({**body, "assets": body["assets"][:1]}) is None


def test_checksum_is_found_by_file_name() -> None:
    text = "AAA  other.zip\nBBB  mengren-desktop-v18.40-windows-x64.zip\n"

    assert update.sha256_from_sums(text, "mengren-desktop-v18.40-windows-x64.zip") == "bbb"
    assert update.sha256_from_sums(text, "missing.zip") == ""


# ------------------------------------------------------------- download ----


def test_download_reports_progress_and_verifies(monkeypatch, tmp_path) -> None:
    release = _release()
    data = b"x" * 600_000
    digest = hashlib.sha256(data).hexdigest().upper()
    _serve(monkeypatch, {release.zip_url: data, release.sums_url: f"{digest}  {release.zip_name}\n".encode()})
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")
    seen = []

    path = update.download(release, progress=lambda got, total: seen.append((got, total)))

    assert path.read_bytes() == data
    assert seen[-1] == (len(data), len(data))
    assert not list((tmp_path / "dl").glob("*.part"))


def test_a_corrupt_download_is_rejected_and_removed(monkeypatch, tmp_path) -> None:
    release = _release()
    _serve(monkeypatch, {release.zip_url: b"broken", release.sums_url: f"{'0' * 64}  {release.zip_name}".encode()})
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")

    with pytest.raises(UpdateError, match="校验"):
        update.download(release)
    assert not any((tmp_path / "dl").iterdir())


def test_cancelling_leaves_no_partial_file(monkeypatch, tmp_path) -> None:
    release = _release(sums=False)
    _serve(monkeypatch, {release.zip_url: b"x" * 10})
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")

    with pytest.raises(UpdateCancelled):
        update.download(release, cancelled=lambda: True)
    assert not any((tmp_path / "dl").iterdir())


def _flaky_server(monkeypatch, release, data: bytes, drops: int, ranges: bool = True) -> list:
    """Serve ``data``, cutting the connection mid-way ``drops`` times."""
    requests = []
    digest = hashlib.sha256(data).hexdigest()

    def fake_open(url, _timeout, headers=None):
        if url == release.sums_url:
            return _Response(f"{digest}  {release.zip_name}".encode())
        requests.append(dict(headers or {}))
        start = int(headers["Range"][6:-1]) if headers and ranges else 0
        body = data[start:]
        drop = len(body) // 2 if len(requests) <= drops else None
        return _Response(body, 206 if start else 200, drop)

    monkeypatch.setattr(update, "_open", fake_open)
    monkeypatch.setattr(update, "RETRY_DELAY_SECONDS", 0)
    return requests


def test_a_dropped_connection_resumes_where_it_stopped(monkeypatch, tmp_path) -> None:
    release = _release()
    data = bytes(range(256)) * 4000
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")
    requests = _flaky_server(monkeypatch, release, data, drops=2)

    path = update.download(release)

    assert path.read_bytes() == data
    assert len(requests) == 3
    assert "Range" not in requests[0] and requests[1]["Range"].startswith("bytes=")


def test_a_server_without_resume_starts_over(monkeypatch, tmp_path) -> None:
    release = _release()
    data = bytes(range(256)) * 4000
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")
    _flaky_server(monkeypatch, release, data, drops=1, ranges=False)

    assert update.download(release).read_bytes() == data


def test_too_many_drops_give_up_cleanly(monkeypatch, tmp_path) -> None:
    release = _release()
    monkeypatch.setattr(update, "download_folder", lambda: tmp_path / "dl")
    _flaky_server(monkeypatch, release, b"x" * 100_000, drops=99)

    with pytest.raises(UpdateError, match="多次中断"):
        update.download(release)
    assert not any((tmp_path / "dl").iterdir())


def test_leftover_downloads_are_cleaned(monkeypatch, tmp_path) -> None:
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "old.zip.part").write_bytes(b"half")
    monkeypatch.setattr(update, "download_folder", lambda: folder)

    update.clean_downloads()

    assert not folder.exists()


# -------------------------------------------------------------- install ----


def test_new_version_is_unpacked_next_to_the_current_one(tmp_path) -> None:
    current = tmp_path / "mengren-desktop-v18.30-windows-x64" / "猛人桌面助手v18.30正式版" / "猛人桌面助手v18.30.exe"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"old")
    archive = tmp_path / "new.zip"
    archive.write_bytes(_zip_bytes("18.40"))

    new_exe = update.install(archive, current, "18.40")

    assert new_exe == (tmp_path / "mengren-desktop-v18.40-windows-x64" / "猛人桌面助手v18.40正式版" / "猛人桌面助手v18.40.exe").resolve() or new_exe.name == "猛人桌面助手v18.40.exe"
    assert new_exe.parent.parent.parent == tmp_path
    assert not archive.exists()
    assert current.exists()


def test_a_zip_escaping_its_folder_is_refused(tmp_path) -> None:
    current = tmp_path / "app" / "猛人桌面助手v18.30正式版" / "猛人桌面助手v18.30.exe"
    current.parent.mkdir(parents=True)
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes("18.40", extra="../../outside.txt"))

    with pytest.raises(UpdateError, match="不安全"):
        update.install(archive, current, "18.40")
    assert not (tmp_path / "outside.txt").exists()


def test_only_updater_made_folders_count_as_old_installs(tmp_path) -> None:
    ours = tmp_path / "mengren-desktop-v18.30-windows-x64" / "猛人桌面助手v18.30正式版" / "x.exe"
    other = tmp_path / "我的工具" / "猛人桌面助手v18.30正式版" / "x.exe"

    assert update.old_install_folder(ours) == tmp_path / "mengren-desktop-v18.30-windows-x64"
    assert update.old_install_folder(other) is None
    assert update.install_root_for(other) == tmp_path / "我的工具"


def test_the_new_copy_reads_the_handoff_arguments() -> None:
    handoff = parse_handoff(["app.exe", "--after-update", "1234", "--previous", r"D:\old\app.exe"])

    assert handoff == Handoff(1234, Path(r"D:\old\app.exe"))
    assert parse_handoff(["app.exe"]) is None
    assert parse_handoff(["app.exe", "--after-update", "x"]) is None


# ------------------------------------------------------------------- ui ----


def _wait_for(condition, seconds: float = 5.0) -> bool:
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_checker_reports_a_newer_release(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    release = _release()
    monkeypatch.setattr(update, "check_for_update", lambda: release)
    checker = UpdateChecker()
    found, manual = [], []
    checker.update_available.connect(found.append)
    checker.manual_check_finished.connect(lambda got, error: manual.append((got, error)))

    checker.check_now(manual=True)

    assert _wait_for(lambda: manual)
    assert found == [release]
    assert manual == [(release, "")]


def test_a_failed_check_is_quiet_unless_asked(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])

    def fail():
        raise UpdateError("无法连接 GitHub")

    monkeypatch.setattr(update, "check_for_update", fail)
    checker = UpdateChecker()
    found, manual = [], []
    checker.update_available.connect(found.append)
    checker.manual_check_finished.connect(lambda got, error: manual.append(error))

    checker.check_now(manual=True)

    assert _wait_for(lambda: manual)
    assert found == [] and "GitHub" in manual[0]


class _Service(QObject):
    capture_failed = Signal(str)

    def start_capture(self):
        pass

    def start_long_capture(self):
        pass

    def toggle_presentation(self):
        pass


def test_main_window_shows_the_update_button_and_github_link() -> None:
    _app = QApplication.instance() or QApplication([])
    window = MainWindow(_Service(), lambda _settings: True)

    assert window._update_button.isHidden()
    window.show_update_available("18.40")

    assert not window._update_button.isHidden()
    assert window._update_button.text() == "发现新版本 v18.40"
    links = [label.text() for label in window.findChildren(QLabel) if "github.com/longpeng1413/mengren-desktop" in label.text()]
    assert links
    window.deleteLater()


def test_source_runs_cannot_update_themselves(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(update, "running_exe", lambda: None)

    dialog = UpdateDialog(_release())

    assert not dialog.update_button.isEnabled()
    assert "源码" in dialog.status.text()
    dialog.deleteLater()


def test_deep_package_folders_unpack_beyond_260_characters(tmp_path) -> None:
    deep = tmp_path / ("很长的文件夹名" * 6) / ("另一个很长的文件夹" * 5)
    current = deep / "mengren-desktop-v18.30-windows-x64" / "猛人桌面助手v18.30正式版" / "猛人桌面助手v18.30.exe"
    current.parent.mkdir(parents=True)
    member = "猛人桌面助手v18.40正式版/_internal/" + "/".join(["numpy-licenses-folder"] * 8) + "/LICENSE.txt"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("猛人桌面助手v18.40正式版/猛人桌面助手v18.40.exe", b"exe")
        bundle.writestr(member, b"license")
    archive = tmp_path / "new.zip"
    archive.write_bytes(buffer.getvalue())
    assert len(str(deep / "mengren-desktop-v18.40-windows-x64" / member)) > 260

    new_exe = update.install(archive, current, "18.40")

    assert new_exe.name == "猛人桌面助手v18.40.exe"


def test_a_dropped_version_check_is_retried(monkeypatch) -> None:
    calls = []
    body = (
        b'{"html_url": "u", "assets": [{"name": "mengren-desktop-v18.40-windows-x64.zip",'
        b' "browser_download_url": "z"}]}'
    )

    def fake_open(url, _timeout, _headers=None):
        calls.append(url)
        if len(calls) == 1:
            return _Response(body, drop_after=3)
        return _Response(body)

    monkeypatch.setattr(update, "_open", fake_open)
    monkeypatch.setattr(update, "RETRY_DELAY_SECONDS", 0)

    assert update.fetch_latest().version == "18.40"
    assert len(calls) == 2


def test_the_running_folder_is_never_replaced(tmp_path) -> None:
    current = tmp_path / "mengren-desktop-v18.40-windows-x64" / "猛人桌面助手v18.40正式版" / "猛人桌面助手v18.40.exe"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"running")
    archive = tmp_path / "same.zip"
    archive.write_bytes(_zip_bytes("18.40"))

    with pytest.raises(UpdateError, match="已经安装"):
        update.install(archive, current, "18.40")
    assert current.read_bytes() == b"running"
