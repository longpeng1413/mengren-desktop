"""Find, download, verify and install new releases from GitHub.

The app asks GitHub for the latest release, compares its version with its own
and, when the user agrees, downloads the release zip, checks it against the
published SHA256SUMS.txt, unpacks it next to the current installation and
hands over to the new EXE. Downloads live in a temporary folder that is removed
after installing and at every start, so an interrupted download never stays
behind.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from app.branding import APP_VERSION

_log = logging.getLogger(__name__)

REPOSITORY = "longpeng1413/mengren-desktop"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
RELEASES_URL = f"{REPOSITORY_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ZIP_PATTERN = re.compile(r"^mengren-desktop-v([\d.]+)-windows-x64\.zip$")
INSTALL_FOLDER = re.compile(r"^mengren-desktop-v[\d.]+-windows-x64$")
# Lets a test copy pretend to be older so it can update itself.
PRETEND_VERSION_VARIABLE = "MENGREN_UPDATE_FROM_VERSION"
_USER_AGENT = "MengRenDesktop-Updater"
_CHUNK = 256 * 1024
DOWNLOAD_ATTEMPTS = 6
RETRY_DELAY_SECONDS = 2

# Services abroad go through the Windows proxy first, then directly.
_ROUTES: tuple[OpenerDirector, ...] = (build_opener(), build_opener(ProxyHandler({})))


class UpdateError(RuntimeError):
    """Checking, downloading or installing an update failed."""


class UpdateCancelled(UpdateError):
    """The user stopped the download."""


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """The latest release as GitHub reports it."""

    version: str
    notes: str
    page_url: str
    zip_name: str
    zip_url: str
    zip_size: int
    sums_url: str


def current_version() -> str:
    return os.environ.get(PRETEND_VERSION_VARIABLE) or APP_VERSION


def version_key(version: str) -> tuple[int, ...]:
    """``"v18.31"`` -> ``(18, 31)``; anything unreadable sorts lowest."""
    numbers = re.findall(r"\d+", version)
    return tuple(int(number) for number in numbers) if numbers else (0,)


def is_newer(remote: str, local: str | None = None) -> bool:
    return version_key(remote) > version_key(local or current_version())


def parse_release(body: dict) -> ReleaseInfo | None:
    """Read GitHub's release JSON; ``None`` when it has no Windows zip."""
    if not isinstance(body, dict) or body.get("draft") or body.get("prerelease"):
        return None
    assets = body.get("assets") or []
    archive = next(
        (asset for asset in assets if ZIP_PATTERN.match(str(asset.get("name", "")))),
        None,
    )
    if archive is None:
        return None
    sums = next((asset for asset in assets if asset.get("name") == "SHA256SUMS.txt"), None)
    version = ZIP_PATTERN.match(archive["name"]).group(1)
    return ReleaseInfo(
        version=version,
        notes=str(body.get("body") or "").strip(),
        page_url=str(body.get("html_url") or RELEASES_URL),
        zip_name=str(archive["name"]),
        zip_url=str(archive.get("browser_download_url") or ""),
        zip_size=int(archive.get("size") or 0),
        sums_url=str(sums.get("browser_download_url") or "") if sums else "",
    )


def _open(url: str, timeout: float, headers: dict[str, str] | None = None):
    """Open ``url`` over the proxy, then directly; raise :class:`UpdateError`."""
    request = Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json", **(headers or {})},
    )
    last: Exception | None = None
    for opener in _ROUTES:
        try:
            return opener.open(request, timeout=timeout)
        except HTTPError as error:
            raise UpdateError(f"GitHub 返回错误（HTTP {error.code}）。") from error
        except (URLError, OSError) as error:
            last = error
    raise UpdateError("无法连接 GitHub，请检查网络或代理。") from last


def _read_small(url: str, timeout: float, attempts: int = 3) -> bytes:
    """Read a small reply, retrying when a proxy cuts the connection."""
    for attempt in range(1, attempts + 1):
        try:
            with _open(url, timeout) as response:
                return response.read()
        except (OSError, UpdateError) as error:
            if isinstance(error, UpdateError) and isinstance(error.__cause__, HTTPError):
                raise
            if attempt == attempts:
                if isinstance(error, UpdateError):
                    raise
                raise UpdateError("连接 GitHub 时网络中断，请稍后再试。") from error
            time.sleep(RETRY_DELAY_SECONDS)
    raise UpdateError("连接 GitHub 失败。")


def fetch_latest(timeout: float = 15) -> ReleaseInfo | None:
    """Return the latest release, or ``None`` if it has no usable zip."""
    try:
        body = json.loads(_read_small(LATEST_API, timeout).decode("utf-8"))
    except ValueError as error:
        raise UpdateError("GitHub 返回了无法识别的数据。") from error
    return parse_release(body)


