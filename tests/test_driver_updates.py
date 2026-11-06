import unittest
from unittest.mock import patch

from smartcleaner.driver_updates import check_driver_updates, compare_offers


class DriverUpdateTests(unittest.TestCase):
    def test_match_compatible_id_and_show_both_versions(self):
        devices = [{"Name": "Audio", "Version": "1.0.0",
                    "Identifiers": ["PCI\\VEN_1234", "PCI\\CC_0403"]}]
        updates = [{"Title": "Vendor - MEDIA - 2.4.1", "Date": "2026-01-03",
                    "Provider": "Vendor", "HardwareID": "pci\\cc_0403"}]
        offer, = compare_offers(devices, updates)
        self.assertEqual((offer.device, offer.installed, offer.offered, offer.date),
                         ("Audio", "1.0.0", "2.4.1", "2026-01-03"))

    def test_unmatched_offer_remains_and_version_is_not_guessed(self):
        offer, = compare_offers([], [{"Model": "Controller", "Title": "Driver for Windows 11"}])
        self.assertEqual((offer.device, offer.installed, offer.offered), ("Controller", "—", "—"))

    @patch("smartcleaner.driver_updates.powershell_rows")
    def test_distinguish_empty_partial_and_failed_scan(self, query):
        query.return_value = [{"ResultCode": 2}]
        result = check_driver_updates()
        self.assertFalse(result.partial)
        self.assertEqual(result.offers, [])
        query.return_value = [{"ResultCode": 3}]
        self.assertTrue(check_driver_updates().partial)
        query.return_value = []
        with self.assertRaises(OSError):
            check_driver_updates()

    def test_driver_page_offers_windows_update_for_selected_item(self):
        import tempfile
        import time
        from datetime import datetime
        from pathlib import Path

        from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTableWidget
        from smartcleaner import gui
        from smartcleaner.driver_updates import DriverOffer, DriverSearch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            window = gui.SmartCleanerMainWindow(Path(folder))
            page = window.drivers_page
            buttons = {button.text(): button for button in page.findChildren(QPushButton)}
            install = buttons["Перейти к обновлению выбранного"]
            self.assertFalse(install.isEnabled())
            offer = DriverOffer("Audio", "1.0", "2.0", "2026-01-03",
                                "Vendor - MEDIA - 2.0", "Vendor", "PCI")
            result = DriverSearch([offer], datetime.now().astimezone(), False)
            with patch.object(gui, "check_driver_updates", return_value=result), \
                    patch.object(gui.DriverManager, "get_installed_drivers", return_value=[]):
                buttons["Проверить обновления"].click()
                deadline = time.monotonic() + 5
                while window.jobs and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.01)
            self.assertFalse(window.jobs)
            table = next(table for table in page.findChildren(QTableWidget) if table.columnCount() == 7)
            self.assertEqual(table.item(0, 2).text(), "2.0")
            table.selectRow(0)
            self.assertTrue(install.isEnabled())
            with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Open), \
                    patch.object(gui.QDesktopServices, "openUrl", return_value=True) as open_url:
                install.click()
            self.assertEqual(open_url.call_args.args[0].toString(), "ms-settings:windowsupdate-optionalupdates")
            window.close()
