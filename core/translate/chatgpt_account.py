"""Sign in with a ChatGPT account and translate on its plan quota.

This works like 猛人学习 and the official Codex command-line tool: the user signs
in through the browser (PKCE), the browser returns to
``http://localhost:1455/auth/callback`` and the tokens are stored encrypted
for the current Windows user, then refreshed shortly before they expire. If
the local callback cannot be reached, the user pastes the address from the
browser instead.

It is not an API OpenAI documents for other applications, so it may stop
working at any time; translation then falls back to the configured API service.
Each app needs its own sign-in: refreshing a token invalidates the old one, so
sharing tokens with 猛人学习 would sign the other app out.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request

from app.branding import PRODUCT_NAME
from app.translation_preferences import protect_for_user, unprotect_for_user
from core.translate.base import BatchTranslator, TranslationError
from core.translate.http import NetworkError, read_response
from core.translate.providers import parse_translations, translation_instructions, translation_prompt

_log = logging.getLogger(__name__)

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
CALLBACK_PORT = 1455
SCOPES = "openid profile email offline_access"
BACKEND_URL = "https://chatgpt.com/backend-api/codex"
CLIENT_VERSION = "0.159.0"
REFRESH_MARGIN_SECONDS = 180
LOGIN_TIMEOUT_SECONDS = 600
_QUOTA = re.compile(r"quota|usage[ _]limit|insufficient|limit reached|额度", re.IGNORECASE)

_refresh_lock = threading.Lock()


class AccountError(TranslationError):
    """Signing in or using the ChatGPT account failed."""


class AccountQuotaExhausted(AccountError):
    """The plan quota is used up for now."""


class AccountSignedOut(AccountError):
    """There is no valid sign-in, or it has expired."""


@dataclass(frozen=True, slots=True)
class AccountTokens:
    """Encrypted sign-in of one ChatGPT account."""

    access: str
    refresh: str
    expires: float
    account_id: str = ""
    email: str = ""
    plan: str = ""


def _token_file() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "AIShot" / "chatgpt-login.bin"


def load_tokens() -> AccountTokens | None:
    """Return the saved sign-in, or ``None`` when signed out."""
    try:
        values = json.loads(unprotect_for_user(_token_file().read_bytes()).decode("utf-8"))
        tokens = AccountTokens(**{key: values[key] for key in AccountTokens.__dataclass_fields__ if key in values})
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return None
    return tokens if tokens.refresh else None


def save_tokens(tokens: AccountTokens) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protect_for_user(json.dumps(asdict(tokens)).encode("utf-8")))


def sign_out() -> None:
    """Forget the sign-in on this computer."""
    try:
        _token_file().unlink()
    except FileNotFoundError:
        pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _claims(jwt: str) -> dict:
    try:
        part = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError, AttributeError):
        return {}


def _tokens_from(response: dict, previous: AccountTokens | None) -> AccountTokens:
    identity = _claims(response.get("id_token", ""))
    access = _claims(response.get("access_token", ""))
    auth = identity.get("https://api.openai.com/auth") or access.get("https://api.openai.com/auth") or {}
    lifetime = float(response.get("expires_in") or (access.get("exp", time.time() + 3600) - time.time()))
    return AccountTokens(
        access=response["access_token"],
        refresh=response.get("refresh_token") or (previous.refresh if previous else ""),
        expires=time.time() + lifetime,
        account_id=auth.get("chatgpt_account_id") or (previous.account_id if previous else ""),
        email=identity.get("email") or (previous.email if previous else ""),
        plan=auth.get("chatgpt_plan_type") or (previous.plan if previous else ""),
    )


def _post_token(fields: dict[str, str]) -> dict:
    request = Request(
        TOKEN_URL,
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        body = json.loads(read_response(request, 60).decode("utf-8"))
    except HTTPError as error:
        reason = _error_text(error)
        if error.code in (400, 401):
            raise AccountSignedOut(f"ChatGPT 登录已失效，请在翻译设置中重新登录。{reason}") from error
        raise AccountError(f"连接 ChatGPT 登录服务失败（HTTP {error.code}）。{reason}") from error
    except NetworkError as error:
        raise AccountError("连接 ChatGPT 登录服务时网络中断，请检查网络或代理后再试。") from error
    except (UnicodeError, ValueError) as error:
        raise AccountError("ChatGPT 登录服务返回了无法识别的数据。") from error
    if not body.get("access_token"):
        raise AccountError("ChatGPT 登录服务没有返回登录凭证。")
    return body


def _error_text(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8", "replace")
    except OSError:
        return ""
    try:
        body = json.loads(raw)
    except ValueError:
        return raw[:160]
    detail = body.get("error_description") or body.get("detail") or body.get("error") or ""
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code") or ""
    return str(detail)[:200]


def fresh_tokens() -> AccountTokens:
    """Return a valid sign-in, refreshing it shortly before it expires."""
    with _refresh_lock:
        tokens = load_tokens()
        if tokens is None:
            raise AccountSignedOut("还没有登录 ChatGPT 账号，请在翻译设置中登录。")
        if tokens.access and tokens.expires - REFRESH_MARGIN_SECONDS > time.time():
            return tokens
        response = _post_token(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": tokens.refresh,
                "scope": "openid profile email",
            }
        )
        tokens = _tokens_from(response, tokens)
        save_tokens(tokens)
        return tokens


class LoginSession:
    """One browser sign-in, waiting for the callback or a pasted address."""

    def __init__(self) -> None:
        self._verifier = _b64url(secrets.token_bytes(48))
        self._state = _b64url(secrets.token_bytes(24))
        challenge = _b64url(hashlib.sha256(self._verifier.encode()).digest())
        self.url = AUTHORIZE_URL + "?" + urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "state": self._state,
                "originator": "codex_cli_rs",
            }
        )
        self.status = "waiting"
        self.error = ""
        self.tokens: AccountTokens | None = None
        self.callback_available = False
        self._server: HTTPServer | None = None
        self._lock = threading.Lock()
        self._started = time.time()

    def start(self, open_browser: bool = True) -> None:
        """Listen for the browser callback and open the sign-in page."""
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:
                accepted = session.accept(self.path)
                message = (
                    f"登录完成，可以关掉这个页面，回到「{PRODUCT_NAME}」。"
                    if accepted
                    else "没有拿到登录结果，请回到软件重试。"
                )
                body = (
                    '<meta charset="utf-8"><body style="font:16px sans-serif;padding:40px">'
                    f"{message}</body>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            self._server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
            self._server.timeout = 1
            self.callback_available = True
            threading.Thread(target=self._serve, daemon=True).start()
        except OSError:
            # The port is busy (for example Codex is signing in): paste instead.
            self._server = None
        if open_browser:
            webbrowser.open(self.url)

    def _serve(self) -> None:
        server = self._server
        while server is not None and self.status == "waiting":
            if time.time() - self._started > LOGIN_TIMEOUT_SECONDS:
                self._fail("登录等待超时，请重新点击“登录”。")
                break
            server.handle_request()
        self._close_server()

    def accept(self, address: str) -> bool:
        """Take the callback address; exchange its code in the background."""
        query = parse_qs(urlparse(address.strip()).query)
        if query.get("error"):
            self._fail((query.get("error_description") or query["error"])[0])
            return False
        code = (query.get("code") or [""])[0]
        if not code:
            return False
        if (query.get("state") or [""])[0] != self._state:
            self._fail("登录结果与本次登录不符，请重新登录。")
            return False
        with self._lock:
            if self.status != "waiting":
                return self.status != "failed"
            self.status = "exchanging"
        threading.Thread(target=self._exchange, args=(code,), daemon=True).start()
        return True

    def _exchange(self, code: str) -> None:
        try:
            response = _post_token(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,
                    "code_verifier": self._verifier,
                }
            )
            tokens = _tokens_from(response, None)
            if not tokens.refresh:
                raise AccountError("ChatGPT 没有返回长期登录凭证，请重新登录。")
            save_tokens(tokens)
            self.tokens = tokens
            self.status = "done"
        except TranslationError as error:
            _log.warning("ChatGPT 登录失败：%s", error)
            self._fail(str(error))

    def _fail(self, message: str) -> None:
        self.error = message
        self.status = "failed"

    def cancel(self) -> None:
        if self.status in ("waiting", "exchanging"):
            self._fail("已取消登录。")
        self._close_server()

    def _close_server(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.server_close()
            except OSError:
                pass


class ChatGPTAccountTranslator(BatchTranslator):
    """Translate through the signed-in ChatGPT plan, like Codex does."""

    service_name = "ChatGPT 账号"

    def __init__(self, model: str) -> None:
        self._model = model.strip() or "gpt-6.1-sol"

    def translate_many(
        self,
        texts: tuple[str, ...],
        target: str = "zh",
        source_language: str = "auto",
    ) -> tuple[str, ...]:
        source = tuple(text.strip() for text in texts if text.strip())
        if not source:
            raise TranslationError("没有可翻译的文字。")
        tokens = fresh_tokens()
        body = {
            "model": self._model,
            "instructions": translation_instructions(target, source_language),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": translation_prompt(source)}],
                }
            ],
            "store": False,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {tokens.access}",
            "originator": "codex_cli_rs",
            "version": CLIENT_VERSION,
            "OpenAI-Beta": "responses=experimental",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if tokens.account_id:
            headers["chatgpt-account-id"] = tokens.account_id
        request = Request(
            f"{BACKEND_URL}/responses",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            raw = read_response(request, 120).decode("utf-8", "replace")
        except HTTPError as error:
            reason = _error_text(error)
            if error.code == 401:
                raise AccountSignedOut("ChatGPT 登录已失效，请在翻译设置中重新登录。") from error
            if error.code == 429 or _QUOTA.search(reason):
                raise AccountQuotaExhausted(f"ChatGPT 套餐额度暂时用完了。{reason}") from error
            raise AccountError(f"ChatGPT 翻译失败（HTTP {error.code}）。{reason}") from error
        except NetworkError as error:
            raise AccountError("连接 ChatGPT 时网络中断或超时，请检查网络或代理后再试。") from error
        return parse_translations(_stream_text(raw), source, "ChatGPT")


def _stream_text(raw: str) -> str:
    """Join the text pieces of a server-sent event stream; raise its errors."""
    pieces: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
            pieces.append(event["delta"])
        elif kind in ("response.failed", "error"):
            error = (event.get("response") or {}).get("error") or event.get("error") or event
            message = str(error.get("message") or error.get("code") or "") if isinstance(error, dict) else str(error)
            if _QUOTA.search(json.dumps(error, ensure_ascii=False)):
                raise AccountQuotaExhausted(f"ChatGPT 套餐额度暂时用完了。{message[:200]}")
            raise AccountError(f"ChatGPT 翻译出错：{message[:200]}")
    return "".join(pieces)
