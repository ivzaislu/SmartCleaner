"""Shared, fail-closed path policy for every cleanup entry point."""

import os
import stat
from pathlib import Path


def contains(parent, child):
    parent = os.path.normcase(os.fspath(parent))
    child = os.path.normcase(os.fspath(child))
    try:
        return os.path.commonpath((parent, child)) == parent
    except ValueError:
        return False


def checked_path(value):
    raw = os.fspath(value)
    path = Path(raw)
    if not raw or not path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected an absolute path without traversal")
    if os.name == "nt":
        if len(path.drive) != 2 or not path.drive.endswith(":"):
            raise ValueError("Device and network paths are blocked")
        reserved = getattr(os.path, "isreserved", lambda part: Path(part).is_reserved())
        if any(part.endswith((".", " ")) or ":" in part or reserved(part)
               for part in path.parts[1:]):
            raise ValueError("Reserved names and alternate streams are blocked")
    return path


def inspect_path(path, missing_leaf=False):
    """Inspect all components without following links or Windows reparse points."""
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing_leaf and component == path:
                return None
            raise
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Symlink or reparse point is blocked")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Invalid parent directory")
    return info


class ProtectionEngine:
    SYSTEM_PROTECTED_PATHS = [
        "/bin", "/sbin", "/etc", "/usr", "/lib", "/lib64", "/boot",
        "/proc", "/sys", "/dev", "/run", "/var/lib/dpkg", "/var/lib/apt",
    ]

    WINDOWS_PROTECTED_PATHS = [
        "C:\\Windows", "C:\\Boot", "C:\\Program Files", "C:\\Program Files (x86)",
        "C:\\System Volume Information", "$Recycle.Bin",
    ]

    PROTECTED_EXTENSIONS = {
        ".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx",
        ".rtf", ".odt", ".ods", ".odp",
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv",
        ".mp3", ".wav", ".flac", ".aac", ".ogg",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
        ".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".h",
        ".db", ".sqlite", ".sql",
        ".ssh", ".pem", ".key", ".crt", ".cer",
        ".save", ".sav", ".dsv", ".gsav",
    }


    @classmethod
    def is_protected_path(cls, path_str):
        path = Path(os.path.abspath(path_str))
        if path == Path(path.anchor) or path == Path.home():
            return True
        if os.name == "nt":
            protected = [Path(path.anchor) / Path(entry).name
                         for entry in cls.WINDOWS_PROTECTED_PATHS]
            protected.extend(Path(os.environ[name]) for name in
                             ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
                             if os.environ.get(name))
        else:
            protected = cls.SYSTEM_PROTECTED_PATHS
        return any(contains(root, path) for root in protected)

    @classmethod
    def is_protected_file_type(cls, path_str):
        return Path(path_str).suffix.lower() in cls.PROTECTED_EXTENSIONS

    @classmethod
    def validate_file(cls, value, exclusions=(), missing_leaf=False):
        path = checked_path(value)
        if cls.is_protected_path(path):
            raise ValueError("System-protected path")
        info = inspect_path(path, missing_leaf)
        canonical = Path(os.path.realpath(path))
        if os.path.normcase(str(canonical)) != os.path.normcase(str(path)):
            raise ValueError("Path aliases are blocked")
        for entry in exclusions:
            expanded = os.path.expanduser(os.path.expandvars(entry))
            excluded = Path(os.path.abspath(expanded))
            if contains(excluded, path) or contains(os.path.realpath(excluded), canonical):
                raise ValueError("User-excluded path")
        if cls.is_protected_file_type(path):
            raise ValueError("Protected user file type")
        if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("Only regular files with one link are supported")
        return path, info

    @classmethod
    def is_safe_to_delete(cls, path_str, user_excluded=None):
        try:
            cls.validate_file(path_str, user_excluded or ())
            return True, "Safe"
        except (OSError, ValueError, TypeError) as exc:
            return False, str(exc)
