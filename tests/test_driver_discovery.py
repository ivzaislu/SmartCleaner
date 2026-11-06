"""Conservative driver availability checks; no real vendor/WUA network activity."""
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from smartcleaner.driver_discovery import build_assessments, compare_versions
from smartcleaner.driver_sources import official_device_sources
from smartcleaner.driver_updates import (DriverOffer, DriverSearch, check_driver_updates,
                                         _tokens_for_offers)


def device(name, identifier, version="31.0.0.1"):
    return {"Name": name, "Version": version, "DeviceID": identifier,
            "Identifiers": [identifier]}


def offer(name, identifier, version, installed="31.0.0.1"):
    return DriverOffer(name, installed, version, "2026-10-12",
                       "Official WUA driver", "Vendor", identifier)


class AssessmentTests(unittest.TestCase):
    def test_version_comparisons_fail_closed(self):
        self.assertEqual(compare_versions("1.2.3.4", "1.2.3.5"), 1)
        self.assertEqual(compare_versions("1.2", "1.2"), 0)
        self.assertEqual(compare_versions("1.2.3.4", "1.2.3.3"), -1)
        self.assertIsNone(compare_versions("31.0.15.5123", "555.12"))
        self.assertIsNone(compare_versions("2026.11.1", "latest"))
        self.assertIsNone(compare_versions("1.2", "1.2.0"))
        self.assertIsNone(compare_versions("1.2-alpha", "1.3"))
        self.assertIsNone(compare_versions("1.2", "1.2.3.4.5"))

    def test_wua_never_claims_manufacturer_latest(self):
        pci = r"PCI\VEN_10DE&DEV_1234"
        d = device("NVIDIA GeForce Test", pci, "31.0.0.1")
        o = offer(d["Name"], pci, "31.0.0.2")
        row, = build_assessments([d], [o])
        self.assertEqual(row.status, "WUA_NEWER")
        self.assertIn("Windows Update", row.origin)
        self.assertNotIn("самую новую версию", row.explanation.split(".")[0])
        self.assertTrue(row.assisted_check_url.startswith("https://www.nvidia.com/"))

    def test_noncomparable_wua_and_lower_version(self):
        pci = r"PCI\VEN_1002&DEV_7000"
        d = device("AMD Radeon Test", pci, "31.0.0.1")
        row, = build_assessments([d], [offer(d["Name"], pci, "555.99")])
        self.assertEqual(row.status, "WUA_OFFER")
        self.assertEqual(row.offered, "555.99")
        row, = build_assessments([d], [offer(d["Name"], pci, "30.0.0.1")])
        self.assertEqual(row.status, "WUA_NOT_NEWER")

    def test_no_offers_vs_incomplete_scan(self):
        d = device("Intel Wi-Fi Test", r"PCI\VEN_8086&DEV_1234")
        row, = build_assessments([d], [])
        self.assertEqual(row.status, "VENDOR_ASSISTANT")
        self.assertEqual(row.offered, "—")
        self.assertIn("intel.com", row.assisted_check_url)
        row, = build_assessments([d], [], partial=True)
        self.assertEqual(row.status, "INCOMPLETE")
        self.assertIn("неполной проверке", row.explanation)

    def test_unmatched_wua_offer_cannot_claim_device_update(self):
        d = device("Realtek HD Audio", r"PCI\VEN_10EC&DEV_0101")
        unrelated = offer(d["Name"], r"PCI\VEN_1234&DEV_0001", "32.0.0.1")
        row, = build_assessments([d], [unrelated])
        self.assertEqual(row.status, "MANUAL")
        self.assertEqual(row.offered, "—")
        self.assertEqual(row.assisted_check_url, "")

    def test_vendor_scanning_assistants_only_for_supported_families(self):
        examples = [
            ("GeForce RTX test", r"PCI\VEN_10DE&DEV_0001", "nvidia.com"),
            ("Radeon RX test", r"PCI\VEN_1002&DEV_0001", "amd.com"),
            ("Intel Graphics test", r"PCI\VEN_8086&DEV_0001", "intel.com"),
        ]
        for name, identifier, expected_domain in examples:
            with self.subTest(name=name):
                item, = official_device_sources([device(name, identifier)])
                self.assertIn(expected_domain, item.assisted_check_url)
        for name, identifier in [
            ("NVIDIA Quadro enterprise", r"PCI\VEN_10DE&DEV_0002"),
            ("AMD HD Audio device", r"PCI\VEN_1002&DEV_0002"),
            ("Realtek Audio", r"PCI\VEN_10EC&DEV_0002"),
        ]:
            with self.subTest(name=name):
                item, = official_device_sources([device(name, identifier)])
                self.assertEqual(item.assisted_check_url, "")

    def test_wua_download_action_requires_single_matching_new_device(self):
        guid = "12345678-1234-4234-8234-123456789012"
        d = device("Intel Adapter", r"PCI\\VEN_8086&DEV_1234", "31.0.0.1")
        row = {"Title": "Intel - Net - 32.0.0.1", "Provider": "Intel",
               "HardwareID": d["DeviceID"], "UpdateID": guid,
               "Revision": 3, "IsBeta": False}
        self.assertEqual(len(_tokens_for_offers([d], [row])), 1)
        self.assertEqual(_tokens_for_offers([], [row]), {})
        self.assertEqual(_tokens_for_offers([d, d], [row]), {})
        older = dict(row, Title="Intel - Net - 30.0.0.1")
        self.assertEqual(_tokens_for_offers([d], [older]), {})
        same = dict(row, Title="Intel - Net - 31.0.0.1")
        self.assertEqual(_tokens_for_offers([d], [same]), {})
        # A generic compatibility ID can match multiple devices: fail closed.
        d2 = device("Second Adapter", d["DeviceID"], "31.0.0.1")
        self.assertEqual(_tokens_for_offers([d, d2], [row]), {})

    @patch("smartcleaner.driver_updates.powershell_rows")
    def test_evidence_from_wua_and_inventory(self, query):
        identifier = r"PCI\VEN_8086&DEV_1234"
        query.side_effect = [
            [{"ResultCode": 2, "Version": "test"},
             {"Title": "Intel - Net - 32.0.0.2", "Provider": "Intel",
              "HardwareID": identifier, "UpdateID": "12345678-1234-4234-8234-123456789012",
              "Revision": 3, "IsBeta": False}],
            [device("Intel Wi-Fi Test", identifier)],
            [{"Manufacturer": "Dell Inc.", "Model": "Laptop Model"}],
        ]
        scan = check_driver_updates()
        self.assertFalse(scan.partial)
        self.assertEqual(len(scan.assessments), 1)
        self.assertEqual(scan.assessments[0].offered, "32.0.0.2")
        self.assertEqual(scan.assessments[0].status, "WUA_NEWER")


class AssistantGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_shows_status_and_opens_only_official_helper(self):
        from PySide6.QtWidgets import QMessageBox, QPushButton, QTableWidget
        from smartcleaner import gui
        d = device("NVIDIA GeForce Test", r"PCI\VEN_10DE&DEV_1234")
        src = official_device_sources([d])
        rows = build_assessments([d], [])
        result = DriverSearch([], datetime.now().astimezone(), False, {}, None, src, rows)
        with tempfile.TemporaryDirectory() as tmp:
            window = gui.SmartCleanerMainWindow(Path(tmp))
            page = window.drivers_page
            table = page.findChild(QTableWidget, "device_driver_sources")
            buttons = {button.text(): button for button in page.findChildren(QPushButton)}
            with patch.object(gui, "check_driver_updates", return_value=result), \
                    patch.object(gui.DriverManager, "get_installed_drivers", return_value=[]):
                buttons["Проверить обновления"].click()
                deadline = time.monotonic() + 10
                while window.jobs and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertFalse(window.jobs)
            self.assertEqual(table.rowCount(), 1)
            self.assertEqual(table.item(0, 2).text(), "—")
            self.assertIn("инструменте", table.item(0, 3).text())
            table.selectRow(0)
            self.app.processEvents()
            btn = buttons["Проверить через инструмент производителя"]
            self.assertTrue(btn.isEnabled())
            with patch.object(QMessageBox, "information"), \
                    patch.object(gui.QDesktopServices, "openUrl", return_value=True) as opened:
                btn.click()
            self.assertEqual(opened.call_args.args[0].toString(), src[0].assisted_check_url)
            window.close()
