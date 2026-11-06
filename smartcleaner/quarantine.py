"""Reversible cleanup of individually approved regular files."""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

from smartcleaner.core import ConfigManager, OperationLogger
from smartcleaner.file_move import identity, locked_move
from smartcleaner.protection import ProtectionEngine, checked_path, contains, inspect_path


class Quarantine:
    def __init__(self, logger=None, config_manager=None):
        self.logger = logger or OperationLogger()
        state_dir = Path(self.logger.db_path).absolute().parent
        self.root = state_dir / "quarantine"
        self.config_manager = config_manager or ConfigManager(
            state_dir / "smartcleaner_config.json")

    def exclusions(self):
        config = self.config_manager.load()
        base = self.config_manager.config_path.parent
        settings = [*config.protected_paths, *config.excluded_paths,
                    *config.browser_profiles_excluded]
        exclusions = [str(base / os.path.expandvars(os.path.expanduser(path)))
                      for path in settings]
        db = str(self.logger.db_path)
        return [*exclusions, str(self.root), str(self.config_manager.config_path),
                db, db + "-wal", db + "-shm", db + "-journal"]

    @staticmethod
    def _checksum(descriptor):
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def delete_item(self, path, move_to_quarantine=True, *, expected=None):
        if not move_to_quarantine:
            return False, "Permanent deletion is disabled"
        try:
            exclusions = self.exclusions()
            if not self.config_manager.config.quarantine_enabled:
                raise ValueError("Quarantine is disabled in settings")
            source, snapshot = ProtectionEngine.validate_file(path, exclusions)
            if expected is not None and identity(snapshot) != expected:
                raise ValueError("File changed after preview")
            inspect_path(self.root.parent)
            self.root.mkdir(mode=0o700, exist_ok=True)
            inspect_path(self.root)
            if not self.root.is_dir():
                raise ValueError("Invalid quarantine directory")
            entry = Path(tempfile.mkdtemp(prefix="item-", dir=self.root))
            destination = entry / source.name
            with locked_move(source, destination) as (descriptor, move):
                if identity(os.fstat(descriptor)) != identity(snapshot):
                    raise ValueError("Source changed")
                checksum = self._checksum(descriptor)
                if identity(os.fstat(descriptor)) != identity(snapshot):
                    raise ValueError("Source changed while hashing")
                # Persist recovery details before attempting the filesystem mutation.
                self.logger.record_quarantine(str(source), str(destination), snapshot.st_size, checksum)
                move()
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return False, str(exc)
        try:
            self.logger.log_operation("QUARANTINE", str(source), snapshot.st_size,
                                      recoverable=True, quarantine_path=str(destination))
        except sqlite3.Error:
            return True, "Moved to quarantine. History could not be written."
        return True, "Moved to quarantine"

    def restore_item(self, item_id):
        try:
            item = next((row for row in self.logger.get_quarantine_items()
                         if row["id"] == item_id), None)
            if item is None:
                raise ValueError("Unknown quarantine item")
            source = checked_path(item["quarantine_path"])
            if not contains(self.root, source) or source == self.root:
                raise ValueError("Invalid quarantine path")
            destination, existing = ProtectionEngine.validate_file(
                item["original_path"], self.exclusions(), missing_leaf=True)
            if existing is not None:
                raise ValueError("Original path already exists")
            _, snapshot = ProtectionEngine.validate_file(source)
            if source.name != destination.name and source.parent != self.root:
                raise ValueError("Invalid quarantine item name")
            with locked_move(source, destination) as (descriptor, move):
                if identity(os.fstat(descriptor)) != identity(snapshot):
                    raise ValueError("Quarantine file changed")
                if self._checksum(descriptor) != item["checksum"]:
                    raise ValueError("Quarantine checksum mismatch")
                if identity(os.fstat(descriptor)) != identity(snapshot):
                    raise ValueError("Quarantine file changed while hashing")
                move()
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return False, str(exc)
        try:
            self.logger.log_operation("RESTORE", str(destination), snapshot.st_size)
        except sqlite3.Error:
            return True, "Restored. History could not be written."
        return True, "Restored"
