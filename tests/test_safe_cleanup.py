"""Regression checks that mutate only files created inside a temporary directory."""

import base64
import hashlib
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from smartcleaner.browser_cleaner import BrowserCacheCleaner, BrowserProfile
from smartcleaner.core import AppConfig, ConfigManager, OperationLogger
from smartcleaner.file_move import identity
from smartcleaner.protection import ProtectionEngine
from smartcleaner.quarantine import Quarantine
from smartcleaner.signer import AsymmetricRuleVerifier, rule_payload


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.logger = OperationLogger(self.root / "history.db")
        self.config = ConfigManager(self.root / "settings.json")
        self.quarantine = Quarantine(self.logger, self.config)

    def file(self, name, data=b"temporary test"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_exclusions_and_disabled_permanent_deletion(self):
        path = self.file("excluded/cache.tmp")
        self.config.save(AppConfig(excluded_paths=[str(path.parent)]))
        self.assertFalse(self.quarantine.delete_item(path)[0])
        self.assertFalse(self.quarantine.delete_item(path.parent)[0])
        self.assertFalse(self.quarantine.delete_item(path, move_to_quarantine=False)[0])
        self.assertTrue(path.is_file())
        sibling = self.file("excluded-sibling/cache.tmp")
        self.assertTrue(ProtectionEngine.is_safe_to_delete(sibling, [str(path.parent)])[0])

    def test_raw_traversal_and_hardlink(self):
        path = self.file("cache.tmp")
        self.assertFalse(self.quarantine.delete_item(self.root / "somewhere" / ".." / path.name)[0])
        os.link(path, self.root / "another.tmp")
        self.assertFalse(self.quarantine.delete_item(path)[0])
        self.assertTrue(path.is_file())

    def test_parent_symlink(self):
        path = self.file("target/cache.tmp")
        link = self.root / "alias"
        try:
            link.symlink_to(path.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        self.assertFalse(self.quarantine.delete_item(link / path.name)[0])
        self.assertTrue(path.is_file())

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_junction_parent_is_blocked(self):
        path = self.file("target/cache.tmp")
        junction = self.root / "junction"
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(path.parent)],
                       check=True, capture_output=True)
        self.assertFalse(self.quarantine.delete_item(junction / path.name)[0])
        self.assertTrue(path.is_file())

    def test_changed_since_preview(self):
        path = self.file("cache.tmp")
        snapshot = identity(path.stat())
        path.write_bytes(b"replacement, different length")
        self.assertFalse(self.quarantine.delete_item(path, expected=snapshot)[0])
        self.assertEqual(path.read_bytes(), b"replacement, different length")

    def test_logging_failure_before_move_preserves_source(self):
        path = self.file("cache.tmp")
        with patch.object(self.logger, "record_quarantine", side_effect=sqlite3.OperationalError):
            self.assertFalse(self.quarantine.delete_item(path)[0])
        self.assertTrue(path.is_file())

    def test_restore_never_overwrites_and_checks_integrity(self):
        path = self.file("cache.tmp", b"original")
        ok, message = self.quarantine.delete_item(path)
        self.assertTrue(ok, message)
        row = self.logger.get_quarantine_items()[0]
        path.write_bytes(b"new file")
        self.assertFalse(self.quarantine.restore_item(row["id"])[0])
        self.assertEqual(path.read_bytes(), b"new file")
        path.unlink()
        backup = Path(row["quarantine_path"])
        backup.write_bytes(b"tampered")
        self.assertFalse(self.quarantine.restore_item(row["id"])[0])
        self.assertFalse(path.exists())
        backup.write_bytes(b"original")
        self.assertTrue(self.quarantine.restore_item(row["id"])[0])
        self.assertEqual(path.read_bytes(), b"original")
        self.assertFalse(self.quarantine.restore_item(row["id"])[0])

    def test_same_filename_separate_items(self):
        files = [self.file(f"{index}/cache.tmp") for index in range(2)]
        for path in files:
            self.assertTrue(self.quarantine.delete_item(path)[0])
        rows = self.logger.get_quarantine_items()
        self.assertEqual(len({item["quarantine_path"] for item in rows}), 2)

    def test_browser_preview_and_exclusions(self):
        profile_dir = self.root / "browser" / "Default"
        valid = self.file("browser/Default/Cache/entry.tmp")
        outside = self.file("browser/Default/History")
        profile = BrowserProfile("Default", str(profile_dir), "chrome",
                                 cache_files=[str(valid), str(outside)])
        cleaner = BrowserCacheCleaner(self.logger, self.config)
        with patch.object(cleaner, "_browser_root", return_value=profile_dir.parent):
            preview = cleaner.clean_profile_cache(profile)
            self.assertEqual(preview["eligible_files"], 1)
            self.assertTrue(valid.exists())
            self.config.save(AppConfig(browser_profiles_excluded=[str(profile_dir)]))
            self.assertEqual(cleaner.clean_profile_cache(profile, dry_run=False)["files_moved"], 0)
            self.config.save(AppConfig())
            self.assertEqual(cleaner.clean_profile_cache(profile, dry_run=False)["files_moved"], 1)
        self.assertFalse(valid.exists())
        self.assertTrue(outside.exists())


class SignatureTests(unittest.TestCase):
    def test_rsa_and_reject_legacy_forgery(self):
        rule = {"id": "test"}
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
        signature = key.sign(rule_payload(rule), padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        verify = AsymmetricRuleVerifier.verify_rule_signature
        self.assertTrue(verify(rule, base64.b64encode(signature), pem)[0])
        self.assertFalse(verify({"id": "modified"}, base64.b64encode(signature), pem)[0])
        digest = hashlib.sha256(rule_payload(rule)).digest()
        fake = hashlib.sha256(digest).digest()[:16] + b"\0" * 16
        self.assertFalse(verify(rule, base64.b64encode(fake), pem)[0])
        self.assertFalse(verify(rule, base64.b64encode(signature), b"invalid key")[0])
