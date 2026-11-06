#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Enhanced Browser Cache Cleaner (Phase 5)
Safe cache cleaning for Chrome, Edge, Firefox, Brave, Opera, Vivaldi.
Preserves passwords, cookies, sessions, bookmarks, history, autofill.
"""

import os
import platform
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass

from smartcleaner.file_move import identity
from smartcleaner.protection import ProtectionEngine, checked_path, contains, inspect_path
from smartcleaner.quarantine import Quarantine


@dataclass
class BrowserProfile:
    name: str
    path: str
    browser: str
    cache_size: int = 0
    cache_files: List[str] = None
    selected: bool = True

    def __post_init__(self):
        if self.cache_files is None:
            self.cache_files = []


class BrowserCacheCleaner:
    """Safe browser cache cleaner that preserves user data."""

    # Cache subdirectories that are SAFE to clean
    SAFE_CACHE_SUBDIRS = [
        "Cache", "Code Cache", "GPUCache", "Media Cache",
        "Application Cache", "CachedData", "ShaderCache",
        "GrShaderCache", "OptimizationCache",
    ]

    # Protected subdirectories that must NEVER be cleaned
    PROTECTED_SUBDIRS = [
        "Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 5",
        "Login Data", "Cookies", "Web Data", "History", "Bookmarks",
        "Autofill", "Sessions", "Local Storage", "IndexedDB",
        "Service Worker", "CacheStorage", "Passwords",
    ]

    BROWSER_PATHS = {
        "chrome": {
            "windows": "%LOCALAPPDATA%\\Google\\Chrome\\User Data",
            "linux": "~/.config/google-chrome",
        },
        "edge": {
            "windows": "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data",
            "linux": "~/.config/microsoft-edge",
        },
        "firefox": {
            "windows": "%APPDATA%\\Mozilla\\Firefox\\Profiles",
            "linux": "~/.mozilla/firefox",
        },
        "brave": {
            "windows": "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data",
            "linux": "~/.config/BraveSoftware/Brave-Browser",
        },
        "opera": {
            "windows": "%APPDATA%\\Opera Software\\Opera Stable",
            "linux": "~/.config/opera",
        },
        "vivaldi": {
            "windows": "%LOCALAPPDATA%\\Vivaldi\\User Data",
            "linux": "~/.config/vivaldi",
        },
    }

    def __init__(self, logger=None, config_manager=None):
        self.quarantine = Quarantine(logger, config_manager)
        self.logger = self.quarantine.logger

    def _browser_root(self, browser):
        system = {"Linux": "linux", "Windows": "windows"}.get(platform.system())
        template = self.BROWSER_PATHS.get(browser, {}).get(system)
        if not template:
            raise ValueError("Unknown browser location")
        return checked_path(os.path.expandvars(os.path.expanduser(template)))

    def detect_browsers(self) -> List[BrowserProfile]:
        profiles = []
        for browser_name in self.BROWSER_PATHS:
            try:
                root = self._browser_root(browser_name)
                inspect_path(root)
            except (OSError, ValueError):
                continue
            expanded = str(root)

            if browser_name == "firefox":
                profiles.extend(self._detect_firefox_profiles(expanded, browser_name))
            else:
                profiles.extend(self._detect_chromium_profiles(expanded, browser_name))

        return profiles

    def _detect_chromium_profiles(self, base_path: str, browser: str) -> List[BrowserProfile]:
        profiles = []
        try:
            entries = os.listdir(base_path)
        except Exception:
            return profiles

        for entry in entries:
            profile_path = os.path.join(base_path, entry)
            if not os.path.isdir(profile_path):
                continue
            if not entry.startswith("Profile") and entry != "Default":
                continue

            profile_name = entry if entry != "Default" else "Default Profile"
            cache_size, cache_files = self._calculate_cache_size(profile_path)

            profiles.append(BrowserProfile(
                name=profile_name, path=profile_path, browser=browser,
                cache_size=cache_size, cache_files=cache_files, selected=True
            ))

        return profiles

    def _detect_firefox_profiles(self, base_path: str, browser: str) -> List[BrowserProfile]:
        profiles = []
        ini_path = os.path.join(base_path, "profiles.ini")
        if os.path.exists(ini_path):
            try:
                with open(ini_path, 'r') as f:
                    content = f.read()
                for line in content.split('\n'):
                    if line.startswith('Path='):
                        rel_path = line.split('=', 1)[1].strip()
                        full_path = os.path.join(base_path, rel_path)
                        if (not Path(rel_path).is_absolute() and ".." not in Path(rel_path).parts
                                and os.path.isdir(full_path)):
                            cache_size, cache_files = self._calculate_cache_size(full_path)
                            profiles.append(BrowserProfile(
                                name=os.path.basename(rel_path), path=full_path,
                                browser=browser, cache_size=cache_size,
                                cache_files=cache_files, selected=True
                            ))
            except Exception:
                pass
        else:
            try:
                for entry in os.listdir(base_path):
                    profile_path = os.path.join(base_path, entry)
                    if os.path.isdir(profile_path) and entry.endswith('.default-release'):
                        cache_size, cache_files = self._calculate_cache_size(profile_path)
                        profiles.append(BrowserProfile(
                            name=entry, path=profile_path, browser=browser,
                            cache_size=cache_size, cache_files=cache_files, selected=True
                        ))
            except Exception:
                pass

        return profiles

    def _calculate_cache_size(self, profile_path: str) -> Tuple[int, List[str]]:
        total_size = 0
        cache_files = []

        for subdir in self.SAFE_CACHE_SUBDIRS:
            cache_dir = os.path.join(profile_path, subdir)
            try:
                inspect_path(Path(cache_dir))
                for dirpath, dirnames, filenames in os.walk(cache_dir):
                    dirnames[:] = [name for name in dirnames
                                   if self._plain_cache_dir(Path(dirpath) / name)]
                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)
                        try:
                            size = os.path.getsize(full_path)
                            total_size += size
                            cache_files.append(full_path)
                        except Exception:
                            continue
            except Exception:
                continue

        return total_size, cache_files

    def _plain_cache_dir(self, directory):
        try:
            inspect_path(directory)
            return directory.name not in self.PROTECTED_SUBDIRS
        except (OSError, ValueError):
            return False

    def validate_candidate(self, profile, file_path):
        root = self._browser_root(profile.browser)
        profile_path = checked_path(profile.path)
        if not contains(root, profile_path) or profile_path == root:
            raise ValueError("Profile outside known browser location")
        exclusions = self.quarantine.exclusions()
        path, info = ProtectionEngine.validate_file(file_path, exclusions)
        for name in self.SAFE_CACHE_SUBDIRS:
            cache = profile_path / name
            if contains(cache, path) and path != cache:
                parts = path.relative_to(cache).parts
                if not any(part.casefold() in self.PROTECTED_CACHE_NAMES for part in parts):
                    return path, info
        raise ValueError("Path outside eligible browser cache")

    PROTECTED_CACHE_NAMES = {name.casefold() for name in PROTECTED_SUBDIRS}

    def clean_profile_cache(self, profile: BrowserProfile, dry_run: bool = True) -> Dict:
        result = {
            "profile": profile.name, "browser": profile.browser,
            "files_found": len(profile.cache_files), "size_bytes": profile.cache_size,
            "files_deleted": 0, "files_moved": 0, "size_freed": 0,
            "eligible_files": 0, "eligible_bytes": 0, "errors": [], "skipped": [],
        }
        for file_path in dict.fromkeys(profile.cache_files):
            try:
                path, info = self.validate_candidate(profile, file_path)
            except (OSError, ValueError, TypeError) as exc:
                result["skipped"].append({"path": file_path, "reason": str(exc)})
                continue
            result["eligible_files"] += 1
            result["eligible_bytes"] += info.st_size
            if not dry_run:
                ok, message = self.quarantine.delete_item(path, expected=identity(info))
                if ok:
                    result["files_moved"] += 1
                else:
                    result["errors"].append({"path": file_path, "error": message})
        return result

    def clean_selected_profiles(self, profiles: List[BrowserProfile], dry_run: bool = True) -> List[Dict]:
        results = []
        for profile in profiles:
            if profile.selected:
                result = self.clean_profile_cache(profile, dry_run=dry_run)
                results.append(result)
        return results


if __name__ == "__main__":
    cleaner = BrowserCacheCleaner()
    profiles = cleaner.detect_browsers()
    print(f"Detected {len(profiles)} browser profiles:")
    for p in profiles:
        print(f"  {p.browser} - {p.name}: {p.cache_size / 1024:.2f} KB cache")
    print("Phase 5 Enhanced Browser Cache Module: OK")
