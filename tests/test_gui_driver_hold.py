"""Offscreen GUI regression: short press cannot download, 1500ms hold can."""
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTableWidget

from smartcleaner import gui
from smartcleaner.driver_actions import DriverActionResult, DriverToken
from smartcleaner.driver_updates import DriverOffer, DriverSearch


class HoldToUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hold_downloads_but_no_install_without_confirmation(self):
        offer = DriverOffer("Demo", "1.0", "2.0", "2026-01-01",
                            "Vendor - MEDIA - 2.0", "Vendor", r"PCI\VEN_1234")
        token = DriverToken("12345678-1234-4234-8234-123456789012", 3)
        scan = DriverSearch([offer], datetime.now().astimezone(), False, {offer: token})
        with tempfile.TemporaryDirectory() as folder:
            window = gui.SmartCleanerMainWindow(Path(folder))
            page = window.drivers_page
            buttons = {button.text(): button for button in page.findChildren(QPushButton)}
            hold = next(button for button in buttons.values()
                        if button.text().startswith("Удерживайте 1,5"))
            table = next(widget for widget in page.findChildren(QTableWidget)
                         if widget.columnCount() == 7)
            with patch.object(gui, "check_driver_updates", return_value=scan), \
                    patch.object(gui.DriverManager, "get_installed_drivers", return_value=[]):
                buttons["Проверить обновления"].click()
                deadline = time.monotonic() + 5
                while window.jobs and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertEqual(table.rowCount(), 1)
            table.selectRow(0)
            self.app.processEvents()
            self.assertTrue(hold.isEnabled())
            self.assertIsNotNone(hold.findChild(QTimer))

            with patch.object(gui, "download_driver", return_value=DriverActionResult(
                    "DOWNLOADED", False, "Downloaded")) as download, \
                    patch.object(gui, "install_driver") as install, \
                    patch.object(QMessageBox, "question",
                                 return_value=QMessageBox.StandardButton.No):
                QTest.mouseClick(hold, Qt.MouseButton.LeftButton)
                QTest.qWait(100)
                download.assert_not_called()
                QTest.mousePress(hold, Qt.MouseButton.LeftButton)
                QTest.qWait(1650)
                QTest.mouseRelease(hold, Qt.MouseButton.LeftButton)
                deadline = time.monotonic() + 5
                while window.jobs and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                download.assert_called_once_with(offer, token)
                install.assert_not_called()
            window.close()
