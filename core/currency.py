"""Exchange rates for the F3 desktop-tool currency calculator.

Rates come from free services that need no key, tried in order until one
answers. The last good table is kept in ``%APPDATA%\\AIShot\\exchange_rates.json``
so the calculator still works offline; that one small file (a few KB) is
overwritten on every update, together with the last chosen currencies, so it
never grows. A half-written ``.tmp`` left by a crash is removed on the next load.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request

from core.translate import http

_log = logging.getLogger(__name__)

_USER_AGENT = "MengRenDesktop-Currency"
# Rates change once a day at the services; refreshing more often only costs time.
REFRESH_AFTER = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.code}"


# Offered in the drop-downs, most used first. Every service below covers them.
CURRENCIES: tuple[Currency, ...] = (
    Currency("CNY", "人民币"),
    Currency("USD", "美元"),
    Currency("EUR", "欧元"),
    Currency("JPY", "日元"),
    Currency("HKD", "港币"),
    Currency("GBP", "英镑"),
    Currency("KRW", "韩元"),
    Currency("TWD", "新台币"),
    Currency("MOP", "澳门元"),
    Currency("AUD", "澳元"),
    Currency("CAD", "加元"),
    Currency("SGD", "新加坡元"),
    Currency("CHF", "瑞士法郎"),
    Currency("NZD", "新西兰元"),
    Currency("THB", "泰铢"),
    Currency("MYR", "马来西亚林吉特"),
    Currency("VND", "越南盾"),
    Currency("PHP", "菲律宾比索"),
    Currency("IDR", "印尼盾"),
    Currency("INR", "印度卢比"),
    Currency("RUB", "俄罗斯卢布"),
    Currency("AED", "阿联酋迪拉姆"),
    Currency("SAR", "沙特里亚尔"),
    Currency("TRY", "土耳其里拉"),
    Currency("BRL", "巴西雷亚尔"),
    Currency("MXN", "墨西哥比索"),
    Currency("ZAR", "南非兰特"),
    Currency("SEK", "瑞典克朗"),
    Currency("NOK", "挪威克朗"),
    Currency("DKK", "丹麦克朗"),
    Currency("PLN", "波兰兹罗提"),
    Currency("KZT", "哈萨克斯坦坚戈"),
    Currency("MNT", "蒙古图格里克"),
    Currency("KHR", "柬埔寨瑞尔"),
    Currency("LAK", "老挝基普"),
    Currency("PKR", "巴基斯坦卢比"),
)
CODES = frozenset(item.code for item in CURRENCIES)
# Shown together under the main result, so one amount is seen in all of them.
OVERVIEW_CODES: tuple[str, ...] = (
    "CNY", "USD", "EUR", "JPY", "HKD", "GBP", "KRW", "TWD", "AUD", "CAD", "SGD", "THB",
)


def currency_name(code: str) -> str:
    return next((item.name for item in CURRENCIES if item.code == code), code)


class RatesError(Exception):
    """No service could provide exchange rates."""


@dataclass(frozen=True, slots=True)
class RateTable:
    """How many units of each currency one US dollar buys."""

    rates: dict[str, float] = field(default_factory=dict)
    # When the service last published the rates, as it reported (date or time).
    published: str = ""
    # When this computer fetched them, ISO local time.
    fetched_at: str = ""
    source: str = ""

    def has(self, code: str) -> bool:
        return self.rates.get(code, 0) > 0

    def convert(self, amount: float, source: str, target: str) -> float:
        if not (self.has(source) and self.has(target)):
            raise KeyError(f"{source}->{target}")
        return amount / self.rates[source] * self.rates[target]

    def fetched_time(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.fetched_at)
        except (TypeError, ValueError):
            return None

    def is_stale(self, now: datetime | None = None) -> bool:
        fetched = self.fetched_time()
        if fetched is None:
            return True
        now = now or datetime.now()
        return fetched > now or now - fetched >= REFRESH_AFTER


def _clean_rates(raw: dict, lower_case: bool = False) -> dict[str, float]:
    rates: dict[str, float] = {}
    for code in CODES:
        value = raw.get(code.lower() if lower_case else code)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if math.isfinite(value) and value > 0:
                rates[code] = float(value)
    rates["USD"] = 1.0
    return rates


def _parse_er_api(body: dict) -> tuple[dict[str, float], str]:
    if body.get("result") != "success" or body.get("base_code") != "USD":
        raise ValueError("unexpected open.er-api.com reply")
    published = ""
    seconds = body.get("time_last_update_unix")
    if isinstance(seconds, (int, float)):
        published = datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    return _clean_rates(body.get("rates") or {}), published


def _parse_currency_api(body: dict) -> tuple[dict[str, float], str]:
    rates = body.get("usd")
    if not isinstance(rates, dict):
        raise ValueError("unexpected currency-api reply")
    return _clean_rates(rates, lower_case=True), str(body.get("date", ""))


_CURRENCY_API = "/v1/currencies/usd.min.json"
# Name shown to the user, address, reader. Checked in November 2026 from China:
# open.er-api.com answers directly and through a proxy; the pages.dev mirror
# answers directly; jsdelivr answers through a proxy.
SOURCES: tuple[tuple[str, str, object], ...] = (
    ("open.er-api.com", "https://open.er-api.com/v6/latest/USD", _parse_er_api),
    ("currency-api", "https://latest.currency-api.pages.dev" + _CURRENCY_API, _parse_currency_api),
    (
        "currency-api (jsDelivr)",
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest" + _CURRENCY_API,
        _parse_currency_api,
    ),
)
# Too few currencies means the reply is broken; better to try the next service.
_MINIMUM_RATES = len(CODES) // 2


def fetch_rates(timeout: float = 6, now: datetime | None = None) -> RateTable:
    """Download fresh rates from the first service that answers sensibly."""
    failures: list[str] = []
    for name, url, parse in SOURCES:
        request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        try:
            body = json.loads(http.read_response(request, timeout, prefer_direct=True).decode("utf-8"))
            rates, published = parse(body)
            if len(rates) < _MINIMUM_RATES or not rates.get("CNY"):
                raise ValueError(f"only {len(rates)} currencies")
        except (HTTPError, OSError, ValueError, AttributeError) as error:
            _log.warning("汇率来源 %s 不可用：%r", name, error)
            failures.append(name)
            continue
        return RateTable(
            rates=rates,
            published=published,
            fetched_at=(now or datetime.now()).isoformat(timespec="seconds"),
            source=name,
        )
    raise RatesError("暂时无法获取汇率，请检查网络后点“刷新”。")


# ---------------------------------------------------------------- local file


def cache_file() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "AIShot" / "exchange_rates.json"


@dataclass(frozen=True, slots=True)
class CurrencyState:
    table: RateTable | None = None
    source_code: str = "USD"
    target_code: str = "CNY"


def load_state() -> CurrencyState:
    path = cache_file()
    leftover = path.with_name(path.name + ".tmp")
    try:
        leftover.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CurrencyState()
    if not isinstance(body, dict):
        return CurrencyState()
    table = None
    raw = body.get("table")
    if isinstance(raw, dict) and isinstance(raw.get("rates"), dict):
        rates = _clean_rates(raw["rates"])
        if len(rates) >= _MINIMUM_RATES:
            table = RateTable(
                rates=rates,
                published=str(raw.get("published", "")),
                fetched_at=str(raw.get("fetched_at", "")),
                source=str(raw.get("source", "")),
            )
    source_code = body.get("source_code")
    target_code = body.get("target_code")
    return CurrencyState(
        table=table,
        source_code=source_code if source_code in CODES else "USD",
        target_code=target_code if target_code in CODES else "CNY",
    )


def save_state(state: CurrencyState) -> None:
    """Replace the single cache file; never leaves a half-written file behind."""
    path = cache_file()
    body: dict = {"source_code": state.source_code, "target_code": state.target_code}
    if state.table is not None:
        body["table"] = {
            "rates": state.table.rates,
            "published": state.table.published,
            "fetched_at": state.table.fetched_at,
            "source": state.table.source,
        }
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        _log.warning("无法保存汇率缓存", exc_info=True)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------ amount and text


class AmountError(ValueError):
    pass


_MAX_EXPRESSION = 120
_TRANSLATE = str.maketrans({
    "×": "*", "x": "*", "X": "*", "÷": "/", "（": "(", "）": ")",
    "＋": "+", "－": "-", "＊": "*", "／": "/", "。": ".", "．": ".",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
})
_UNITS = re.compile(r"(\d+(?:\.\d*)?|\.\d+)\s*([万亿kKwW])")
_UNIT_FACTORS = {"万": "10000", "w": "10000", "W": "10000", "亿": "100000000", "k": "1000", "K": "1000"}


def evaluate_amount(text: str) -> float:
    """Read an amount such as ``1,280``, ``1.5万`` or ``(120+80)*3``.

    Only numbers, + - * / and brackets are accepted, so nothing else can run.
    """
    expression = _plain(text)
    if not expression:
        raise AmountError("请输入金额")
    if len(expression) > _MAX_EXPRESSION:
        raise AmountError("算式太长")
    expression = _UNITS.sub(lambda m: f"({m.group(1)}*{_UNIT_FACTORS[m.group(2)]})", expression)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise AmountError("金额或算式有误") from error
    value = _evaluate(tree.body)
    if not math.isfinite(value):
        raise AmountError("数字太大")
    return value


def _plain(text: str) -> str:
    return text.strip().translate(_TRANSLATE).replace(",", "").replace("，", "").replace(" ", "")


def is_expression(text: str) -> bool:
    """Whether the amount is a sum or uses 万/亿/k rather than a plain number."""
    plain = _plain(text)
    return bool(plain) and re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", plain) is None


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise AmountError("不能除以 0")
        return left / right
    raise AmountError("金额或算式有误")


def format_amount(value: float) -> str:
    """Thousands separators; two decimals, more for tiny amounts."""
    if value == 0:
        return "0"
    size = abs(value)
    if size >= 1:
        text = f"{value:,.2f}"
    else:
        # Keep four significant digits, e.g. 0.001497.
        decimals = min(10, 3 - math.floor(math.log10(size)))
        text = f"{value:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_rate(value: float) -> str:
    """A unit rate with enough digits to be useful, e.g. 6.6798 or 0.1497."""
    if value <= 0:
        return "0"
    decimals = max(4, min(10, 3 - math.floor(math.log10(value))))
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")
