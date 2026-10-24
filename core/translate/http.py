"""Network requests for translation services that survive dropped connections.

Windows hands Python the system proxy (for example Clash). Services inside
China, such as Youdao, are often cut off half-way through such a proxy, so they
are reached directly first and through the proxy only as a fallback. Services
abroad go through the proxy as before. A connection that is dropped or times
out is retried once over the next route.
"""

from __future__ import annotations

import logging
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

_log = logging.getLogger(__name__)

_DIRECT = build_opener(ProxyHandler({}))
_SYSTEM_PROXY = build_opener()


class NetworkError(OSError):
    """Raised when every route failed before the service answered."""


def read_response(request: Request, timeout: float, *, prefer_direct: bool = False) -> bytes:
    """Return the response body, trying a second route if the first one fails.

    ``HTTPError`` is raised unchanged: the service answered, so another route
    would not help.
    """
    routes = (
        (("直连", _DIRECT), ("系统代理", _SYSTEM_PROXY))
        if prefer_direct
        else (("系统代理", _SYSTEM_PROXY), ("系统代理重试", _SYSTEM_PROXY))
    )
    last_error: Exception | None = None
    for name, opener in routes:
        try:
            return _open(opener, request, timeout)
        except HTTPError:
            raise
        except (URLError, HTTPException, OSError) as error:
            last_error = error
            _log.warning("连接 %s 失败（%s）：%r", request.host, name, error)
    raise NetworkError(str(last_error)) from last_error


def _open(opener: OpenerDirector, request: Request, timeout: float) -> bytes:
    with opener.open(request, timeout=timeout) as response:
        return response.read()
