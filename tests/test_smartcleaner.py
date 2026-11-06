#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Automated Test Suite
Tests core modules: Protection Engine, Scanner, Analyzer, Diagnostics, Config, Logger
"""

import unittest
from unittest.mock import patch
import os
import tempfile
import shutil
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smartcleaner.core import ProtectionEngine, OperationLogger, ConfigManager, AppConfig
from smartcleaner.scanner import DiskScanner, QuickScanner, FileScanner, ScanType, ScanStatus
from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.diagnostics import SmartCleanerDelete, SystemDiagnostics


class TestProtectionEngine(unittest.TestCase):
    """Test Protection Engine safety checks."""

    def test_protected_system_path(self):
        from pathlib import Path
        root = Path.cwd().anchor
        protected = "Windows/System32" if os.name == "nt" else "etc/passwd"
        self.assertTrue(ProtectionEngine.is_protected_path(os.path.join(root, protected)))

    def test_safe_temp_path(self):
        # Create a temp file first
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as f:
            tmp_path = f.name
        try:
            safe, reason = ProtectionEngine.is_safe_to_delete(tmp_path)
            self.assertTrue(safe, f"Expected safe, got: {reason}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_protected_file_type(self):
        self.assertTrue(ProtectionEngine.is_protected_file_type("/home/user/document.pdf"))
        self.assertTrue(ProtectionEngine.is_protected_file_type("/home/user/photo.jpg"))
        self.assertFalse(ProtectionEngine.is_protected_file_type("/home/user/cache.tmp"))

    def test_symlink_protection(self):
        # Create a symlink to a protected path
        with tempfile.TemporaryDirectory() as tmpdir:
            link_path = os.path.join(tmpdir, "evil_link")
            # Create a dummy target so os.path.exists follows the link successfully
            target = os.path.join(tmpdir, "target_file")
            with open(target, "w") as f:
                f.write("dummy")
            try:
                os.symlink(target, link_path)
            except OSError as exc:
                self.skipTest(str(exc))
            safe, reason = ProtectionEngine.is_safe_to_delete(link_path)
            self.assertFalse(safe)
            self.assertIn("symlink", reason.lower())


class TestOperationLogger(unittest.TestCase):
    """Test SQLite operation logging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_history.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_log_and_retrieve(self):
        logger = OperationLogger(self.db_path)
        logger.log_operation("SCAN", "/tmp", 1024, "SUCCESS", "Test scan")
        history = logger.get_history(10)
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["operation_type"], "SCAN")
        self.assertEqual(history[0]["target_path"], "/tmp")


class TestConfigManager(unittest.TestCase):
    """Test configuration loading and saving."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "test_config.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_default_config(self):
        cm = ConfigManager(self.config_path)
        config = cm.load()
        self.assertEqual(config.language, "ru")
        self.assertEqual(config.theme, "light")

    def test_save_and_load(self):
        cm = ConfigManager(self.config_path)
        config = AppConfig(language="en", theme="dark")
        cm.save(config)
        loaded = cm.load()
        self.assertEqual(loaded.language, "en")
        self.assertEqual(loaded.theme, "dark")


class TestDiskScanner(unittest.TestCase):
    """Test disk detection."""

    def test_get_disks(self):
        disks = DiskScanner.get_disks()
        self.assertIsInstance(disks, list)
        self.assertGreater(len(disks), 0)
        for d in disks:
            self.assertIsNotNone(d.mountpoint)
            self.assertGreaterEqual(d.total, 0)


class TestQuickScanner(unittest.TestCase):
    """Test quick scan functionality."""

    def test_quick_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "cache.tmp"), "wb") as stream:
                stream.write(b"test")
            with patch.object(QuickScanner, "KNOWN_CACHE_LOCATIONS", [folder]):
                result = QuickScanner().scan()
        self.assertEqual(result.file_count, 1)
        self.assertIsInstance(result.file_count, int)
        self.assertIsInstance(result.total_size, int)
        self.assertIn(result.status, [ScanStatus.COMPLETED, ScanStatus.CANCELLED])


class TestDiskAnalyzer(unittest.TestCase):
    """Test duplicate finder and large file finder."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create duplicate files
        content = b"duplicate content for testing"
        with open(os.path.join(self.tmpdir, "file1.txt"), "wb") as f:
            f.write(content)
        with open(os.path.join(self.tmpdir, "file2.txt"), "wb") as f:
            f.write(content)
        # Create unique file
        with open(os.path.join(self.tmpdir, "unique.txt"), "wb") as f:
            f.write(b"unique content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_find_duplicates(self):
        duplicates = DiskAnalyzerEngine.find_duplicates(self.tmpdir, min_size=1)
        self.assertGreaterEqual(len(duplicates), 1)
        # Check that file1.txt and file2.txt are grouped together
        found_group = False
        for group in duplicates:
            group_names = [os.path.basename(p) for p in group]
            if "file1.txt" in group_names and "file2.txt" in group_names:
                found_group = True
        self.assertTrue(found_group, "Duplicate files not grouped correctly")

    def test_find_large_files(self):
        large = DiskAnalyzerEngine.find_large_files(self.tmpdir, min_size_mb=0, limit=10)
        self.assertGreaterEqual(len(large), 3)


class TestSmartCleanerDelete(unittest.TestCase):
    """Test manual deletion utility."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "to_delete.txt")
        with open(self.test_file, "w") as f:
            f.write("test content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_file(self):
        deleter = SmartCleanerDelete(OperationLogger(os.path.join(self.tmpdir, "operations.db")))
        success, message = deleter.delete_item(self.test_file)
        self.assertTrue(success, f"Delete failed: {message}")
        self.assertFalse(os.path.exists(self.test_file))

    def test_delete_protected_path(self):
        deleter = SmartCleanerDelete(OperationLogger(os.path.join(self.tmpdir, "operations.db")))
        success, message = deleter.delete_item(self.tmpdir)
        self.assertFalse(success)
        self.assertTrue(os.path.isfile(self.test_file))


class TestSystemDiagnostics(unittest.TestCase):
    """Test system diagnostics."""

    def test_get_drive_health(self):
        with patch("smartcleaner.diagnostics.powershell_rows", return_value=[{"Model": "test"}]):
            drives = SystemDiagnostics.get_drive_health()
        self.assertIsInstance(drives, list)

    def test_check_system_integrity(self):
        with patch("smartcleaner.diagnostics.command_report", return_value=(True, "test")):
            ready, message = SystemDiagnostics.check_system_integrity()
        self.assertIsInstance(ready, bool)
        self.assertIsInstance(message, str)


if __name__ == "__main__":
    unittest.main()
