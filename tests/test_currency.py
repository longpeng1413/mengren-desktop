"""Tests for the F3 currency calculator: amounts, rates, cache and window."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest
from PySide6.QtWidgets import QApplication

from core import currency
from core.currency import AmountError, CurrencyState, RateTable, RatesError
from ui import reminder_widget
from ui.currency_window import CurrencyWindow
from ui.reminder_widget import DesktopReminderManager

_RATES = {code: 1.0 for code in currency.CODES} | {
    "USD": 1.0, "CNY": 7.0, "EUR": 0.5, "JPY": 150.0, "HKD": 7.8,
}


def _table(**changes) -> RateTable:
    values = {
        "rates": dict(_RATES),
        "published": "2026-11-09 08:00",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "source": "测试",
    }
    values.update(changes)
    return RateTable(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("100", 100),
        (" 1,280.5 ", 1280.5),
        ("(120+80)*3", 600),
        ("120×3÷4", 90),
        ("１２０＋３", 123),
        ("1.5万", 15000),
        ("2亿", 200_000_000),
        ("3k", 3000),
        ("-5", -5),
        (".5", 0.5),
    ],
)
def test_amount_accepts_numbers_and_simple_sums(text, expected) -> None:
    assert currency.evaluate_amount(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "1/0", "__import__('os')", "2**10", "1+", "9" * 200])
def test_amount_rejects_anything_but_arithmetic(text) -> None:
    with pytest.raises(AmountError):
        currency.evaluate_amount(text)


def test_is_expression_tells_sums_from_plain_numbers() -> None:
    assert not currency.is_expression("1,280.50")
    assert currency.is_expression("120*3")
    assert currency.is_expression("1.5万")


def test_conversion_goes_through_the_dollar() -> None:
    table = _table()
    assert table.convert(100, "USD", "CNY") == pytest.approx(700)
    assert table.convert(700, "CNY", "EUR") == pytest.approx(50)
    assert table.convert(1, "JPY", "JPY") == pytest.approx(1)


def test_amounts_are_formatted_with_separators_and_useful_decimals() -> None:
    assert currency.format_amount(1234567.891) == "1,234,567.89"
    assert currency.format_amount(100) == "100"
    assert currency.format_amount(0.0014968) == "0.001497"
    assert currency.format_rate(6.679814) == "6.6798"
    assert currency.format_rate(0.149705) == "0.1497"


def test_rates_are_stale_after_six_hours() -> None:
    now = datetime(2026, 11, 9, 12, 0)
    assert not _table(fetched_at="2026-11-09T07:00:00").is_stale(now)
    assert _table(fetched_at="2026-11-09T05:59:00").is_stale(now)
    assert _table(fetched_at="").is_stale(now)
    # A clock moved backwards must not keep old rates forever.
    assert _table(fetched_at="2026-11-10T00:00:00").is_stale(now)


def _er_api_body() -> dict:
    return {
        "result": "success",
        "base_code": "USD",
        "time_last_update_unix": 1_762_646_400,
        "rates": {code: value for code, value in _RATES.items()},
    }


def _currency_api_body() -> dict:
    return {"date": "2026-11-09", "usd": {code.lower(): value for code, value in _RATES.items()}}


def test_fetch_uses_the_first_service_that_answers(monkeypatch) -> None:
    hosts: list[str] = []

    def reply(request, timeout, prefer_direct=False):
        hosts.append(request.host)
        if request.host == "open.er-api.com":
            raise OSError("connection reset")
        return json.dumps(_currency_api_body()).encode()

    monkeypatch.setattr(currency.http, "read_response", reply)
    table = currency.fetch_rates(now=datetime(2026, 11, 9, 9, 30))

    assert hosts == ["open.er-api.com", "latest.currency-api.pages.dev"]
    assert table.source == "currency-api"
    assert table.published == "2026-11-09"
    assert table.fetched_at == "2026-11-09T09:30:00"
    assert table.convert(1, "USD", "CNY") == pytest.approx(7)


def test_fetch_reads_open_er_api(monkeypatch) -> None:
    monkeypatch.setattr(
        currency.http, "read_response", lambda *args, **kwargs: json.dumps(_er_api_body()).encode()
    )
    table = currency.fetch_rates()
    assert table.source == "open.er-api.com"
    assert table.rates["JPY"] == 150.0
    assert table.published


def test_fetch_skips_broken_replies_and_reports_when_all_fail(monkeypatch) -> None:
    replies = iter([b"not json", json.dumps({"result": "error"}).encode(), json.dumps({"usd": {"cny": 7}}).encode()])
    monkeypatch.setattr(currency.http, "read_response", lambda *args, **kwargs: next(replies))
    with pytest.raises(RatesError):
        currency.fetch_rates()


def test_state_round_trips_and_clears_a_crashed_temporary_file() -> None:
    path = currency.cache_file()
    currency.save_state(CurrencyState(table=_table(), source_code="EUR", target_code="JPY"))
    leftover = path.with_name(path.name + ".tmp")
    leftover.write_text("half written", encoding="utf-8")

    state = currency.load_state()

    assert not leftover.exists()
    assert state.source_code == "EUR" and state.target_code == "JPY"
    assert state.table is not None and state.table.rates["CNY"] == 7.0
    # One small file, overwritten each time.
    assert path.stat().st_size < 8_000
    assert [item.name for item in path.parent.iterdir()] == [path.name]


def test_broken_cache_file_falls_back_to_defaults() -> None:
    path = currency.cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops", encoding="utf-8")
    state = currency.load_state()
    assert state == CurrencyState()


def _window(table: RateTable | None = None, fetcher=None) -> CurrencyWindow:
    _application = QApplication.instance() or QApplication([])
    if table is not None:
        currency.save_state(CurrencyState(table=table))
    return CurrencyWindow(fetcher=fetcher or (lambda: _table()))


def test_window_converts_as_the_amount_is_typed() -> None:
    window = _window(_table())

    assert window.source_code == "USD" and window.target_code == "CNY"
    assert window.result_label.text().startswith("700 ")
    window.amount_edit.setText("(10+10)*5")
    assert window.result_label.text().startswith("700 ")
    assert "算式结果 100 USD" in window.rate_label.text()
    window.amount_edit.setText("abc")
    assert not window.copy_button.isEnabled()
    window.close()


def test_window_swap_and_overview_click_change_currencies() -> None:
    window = _window(_table())

    window.swap_currencies()
    assert (window.source_code, window.target_code) == ("CNY", "USD")
    assert window.result_label.text().startswith("14.29 ")
    assert currency.load_state().source_code == "CNY"

    codes = [window.overview.item(row, 0).data(0x0100) for row in range(window.overview.rowCount())]
    assert "CNY" not in codes
    window._choose_overview_row(codes.index("JPY"), 0)
    assert window.target_code == "JPY"
    window.close()


def test_window_downloads_rates_when_none_are_saved() -> None:
    calls: list[str] = []
    window = _window(fetcher=lambda: calls.append("fetch") or _table())
    assert "暂无汇率" in window.result_label.text()

    window.open()
    deadline = datetime.now() + timedelta(seconds=5)
    while window._thread is not None and datetime.now() < deadline:
        QApplication.processEvents()

    assert calls == ["fetch"]
    assert window.result_label.text().startswith("700 ")
    assert "来源 测试" in window.status_label.text()
    assert currency.load_state().table is not None
    window.close()


def test_window_keeps_saved_rates_when_offline() -> None:
    old = _table(fetched_at="2026-01-01T00:00:00")

    def offline():
        raise RatesError("暂时无法获取汇率")

    window = _window(old, fetcher=offline)
    window.open()
    deadline = datetime.now() + timedelta(seconds=5)
    while window._thread is not None and datetime.now() < deadline:
        QApplication.processEvents()

    assert window.result_label.text().startswith("700 ")
    assert "上次保存的汇率" in window.status_label.text()
    window.close()


def test_launcher_currency_action_opens_the_calculator(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    opened: list[str] = []

    class _Fake:
        def open(self) -> None:
            opened.append("open")

    monkeypatch.setattr(reminder_widget, "CurrencyWindow", _Fake)
    manager = DesktopReminderManager()

    manager._create_action("currency")
    manager._create_action("currency")

    assert opened == ["open", "open"]
    assert isinstance(manager._currency, _Fake)
    manager.shutdown()
