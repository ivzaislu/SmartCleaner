#!/usr/bin/env python3
"""
SmartCleaner 2.0 - PySide6 GUI Application (CCleaner Style)
Modern interface: dark vertical sidebar, light/dark themes, bilingual support (RU/EN).
"""

import argparse
from datetime import datetime, timezone
from itertools import islice
import sqlite3
import sys
from pathlib import Path
import os
import platform

PYSIDE6_AVAILABLE = False
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QListWidget, QTreeWidget, QTreeWidgetItem,
        QStackedWidget, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
        QProgressBar, QMessageBox, QFileDialog, QCheckBox, QComboBox,
        QGroupBox, QFormLayout, QLineEdit, QTextEdit, QScrollArea,
        QFrame, QSizePolicy, QSpacerItem, QInputDialog, QListWidgetItem, QSpinBox, QAbstractItemView
    )
    from PySide6.QtCore import Qt, QTimer, QThreadPool, QRunnable, QObject, Signal, QUrl
    from PySide6.QtGui import QIcon, QFont, QColor, QPalette, QPixmap, QDesktopServices
    PYSIDE6_AVAILABLE = True
except ImportError as exc:
    print(repr(exc), file=sys.stderr)

from smartcleaner.file_move import identity
from smartcleaner.protection import checked_path, inspect_path
from smartcleaner.core import ConfigManager, OperationLogger, ProtectionEngine, AppConfig
from smartcleaner.scanner import DiskScanner, QuickScanner, FileScanner, ScanType, ScanStatus
from smartcleaner.browser_cleaner import BrowserCacheCleaner
from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.app_cache import application_caches, leftover_candidates
from smartcleaner.driver_updates import check_driver_updates
from smartcleaner.driver_actions import download_driver, install_driver
from smartcleaner.driver_sources import is_trusted_support_url
from smartcleaner.diagnostics import SmartCleanerDelete, SystemDiagnostics
from smartcleaner.extensions import StartupManager, DriverManager, ApplicationManager, SchedulerService

# --- Localization ---
LANGUAGES = {
    "ru": {
        "app_name": "SmartCleaner 2.0.2",
        "sidebar_home": "Главная",
        "sidebar_quick": "Быстрая очистка",
        "sidebar_deep": "Глубокая очистка",
        "sidebar_browsers": "Браузеры",
        "sidebar_apps": "Программы и игры",
        "sidebar_disk": "Анализ дисков",
        "sidebar_duplicates": "Дубликаты",
        "sidebar_large": "Большие файлы",
        "sidebar_leftovers": "Остатки программ",
        "sidebar_drivers": "Драйверы",
        "sidebar_ssd": "SSD/HDD",
        "sidebar_startup": "Автозагрузка",
        "sidebar_installed": "Установленные программы",
        "sidebar_integrity": "Целостность системы",
        "sidebar_filesystem": "Диагностика ФС",
        "sidebar_history": "История и восстановление",
        "sidebar_protected": "Защищённые папки",
        "sidebar_scheduler": "Планировщик",
        "sidebar_settings": "Настройки",
        "btn_scan": "Сканировать",
        "btn_clean": "Очистить выбранное",
        "btn_cancel": "Отмена",
        "theme_light": "Светлая тема",
        "theme_dark": "Тёмная тема",
        "lang_ru": "Русский",
        "lang_en": "English",
        "status_ready": "Готов к работе",
        "status_scanning": "Сканирование...",
        "status_cleaning": "Очистка...",
        "status_complete": "Завершено",
    },
    "en": {
        "app_name": "SmartCleaner 2.0.2",
        "sidebar_home": "Home",
        "sidebar_quick": "Quick Clean",
        "sidebar_deep": "Deep Clean",
        "sidebar_browsers": "Browsers",
        "sidebar_apps": "Programs & Games",
        "sidebar_disk": "Disk Analysis",
        "sidebar_duplicates": "Duplicates",
        "sidebar_large": "Large Files",
        "sidebar_leftovers": "Leftovers",
        "sidebar_drivers": "Drivers",
        "sidebar_ssd": "SSD/HDD",
        "sidebar_startup": "Startup",
        "sidebar_installed": "Installed Apps",
        "sidebar_integrity": "System Integrity",
        "sidebar_filesystem": "Filesystem Diagnostics",
        "sidebar_history": "History & Recovery",
        "sidebar_protected": "Protected Folders",
        "sidebar_scheduler": "Scheduler",
        "sidebar_settings": "Settings",
        "btn_scan": "Scan",
        "btn_clean": "Clean Selected",
        "btn_cancel": "Cancel",
        "theme_light": "Light Theme",
        "theme_dark": "Dark Theme",
        "lang_ru": "Русский",
        "lang_en": "English",
        "status_ready": "Ready",
        "status_scanning": "Scanning...",
        "status_cleaning": "Cleaning...",
        "status_complete": "Complete",
    }
}


if PYSIDE6_AVAILABLE:
    class WorkResult(QObject):
        ready = Signal(object, str)

    class BackgroundWork(QRunnable):
        def __init__(self, operation):
            super().__init__()
            self.operation = operation
            self.result = WorkResult()

        def run(self):
            try:
                data = self.operation()
            except Exception as exc:
                self.result.ready.emit(None, str(exc))
            else:
                self.result.ready.emit(data, "")


