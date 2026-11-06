"""Official driver source regression tests. No external downloads."""
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from smartcleaner.driver_sources import (
    DeviceDriverSource, identify_manufacturer, is_trusted_support_url,
    official_device_sources,
)
from smartcleaner.driver_updates import DriverSearch, check_driver_updates


def device(name, ident, version="1.0", provider=""):
    return {"Name": name, "DeviceID": ident, "Version": version,
            "Identifiers": [ident], "Provider": provider}


class SourceTests(unittest.TestCase):
    def test_pci_vendor_ids_and_fallback_provider(self):
        expectations = (
            (r"PCI\VEN_10DE&DEV_2204", "NVIDIA"),
            (r"PCI\VEN_1002&DEV_73BF", "AMD Radeon / AMD"),
            (r"PCI\VEN_1022&DEV_1483", "AMD Radeon / AMD"),
            (r"PCI\VEN_8086&DEV_1234", "Intel"),
            (r"PCI\VEN_10EC&DEV_8168", "Realtek"),
            (r"PCI\VEN_14E4&DEV_4321", "Broadcom"),
            (r"PCI\VEN_168C&DEV_003E", "Qualcomm"),
            (r"PCI\VEN_14C3&DEV_1234", "MediaTek"),
            (r"PCI\VEN_1102&DEV_0007", "Creative"),
        )
        for hardware_id, manufacturer in expectations:
            with self.subTest(hardware_id=hardware_id):
                self.assertEqual(identify_manufacturer(device("Device", hardware_id)),
                                 manufacturer)
        self.assertEqual(identify_manufacturer(device("Audio", "UNKNOWN", provider="Realtek Semiconductor Corp.")), "Realtek")
        self.assertIsNone(identify_manufacturer(device("NVIDIA fake name", "UNKNOWN")))

    def test_usb_and_id_takes_precedence_over_provider(self):
        self.assertEqual(identify_manufacturer(device("Wi-Fi", r"USB\VID_0BDA&PID_1234")), "Realtek")
        self.assertEqual(identify_manufacturer(device("Unknown", r"PCI\VEN_8086&DEV_1234",
                                                       provider="NVIDIA Corporation")), "Intel")

    def test_fixed_official_https_hosts_and_lookalikes(self):
        safe = [
            "https://www.nvidia.com/en-us/drivers/",
            "https://www.amd.com/en/support.html",
            "https://www.intel.com/content/www/us/en/download-center/home.html",
            "https://www.realtek.com/download/list",
        ]
        for url in safe:
            self.assertTrue(is_trusted_support_url(url), url)
        unsafe = [
            "http://www.nvidia.com/en-us/drivers/",
            "https://www.nvidia.com.evil.test/drivers",
            "https://www.nvidia.com@evil.test/drivers",
            "https://evil.test/?u=www.realtek.com",
            "file:///C:/danger.exe",
            "https://www.nvidia.com:444/drivers",
        ]
        for url in unsafe:
            self.assertFalse(is_trusted_support_url(url), url)

    def test_all_devices_included_without_claiming_new_driver(self):
        from smartcleaner.driver_updates import OEMSupport
        d = [device("RTX", r"PCI\VEN_10DE&DEV_1234"),
             device("Audio", r"PCI\VEN_10EC&DEV_0001"),
             device("Mystery", r"PCI\VEN_FFFF&DEV_0000")]
        sources = official_device_sources(d, OEMSupport(
            "Dell", "Laptop", "https://www.dell.com/support/home"))
        self.assertEqual(len(sources), 3)
        self.assertTrue(all(isinstance(s, DeviceDriverSource) for s in sources))
        unknown = next(s for s in sources if s.device == "Mystery")
        self.assertEqual(unknown.manufacturer, "OEM: Dell")
        self.assertEqual(unknown.url, "https://www.dell.com/support/home")
        realtek = next(s for s in sources if s.device == "Audio")
        self.assertIn("предпочтителен", realtek.guidance)
        self.assertEqual(official_device_sources(d + d), sources)

    @patch("smartcleaner.driver_updates.powershell_rows")
    def test_scan_enumerates_devices_even_without_windows_updates(self, command):
        command.side_effect = [
            [{"ResultCode": 2}],
            [device("RTX", r"PCI\VEN_10DE&DEV_1234")],
            [{"Manufacturer": "Dell Inc.", "Model": "Model"}],
        ]
        scan = check_driver_updates()
        self.assertEqual(scan.offers, [])
        self.assertEqual(len(scan.sources), 1)
        self.assertEqual(scan.sources[0].manufacturer, "NVIDIA")
        self.assertEqual(command.call_count, 3)


class SourceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_gui_selection_only_opens_allowlisted_source(self):
        from PySide6.QtWidgets import QPushButton, QTableWidget
        from smartcleaner import gui
        from smartcleaner.driver_updates import DriverSearch
        sources = [
            DeviceDriverSource("GPU", "1.0", "NVIDIA", r"PCI\VEN_10DE",
                               "https://www.nvidia.com/en-us/drivers/", "Manual verification"),
            DeviceDriverSource("Unknown", "—", "Unknown", "Unknown",
                               "https://evil.example/installer.exe", "Not trustworthy"),
        ]
        result = DriverSearch([], datetime.now().astimezone(), False, {}, None, sources)
        with tempfile.TemporaryDirectory() as tmp:
            win = gui.SmartCleanerMainWindow(Path(tmp))
            page = win.drivers_page
            controls = {btn.text(): btn for btn in page.findChildren(QPushButton)}
            table = page.findChild(QTableWidget, "device_driver_sources")
            self.assertIsNotNone(table)
            button = controls["Официальный сайт выбранного устройства"]
            self.assertFalse(button.isEnabled())
            with patch.object(gui, "check_driver_updates", return_value=result), \
                    patch.object(gui.DriverManager, "get_installed_drivers", return_value=[]):
                controls["Проверить обновления"].click()
                deadline = time.monotonic() + 8
                while win.jobs and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
            self.assertFalse(win.jobs)
            self.assertEqual(table.rowCount(), 2)
            table.selectRow(0)
            self.app.processEvents()
            self.assertTrue(button.isEnabled())
            with patch.object(gui.QDesktopServices, "openUrl", return_value=True) as open_url:
                button.click()
            self.assertEqual(open_url.call_args.args[0].toString(), sources[0].url)
            table.selectRow(1)
            self.app.processEvents()
            self.assertFalse(button.isEnabled())
            win.close()