def check_for_update(timeout: float = 15) -> ReleaseInfo | None:
    """Return the latest release only if it is newer than this copy."""
    release = fetch_latest(timeout)
    if release is None or not is_newer(release.version):
        return None
    return release


def download_folder() -> Path:
    return Path(tempfile.gettempdir()) / "MengRenDesktop-update"


def clean_downloads() -> None:
    """Delete leftover downloads, including half-finished ones."""
    shutil.rmtree(download_folder(), ignore_errors=True)


def download(
    release: ReleaseInfo,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 60,
) -> Path:
    """Download and verify the release zip; return its path.

    Proxies often cut long transfers, so a dropped connection resumes from
    the bytes already received (an HTTP range request), up to
    :data:`DOWNLOAD_ATTEMPTS` times; a server that ignores the range makes the
    download start over.
    """
    folder = download_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.zip_name
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0
    total = release.zip_size
    attempt = 0
    with partial.open("wb") as output:
        while True:
            attempt += 1
            headers = {"Range": f"bytes={received}-"} if received else None
            try:
                with _open(release.zip_url, timeout, headers) as response:
                    if received and getattr(response, "status", 206) != 206:
                        # No resume support: start again from the first byte.
                        output.seek(0)
                        output.truncate()
                        digest = hashlib.sha256()
                        received = 0
                    length = int(response.headers.get("Content-Length") or 0)
                    if length:
                        total = received + length
                    while True:
                        if cancelled is not None and cancelled():
                            raise UpdateCancelled("已取消下载。")
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if progress is not None:
                            progress(received, total)
                if not total or received >= total:
                    break
                raise ConnectionResetError("连接提前结束")
            except UpdateCancelled:
                output.close()
                partial.unlink(missing_ok=True)
                raise
            except (OSError, UpdateError) as error:
                if attempt >= DOWNLOAD_ATTEMPTS:
                    output.close()
                    partial.unlink(missing_ok=True)
                    raise UpdateError("下载时网络多次中断，请稍后重试，或打开下载页自己下载。") from error
                _log.warning("下载中断（第 %s 次），从 %s 字节处继续：%r", attempt, received, error)
                time.sleep(RETRY_DELAY_SECONDS * attempt)
    if total and received != total:
        partial.unlink(missing_ok=True)
        raise UpdateError("下载不完整，请重试。")
    expected = expected_sha256(release)
    if expected and digest.hexdigest().lower() != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError("下载的文件校验不通过，可能已损坏，请重试。")
    partial.replace(target)
    return target


def expected_sha256(release: ReleaseInfo) -> str:
    """Read the zip's checksum from SHA256SUMS.txt; empty when unavailable."""
    if not release.sums_url:
        return ""
    text = _read_small(release.sums_url, 30).decode("utf-8", "replace")
    return sha256_from_sums(text, release.zip_name)


def sha256_from_sums(text: str, file_name: str) -> str:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == file_name:
            return parts[0].lower()
    return ""


def install_root_for(exe: Path) -> Path:
    """The folder that receives new versions, next to the current one."""
    release_folder = exe.resolve().parent
    wrapper = release_folder.parent
    return wrapper.parent if INSTALL_FOLDER.match(wrapper.name) else wrapper


def install(archive: Path, exe: Path, version: str) -> Path:
    """Unpack the zip next to the current installation; return the new EXE."""
    target = install_root_for(exe) / f"mengren-desktop-v{version}-windows-x64"
    if target.resolve() in exe.resolve().parents:
        # Never replace the folder this copy is running from.
        raise UpdateError(f"v{version} 已经安装在当前文件夹，无需更新。")
    if target.exists():
        shutil.rmtree(_long_path(target), ignore_errors=True)
    target.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            root = target.resolve()
            for member in bundle.namelist():
                destination = (target / member).resolve()
                if root not in destination.parents and destination != root:
                    raise UpdateError("更新包里有不安全的路径，已停止安装。")
            bundle.extractall(_long_path(target))
    except (zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(_long_path(target), ignore_errors=True)
        raise UpdateError(f"解压新版本失败：{error}") from error
    found = sorted(target.glob(f"*/*v{version}.exe"))
    if not found:
        shutil.rmtree(_long_path(target), ignore_errors=True)
        raise UpdateError("更新包里没有找到程序文件。")
    archive.unlink(missing_ok=True)
    return found[0]


def _long_path(path: Path) -> str:
    """Windows' extended form, so deep folders inside the package can exceed 260 characters."""
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def old_install_folder(old_exe: Path) -> Path | None:
    """The previous version's folder, only if it is one this updater made."""
    release_folder = old_exe.resolve().parent
    wrapper = release_folder.parent
    return wrapper if INSTALL_FOLDER.match(wrapper.name) else None


def running_exe() -> Path | None:
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