class SmartCleanerMainWindow(QMainWindow if PYSIDE6_AVAILABLE else object):
    """Main application window with CCleaner-style layout."""

    def __init__(self, state_dir=None):
        if not PYSIDE6_AVAILABLE:
            print("PySide6 is not available. GUI cannot run in this environment.")
            print("Install dependencies: pip install -r requirements.txt")
            return

        super().__init__()
        self.setWindowTitle("SmartCleaner 2.0.2")
        self.resize(1200, 800)

        # Core components
        state_dir = state_dir or user_state_dir()
        self.config_manager = ConfigManager(state_dir / "smartcleaner_config.json")
        self.config = self.config_manager.load()
        self.logger = OperationLogger(state_dir / "smartcleaner_history.db")
        self.deleter = SmartCleanerDelete(self.logger, self.config_manager)
        self.browser_cleaner = BrowserCacheCleaner(self.logger, self.config_manager)

        # UI state
        self.current_language = self.config.language
        self.current_theme = self.config.theme
        self.jobs = set()

        self._setup_ui()
        self._apply_theme()
        self._apply_language()
        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(60_000)
        self.schedule_timer.timeout.connect(self._schedule_tick)
        self.schedule_timer.start()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Sidebar ---
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(220)
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                border: none;
                font-size: 14px;
            }
            QListWidget::item:selected {
                background-color: #4a90e2;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)

        sidebar_items = [
            ("Главная", "Home"),
            ("Быстрая очистка", "Quick Clean"),
            ("Глубокая очистка", "Deep Clean"),
            ("Браузеры", "Browsers"),
            ("Программы и игры", "Programs & Games"),
            ("Анализ дисков", "Disk Analysis"),
            ("Дубликаты", "Duplicates"),
            ("Большие файлы", "Large Files"),
            ("Остатки программ", "Leftovers"),
            ("Драйверы", "Drivers"),
            ("SSD/HDD", "SSD/HDD"),
            ("Автозагрузка", "Startup"),
            ("Установленные программы", "Installed Apps"),
            ("Целостность системы", "System Integrity"),
            ("Диагностика ФС", "Filesystem Diagnostics"),
            ("История и восстановление", "History & Recovery"),
            ("Защищённые папки", "Protected Folders"),
            ("Планировщик", "Scheduler"),
            ("Настройки", "Settings"),
        ]

        for ru, en in sidebar_items:
            self.sidebar.addItem(ru if self.current_language == "ru" else en)

        main_layout.addWidget(self.sidebar)
        self.content_stack = QStackedWidget()

        # Create pages
        self.home_page = self._create_home_page()
        self.quick_clean_page = self._create_quick_clean_page()
        self.deep_clean_page = self._create_deep_clean_page()
        self.browsers_page = self._create_browsers_page()
        self.apps_page = self._create_apps_page()
        self.disk_page = self._create_disk_page()
        self.duplicates_page = self._create_duplicates_page()
        self.large_files_page = self._create_large_files_page()
        self.leftovers_page = self._create_leftovers_page()
        self.drivers_page = self._create_drivers_page()
        self.ssd_page = self._create_ssd_page()
        self.startup_page = self._create_startup_page()
        self.installed_page = self._create_installed_page()
        self.integrity_page = self._create_integrity_page()
        self.filesystem_page = self._create_filesystem_page()
        self.history_page = self._create_history_page()
        self.protected_page = self._create_protected_page()
        self.scheduler_page = self._create_scheduler_page()
        self.settings_page = self._create_settings_page()

        pages = [
            self.home_page, self.quick_clean_page, self.deep_clean_page,
            self.browsers_page, self.apps_page, self.disk_page,
            self.duplicates_page, self.large_files_page, self.leftovers_page,
            self.drivers_page, self.ssd_page, self.startup_page,
            self.installed_page, self.integrity_page, self.filesystem_page,
            self.history_page, self.protected_page, self.scheduler_page,
            self.settings_page,
        ]

        for page in pages:
            self.content_stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self._on_sidebar_changed)
        self.sidebar.setCurrentRow(0)
        main_layout.addWidget(self.content_stack)

        # --- Status Bar ---
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Готов к работе" if self.current_language == "ru" else "Ready")

        # --- Progress Bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _create_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("SmartCleaner 2.0.2")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #2b2b2b;")
        layout.addWidget(title)

        subtitle = QLabel("Система очистки и оптимизации")
        subtitle.setStyleSheet("font-size: 16px; color: #666666;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Disk info cards
        info_layout = QHBoxLayout()
        self.card_total = QLabel("Общий объём: --")
        self.card_used = QLabel("Занято: --")
        self.card_free = QLabel("Свободно: --")
        self.card_scan = QLabel("Последнее сканирование: --")
        self.card_clean = QLabel("Последняя очистка: --")

        for card in [self.card_total, self.card_used, self.card_free, self.card_scan, self.card_clean]:
            card.setStyleSheet("""
                QLabel {
                    background-color: #ffffff;
                    border: 1px solid #dddddd;
                    border-radius: 8px;
                    padding: 16px;
                    font-size: 14px;
                }
            """)
            info_layout.addWidget(card)

        layout.addLayout(info_layout)
        layout.addSpacing(20)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.btn_scan_home = QPushButton("Сканировать")
        self.btn_clean_home = QPushButton("Очистить выбранное")
        self.btn_scan_home.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #357abd; }
        """)
        self.btn_clean_home.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c0392b; }
        """)
        self.btn_scan_home.clicked.connect(self._start_scan)
        self.btn_clean_home.clicked.connect(self._start_clean)

        btn_layout.addWidget(self.btn_scan_home)
        btn_layout.addWidget(self.btn_clean_home)
        layout.addLayout(btn_layout)
        layout.addStretch()

        return page

    def _create_quick_clean_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        label = QLabel("Быстрая очистка")
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)

        desc = QLabel("Быстрое сканирование известных безопасных областей (кеш системы, временные файлы).")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.btn_quick_scan = QPushButton("Сканировать быстрые области")
        self.btn_quick_scan.clicked.connect(self._quick_scan)
        layout.addWidget(self.btn_quick_scan)

        self.quick_results = QTextEdit()
        self.quick_results.setReadOnly(True)
        layout.addWidget(self.quick_results)
        self.quick_files = QListWidget()
        self.quick_files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.quick_files)
        quarantine = QPushButton("Проверить выбранные файлы")
        quarantine.clicked.connect(lambda: self._confirm_move(
            [item.data(Qt.UserRole) for item in self.quick_files.selectedItems()]))
        layout.addWidget(quarantine)

        layout.addStretch()
        return page

    def _create_deep_clean_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        label = QLabel("Глубокая очистка")
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)

        desc = QLabel("Глубокое сканирование выбранных локальных дисков и разделов.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.disk_combo = QComboBox()
        for d in DiskScanner.get_disks():
            self.disk_combo.addItem(f"{d.mountpoint} ({d.free / (1024**3):.1f} GB free)", d.mountpoint)
        layout.addWidget(self.disk_combo)

        self.btn_deep_scan = QPushButton("Глубокое сканирование")
        self.btn_deep_scan.clicked.connect(self._deep_scan)
        layout.addWidget(self.btn_deep_scan)

        self.deep_results = QTextEdit()
        self.deep_results.setReadOnly(True)
        layout.addWidget(self.deep_results)

        layout.addStretch()
        return page

    def _create_browsers_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        label = QLabel("Браузеры")
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)

        desc = QLabel("Выберите браузеры и профили для очистки кеша. Пароли, cookies, закладки и история сохраняются.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.browser_tree = QTreeWidget()
        self.browser_tree.setHeaderLabels(["Браузер / Профиль", "Размер кеша", "Выбрать"])
        self.browser_tree.setColumnWidth(0, 300)
        self.browser_tree.setColumnWidth(1, 150)
        layout.addWidget(self.browser_tree)

        btn_layout = QHBoxLayout()
        self.btn_browser_scan = QPushButton("Обновить список браузеров")
        self.btn_browser_scan.clicked.connect(self._load_browsers)
        self.btn_browser_clean = QPushButton("Очистить выбранное")
        self.btn_browser_clean.clicked.connect(self._clean_browsers)
        btn_layout.addWidget(self.btn_browser_scan)
        btn_layout.addWidget(self.btn_browser_clean)
        layout.addLayout(btn_layout)

        layout.addStretch()
        return page

    def _data_page(self, title, description, columns=()):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(title)
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)
        hint = QLabel(description)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        if columns:
            output = QTableWidget(0, len(columns))
            output.setHorizontalHeaderLabels(columns)
            output.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            output.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            output.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            output.horizontalHeader().setStretchLastSection(True)
        else:
            output = QTextEdit()
            output.setReadOnly(True)
        layout.addWidget(output)
        return page, controls, output

    @staticmethod
    def _button(controls, label, action):
        button = QPushButton(label)
        button.clicked.connect(action)
        controls.addWidget(button)
        return button

    @staticmethod
    def _show_rows(table, rows):
        rows = list(rows)
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(str(value) if value is not None else "—")
                item.setToolTip(item.text())
                table.setItem(index, column, item)

    def _run_job(self, button, output, operation, render=None, on_error=None):
        if not button.isEnabled():
            return
        button.setEnabled(False)
        self.status_bar.showMessage("Выполняется проверка…")
        job = BackgroundWork(operation)
        signal = job.result
        self.jobs.add(signal)

        def finished(data, error):
            self.jobs.discard(signal)
            button.setEnabled(True)
            if error:
                if on_error:
                    on_error(error)
                self.status_bar.showMessage("Проверка завершилась ошибкой.")
                if isinstance(output, QTextEdit):
                    output.setPlainText(error)
                else:
                    self._show_rows(output, [])
                    QMessageBox.warning(self, "SmartCleaner", error)
                return
            if render:
                render(data)
            elif isinstance(output, QTextEdit):
                output.setPlainText(str(data))
            else:
                self._show_rows(output, data)
            self.status_bar.showMessage("Проверка завершена.", 4000)

        signal.ready.connect(finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _folder_job(self, button, output, operation, render=None):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для анализа")
        if path:
            self._run_job(button, output, lambda: operation(path), render)

    def _settings_link(self, uri):
        if os.name != "nt" or not QDesktopServices.openUrl(QUrl("ms-settings:" + uri)):
            QMessageBox.warning(self, "Настройки Windows", "Раздел Windows не удалось открыть.")

    def _create_apps_page(self):
        page, controls, table = self._data_page(
            "Кеш приложений", "Проверяются известные каталоги кеша Discord, VS Code, Teams и NVIDIA. "
            "Показано до 2000 файлов. Выбранные файлы можно отправить в карантин.",
            ["Приложение", "Байт", "Путь"])
        scan = self._button(controls, "Найти кеш", lambda: self._run_job(
            scan, table, lambda: [(app, size, path) for app, path, size in
                                 islice(application_caches(), 2000)]))
        self._button(controls, "Проверить выбранные файлы", lambda: self._confirm_move(
            [table.item(index.row(), 2).text() for index in table.selectionModel().selectedRows()]))
        return page

    def _create_disk_page(self):
        page, controls, table = self._data_page(
            "Использование места", "До 50 крупнейших элементов папки. "
            "Доля рассчитывается по прочитанным файлам. Двойной щелчок открывает анализ подпапки.",
            ["Элемент", "МиБ", "Доля", "Путь"])

        def render(data):
            root = Path(data["path"])
            rows = []
            for item in data["children"]:
                size = item["size"]
                percent = size * 100 / data["size"] if data["size"] else 0
                rows.append((item["name"], f"{size / 1024**2:.2f}", f"{percent:.1f} %",
                             str(root / item["name"])))
            self._show_rows(table, rows)

        def drill(row, _column):
            path = table.item(row, 3).text()
            if Path(path).is_dir():
                self._run_job(scan, table, lambda: DiskAnalyzerEngine.generate_treemap(path), render)

        scan = self._button(controls, "Выбрать папку", lambda: self._folder_job(
            scan, table, DiskAnalyzerEngine.generate_treemap, render))
        table.cellDoubleClicked.connect(drill)
        return page

    def _create_duplicates_page(self):
        page, controls, table = self._data_page(
            "Дубликаты", "Совпадения по размеру и SHA-256 для файлов от 1 КиБ. Только анализ.",
            ["Группа", "Путь"])
        scan = self._button(controls, "Выбрать папку", lambda: self._folder_job(
            scan, table, DiskAnalyzerEngine.find_duplicates, lambda groups: self._show_rows(
                table, islice(((i, path) for i, group in enumerate(groups, 1) for path in group), 5000))))
        return page

    def _create_large_files_page(self):
        page, controls, table = self._data_page(
            "Большие и старые файлы", "До 100 результатов. Возраст отсчитывается от даты изменения.",
            ["МиБ", "Путь"])
        size = QSpinBox()
        size.setRange(0, 1_000_000)
        size.setValue(50)
        size.setSuffix(" МиБ и больше")
        days = QSpinBox()
        days.setRange(0, 36500)
        days.setSuffix(" дней и старше")
        extension = QLineEdit()
        extension.setPlaceholderText("Расширение, например .zip")
        for field in (size, days, extension):
            controls.addWidget(field)

        def choose():
            minimum, age, suffix = size.value(), days.value(), extension.text()
            self._folder_job(scan, table,
                             lambda path: DiskAnalyzerEngine.find_large_files(
                                 path, minimum, extension=suffix, min_age_days=age),
                             lambda rows: self._show_rows(
                                 table, ((f"{size / 1024**2:.2f}", path) for path, size in rows)))

        scan = self._button(controls, "Выбрать папку", choose)
        return page

    def _create_leftovers_page(self):
        page, controls, table = self._data_page(
            "Возможные остатки программ", "Ищет каталоги известных приложений, "
            "для которых нет записи в реестре установленных программ. "
            "Наличие папки не означает, что её можно удалять.",
            ["Приложение", "Папка"])
        scan = self._button(controls, "Проверить", lambda: self._run_job(
            scan, table, lambda: list(leftover_candidates(
                app.name for app in ApplicationManager.get_installed_applications()))))
        return page

    def _create_drivers_page(self):
        page, controls, table = self._data_page(
            "Драйверы", "Источник обновлений — служба Windows Update, настроенная на этом компьютере. "
            "Она подбирает предложения по оборудованию и версии Windows. "
            "Версия определяется по названию пакета, если она там указана. "
            "Загрузка/установка возможна только через Windows Update. OEM — официальный портал вручную.",
            ["Устройство", "Поставщик", "Установлено", "Подпись", "ID"])
        layout = page.layout()
        offer_status = QLabel("Проверка обновлений ещё не запускалась.")
        offer_status.setWordWrap(True)
        layout.addWidget(offer_status)
        oem_status = QLabel("OEM: сначала запустите сканирование.")
        oem_status.setWordWrap(True)
        layout.addWidget(oem_status)
        source_status = QLabel(
            "Источники устройств: сначала запустите сканирование. "
            "Официальный сайт не означает наличия нового драйвера.")
        source_status.setWordWrap(True)
        layout.addWidget(source_status)
        sources_table = QTableWidget(0, 5)
        sources_table.setObjectName("device_driver_sources")
        sources_table.setHorizontalHeaderLabels(
            ["Устройство", "Версия", "Производитель", "Источник", "ID оборудования"])
        sources_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        sources_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        sources_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        sources_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(sources_table)
        offers = QTableWidget(0, 7)
        offers.setHorizontalHeaderLabels(["Устройство", "Установлено", "Предлагается",
                                          "Дата драйвера", "Обновление Windows Update",
                                          "Поставщик", "ID оборудования"])
        offers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        offers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        offers.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        offers.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(offers)

        inventory = self._button(controls, "Установленные драйверы", lambda: self._run_job(
            inventory, table, lambda: [(d.device_name, d.provider, d.current_version, d.status, d.hardware_id)
                                       for d in DriverManager.get_installed_drivers()]))

        def open_update():
            row = offers.currentRow()
            if row < 0:
                return
            title = offers.item(row, 4).text()
            confirmation = QMessageBox(self)
            confirmation.setWindowTitle("Обновление драйвера")
            confirmation.setTextFormat(Qt.PlainText)
            confirmation.setText(f"Открыть Windows Update для обновления?\n\n{title}")
            confirmation.setInformativeText(
                "В Windows выберите это обновление в списке необязательных обновлений драйверов.")
            confirmation.setStandardButtons(QMessageBox.StandardButton.Open |
                                            QMessageBox.StandardButton.Cancel)
            confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if confirmation.exec() == QMessageBox.StandardButton.Open:
                if not QDesktopServices.openUrl(QUrl("ms-settings:windowsupdate-optionalupdates")):
                    self._settings_link("windowsupdate")

        install = self._button(controls, "Перейти к обновлению выбранного", open_update)
        install.setEnabled(False)
        offers.itemSelectionChanged.connect(
            lambda: install.setEnabled(bool(offers.selectedItems())))

        # Holding the button for 1500 ms triggers a WUA download only.
        # Installation still requires a separate confirmation dialog.
        selected_scan = {"result": None}
        action_output = QTextEdit(page)
        action_output.setVisible(False)
        hold_update = QPushButton("Удерживайте 1,5 с — скачать выбранный драйвер")
        hold_update.setToolTip("Только Windows Update Agent; сторонние EXE не запускаются")
        controls.addWidget(hold_update)
        hold_timer = QTimer(hold_update)
        hold_timer.setSingleShot(True)

        def selected_offer():
            result = selected_scan["result"]
            row = offers.currentRow()
            if result is None or result.partial or row < 0 or row >= len(result.offers):
                return None
            offer = result.offers[row]
            token = (result.tokens or {}).get(offer)
            return (offer, token) if token else None

        def update_selection():
            hold_update.setEnabled(selected_offer() is not None)

        def action_error(error):
            offer_status.setText("Операция не завершена. Подробности в предупреждении.")
            QMessageBox.warning(self, "Windows Update", error)
            update_selection()

        def begin_download():
            selection = selected_offer()
            if selection is None or not hold_update.isDown():
                return
            offer, token = selection

            def installed(result):
                offer_status.setText("Результат установки: " + result.message +
                                     (". Нужна перезагрузка." if result.reboot_required else "."))
                try:
                    self.logger.log_operation("DRIVER_INSTALL", offer.device,
                                              details=f"WUA: {offer.title}; {result.message}")
                except sqlite3.Error:
                    pass
                QMessageBox.information(self, "Windows Update", offer_status.text())
                update_selection()

            def downloaded(result):
                offer_status.setText(f"{offer.device}: загружено через Windows Update; не установлено.")
                answer = QMessageBox.question(
                    self, "Подтверждение установки драйвера",
                    f"Установить драйвер?\n\nУстройство: {offer.device}\n"
                    f"Поставщик: {offer.provider}\nПакет: {offer.title}\n\n"
                    "Драйвер может потребовать перезагрузку. "
                    "Windows Update повторно проверит применимость пакета.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes:
                    self._run_job(hold_update, action_output,
                                  lambda: install_driver(offer, token, confirmed=True),
                                  installed, action_error)
                else:
                    update_selection()

            offer_status.setText(f"Загрузка {offer.device} через Windows Update…")
            self._run_job(hold_update, action_output,
                          lambda: download_driver(offer, token), downloaded, action_error)

        hold_timer.timeout.connect(begin_download)
        hold_update.pressed.connect(lambda: hold_timer.start(1500))
        hold_update.released.connect(hold_timer.stop)
        hold_update.setEnabled(False)
        offers.itemSelectionChanged.connect(update_selection)

        oem_link = QPushButton("Официальная поддержка производителя ПК")
        oem_link.setEnabled(False)
        controls.addWidget(oem_link)

        def open_oem():
            result = selected_scan["result"]
            if result is not None and result.oem is not None:
                QDesktopServices.openUrl(QUrl(result.oem.url))

        oem_link.clicked.connect(open_oem)

        vendor_link = self._button(
            controls, "Официальный сайт выбранного устройства", lambda: open_vendor())
        vendor_link.setEnabled(False)
        source_entries = {"items": []}

        def selected_source():
            row = sources_table.currentRow()
            entries = source_entries["items"]
            return entries[row] if 0 <= row < len(entries) else None

        def update_vendor_selection():
            entry = selected_source()
            vendor_link.setEnabled(
                entry is not None and is_trusted_support_url(entry.url))

        def open_vendor():
            entry = selected_source()
            if entry is None or not is_trusted_support_url(entry.url):
                QMessageBox.warning(
                    self, "Источник драйвера",
                    "Для устройства нет подтверждённого официального сайта.")
                return
            if not QDesktopServices.openUrl(QUrl(entry.url)):
                QMessageBox.warning(self, "Источник драйвера",
                                    "Не удалось открыть страницу производителя.")

        sources_table.itemSelectionChanged.connect(update_vendor_selection)

        def render(result):
            selected_scan["result"] = result
            self._show_rows(offers, result.offers)
            update_selection()
            source_entries["items"] = list(result.sources or [])
            self._show_rows(
                sources_table,
                ((entry.device, entry.installed, entry.manufacturer,
                  "Официальный сайт — проверка вручную" if is_trusted_support_url(entry.url)
                  else "Источник не определён", entry.hardware_id)
                 for entry in source_entries["items"]))
            for row, entry in enumerate(source_entries["items"]):
                for column in range(sources_table.columnCount()):
                    item = sources_table.item(row, column)
                    if item is not None:
                        item.setToolTip(entry.guidance +
                                        (f"\n{entry.url}" if is_trusted_support_url(entry.url) else ""))
            source_status.setText(
                f"Обнаружено устройств: {len(source_entries['items'])}. "
                "Официальные ссылки не являются результатом проверки версии "
                "и не позволяют автоматически устанавливать драйверы.")
            update_vendor_selection()
            oem_link.setEnabled(result.oem is not None)
            if result.oem is None:
                oem_status.setText("OEM: официальный портал не определён; "
                                   "проверка OEM-версий автоматически не выполнялась.")
            else:
                oem_status.setText(
                    f"OEM: {result.oem.manufacturer} / {result.oem.model}. "
                    "Официальный сайт доступен по кнопке; версии OEM проверяются вручную.")
            stamp = result.checked_at.strftime("%d.%m.%Y %H:%M")
            if result.partial:
                message = f"Windows Update завершил проверку с ошибками. Строк: {len(result.offers)}."
            elif result.offers:
                message = f"Windows Update предлагает обновления. Строк: {len(result.offers)}."
            else:
                message = "Windows Update сейчас не предлагает обновлений драйверов для этого компьютера."
            offer_status.setText(f"{message} Проверено: {stamp}.")

        def start():
            selected_scan["result"] = None
            self._show_rows(offers, [])
            source_entries["items"] = []
            self._show_rows(sources_table, [])
            source_status.setText("Выполняется инвентаризация устройств…")
            vendor_link.setEnabled(False)
            install.setEnabled(False)
            hold_update.setEnabled(False)
            oem_link.setEnabled(False)
            offer_status.setText("Запрос к Windows Update. Это может занять несколько минут…")
            self._run_job(search, offers, check_driver_updates, render,
                          on_error=lambda error: offer_status.setText(
                              "Проверка Windows Update не удалась. Повторите позже или откройте Windows Update."))
            inventory.click()

        search = self._button(controls, "Проверить обновления", start)
        self._button(controls, "Windows Update", lambda: self._settings_link("windowsupdate"))
        return page

    def _create_ssd_page(self):
        page, controls, table = self._data_page(
            "SSD/HDD", "Состояние накопителя по данным Windows. Прочерк означает, что контроллер не предоставил показатель.",
            ["Модель", "Тип", "Шина", "ГиБ", "Состояние", "°C", "Износ %", "Часов"])
        scan = self._button(controls, "Опросить накопители", lambda: self._run_job(
            scan, table, lambda: [(d.get("Model", d.get("device")), d.get("Media"), d.get("Bus"),
                                   f'{d["Size"] / 1024**3:.1f}' if d.get("Size") else None,
                                   d.get("Health", d.get("smart_status")), d.get("Temperature"),
                                   d.get("Wear"), d.get("PowerOnHours"))
                                  for d in SystemDiagnostics.get_drive_health()]))
        return page

    def _create_startup_page(self):
        page, controls, table = self._data_page(
            "Автозагрузка", "Показывает зарегистрированные команды. Включение и отключение выполняются средствами Windows.",
            ["Имя", "Источник", "Команда"])
        scan = self._button(controls, "Обновить", lambda: self._run_job(
            scan, table, lambda: [(item.name, item.source, item.path)
                                  for item in StartupManager.get_startup_items()]))
        self._button(controls, "Управление автозагрузкой", lambda: self._settings_link("startupapps"))
        return page

    def _create_installed_page(self):
        page, controls, table = self._data_page(
            "Установленные программы", "Показывает зарегистрированные программы. "
            "Для удаления и списка приложений Microsoft Store откройте настройки Windows.",
            ["Имя", "Версия", "Издатель"])
        scan = self._button(controls, "Обновить", lambda: self._run_job(
            scan, table, lambda: [(app.name, app.version, app.publisher)
                                  for app in ApplicationManager.get_installed_applications()]))
        self._button(controls, "Приложения Windows", lambda: self._settings_link("appsfeatures"))
        return page

    def _create_integrity_page(self):
        page, controls, output = self._data_page(
            "Целостность системы", "SFC проверяет системные файлы. DISM показывает, отмечено ли "
            "хранилище компонентов как повреждённое. Обе проверки выполняются без исправлений. "
            "Для них могут потребоваться права администратора.")
        scan = self._button(controls, "Проверить системные файлы", lambda: self._run_job(
            scan, output, lambda: SystemDiagnostics.check_system_integrity()[1]))
        dism = self._button(controls, "Проверить хранилище DISM", lambda: self._run_job(
            dism, output, lambda: SystemDiagnostics.check_component_store()[1]))
        return page

    def _create_filesystem_page(self):
        page, controls, output = self._data_page(
            "Диагностика файловых систем", "CHKDSK проверяет выбранный том без исправлений. "
            "Для проверки могут потребоваться права администратора.")
        volumes = QComboBox()
        for disk in DiskScanner.get_disks():
            if len(disk.mountpoint) in (2, 3) and disk.mountpoint[1] == ":":
                volumes.addItem(disk.mountpoint)
        controls.addWidget(volumes)

        def check():
            volume = volumes.currentText()
            if volume:
                self._run_job(scan, output, lambda: SystemDiagnostics.check_filesystem(volume)[1])

        scan = self._button(controls, "Проверить том", check)
        scan.setEnabled(bool(volumes.count()))
        return page

    def _create_history_page(self):
        page, controls, self.history_table = self._data_page(
            "История и восстановление", "Последние 100 операций. Восстановление проверяет содержимое "
            "и сохраняет любой файл, уже находящийся по исходному пути.",
            ["Время UTC", "Действие", "Статус", "Путь"])
        self._button(controls, "Обновить", self._refresh_history)
        self._button(controls, "Восстановить из карантина", self._restore_item)
        return page

    def _refresh_history(self):
        self._show_rows(self.history_table, ((entry["timestamp"], entry["operation_type"],
                                             entry["status"], entry["target_path"])
                                            for entry in self.logger.get_history()))

    def _create_protected_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("Защищённые папки")
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)
        desc = QLabel("Один путь на строку. Действует для ручной очистки и кеша браузеров.")
        self.exclusion_editor = QTextEdit()
        self.exclusion_editor.setPlainText("\n".join(self.config.excluded_paths))
        layout.addWidget(self.exclusion_editor)
        save = QPushButton("Сохранить исключения")
        save.clicked.connect(self._save_exclusions)
        layout.addWidget(save)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addStretch()
        return page

    def _create_scheduler_page(self):
        page, controls, self.schedule_output = self._data_page(
            "Планировщик", "Анализ кеша запускается по расписанию, пока SmartCleaner открыт. "
            "Файлы при анализе не перемещаются.")
        self.schedule_enabled = QCheckBox("Включить")
        self.schedule_enabled.setChecked(self.config.scheduler_enabled)
        self.schedule_interval = QComboBox()
        for label, key in (("Ежедневно", "daily"), ("Еженедельно", "weekly"),
                           ("Каждые 30 дней", "monthly")):
            self.schedule_interval.addItem(label, key)
        self.schedule_interval.setCurrentIndex(max(0, self.schedule_interval.findData(self.config.scheduler_interval)))
        controls.addWidget(self.schedule_enabled)
        controls.addWidget(self.schedule_interval)
        self._button(controls, "Сохранить", self._save_schedule)
        self.schedule_run = self._button(controls, "Анализ сейчас", self._run_schedule)
        return page

    def _save_schedule(self):
        config = self.config_manager.load()
        config.scheduler_enabled = self.schedule_enabled.isChecked()
        config.scheduler_interval = self.schedule_interval.currentData()
        self.config_manager.save(config)
        self.config = config
        self._schedule_tick()

    def _schedule_tick(self):
        if not self.config.scheduler_enabled:
            return
        days = {"daily": 1, "weekly": 7, "monthly": 30}.get(self.config.scheduler_interval, 1)
        last_run = self.logger.latest_operation_time("SCHEDULE_SCAN")
        if not last_run or (datetime.now(timezone.utc) - last_run).total_seconds() >= days * 86400:
            self._run_schedule()

    def _run_schedule(self):
        def operation():
            result = SchedulerService.run_scheduled_analysis()
            message = f'Файлов: {result["files_found"]}\nОбъём: {result["total_size"] / 1024**2:.2f} МиБ'
            self.logger.log_operation("SCHEDULE_SCAN", "Кеш", result["total_size"], details=message)
            return message

        self._run_job(self.schedule_run, self.schedule_output, operation)

    def _create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("Настройки")
        label.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(label)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Светлая тема", "Тёмная тема"] if self.current_language == "ru" else ["Light Theme", "Dark Theme"])
        self.theme_combo.setCurrentIndex(int(self.config.theme == 'dark'))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addWidget(QLabel("Тема оформления:"))
        layout.addWidget(self.theme_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Русский", "English"])
        self.lang_combo.setCurrentIndex(int(self.config.language == 'en'))
        self.lang_combo.currentTextChanged.connect(self._on_language_changed)
        layout.addWidget(QLabel("Язык:"))
        layout.addWidget(self.lang_combo)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        self._button(controls, "Экспорт настроек", self._export_settings)
        self._button(controls, "Импорт настроек", self._import_settings)

        layout.addStretch()
        return page

    def _export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт настроек", "SmartCleaner.json", "JSON (*.json)")
        if path and not self.config_manager.export_settings(path):
            QMessageBox.warning(self, "Настройки", "Сохранить настройки не удалось.")

    def _import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт настроек", "", "JSON (*.json)")
        if not path:
            return
        answer = QMessageBox.question(self, "Настройки",
                                      "Заменить текущие настройки и исключения данными из файла?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.config_manager.import_settings(path):
            QMessageBox.warning(self, "Настройки", "Импортировать настройки не удалось.")
            return
        self.config = self.config_manager.load()
        self.current_language, self.current_theme = self.config.language, self.config.theme
        self.exclusion_editor.setPlainText("\n".join(self.config.excluded_paths))
        self.schedule_enabled.setChecked(self.config.scheduler_enabled)
        self.schedule_interval.setCurrentIndex(max(0, self.schedule_interval.findData(self.config.scheduler_interval)))
        for widget, index in ((self.theme_combo, int(self.current_theme == "dark")),
                              (self.lang_combo, int(self.current_language == "en"))):
            previous = widget.blockSignals(True)
            widget.setCurrentIndex(index)
            widget.blockSignals(previous)
        self._apply_theme()
        self._apply_language()
        self._schedule_tick()

    def _apply_theme(self):
        if PYSIDE6_AVAILABLE:
            app = QApplication.instance()
            if self.current_theme == "dark":
                app.setStyleSheet("""
                    QMainWindow { background-color: #2b2b2b; color: #ffffff; }
                    QWidget { background-color: #2b2b2b; color: #ffffff; }
                    QTabWidget::pane { background-color: #3a3a3a; }
                    QTabBar::tab { background-color: #4a4a4a; color: #ffffff; }
                    QTabBar::tab:selected { background-color: #2b2b2b; border-bottom: 2px solid #4a90e2; }
                    QPushButton { background-color: #4a90e2; color: white; border: none; padding: 8px 16px; border-radius: 4px; }
                    QPushButton:hover { background-color: #357abd; }
                    QTextEdit { background-color: #3a3a3a; color: #ffffff; border: 1px solid #555555; }
                    QTreeWidget { background-color: #3a3a3a; color: #ffffff; border: 1px solid #555555; }
                    QComboBox { background-color: #4a4a4a; color: #ffffff; border: 1px solid #555555; }
                    QLabel { color: #ffffff; }
                """)
            else:
                app.setStyleSheet("")

    def _apply_language(self):
        lang = LANGUAGES.get(self.current_language, LANGUAGES["ru"])
        self.setWindowTitle(lang["app_name"])
        # Update sidebar items
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            # Map index to key
            keys = [
                "sidebar_home", "sidebar_quick", "sidebar_deep", "sidebar_browsers",
                "sidebar_apps", "sidebar_disk", "sidebar_duplicates", "sidebar_large",
                "sidebar_leftovers", "sidebar_drivers", "sidebar_ssd", "sidebar_startup",
                "sidebar_installed", "sidebar_integrity", "sidebar_filesystem",
                "sidebar_history", "sidebar_protected", "sidebar_scheduler", "sidebar_settings",
            ]
            if i < len(keys):
                item.setText(lang[keys[i]])
        self.status_bar.showMessage(lang["status_ready"])

    def _on_sidebar_changed(self, index):
        self.content_stack.setCurrentIndex(index)
        if index == self.content_stack.indexOf(self.history_page):
            self._refresh_history()

    def _on_theme_changed(self, text):
        self.current_theme = "dark" if "Тёмная" in text or "Dark" in text else "light"
        self.config.theme = self.current_theme
        self.config_manager.save(self.config)
        self._apply_theme()

    def _on_language_changed(self, text):
        self.current_language = "ru" if "Русский" in text else "en"
        self.config.language = self.current_language
        self.config_manager.save(self.config)
        self._apply_language()

    def _start_scan(self):
        self._quick_scan()
        self.sidebar.setCurrentRow(1)

    def _quick_scan(self):
        self._run_job(self.btn_quick_scan, self.quick_results, QuickScanner().scan,
                      self._show_quick_scan)

    def _show_quick_scan(self, result):
        self.quick_files.clear()
        for entry in result.files:
            item = QListWidgetItem(entry.path)
            item.setData(Qt.UserRole, entry.path)
            self.quick_files.addItem(item)
        self.quick_results.setText(
            f"Найдено файлов: {result.file_count}\n"
            f"Общий размер: {result.total_size / (1024*1024):.2f} МБ\n"
            f"Статус: {result.status.value}\n"
            f"Ошибок: {len(result.errors)}"
        )

    def _deep_scan(self):
        mountpoint = self.disk_combo.currentData()
        if not mountpoint:
            return
        self._run_job(self.btn_deep_scan, self.deep_results,
                      lambda: FileScanner().scan_directory(mountpoint, max_depth=3),
                      lambda result: self._show_deep_scan(mountpoint, result))

    def _show_deep_scan(self, mountpoint, result):
        self.deep_results.setPlainText(
            f"Диск: {mountpoint}\n"
            f"Найдено файлов: {result.file_count}\n"
            f"Общий размер: {result.total_size / (1024*1024):.2f} МБ\n"
            f"Статус: {result.status.value}\n"
            f"Ошибок: {len(result.errors)}"
        )

    def _save_exclusions(self):
        try:
            config = self.config_manager.load()
            config.excluded_paths = self.exclusion_editor.toPlainText().splitlines()
            config.excluded_paths = [path.strip() for path in config.excluded_paths if path.strip()]
            self.config_manager.save(config)
            self.config = config
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Исключения", str(exc))

    def _restore_item(self):
        rows = [row for row in self.logger.get_quarantine_items()
                if os.path.lexists(row["quarantine_path"])]
        if not rows:
            QMessageBox.information(self, "Карантин", "Доступных файлов нет.")
            return
        labels = {f'{row["id"]} — {row["original_path"]}': row["id"] for row in rows}
        label, confirmed = QInputDialog.getItem(
            self, "Карантин", "Выберите файл для восстановления", list(labels), 0, False)
        if confirmed:
            success, message = self.deleter.restore_item(labels[label])
            self._refresh_history()
            (QMessageBox.information if success else QMessageBox.warning)(self, "Карантин", message)

    def _load_browsers(self):
        self.browser_tree.clear()
        self.browser_profiles = self.browser_cleaner.detect_browsers()
        for index, profile in enumerate(self.browser_profiles):
            item = QTreeWidgetItem(
                [f"{profile.browser.title()} / {profile.name}", f"{profile.cache_size / 1024:.2f} KB", ""])
            item.setData(0, Qt.UserRole, index)
            item.setCheckState(2, Qt.Unchecked)
            self.browser_tree.addTopLevelItem(item)

    def _clean_browsers(self):
        files = {}
        for index in range(self.browser_tree.topLevelItemCount()):
            item = self.browser_tree.topLevelItem(index)
            if item.checkState(2) == Qt.Checked:
                profile = self.browser_profiles[item.data(0, Qt.UserRole)]
                files.update((path, profile) for path in profile.cache_files)
        return self._confirm_move(files, files)

    def _confirm_move(self, paths, profiles=None):
        approved = {}
        blocked = []
        for path in dict.fromkeys(paths):
            try:
                if profiles is None:
                    candidate, info = ProtectionEngine.validate_file(path, self.deleter.exclusions())
                else:
                    candidate, info = self.browser_cleaner.validate_candidate(profiles[path], path)
                approved[candidate] = identity(info)
            except (OSError, ValueError, TypeError) as exc:
                blocked.append(f"{path} — {exc}")

        if not approved:
            QMessageBox.warning(self, "Карантин", "\n".join(blocked[:12]) or "Выберите файлы.")
            return 1

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Карантин")
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText(f"Переместить файлов в карантин: {len(approved)}? Заблокировано: {len(blocked)}.")
        dialog.setInformativeText("Список путей доступен в подробностях. Место на диске не освобождается.")
        dialog.setDetailedText("\n".join([*(repr(str(path)) for path in approved), *blocked]))
        move = dialog.addButton("Переместить", QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() != move:
            return 1

        moved = 0
        errors = []
        for path, snapshot in approved.items():
            success, message = self.deleter.delete_item(path, expected=snapshot)
            if success:
                moved += 1
            else:
                errors.append(f"{path} — {message}")
        QMessageBox.information(
            self, "Карантин",
            f"Перемещено: {moved}. Ошибок: {len(errors)}.\n" + "\n".join(errors[:12]))
        return int(bool(errors or blocked))

    def _start_clean(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для карантина")
        if paths:
            self._confirm_move(paths)


def user_state_dir(portable=False):
    if portable:
        base = Path(sys.executable).parent
        inspect_path(base)
        directory = base / "SmartCleaner-data"
        directory.mkdir(mode=0o700, exist_ok=True)
        inspect_path(directory)
        return directory
    if os.name == "nt":
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    directory = checked_path(base / "SmartCleaner")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    inspect_path(directory)
    return directory


def main(argv=None, *, portable=False):
    parser = argparse.ArgumentParser(description="SmartCleaner")
    parser.add_argument("--delete", nargs="+", metavar="FILE",
                        help="Review files and confirm moving them to quarantine")
    args = parser.parse_args(argv)
    if not PYSIDE6_AVAILABLE:
        print("PySide6 is required to display the confirmation dialog.", file=sys.stderr)
        return 2

    app = QApplication([sys.argv[0]])
    try:
        window = SmartCleanerMainWindow(user_state_dir(portable) if portable else None)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        QMessageBox.critical(None, "SmartCleaner", str(exc))
        return 2
    if args.delete:
        return window._confirm_move(args.delete)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
