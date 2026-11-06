"""Static cross-check of installer templates. This does not build packages."""

import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    required = [
        "smartcleaner.spec",
        "smartcleaner/gui.py",
        "smartcleaner.desktop",
        "installers/windows/smartcleaner.iss",
        "installers/linux/smartcleaner",
        "installers/linux/build-deb.sh",
        "installers/linux/debian/DEBIAN/control",
        "installers/linux/rpm/smartcleaner.spec",
        "installers/linux/rpm/nautilus-scripts/Delete via SmartCleaner",
    ]
    files = {name: (ROOT / name).read_text(encoding="utf-8-sig") for name in required}
    iss = files["installers/windows/smartcleaner.iss"]
    desktop = configparser.ConfigParser(interpolation=None)
    desktop.read_string(files["smartcleaner.desktop"])
    checks = {
        "desktop command": desktop["Desktop Entry"]["Exec"] == "smartcleaner",
        "Inno per-user installation": "PrivilegesRequired=lowest" in iss and "Root: HKCU" in iss,
        "Inno file argument": '--delete ""%1""' in iss,
        "Inno generated binary path": r'..\..\dist\SmartCleaner.exe' in iss,
        "no installer data cleanup": "[UninstallDelete]" not in iss
            and set(path.name for path in (ROOT / "installers/linux/debian/DEBIAN").iterdir()) == {"control"}
            and "%preun" not in files["installers/linux/rpm/smartcleaner.spec"],
        "Linux isolated launcher": "python3 -I" in files["installers/linux/smartcleaner"],
        "Linux staged modules": all("smartcleaner/smartcleaner" in files[name] for name in (
            "installers/linux/build-deb.sh", "installers/linux/rpm/smartcleaner.spec")),
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    raise SystemExit(main())
