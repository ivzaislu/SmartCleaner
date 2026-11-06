#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Enhanced Disk Analyzer (Phase 7)
SHA-256 duplicate finder with hard link awareness, Treemap generator, large file finder.
"""

import os
import hashlib
import stat
import time
from pathlib import Path
from typing import List, Dict, Tuple

from smartcleaner.protection import inspect_path

class DiskAnalyzerEngine:
    """Advanced disk analysis: Treemap structure, SHA-256 duplicate finder with hard link awareness."""

    @staticmethod
    def walk_files(root_path):
        root = Path(root_path).absolute()
        inspect_path(root)
        if not root.is_dir():
            raise ValueError("Выберите каталог.")
        pending = [root]
        while pending:
            folder = pending.pop()
            try:
                inspect_path(folder)
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            # DirEntry.stat on Windows omits file IDs needed to deduplicate hard links.
                            info = Path(entry.path).lstat() if os.name == "nt" else entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(Path(entry.path))
                        elif stat.S_ISREG(info.st_mode):
                            yield Path(entry.path), info
            except (OSError, ValueError):
                if folder == root:
                    raise

    @staticmethod
    def find_duplicates(root_path: str, min_size: int = 1024) -> List[List[str]]:
        size_map = {}
        seen = set()
        for path, info in DiskAnalyzerEngine.walk_files(root_path):
            key = (info.st_dev, info.st_ino)
            if info.st_size >= min_size and (not info.st_ino or key not in seen):
                size_map.setdefault(info.st_size, []).append(path)
                seen.add(key)
        duplicates = []
        for group in size_map.values():
            if len(group) < 2:
                continue
            hashes = {}
            for path in group:
                digest = DiskAnalyzerEngine._hash_file_sha256(path)
                if digest:
                    hashes.setdefault(digest, []).append(str(path))
            duplicates.extend(paths for paths in hashes.values() if len(paths) > 1)
        return duplicates

    @staticmethod
    def _hash_file_sha256(path, block_size=65536):
        try:
            path = Path(path)
            before = inspect_path(path)
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
                    return ""
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = os.fstat(stream.fileno())
            if (opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                return digest
        except (OSError, ValueError):
            pass
        return ""

    @staticmethod
    def generate_treemap(folder_path: str, max_items: int = 50) -> Dict:
        root = Path(folder_path).absolute()
        sizes = {}
        seen = set()
        for path, info in DiskAnalyzerEngine.walk_files(root):
            key = (info.st_dev, info.st_ino)
            if info.st_ino and key in seen:
                continue
            seen.add(key)
            parts = path.relative_to(root).parts
            name = parts[0]
            node = sizes.setdefault(name, {"name": name, "size": 0,
                                           "type": "dir" if len(parts) > 1 else "file"})
            node["size"] += info.st_size
        children = sorted(sizes.values(), key=lambda entry: entry["size"], reverse=True)
        return {"name": root.name, "path": str(root),
                "size": sum(child["size"] for child in children), "children": children[:max_items]}

    @staticmethod
    def find_large_files(root_path: str, min_size_mb: int = 50, limit: int = 100,
                         extension="", min_age_days=0) -> List[Tuple[str, int]]:
        threshold = min_size_mb * 1024 ** 2
        cutoff = time.time() - min_age_days * 86400
        suffix = "." + extension.strip().lstrip(".").casefold() if extension.strip() else ""
        files = [(str(path), info.st_size) for path, info in DiskAnalyzerEngine.walk_files(root_path)
                 if info.st_size >= threshold and (not suffix or path.suffix.casefold() == suffix)
                 and (not min_age_days or info.st_mtime <= cutoff)]
        return sorted(files, key=lambda entry: entry[1], reverse=True)[:limit]
