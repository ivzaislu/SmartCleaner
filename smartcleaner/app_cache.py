"""Non-destructive inventory and review of known application locations."""

import os
from pathlib import Path

from smartcleaner.analyzer import DiskAnalyzerEngine
from smartcleaner.protection import inspect_path

# Each entry identifies a specific regenerable cache inside the app's data root.
KNOWN_CACHES = (
    ("Discord", "APPDATA", "discord", ("Cache", "Code Cache", "GPUCache")),
    ("Visual Studio Code", "APPDATA", "Code", ("Cache", "Code Cache", "GPUCache")),
    ("Microsoft Teams (classic)", "APPDATA", "Microsoft/Teams", ("Cache", "Code Cache", "GPUCache")),
    ("NVIDIA", "LOCALAPPDATA", "NVIDIA", ("DXCache", "GLCache")),
)


def application_caches():
    for name, variable, folder, caches in KNOWN_CACHES:
        base = os.environ.get(variable)
        if not base or not Path(base).is_absolute():
            continue
        for cache in caches:
            path = Path(base) / folder / cache
            try:
                inspect_path(path)
            except (OSError, ValueError):
                continue
            for file_path, info in DiskAnalyzerEngine.walk_files(path):
                yield name, str(file_path), info.st_size


def leftover_candidates(installed_names):
    installed = [name.casefold() for name in installed_names]
    for name, variable, folder, _ in KNOWN_CACHES:
        base = os.environ.get(variable)
        if not base or not Path(base).is_absolute():
            continue
        if name.startswith(("NVIDIA", "Microsoft Teams")):
            continue  # Registry entries do not reliably identify these installations.
        if any(name.casefold() in entry for entry in installed):
            continue
        path = Path(base) / folder
        try:
            inspect_path(path)
        except (OSError, ValueError):
            continue
        if path.is_dir():
            yield name, str(path)
