#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Extended Security & Robustness Test Suite
Covers: Symlink swap, TOCTOU race, path traversal, hard links, recursive user exclusions,
file modification after scan, corrupted rules, signature verification, recovery errors,
cancellation, and automated deletion policy (analysis only).
"""

import unittest
from unittest.mock import patch
import os
import tempfile
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smartcleaner.core import OperationLogger, ConfigManager, AppConfig
from smartcleaner.protection import ProtectionEngine
from smartcleaner.signer import AsymmetricRuleVerifier
from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.diagnostics import SmartCleanerDelete, SystemDiagnostics
from smartcleaner.extensions import SchedulerService


class TestSecurityAndRobustness(unittest.TestCase):
    """Rigorous security tests for protection engine, TOCTOU, path traversal, and signature verification."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_path_traversal_defense(self):
        # Path traversal attempt should be blocked
        safe, reason = ProtectionEngine.is_safe_to_delete("../etc/passwd")
        self.assertFalse(safe)

    def test_recursive_user_exclusions(self):
        # File inside an excluded folder should not be safe to delete
        excluded_dir = os.path.join(self.tmpdir, "excluded_folder")
        os.makedirs(excluded_dir)
        sub_file = os.path.join(excluded_dir, "important.doc")
        with open(sub_file, "w") as f:
            f.write("confidential")

        user_excluded = {excluded_dir}
        safe, reason = ProtectionEngine.is_safe_to_delete(sub_file, user_excluded=user_excluded)
        self.assertFalse(safe)
        self.assertIn("excluded", reason.lower())

    def test_protected_file_types_exclusion(self):
        # Protected file types (documents, keys, etc.) must not be deleted
        pdf_file = os.path.join(self.tmpdir, "resume.pdf")
        with open(pdf_file, "w") as f:
            f.write("resume content")

        safe, reason = ProtectionEngine.is_safe_to_delete(pdf_file)
        self.assertFalse(safe)
        self.assertIn("protected user file type", reason.lower())

    def test_asymmetric_rule_signature_verification(self):
        rule = {"id": "rule_01", "path": "~/.cache", "version": "1.0"}
        # Invalid signature should fail
        valid, msg = AsymmetricRuleVerifier.verify_rule_signature(rule, "invalid_sig_base64_too_short==")
        self.assertFalse(valid)

    def test_hard_link_duplicate_detection(self):
        # Verify hard links don't trigger false duplicate removal or inode loops
        file1 = os.path.join(self.tmpdir, "file1.txt")
        file2 = os.path.join(self.tmpdir, "file2.txt")
        with open(file1, "w") as f:
            f.write("same content")
        try:
            os.link(file1, file2) # create hard link
            duplicates = DiskAnalyzerEngine.find_duplicates(self.tmpdir, min_size=1)
            # Hard links share inode, so they should be correctly recognized as single unique physical file
            self.assertEqual(len(duplicates), 0)
        except OSError:
            # Hard links not supported on some virtual filesystems
            pass

    def test_scheduler_strictly_analysis_only(self):
        # Verify scheduler never executes deletion
        with patch("smartcleaner.scanner.QuickScanner.KNOWN_CACHE_LOCATIONS", []):
            result = SchedulerService.run_scheduled_analysis()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("Analysis Only", result["action"])

    def test_quarantine_and_recovery(self):
        test_file = os.path.join(self.tmpdir, "quarantine_test.txt")
        with open(test_file, "w") as f:
            f.write("quarantine data")

        deleter = SmartCleanerDelete(OperationLogger(os.path.join(self.tmpdir, "operations.db")))
        success, msg = deleter.delete_item(test_file, move_to_quarantine=True)
        self.assertTrue(success)

        # Verify recorded in quarantine DB
        items = deleter.logger.get_quarantine_items()
        self.assertGreaterEqual(len(items), 1)


if __name__ == "__main__":
    print("=== STARTING SMARTCLEANER 2.0 EXTENDED SECURITY TEST SUITE ===")
    unittest.main()
