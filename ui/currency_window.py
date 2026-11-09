"""F3 desktop-tool currency calculator.

Type an amount (sums such as ``120*3`` or ``1.5万`` work too), pick two
currencies and the result updates as you type. The most used currencies are
listed underneath at once. Rates are downloaded on a background thread and kept
on disk, so the calculator still works offline with the last known rates.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from core import currency
from core.currency import AmountError, CurrencyState, RateTable, RatesError
from ui import theme
from ui.translator_window import tool_window_style

_log = logging.getLogger(__name__)

_NAME = "currencyWindow"
_STYLE = tool_window_style(_NAME) + f"""
#{_NAME} QLineEdit {{
    color: {theme.TEXT};
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 10px;
    padding: 6px 12px;
    font-family: {theme.FONT};
    font-size: 22px;
    selection-background-color: #2f5a46;
}}
#{_NAME} QLineEdit:focus {{ border-color: {theme.ACCENT}; }}
#{_NAME} QLabel#result {{ color: {theme.ACCENT}; font-size: 26px; font-weight: 600; }}
#{_NAME} QTableWidget {{
    color: {theme.TEXT};
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 10px;
    font-family: {theme.FONT};
    font-size: 14px;
    outline: none;
}}
#{_NAME} QTableWidget::item {{ padding: 0 10px; border: none; }}
#{_NAME} QTableWidget::item:hover {{ background: {theme.HOVER}; }}
#{_NAME} QTableWidget::item:selected {{ background: {theme.HOVER}; color: {theme.TEXT}; }}
"""


class _Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, fetcher: Callable[[], RateTable]) -> None:
        super().__init__()
        self._fetcher = fetcher

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._fetcher())
        except RatesError as error:
            self.failed.emit(str(error))
        except Exception:
            _log.exception("更新汇率出现意外错误")
            self.failed.emit("更新汇率失败，详细原因已写入日志。")
        finally:
            self.finished.emit()


class CurrencyWindow(QWidget):
    """A small dark window that converts an amount between currencies."""

    def __init__(
        self,
        parent=None,
        fetcher: Callable[[], RateTable] = currency.fetch_rates,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName(_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 汇率")
        self.resize(480, 680)
        self.setStyleSheet(_STYLE)
        self._fetcher = fetcher
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        state = currency.load_state()
        self._table: RateTable | None = state.table
        self._last_error = ""
        self._result_text = ""

        title = QLabel("汇率")
        title.setObjectName("title")
        hint = QLabel("输入金额实时换算，可写 120*3、1.5万")
        hint.setObjectName("muted")

        self.amount_edit = QLineEdit("100")
        self.amount_edit.setPlaceholderText("金额")
        self.amount_edit.textChanged.connect(self._recalculate)

        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for item in currency.CURRENCIES:
            self.source_combo.addItem(item.label, item.code)
            self.target_combo.addItem(item.label, item.code)
        self.source_combo.setMaxVisibleItems(16)
        self.target_combo.setMaxVisibleItems(16)
        self.source_combo.setCurrentIndex(self.source_combo.findData(state.source_code))
        self.target_combo.setCurrentIndex(self.target_combo.findData(state.target_code))
        self.source_combo.currentIndexChanged.connect(self._selection_changed)
        self.target_combo.currentIndexChanged.connect(self._selection_changed)
        self.swap_button = QPushButton("⇄")
        self.swap_button.setToolTip("交换两种货币")
        self.swap_button.setFixedWidth(44)
        self.swap_button.setStyleSheet("font-size: 17px;")
        self.swap_button.clicked.connect(self.swap_currencies)

        self.result_label = QLabel()
        self.result_label.setObjectName("result")
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setWordWrap(True)
        self.copy_button = QPushButton("复制结果")
        self.copy_button.clicked.connect(self._copy)
        self.rate_label = QLabel()
        self.rate_label.setObjectName("muted")
        self.rate_label.setWordWrap(True)

        overview_title = QLabel("常用币种（单击设为目标货币）")
        overview_title.setObjectName("muted")
        self.overview = QTableWidget(0, 2)
        self.overview.horizontalHeader().hide()
        self.overview.verticalHeader().hide()
        self.overview.setShowGrid(False)
        self.overview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.overview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.overview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.overview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.overview.verticalHeader().setDefaultSectionSize(30)
        self.overview.cellClicked.connect(self._choose_overview_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setToolTip("立即从网上获取最新汇率")
        self.refresh_button.clicked.connect(self.refresh)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addWidget(hint, 0, Qt.AlignmentFlag.AlignBottom)
        heading.addStretch()
        currency_row = QHBoxLayout()
        currency_row.setSpacing(8)
        currency_row.addWidget(self.source_combo, 1)
        currency_row.addWidget(self.swap_button)
        currency_row.addWidget(self.target_combo, 1)
        result_row = QHBoxLayout()
        result_row.addWidget(self.result_label, 1)
        result_row.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addLayout(heading)
        layout.addWidget(self.amount_edit)
        layout.addLayout(currency_row)
        layout.addLayout(result_row)
        layout.addWidget(self.rate_label)
        layout.addSpacing(4)
        layout.addWidget(overview_title)
        layout.addWidget(self.overview, 1)
        layout.addLayout(status_row)

        self._recalculate()
        self._show_status()

    # ------------------------------------------------------------ public

    def open(self) -> None:
        """Show the window in front; fetch new rates when the saved ones are old."""
        self.show()
        self.raise_()
        self.activateWindow()
        self.amount_edit.setFocus()
        self.amount_edit.selectAll()
        if self._table is None or self._table.is_stale():
            self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        theme.dark_title_bar(self)

    @property
    def source_code(self) -> str:
        return self.source_combo.currentData()

    @property
    def target_code(self) -> str:
        return self.target_combo.currentData()

    def swap_currencies(self) -> None:
        source, target = self.source_code, self.target_code
        self.source_combo.blockSignals(True)
        self.source_combo.setCurrentIndex(self.source_combo.findData(target))
        self.source_combo.blockSignals(False)
        self.target_combo.setCurrentIndex(self.target_combo.findData(source))
        self._selection_changed()

    def refresh(self) -> None:
        if self._thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("更新中…")
        self.status_label.setText("正在获取最新汇率……")
        thread = QThread(self)
        worker = _Worker(self._fetcher)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._rates_arrived)
        worker.failed.connect(self._rates_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finish)
        self._thread = thread
        self._worker = worker
        thread.start()

    # ----------------------------------------------------------- private

    def _rates_arrived(self, table: RateTable) -> None:
        self._table = table
        self._last_error = ""
        self._save()
        self._recalculate()
        self._show_status()

    def _rates_failed(self, message: str) -> None:
        self._last_error = message
        self._show_status()

    def _finish(self) -> None:
        self.refresh_button.setText("刷新")
        self.refresh_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _save(self) -> None:
        currency.save_state(
            CurrencyState(table=self._table, source_code=self.source_code, target_code=self.target_code)
        )

    def _selection_changed(self, *_args) -> None:
        self._save()
        self._recalculate()

    def _show_status(self) -> None:
        table = self._table
        if table is None:
            text = self._last_error or "还没有汇率数据，正在联网获取……"
            self.status_label.setText(f"<span style='color:{theme.DANGER}'>{text}</span>"
                                      if self._last_error else text)
            return
        fetched = table.fetched_time()
        when = table.published or (fetched.strftime("%Y-%m-%d %H:%M") if fetched else "未知时间")
        text = f"汇率日期 {when} · 来源 {table.source}"
        if self._last_error:
            text = f"<span style='color:{theme.DANGER}'>无法联网更新，正在使用上次保存的汇率。</span><br>{text}"
        self.status_label.setText(text)

    def _recalculate(self, *_args) -> None:
        table = self._table
        source, target = self.source_code, self.target_code
        try:
            amount = currency.evaluate_amount(self.amount_edit.text())
        except AmountError as error:
            self.result_label.setText(f"<span style='color:{theme.MUTED}; font-size:15px'>{error}</span>")
            self.rate_label.clear()
            self.copy_button.setEnabled(False)
            self._fill_overview(None)
            return
        if table is None or not (table.has(source) and table.has(target)):
            self.result_label.setText(f"<span style='color:{theme.MUTED}; font-size:15px'>暂无汇率</span>")
            self.rate_label.clear()
            self.copy_button.setEnabled(False)
            self._fill_overview(None)
            return
        value = table.convert(amount, source, target)
        self._result_text = currency.format_amount(value)
        self.result_label.setText(
            f"{self._result_text} <span style='font-size:15px; font-weight:400'>"
            f"{currency.currency_name(target)} {target}</span>"
        )
        self.copy_button.setEnabled(True)
        rates = (
            f"1 {source} = {currency.format_rate(table.convert(1, source, target))} {target}"
            f"　·　1 {target} = {currency.format_rate(table.convert(1, target, source))} {source}"
        )
        if currency.is_expression(self.amount_edit.text()):
            rates = f"算式结果 {currency.format_amount(amount)} {source}<br>{rates}"
        self.rate_label.setText(rates)
        self._fill_overview(amount)

    def _fill_overview(self, amount: float | None) -> None:
        table = self._table
        source = self.source_code
        codes = [code for code in currency.OVERVIEW_CODES if code != source]
        self.overview.setRowCount(len(codes))
        for row, code in enumerate(codes):
            name = QTableWidgetItem(f"{currency.currency_name(code)} {code}")
            name.setData(Qt.ItemDataRole.UserRole, code)
            if amount is not None and table is not None and table.has(code) and table.has(source):
                text = currency.format_amount(table.convert(amount, source, code))
            else:
                text = "—"
            value = QTableWidgetItem(text)
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if code == self.target_code:
                for item in (name, value):
                    item.setForeground(QBrush(QColor(theme.ACCENT)))
            self.overview.setItem(row, 0, name)
            self.overview.setItem(row, 1, value)

    def _choose_overview_row(self, row: int, _column: int) -> None:
        item = self.overview.item(row, 0)
        if item is None:
            return
        self.target_combo.setCurrentIndex(self.target_combo.findData(item.data(Qt.ItemDataRole.UserRole)))

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._result_text.replace(",", ""))
        self.status_label.setText(f"已复制 {self._result_text.replace(',', '')}")
