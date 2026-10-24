"""Translation provider and credential settings dialog."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.translation_preferences import (
    OPENAI_MODEL_CHOICES,
    PROVIDER_LABELS,
    TranslationSettings,
    load_translation_settings,
    save_translation_settings,
)
from core.translate import chatgpt_account

_PLAN_NAMES = {"plus": "Plus", "pro": "Pro", "team": "Team", "business": "Business", "free": "免费"}


class TranslationSettingsDialog(QDialog):
    """Select a translation service and store its credentials locally."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 翻译设置")
        self.setMinimumWidth(560)
        current = load_translation_settings()
        self._login: chatgpt_account.LoginSession | None = None

        self._provider = QComboBox()
        for key, label in PROVIDER_LABELS:
            self._provider.addItem(label, key)

        self._pages = QStackedWidget()
        self._youdao_key = QLineEdit(current.youdao_app_key)
        self._youdao_secret = self._password_edit(current.youdao_app_secret)
        self._pages.addWidget(
            self._form_page(
                ("应用 ID", self._youdao_key),
                ("应用密钥", self._youdao_secret),
            )
        )

        self._deepl_key = self._password_edit(current.deepl_api_key)
        self._deepl_free = QCheckBox("使用 DeepL API Free 接口")
        self._deepl_free.setChecked(current.deepl_use_free_api)
        self._pages.addWidget(
            self._form_page(("API Key", self._deepl_key), ("接口类型", self._deepl_free))
        )

        self._openai_key = self._password_edit(current.openai_api_key)
        self._openai_model, openai_model_note = self._model_choice(current.openai_model)
        self._openai_base_url = QLineEdit(current.openai_base_url)
        openai_page = self._form_page(
            ("API Key", self._openai_key),
            ("模型", self._openai_model),
            ("", openai_model_note),
            ("接口地址", self._openai_base_url),
        )
        openai_note = QLabel(
            "OpenAI API 需要独立的 API 密钥，按用量付费（用 gpt-6.1-sol 翻一张截图通常不到 1 分钱）。"
            "模型可从下拉中选择，也可以直接输入其他模型名称。"
        )
        openai_note.setWordWrap(True)
        openai_page.layout().addWidget(openai_note)
        self._pages.addWidget(openai_page)

        self._google_key = self._password_edit(current.google_api_key)
        self._pages.addWidget(self._form_page(("API Key", self._google_key)))

        self._microsoft_key = self._password_edit(current.microsoft_api_key)
        self._microsoft_region = QLineEdit(current.microsoft_region)
        self._microsoft_region.setPlaceholderText("例如：eastasia；全局资源可留空")
        self._pages.addWidget(
            self._form_page(
                ("订阅密钥", self._microsoft_key),
                ("资源区域", self._microsoft_region),
            )
        )

        index = max(0, self._provider.findData(current.provider))
        self._provider.setCurrentIndex(index)
        self._pages.setCurrentIndex(index)
        self._provider.currentIndexChanged.connect(self._pages.setCurrentIndex)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._account_group(current))
        provider_form = QFormLayout()
        provider_form.addRow("翻译服务", self._provider)
        layout.addLayout(provider_form)
        layout.addWidget(self._pages)
        layout.addWidget(
            QLabel("密钥使用 Windows 当前账户加密，只保存在本机，不会写入项目或 Git。")
        )
        layout.addWidget(buttons)

    def _account_group(self, current: TranslationSettings) -> QGroupBox:
        """Sign in with ChatGPT and translate on the plan quota first."""
        group = QGroupBox("ChatGPT 账号（用会员套餐额度翻译，省 API 费用）")
        self._account_status = QLabel()
        self._account_status.setWordWrap(True)
        self._login_button = QPushButton("登录")
        self._logout_button = QPushButton("退出登录")
        self._login_button.clicked.connect(self._start_login)
        self._logout_button.clicked.connect(self._sign_out)
        self._account_preferred = QCheckBox(
            "优先用 ChatGPT 账号额度翻译；额度用完或出错时，自动改用下面选择的翻译服务"
        )
        self._account_preferred.setChecked(current.chatgpt_preferred)
        self._account_model, account_model_note = self._model_choice(current.chatgpt_model)

        self._paste_edit = QLineEdit()
        self._paste_edit.setPlaceholderText(
            "浏览器登录后没有自动回到软件时，把地址栏的完整网址粘贴到这里"
        )
        paste_button = QPushButton("确定")
        paste_button.clicked.connect(self._accept_pasted_address)
        self._paste_row = QWidget()
        paste_layout = QHBoxLayout(self._paste_row)
        paste_layout.setContentsMargins(0, 0, 0, 0)
        paste_layout.addWidget(self._paste_edit, 1)
        paste_layout.addWidget(paste_button)
        self._paste_row.hide()

        risk = QLabel(
            "说明：这里借用 Codex 的登录方式使用套餐额度，不是 OpenAI 正式开放给其他软件的接口，"
            "可能随时失效；失效时会自动改用下面的翻译服务。登录凭证加密保存在本机。"
        )
        risk.setWordWrap(True)
        risk.setStyleSheet("color: #888;")

        status_row = QHBoxLayout()
        status_row.addWidget(self._account_status, 1)
        status_row.addWidget(self._login_button)
        status_row.addWidget(self._logout_button)
        model_form = QFormLayout()
        model_form.addRow("账号模型", self._account_model)
        model_form.addRow("", account_model_note)
        layout = QVBoxLayout(group)
        layout.addLayout(status_row)
        layout.addWidget(self._paste_row)
        layout.addWidget(self._account_preferred)
        layout.addLayout(model_form)
        layout.addWidget(risk)

        self._login_timer = QTimer(self)
        self._login_timer.setInterval(1000)
        self._login_timer.timeout.connect(self._check_login)
        self._show_account()
        return group

    def _show_account(self) -> None:
        tokens = chatgpt_account.load_tokens()
        if tokens is None:
            self._account_status.setText("未登录")
        else:
            plan = _PLAN_NAMES.get(tokens.plan, tokens.plan)
            self._account_status.setText(
                f"已登录：{tokens.email or 'ChatGPT 账号'}" + (f"（{plan} 套餐）" if plan else "")
            )
        self._login_button.setText("重新登录" if tokens else "登录")
        self._logout_button.setEnabled(tokens is not None)

    def _start_login(self) -> None:
        if self._login is not None:
            self._login.cancel()
        self._login = chatgpt_account.LoginSession()
        self._login.start()
        self._account_status.setText("已在浏览器打开 ChatGPT 登录页，登录完成后会自动回到这里……")
        self._paste_row.show()
        self._login_timer.start()

    def _accept_pasted_address(self) -> None:
        if self._login is None:
            return
        if not self._login.accept(self._paste_edit.text()):
            QMessageBox.warning(
                self,
                APP_DISPLAY_NAME,
                self._login.error
                or "这个网址里没有登录结果。请复制登录完成后浏览器地址栏里"
                "以 http://localhost:1455/auth/callback 开头的完整网址。",
            )

    def _check_login(self) -> None:
        login = self._login
        if login is None:
            self._login_timer.stop()
            return
        if login.status == "done":
            self._finish_login()
            self._account_preferred.setChecked(True)
            self._show_account()
        elif login.status == "failed":
            error = login.error
            self._finish_login()
            self._show_account()
            QMessageBox.warning(self, APP_DISPLAY_NAME, f"ChatGPT 登录没有完成：{error}")

    def _finish_login(self) -> None:
        self._login_timer.stop()
        self._paste_row.hide()
        self._paste_edit.clear()
        if self._login is not None:
            self._login.cancel()
        self._login = None

    def _sign_out(self) -> None:
        chatgpt_account.sign_out()
        self._account_preferred.setChecked(False)
        self._show_account()

    def done(self, result: int) -> None:
        """Stop listening for a sign-in that was never finished."""
        if self._login is not None:
            self._finish_login()
        super().done(result)

    @staticmethod
    def _model_choice(current: str) -> tuple[QComboBox, QLabel]:
        """A dropdown of recommended models that also accepts any other name."""
        combo = QComboBox()
        combo.setEditable(True)
        notes = dict(OPENAI_MODEL_CHOICES)
        for model, _note in OPENAI_MODEL_CHOICES:
            combo.addItem(model)
        combo.setEditText(current or OPENAI_MODEL_CHOICES[0][0])
        note = QLabel()
        note.setStyleSheet("color: #888;")

        def describe(text: str) -> None:
            note.setText(notes.get(text.strip(), "自定义模型：请确认你的账号可以使用这个模型。"))

        combo.currentTextChanged.connect(describe)
        describe(combo.currentText())
        return combo, note

    @staticmethod
    def _password_edit(value: str) -> QLineEdit:
        edit = QLineEdit(value)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    @staticmethod
    def _form_page(*rows: tuple[str, QWidget]) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        for label, widget in rows:
            layout.addRow(label, widget)
        return page

    def _save(self) -> None:
        provider = str(self._provider.currentData())
        settings = TranslationSettings(
            provider=provider,
            youdao_app_key=self._youdao_key.text().strip(),
            youdao_app_secret=self._youdao_secret.text().strip(),
            deepl_api_key=self._deepl_key.text().strip(),
            deepl_use_free_api=self._deepl_free.isChecked(),
            openai_api_key=self._openai_key.text().strip(),
            openai_model=self._openai_model.currentText().strip(),
            openai_base_url=self._openai_base_url.text().strip(),
            google_api_key=self._google_key.text().strip(),
            microsoft_api_key=self._microsoft_key.text().strip(),
            microsoft_region=self._microsoft_region.text().strip(),
            chatgpt_preferred=self._account_preferred.isChecked(),
            chatgpt_model=self._account_model.currentText().strip(),
        )
        error = self._validation_error(settings)
        if error:
            QMessageBox.warning(self, APP_DISPLAY_NAME, error)
            return
        try:
            save_translation_settings(settings)
        except OSError as error:
            QMessageBox.warning(self, APP_DISPLAY_NAME, str(error))
            return
        self.accept()

    @staticmethod
    def _validation_error(settings: TranslationSettings) -> str:
        if settings.chatgpt_preferred and chatgpt_account.load_tokens() is None:
            return "要优先用 ChatGPT 账号额度翻译，请先点“登录”登录 ChatGPT 账号。"
        if settings.provider == "youdao" and not (
            settings.youdao_app_key and settings.youdao_app_secret
        ):
            return "请填写有道应用 ID 和应用密钥。"
        if settings.provider == "deepl" and not settings.deepl_api_key:
            return "请填写 DeepL API Key。"
        if settings.provider == "openai" and not (
            settings.openai_api_key and settings.openai_model and settings.openai_base_url
        ):
            return "请填写 OpenAI API Key、模型和接口地址。"
        if settings.provider == "google" and not settings.google_api_key:
            return "请填写 Google Cloud API Key。"
        if settings.provider == "microsoft" and not settings.microsoft_api_key:
            return "请填写 Microsoft Translator 订阅密钥。"
        return ""
