#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Scanner Module
Disk detection, quick scan, deep scan, progress, cancellation
"""

import os
import sys
import stat
import hashlib
import platform
import shutil
import threading
import time
from pathlib import Path
from typing import List, Dict, Set, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum

from smartcleaner.core import ProtectionEngine, OperationLogger

class ScanType(Enum):
    QUICK = "quick"
    DEEP = "deep"

class ScanStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"

@dataclass
class DiskInfo:
    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    is_removable: bool = False
    is_system: bool = False

@dataclass
class FileEntry:
    path: str
    size: int
    modified: float
    is_symlink: bool = False
    is_directory: bool = False
    category: str = "other"
    safe_to_delete: bool = True
    hash: Optional[str] = None

@dataclass
class ScanResult:
    scan_type: ScanType
    disks_scanned: List[DiskInfo]
    files: List[FileEntry]
    total_size: int
    file_count: int
    directory_count: int
    errors: List[str]
    duration_seconds: float
    status: ScanStatus
    categories: Dict[str, int] = field(default_factory=dict)

class DiskScanner:
    """Detects disks and mount points."""

    @staticmethod
    def get_disks() -> List[DiskInfo]:
        """Get all available disks/mount points."""
        disks = []

        if platform.system() == "Windows":
            import string
            from ctypes import windll, wintypes
            drives = []
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1

            for drive in drives:
                try:
                    total, used, free = shutil.disk_usage(drive)
                    drive_type = windll.kernel32.GetDriveTypeW(drive)
                    # DRIVE_FIXED=3, DRIVE_REMOVABLE=2, DRIVE_CDROM=5, DRIVE_RAMDISK=6
                    is_removable = drive_type in (2,)
                    is_system = drive.lower() == "c:\\"
                    disks.append(DiskInfo(
                        device=drive,
                        mountpoint=drive,
                        fstype="NTFS",  # simplified
                        total=total, used=used, free=free,
                        is_removable=is_removable, is_system=is_system
                    ))
                except Exception:
                    continue
        else:
            # Linux - parse /proc/mounts and use shutil.disk_usage
            try:
                with open("/proc/mounts", "r") as f:
                    mounts = f.readlines()
            except Exception:
                mounts = []

            seen_mounts = set()
            for line in mounts:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device = parts[0]
                mountpoint = parts[1]
                fstype = parts[2]

                # Skip virtual filesystems
                if fstype in ("proc", "sysfs", "devpts", "tmpfs", "cgroup", "cgroup2",
                              "pstore", "bpf", "autofs", "rpc_pipefs", "fusectl",
                              "mqueue", "configfs", "squashfs", "overlay"):
                    continue

                # Skip duplicate mountpoints
                if mountpoint in seen_mounts:
                    continue
                seen_mounts.add(mountpoint)

                try:
                    total, used, free = shutil.disk_usage(mountpoint)
                    is_removable = mountpoint in ("/media", "/mnt") or mountpoint.startswith("/media/") or mountpoint.startswith("/mnt/")
                    is_system = mountpoint == "/"
                    disks.append(DiskInfo(
                        device=device, mountpoint=mountpoint, fstype=fstype,
                        total=total, used=used, free=free,
                        is_removable=is_removable, is_system=is_system
                    ))
                except Exception:
                    continue

        return disks

class FileScanner:
    """Recursive file enumeration with safety checks."""

    # Known safe cache directories by category
    CACHE_PATTERNS = {
        "browser_cache": ["cache", "cachedata", "gpu-cache", "code cache", "application cache"],
        "system_cache": [".cache", "tmp", "temp", "var/cache", "var/tmp"],
        "thumbnails": ["thumbnails", ".thumbnails"],
        "logs": ["logs", "log", ".log"],
        "crash_reports": ["crashreports", "crash_reports", "core"],
    }

    def __init__(self, cancel_event: threading.Event = None,
                 progress_callback: Callable[[int, str], None] = None):
        self.cancel_event = cancel_event or threading.Event()
        self.progress_callback = progress_callback
        self.errors: List[str] = []
        self.files: List[FileEntry] = []
        self.directory_count = 0

    def scan_directory(self, root_path: str, max_depth: int = None,
                       follow_symlinks: bool = False,
                       min_size: int = 0) -> ScanResult:
        """Scan a directory recursively."""
        start_time = time.time()
        self.files = []
        self.errors = []
        self.directory_count = 0

        root = Path(root_path).resolve()
        if not root.exists():
            return ScanResult(
                scan_type=ScanType.QUICK, disks_scanned=[], files=[],
                total_size=0, file_count=0, directory_count=0,
                errors=[f"Path does not exist: {root_path}"],
                duration_seconds=0, status=ScanStatus.ERROR
            )

        count = 0
        for dirpath, dirnames, filenames in os.walk(root, onerror=self._walk_error,
                                                     followlinks=follow_symlinks):
            if self.cancel_event.is_set():
                break

            self.directory_count += 1
            count += 1

            if self.progress_callback and count % 50 == 0:
                self.progress_callback(count, f"Scanning: {dirpath}")

            # Depth limit
            if max_depth is not None:
                depth = dirpath[len(str(root)):].count(os.sep)
                if depth >= max_depth:
                    dirnames.clear()
                    continue

            # Filter out system directories on Linux
            if platform.system() != "Windows":
                dirnames[:] = [d for d in dirnames if not self._is_system_dir(dirpath, d)]

            for filename in filenames:
                if self.cancel_event.is_set():
                    break

                full_path = os.path.join(dirpath, filename)
                try:
                    entry = self._create_file_entry(full_path)
                    if entry and entry.size >= min_size:
                        self.files.append(entry)
                except Exception as e:
                    self.errors.append(f"Error accessing {full_path}: {e}")

        duration = time.time() - start_time
        total_size = sum(f.size for f in self.files)
        file_count = len(self.files)

        # Categorize
        categories = {}
        for f in self.files:
            cat = f.category
            categories[cat] = categories.get(cat, 0) + f.size

        status = ScanStatus.CANCELLED if self.cancel_event.is_set() else ScanStatus.COMPLETED

        # Get disk info for the scanned path
        disks = DiskScanner.get_disks()
        relevant_disk = None
        for d in disks:
            if str(root).startswith(d.mountpoint):
                relevant_disk = d
                break

        return ScanResult(
            scan_type=ScanType.QUICK,
            disks_scanned=[relevant_disk] if relevant_disk else disks,
            files=self.files,
            total_size=total_size,
            file_count=file_count,
            directory_count=self.directory_count,
            errors=self.errors,
            duration_seconds=duration,
            status=status,
            categories=categories
        )

    def _walk_error(self, error):
        self.errors.append(f"Walk error: {error}")

    def _is_system_dir(self, dirpath: str, dirname: str) -> bool:
        """Check if directory is a system directory that should be skipped."""
        system_dirs = {"proc", "sys", "dev", "run", "var/lib/dpkg", "var/lib/apt",
                       "var/cache", "var/tmp", "etc", "bin", "sbin", "usr", "lib",
                       "lib64", "boot", "snap"}
        full = os.path.join(dirpath, dirname)
        if dirname in system_dirs:
            return True
        # Skip hidden system dirs at root level
        if dirpath == "/" and dirname.startswith("."):
            return True
        return False

    def _create_file_entry(self, path: str) -> Optional[FileEntry]:
        """Create a FileEntry for a given path."""
        try:
            if os.path.islink(path):
                target = os.path.realpath(path)
                # Don't follow symlinks to protected paths
                if ProtectionEngine.is_protected_path(target):
                    return None
                stat_info = os.lstat(path)
                size = stat_info.st_size
                is_symlink = True
            else:
                stat_info = os.stat(path)
                size = stat_info.st_size
                is_symlink = False

            if stat.S_ISDIR(stat_info.st_mode):
                return None  # Directories handled separately

            modified = stat_info.st_mtime
            category = self._categorize_file(path)
            safe = not ProtectionEngine.is_protected_path(path)

            return FileEntry(
                path=path, size=size, modified=modified,
                is_symlink=is_symlink, is_directory=False,
                category=category, safe_to_delete=safe
            )
        except (OSError, PermissionError, FileNotFoundError):
            return None

    def _categorize_file(self, path: str) -> str:
        """Categorize a file based on its path and name."""
        path_lower = path.lower()
        name = Path(path).name.lower()

        for category, patterns in self.CACHE_PATTERNS.items():
            for pattern in patterns:
                if pattern in path_lower or pattern in name:
                    return category

        # By extension
        ext = Path(path).suffix.lower()
        if ext in (".log", ".tmp", ".temp", ".cache", ".bak", ".old"):
            return "system_cache"
        if ext in (".crash", ".core", ".dump"):
            return "crash_reports"

        return "other"

class QuickScanner:
    """Quick scan of known safe cache locations."""

    KNOWN_CACHE_LOCATIONS = [
        # Linux
        "~/.cache",
        "~/.thumbnails",
        "~/.mozilla/firefox/*/Cache",
        "~/.config/google-chrome/*/Cache",
        "~/.config/microsoft-edge/*/Cache",
        # Windows
        "%TEMP%",
        "%LOCALAPPDATA%\\Temp",
        "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\*\\Cache",
        "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\*\\Cache",
    ]

    def __init__(self, cancel_event: threading.Event = None,
                 progress_callback: Callable[[int, str], None] = None):
        self.cancel_event = cancel_event or threading.Event()
        self.progress_callback = progress_callback

    def scan(self) -> ScanResult:
        """Perform quick scan of known cache locations."""
        start_time = time.time()
        all_files = []
        errors = []

        for location in self.KNOWN_CACHE_LOCATIONS:
            if self.cancel_event.is_set():
                break

            expanded = os.path.expandvars(os.path.expanduser(location))

            # Handle glob patterns
            if "*" in expanded:
                import glob
                matches = glob.glob(expanded)
            else:
                matches = [expanded] if os.path.exists(expanded) else []

            for match in matches:
                if self.cancel_event.is_set():
                    break
                if os.path.isdir(match):
                    try:
                        for dirpath, dirnames, filenames in os.walk(match, onerror=lambda e: errors.append(str(e))):
                            if self.cancel_event.is_set():
                                break
                            for filename in filenames:
                                full_path = os.path.join(dirpath, filename)
                                try:
                                    size = os.path.getsize(full_path)
                                    all_files.append(FileEntry(
                                        path=full_path, size=size,
                                        modified=os.path.getmtime(full_path),
                                        is_symlink=os.path.islink(full_path),
                                        category="browser_cache" if "cache" in full_path.lower() else "system_cache",
                                        safe_to_delete=True
                                    ))
                                except Exception:
                                    continue
                    except Exception as e:
                        errors.append(str(e))
                elif os.path.isfile(match):
                    try:
                        size = os.path.getsize(match)
                        all_files.append(FileEntry(
                            path=match, size=size,
                            modified=os.path.getmtime(match),
                            category="system_cache", safe_to_delete=True
                        ))
                    except Exception:
                        continue

        duration = time.time() - start_time
        total_size = sum(f.size for f in all_files)

        categories = {}
        for f in all_files:
            categories[f.category] = categories.get(f.category, 0) + f.size

        status = ScanStatus.CANCELLED if self.cancel_event.is_set() else ScanStatus.COMPLETED

        return ScanResult(
            scan_type=ScanType.QUICK,
            disks_scanned=DiskScanner.get_disks(),
            files=all_files,
            total_size=total_size,
            file_count=len(all_files),
            directory_count=0,
            errors=errors,
            duration_seconds=duration,
            status=status,
            categories=categories
        )

if __name__ == "__main__":
    # Test disk detection
    disks = DiskScanner.get_disks()
    print(f"Found {len(disks)} disks:")
    for d in disks:
        print(f"  {d.mountpoint} ({d.fstype}): {d.free / (1024**3):.2f} GB free of {d.total / (1024**3):.2f} GB total")

    # Test quick scan
    scanner = QuickScanner()
    result = scanner.scan()
    print(f"\nQuick scan: {result.file_count} files, {result.total_size / (1024**2):.2f} MB, status: {result.status.value}")
    print(f"Errors: {len(result.errors)}")
    print("Phase 3 Scanner Module: OK")
