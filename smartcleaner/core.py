#!/usr/bin/env python3
"""
SmartCleaner 2.0 - Enhanced Core & Protection Engine
Advanced security: TOCTOU mitigation, strict symlink checks, path traversal defense,
cryptographic rule signature validation, quarantine and recovery engine.
"""

import os
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict

from smartcleaner.protection import ProtectionEngine, inspect_path
from smartcleaner.signer import RuleSigner
from dataclasses import dataclass, asdict

APP_NAME = "SmartCleaner"
APP_VERSION = "2.0.2"

@dataclass
class AppConfig:
    language: str = "ru"
    theme: str = "light"
    scan_depth: str = "quick"
    protected_paths: List[str] = None
    excluded_paths: List[str] = None
    browser_profiles_excluded: List[str] = None
    scheduler_enabled: bool = False
    scheduler_interval: str = "daily"
    free_space_threshold_mb: int = 5000
    notifications_enabled: bool = True
    quarantine_enabled: bool = True
    dry_run_default: bool = True

    def __post_init__(self):
        if type(self.quarantine_enabled) is not bool:
            raise ValueError("Invalid quarantine setting")
        for paths in (self.protected_paths, self.excluded_paths, self.browser_profiles_excluded):
            if paths is not None and (not isinstance(paths, list) or
                                      any(not isinstance(path, str) or not path for path in paths)):
                raise ValueError("Invalid exclusion list")
        if self.protected_paths is None:
            self.protected_paths = []
        if self.excluded_paths is None:
            self.excluded_paths = []
        if self.browser_profiles_excluded is None:
            self.browser_profiles_excluded = []

CONFIG_FILE = "smartcleaner_config.json"
DB_FILE = "smartcleaner_history.db"
QUARANTINE_DIR = "quarantine"

class OperationLogger:
    """SQLite-based operation logger with quarantine and recovery support."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = Path(db_path).absolute()
        inspect_path(self.db_path, missing_leaf=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operations_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                target_path TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                details TEXT,
                recoverable INTEGER DEFAULT 0,
                quarantine_path TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quarantine_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                quarantine_path TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                checksum TEXT
            )
        ''')
        # Schema migration
        for col, col_type in [("recoverable", "INTEGER DEFAULT 0"), ("quarantine_path", "TEXT")]:
            try:
                cursor.execute(f"ALTER TABLE operations_log ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    def log_operation(self, operation_type: str, target_path: str,
                      size_bytes: int = 0, status: str = "SUCCESS",
                      details: str = "", recoverable: bool = False,
                      quarantine_path: str = ""):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO operations_log
            (timestamp, operation_type, target_path, size_bytes, status, details, recoverable, quarantine_path)
            VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)
        ''', (operation_type, target_path, size_bytes, status, details,
              int(recoverable), quarantine_path))
        conn.commit()
        conn.close()

    def get_history(self, limit: int = 100) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, timestamp, operation_type, target_path, size_bytes,
                   status, details, recoverable, quarantine_path
            FROM operations_log ORDER BY id DESC LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "timestamp": r[1], "operation_type": r[2],
                "target_path": r[3], "size_bytes": r[4], "status": r[5],
                "details": r[6], "recoverable": bool(r[7]), "quarantine_path": r[8]
            }
            for r in rows
        ]

    def latest_operation_time(self, operation_type):
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT timestamp FROM operations_log WHERE operation_type = ? ORDER BY id DESC LIMIT 1",
                (operation_type,),
            ).fetchone()
        return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc) if row else None

    def record_quarantine(self, original_path: str, quarantine_path: str,
                          size_bytes: int, checksum: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO quarantine_items (original_path, quarantine_path, timestamp, size_bytes, checksum)
            VALUES (?, ?, datetime('now'), ?, ?)
        ''', (original_path, quarantine_path, size_bytes, checksum))
        conn.commit()
        conn.close()

    def get_quarantine_items(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT id, original_path, quarantine_path, timestamp, size_bytes, checksum FROM quarantine_items')
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "original_path": r[1], "quarantine_path": r[2], "timestamp": r[3], "size_bytes": r[4], "checksum": r[5]}
            for r in rows
        ]


class ConfigManager:
    """Configuration and Settings Backup / Export / Import with validation."""

    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = Path(config_path).absolute()
        self.config = AppConfig()

    def load(self) -> AppConfig:
        if inspect_path(self.config_path, missing_leaf=True) is not None:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.config = AppConfig(**data)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("Invalid SmartCleaner configuration") from exc
        return self.config

    def save(self, config: AppConfig = None):
        if config:
            self.config = config
        inspect_path(self.config_path, missing_leaf=True)
        stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                             dir=self.config_path.parent)
        staged = Path(stream.name)
        try:
            with stream:
                json.dump(asdict(self.config), stream, indent=2, ensure_ascii=False)
            os.replace(staged, self.config_path)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

    def export_settings(self, export_path: str) -> bool:
        try:
            data = {
                "app": APP_NAME,
                "version": APP_VERSION,
                "exported_at": datetime.now().isoformat(),
                "config": asdict(self.config)
            }
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def import_settings(self, import_path: str) -> bool:
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "config" in data and isinstance(data["config"], dict):
                self.config = AppConfig(**data["config"])
                self.save()
                return True
        except Exception:
            pass
        return False


if __name__ == "__main__":
    print("Enhanced Core module loaded successfully.")
