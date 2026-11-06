import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton, QTableWidget

from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.app_cache import application_caches
from smartcleaner.diagnostics import SystemDiagnostics
from smartcleaner.gui import SmartCleanerMainWindow
from smartcleaner.windows_tools import filesystem_report


class InventoryTests(unittest.TestCase):
    def test_cache_scan_uses_explicit_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / "discord" / "Cache"
            cache.mkdir(parents=True)
            sample = cache / "entry"
            sample.write_bytes(b"cache")
            (root / "discord" / "settings.json").write_text("{}")
            with patch.dict(os.environ, {"APPDATA": folder, "LOCALAPPDATA": folder}):
                self.assertEqual(list(application_caches()), [("Discord", str(sample), 5)])
            self.assertTrue(sample.exists())

    def test_size_filter_and_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sub").mkdir()
            target = root / "sub" / "data.zip"
            target.write_bytes(b"x" * 100)
            (root / "data.txt").write_bytes(b"y" * 50)
            self.assertEqual(DiskAnalyzerEngine.generate_treemap(root)["size"], 150)
            self.assertEqual(DiskAnalyzerEngine.find_large_files(root, 0, extension="ZIP"),
                             [(str(target), 100)])
            self.assertEqual(DiskAnalyzerEngine.find_large_files(root, 0, min_age_days=7), [])

    @unittest.skipUnless(os.name == "nt", "Windows")
    def test_diagnostics_use_read_only_flags(self):
        with patch("smartcleaner.diagnostics.command_report", return_value=(True, "test")) as run:
            SystemDiagnostics.check_system_integrity()
            run.assert_called_once_with("sfc.exe", ["/verifyonly"], 1800)
        with patch("smartcleaner.windows_tools.ctypes.windll.kernel32.GetDriveTypeW", return_value=3), \
                patch("smartcleaner.windows_tools.command_report", return_value=(True, "test")) as run:
            filesystem_report("C:\\")
            run.assert_called_once_with("chkdsk.exe", ["C:"], 900)
        with self.assertRaises(ValueError):
            filesystem_report("C: /f")


class PageTests(unittest.TestCase):
    def test_background_disk_scan_renders_results(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "input").mkdir()
            (root / "input" / "example.txt").write_text("test")
            window = SmartCleanerMainWindow(root)
            page = window.disk_page
            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(root / "input")):
                page.findChild(QPushButton).click()
            deadline = time.monotonic() + 5
            while window.jobs and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            table = page.findChild(QTableWidget)
            self.assertFalse(window.jobs)
            self.assertEqual(table.rowCount(), 1)
            self.assertEqual(table.item(0, 0).text(), "example.txt")
            window.close()
