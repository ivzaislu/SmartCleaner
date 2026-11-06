"""All WUA actions mocked: no download or installation during tests."""
import base64
import json
import re
import unittest
from unittest.mock import patch

from smartcleaner.driver_actions import (
    DriverActionResult, DriverToken, download_driver, install_driver,
)
from smartcleaner.driver_updates import (
    DriverOffer, OEMSupport, _tokens_for_offers, check_driver_updates, oem_support,
)

GUID = "12345678-1234-4234-8234-123456789012"
OFFER = DriverOffer("Test device", "1.0", "2.0", "2026-01-01",
                    "Test - MEDIA - 2.0", "Trusted OEM", r"PCI\VEN_1234")
TOKEN = DriverToken(GUID, 7)


class DriverActionTests(unittest.TestCase):
    def test_download_only_calls_wua_and_uses_encoded_metadata(self):
        with patch("smartcleaner.driver_actions._is_windows", return_value=True), \
                patch("smartcleaner.driver_actions.powershell_rows", return_value=[
                    {"State": "DOWNLOADED", "RebootRequired": False,
                     "Message": "Downloaded by Windows Update"}]) as query:
            result = download_driver(OFFER, TOKEN)
        self.assertEqual(result.state, "DOWNLOADED")
        script = query.call_args.args[0]
        self.assertIn("Microsoft.Update.Session", script)
        self.assertIn("CreateUpdateDownloader", script)
        self.assertNotIn("CreateUpdateInstaller", script)
        self.assertNotIn(OFFER.title, script)
        match = re.search(r"FromBase64String\('([^']+)'\)", script)
        payload = json.loads(base64.b64decode(match.group(1)))
        self.assertEqual((payload["update_id"], payload["revision"]), (GUID, 7))
        self.assertEqual(payload["hardware_id"], OFFER.hardware_id)

    def test_install_requires_separate_confirmation(self):
        with self.assertRaises(PermissionError):
            install_driver(OFFER, TOKEN)
        with patch("smartcleaner.driver_actions._is_windows", return_value=True), \
                patch("smartcleaner.driver_actions.powershell_rows", return_value=[
                    {"State": "INSTALLED", "RebootRequired": True,
                     "Message": "Installed by Windows Update"}]) as query:
            result = install_driver(OFFER, TOKEN, confirmed=True)
        self.assertEqual(result, DriverActionResult("INSTALLED", True,
                                                   "Installed by Windows Update"))
        self.assertIn("CreateUpdateInstaller", query.call_args.args[0])
        self.assertIn("IsDownloaded", query.call_args.args[0])

    def test_reject_injection_invalid_tokens_and_wrong_result(self):
        with patch("smartcleaner.driver_actions._is_windows", return_value=True), \
                patch("smartcleaner.driver_actions.powershell_rows") as query:
            with self.assertRaises(ValueError):
                download_driver(OFFER, DriverToken("';exit 0;#", 1))
            with self.assertRaises(ValueError):
                download_driver(OFFER, DriverToken(GUID, -1))
            with self.assertRaises(ValueError):
                download_driver(OFFER, (GUID, 7))
            query.assert_not_called()
        with patch("smartcleaner.driver_actions._is_windows", return_value=True), \
                patch("smartcleaner.driver_actions.powershell_rows",
                      return_value=[{"State": "DOWNLOADED", "RebootRequired": "false"}]):
            with self.assertRaises(OSError):
                download_driver(OFFER, TOKEN)

    def test_non_windows_fails_closed(self):
        with patch("smartcleaner.driver_actions._is_windows", return_value=False):
            with self.assertRaises(OSError):
                download_driver(OFFER, TOKEN)


class TrustedSourceTests(unittest.TestCase):
    def test_allowlisted_oem_portals_are_not_download_urls(self):
        for manufacturer, label in [("Dell Inc.", "Dell"), ("HP", "HP"),
                                    ("LENOVO", "Lenovo"), ("ASUSTeK COMPUTER INC.", "ASUS")]:
            with self.subTest(manufacturer=manufacturer):
                result = oem_support(manufacturer, "Example Model")
                self.assertIsInstance(result, OEMSupport)
                self.assertEqual(result.manufacturer, label)
                self.assertTrue(result.url.startswith("https://"))
        self.assertIsNone(oem_support("Totally Unknown OEM", "Example"))
        self.assertIsNone(oem_support("Dell malicious", ""))

    def test_update_tokens_only_for_identified_non_beta_wua_offers(self):
        devices = [{"Name": "Audio", "Version": "1.0",
                    "Identifiers": [r"PCI\VEN_1234"]}]
        row = {"Title": OFFER.title, "Provider": OFFER.provider,
               "HardwareID": OFFER.hardware_id, "Date": OFFER.date,
               "UpdateID": GUID, "Revision": 7, "IsBeta": False}
        tokens = _tokens_for_offers(devices, [row])
        self.assertEqual(list(tokens.values()), [TOKEN])
        self.assertEqual(_tokens_for_offers(devices, [dict(row, IsBeta=True)]), {})
        self.assertEqual(_tokens_for_offers(devices, [dict(row, UpdateID="bad")]), {})
        self.assertEqual(_tokens_for_offers(devices, [
            row, dict(row, UpdateID="87654321-1234-4234-8234-123456789012")]), {})

    def test_scan_preserves_tokens_and_oem_on_mocked_windows(self):
        updates = [{"ResultCode": 2}, {"Title": OFFER.title, "Provider": OFFER.provider,
                   "HardwareID": OFFER.hardware_id, "UpdateID": GUID,
                   "Revision": 7, "IsBeta": False}]
        devices = [{"Name": "Test device", "Version": "1.0",
                    "Identifiers": [OFFER.hardware_id]}]
        with patch("smartcleaner.driver_updates.powershell_rows", side_effect=[
                updates, devices, [{"Manufacturer": "Dell Inc.", "Model": "Test Model"}]]):
            scan = check_driver_updates()
        self.assertEqual(len(scan.offers), 1)
        self.assertEqual(scan.tokens[scan.offers[0]], TOKEN)
        self.assertEqual(scan.oem.manufacturer, "Dell")
        self.assertFalse(scan.partial)
