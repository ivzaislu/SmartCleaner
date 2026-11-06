"""Read-only Windows inventory and explicit handoff to Windows Settings."""

import ctypes
import json
import os
import re
import subprocess
from pathlib import Path


def system_dir():
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Не удалось найти системную папку Windows")
    return Path(buffer.value)


def run_windows(executable, arguments, timeout):
    if os.name != "nt":
        raise OSError("Эта проверка доступна в Windows.")
    return subprocess.run([str(system_dir() / executable), *arguments], timeout=timeout,
                          stdin=subprocess.DEVNULL, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, check=False)


def powershell_rows(command, timeout=60):
    prefix = ("$ErrorActionPreference='Stop'; "
              "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); ")
    result = run_windows("WindowsPowerShell/v1.0/powershell.exe", [
        "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        prefix + "$rows=@(" + command + "); ConvertTo-Json -InputObject $rows -Compress"
    ], timeout)
    if result.returncode:
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip() or
                      f"Код PowerShell: {result.returncode}")
    return json.loads(result.stdout.decode("utf-8-sig"))


def decode_report(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:100]:
        return data.decode("utf-16-le", errors="replace")
    return data.decode("oem", errors="replace")


def filesystem_report(volume):
    if not re.fullmatch(r"[A-Za-z]:[\\/]?", volume):
        raise ValueError("Выберите локальный том с буквой диска.")
    drive = volume[:2] + "\\"
    if os.name != "nt" or ctypes.windll.kernel32.GetDriveTypeW(drive) not in (2, 3):
        raise ValueError("Выберите локальный или съёмный том.")
    return command_report("chkdsk.exe", [volume[:2]], 900)


def command_report(executable, arguments, timeout):
    result = run_windows(executable, arguments, timeout)
    output = "\n".join(decode_report(stream).strip() for stream in
                       (result.stdout, result.stderr) if stream)
    return result.returncode == 0, f"Код завершения: {result.returncode}\n{output}"


def installed_programs():
    import winreg

    results = {}
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                root = winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as entry:
                            def field(name, default=""):
                                try:
                                    return winreg.QueryValueEx(entry, name)[0]
                                except FileNotFoundError:
                                    return default

                            name = str(field("DisplayName")).strip()
                            if name and not field("SystemComponent", 0):
                                version, publisher = str(field("DisplayVersion")), str(field("Publisher"))
                                results[(name.casefold(), version, publisher)] = (name, version, publisher)
                    except OSError:
                        continue
    return sorted(results.values(), key=lambda row: row[0].casefold())
