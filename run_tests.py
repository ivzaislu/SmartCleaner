#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Comprehensive Test Script
Runs all unit and integration tests, verifying core functionality.
"""

import unittest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests.test_smartcleaner import *
from smartcleaner.browser_cleaner import BrowserCacheCleaner
from smartcleaner.extensions import ApplicationAndGameCache, StartupManager, DriverManager


class TestBrowserAndExtensions(unittest.TestCase):
    """Test browser cache cleaning and system extensions."""

    def test_browser_detection(self):
        cleaner = BrowserCacheCleaner()
        profiles = cleaner.detect_browsers()
        self.assertIsInstance(profiles, list)

    def test_startup_manager(self):
        items = StartupManager.get_startup_items()
        self.assertIsInstance(items, list)

    def test_driver_manager(self):
        drivers = DriverManager.get_installed_drivers()
        self.assertIsInstance(drivers, list)


if __name__ == "__main__":
    print("=== STARTING SMARTCLEANER 2.0 FULL TEST SUITE ===")
    unittest.main()
