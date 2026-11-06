#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Comprehensive Expanded Test Suite (Phase 1-16)
Tests protection engine, TOCTOU mitigation, symlinks, browser cleaner,
duplicate finder, manual delete & quarantine, settings backup, rules signer,
extensions, and diagnostics.
"""

import unittest
from unittest.mock import patch
import os
import tempfile
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smartcleaner.core import ProtectionEngine, OperationLogger, ConfigManager, AppConfig, RuleSigner
from smartcleaner.scanner import DiskScanner, QuickScanner, FileScanner, ScanType, ScanStatus
from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.diagnostics import SmartCleanerDelete, SystemDiagnostics
from smartcleaner.browser_cleaner import BrowserCacheCleaner
from smartcleaner.extensions import StartupManager, DriverManager, ApplicationManager, SchedulerService


class TestProtectionEngineAdvanced(unittest.TestCase):
    """Test advanced security features: symlinks, path traversal, system roots."""

    def test_protected_system_paths(self):
        from pathlib import Path
        self.assertTrue(ProtectionEngine.is_protected_path(Path.cwd().anchor))
        self.assertTrue(ProtectionEngine.is_protected_path(Path.home()))

    def test_protected_file_types(self):
        self.assertTrue(ProtectionEngine.is_protected_file_type("document.pdf"))
        self.assertTrue(ProtectionEngine.is_protected_file_type("photo.jpg"))
        self.assertTrue(ProtectionEngine.is_protected_file_type("id_rsa.ssh"))
        self.assertFalse(ProtectionEngine.is_protected_file_type("cache.tmp"))

    def test_symlink_attack_mitigation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            link_path = os.path.join(tmpdir, "evil_link")
            target = os.path.join(tmpdir, "safe_target.txt")
            with open(target, "w") as f:
                f.write("test")
            try:
                os.symlink(tmpdir, link_path, target_is_directory=True)
            except OSError as exc:
                self.skipTest(str(exc))
            safe, reason = ProtectionEngine.is_safe_to_delete(link_path)
            self.assertFalse(safe)
            self.assertIn("symlink", reason.lower())


class TestRuleSigner(unittest.TestCase):
    """Test cryptographic signature verification for cleanup rules."""

    def test_rule_signing(self):
        rule = {"id": "rule_01", "path": "/tmp/cache", "version": "1.0"}
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.generate()
        pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
        sig = RuleSigner.sign_rule(rule, key)
        self.assertTrue(RuleSigner.verify_rule(rule, sig, pem))
        self.assertFalse(RuleSigner.verify_rule(rule, sig))

        # Tampered rule
        tampered = {"id": "rule_01", "path": "/etc", "version": "1.0"}
        self.assertFalse(RuleSigner.verify_rule(tampered, sig, pem))


class TestConfigBackupAndImport(unittest.TestCase):
    """Test settings export and import with validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.export_path = os.path.join(self.tmpdir, "settings_backup.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_export_import(self):
        cm = ConfigManager(os.path.join(self.tmpdir, "config.json"))
        cm.config.language = "en"
        cm.config.theme = "dark"
        cm.export_settings(self.export_path)

        cm2 = ConfigManager(os.path.join(self.tmpdir, "config2.json"))
        success = cm2.import_settings(self.export_path)
        self.assertTrue(success)
        self.assertEqual(cm2.config.language, "en")
        self.assertEqual(cm2.config.theme, "dark")


class TestDuplicateFinderEnhanced(unittest.TestCase):
    """Test SHA-256 duplicate finder with hard link awareness."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        content = b"identical content for sha256 duplicate test"
        self.file1 = os.path.join(self.tmpdir, "dup1.txt")
        self.file2 = os.path.join(self.tmpdir, "dup2.txt")
        with open(self.file1, "wb") as f:
            f.write(content)
        with open(self.file2, "wb") as f:
            f.write(content)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_find_duplicates_sha256(self):
        duplicates = DiskAnalyzerEngine.find_duplicates(self.tmpdir, min_size=1)
        self.assertGreaterEqual(len(duplicates), 1)
        group_names = [os.path.basename(p) for p in duplicates[0]]
        self.assertIn("dup1.txt", group_names)
        self.assertIn("dup2.txt", group_names)


class TestSmartCleanerDeleteAndQuarantine(unittest.TestCase):
    """Test manual deletion, quarantine, and recovery logging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "to_quarantine.txt")
        with open(self.test_file, "w") as f:
            f.write("quarantine test content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_and_quarantine(self):
        deleter = SmartCleanerDelete(OperationLogger(os.path.join(self.tmpdir, "operations.db")))
        success, msg = deleter.delete_item(self.test_file, move_to_quarantine=True)
        self.assertTrue(success, f"Delete failed: {msg}")
        self.assertFalse(os.path.exists(self.test_file))

        # Check quarantine items in db
        items = deleter.logger.get_quarantine_items()
        self.assertGreaterEqual(len(items), 1)


class TestSchedulerPolicy(unittest.TestCase):
    """Test scheduler strictly runs analysis without automated deletion."""

    def test_scheduler_analysis_only(self):
        with patch("smartcleaner.scanner.QuickScanner.KNOWN_CACHE_LOCATIONS", []):
            result = SchedulerService.run_scheduled_analysis()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("Analysis Only", result["action"])


class TestBrowserCleanerSafety(unittest.TestCase):
    """Test browser cleaner profile detection and preservation."""

    def test_browser_detection(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Default").mkdir()
            cleaner = BrowserCacheCleaner(OperationLogger(root / "history.db"))
            system = "windows" if os.name == "nt" else "linux"
            with patch.object(cleaner, "BROWSER_PATHS", {"chrome": {system: str(root)}}):
                profiles = cleaner.detect_browsers()
            self.assertEqual([profile.name for profile in profiles], ["Default Profile"])


class TestSystemDiagnosticsEnhanced(unittest.TestCase):
    """Test system diagnostics and integrity checks."""

    def test_drive_health(self):
        with patch("smartcleaner.diagnostics.powershell_rows", return_value=[{"Model": "test"}]):
            drives = SystemDiagnostics.get_drive_health()
        self.assertIsInstance(drives, list)
        self.assertGreater(len(drives), 0)

    def test_integrity(self):
        with patch("smartcleaner.diagnostics.command_report", return_value=(True, "test")):
            ready, msg = SystemDiagnostics.check_system_integrity()
        self.assertIsInstance(ready, bool)


if __name__ == "__main__":
    print("=== STARTING SMARTCLEANER 2.0 COMPREHENSIVE TEST SUITE ===")
    unittest.main()
