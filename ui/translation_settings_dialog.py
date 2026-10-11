"""Translation provider and credential settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.translation_preferences import (
    PROVIDER_LABELS,
    TranslationSettings,
    load_translation_settings,
    save_translation_settings,
)


class TranslationSettingsDialog(QDialog):
    """Select a translation service and store its credentials locally."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 翻译设置")
        self.setMinimumWidth(560)
        current = load_translation_settings()

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
        self._openai_model = QLineEdit(current.openai_model)
        self._openai_base_url = QLineEdit(current.openai_base_url)
        openai_page = self._form_page(
            ("API Key", self._openai_key),
            ("模型", self._openai_model),
            ("接口地址", self._openai_base_url),
        )
        openai_note = QLabel("OpenAI API 需要独立的 API 密钥；模型和接口地址可以自行修改。")
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
        provider_form = QFormLayout()
        provider_form.addRow("翻译服务", self._provider)
        layout.addLayout(provider_form)
        layout.addWidget(self._pages)
        layout.addWidget(
            QLabel("密钥使用 Windows 当前账户加密，只保存在本机，不会写入项目或 Git。")
        )
        layout.addWidget(buttons)

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
            openai_model=self._openai_model.text().strip(),
            openai_base_url=self._openai_base_url.text().strip(),
            google_api_key=self._google_key.text().strip(),
            microsoft_api_key=self._microsoft_key.text().strip(),
            microsoft_region=self._microsoft_region.text().strip(),
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
