"""Trusted manufacturer support sources for installed Windows PnP devices.

These are fixed, official *support pages* only. They are NOT APIs, driver
download locations or proof that a newer/compatible version exists.
Automatic download and installation remain exclusively with Windows Update.
"""
import re
from typing import NamedTuple


class DeviceDriverSource(NamedTuple):
    device: str
    installed: str
    manufacturer: str
    hardware_id: str
    url: str
    guidance: str


# Official pages manually verified. Never derive a URL from input metadata.
VENDORS = {
    "NVIDIA": "https://www.nvidia.com/en-us/drivers/",
    "AMD Radeon / AMD": "https://www.amd.com/en/support.html",
    "Intel": "https://www.intel.com/content/www/us/en/download-center/home.html",
    "Realtek": "https://www.realtek.com/download/list",
    "Broadcom": "https://www.broadcom.com/support/download-search",
    "Qualcomm": "https://www.qualcomm.com/drivers",
    "Creative": "https://support.creative.com/",
}

# Vendor IDs in PnP identifiers, not arbitrary device-name substrings.
PCI_VENDOR_IDS = {
    "10DE": "NVIDIA",
    "1002": "AMD Radeon / AMD",
    "1022": "AMD Radeon / AMD",
    "8086": "Intel",
    "10EC": "Realtek",
    "14E4": "Broadcom",
    "168C": "Qualcomm",
    "17CB": "Qualcomm",
    "14C3": "MediaTek",
    "1102": "Creative",
}
USB_VENDOR_IDS = {
    "0BDA": "Realtek",
    "0A5C": "Broadcom",
    "0CF3": "Qualcomm",
    "0E8D": "MediaTek",
    "041E": "Creative",
}
PCI_ID = re.compile(r"(?:^|\\)VEN_([0-9A-F]{4})(?=&|\\|$)", re.I)
USB_ID = re.compile(r"(?:^|\\)VID_([0-9A-F]{4})(?=&|\\|$)", re.I)
PROVIDER_NAMES = (
    (re.compile(r"^nvidia(?:\b|\s)", re.I), "NVIDIA"),
    (re.compile(r"^(?:advanced micro devices|amd(?:\b|\s)|ati technologies)", re.I), "AMD Radeon / AMD"),
    (re.compile(r"^intel(?:\b|\s|\()", re.I), "Intel"),
    (re.compile(r"^realtek(?:\b|\s)", re.I), "Realtek"),
    (re.compile(r"^broadcom(?:\b|\s)", re.I), "Broadcom"),
    (re.compile(r"^(?:qualcomm|atheros)(?:\b|\s)", re.I), "Qualcomm"),
    (re.compile(r"^mediatek(?:\b|\s)", re.I), "MediaTek"),
    (re.compile(r"^creative(?:\b|\s)", re.I), "Creative"),
)


def _identifiers(device):
    raw = device.get("Identifiers") or []
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = []
    values = [device.get("DeviceID"), device.get("HardwareID"), *raw]
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def identify_manufacturer(device):
    """Recognise a vendor; hardware IDs take precedence over driver provider."""
    for identifier in _identifiers(device):
        match = PCI_ID.search(identifier)
        if match and match.group(1).upper() in PCI_VENDOR_IDS:
            return PCI_VENDOR_IDS[match.group(1).upper()]
        match = USB_ID.search(identifier)
        if match and match.group(1).upper() in USB_VENDOR_IDS:
            return USB_VENDOR_IDS[match.group(1).upper()]
    provider = device.get("Provider") or ""
    if isinstance(provider, str):
        provider = provider.strip()
        for pattern, name in PROVIDER_NAMES:
            if pattern.search(provider):
                return name
    return None


def official_device_sources(devices, oem=None):
    """One inventory entry per installed device, including unknown vendors.

    For MediaTek, unknown vendors and other components without verified direct
    support catalogs, use the machine OEM portal when available; otherwise
    show an explicit unavailable state, never invent a download URL.
    """
    result = []
    seen = set()
    for device in devices:
        if not isinstance(device, dict):
            continue
        ids = _identifiers(device)
        device_id = ids[0] if ids else ""
        name = str(device.get("Name") or device.get("DeviceID") or "").strip()
        if not name:
            continue
        version = str(device.get("Version") or "—").strip() or "—"
        key = (device_id.casefold(), name.casefold(), version)
        if key in seen:
            continue
        seen.add(key)
        manufacturer = identify_manufacturer(device)
        url = VENDORS.get(manufacturer, "") if manufacturer else ""
        if manufacturer == "Realtek":
            guidance = ("Только ручная проверка. Для встроенного аудио и Wi-Fi "
                        "предпочтителен драйвер производителя ПК/платы.")
        elif manufacturer == "Qualcomm":
            guidance = ("Qualcomm рекомендует OEM/Windows Update для большинства устройств; "
                        "на странице производителя нет универсальных драйверов.")
        elif manufacturer and url:
            guidance = ("Официальный сайт. Версия и совместимость здесь не проверялись; "
                        "для ноутбука сначала проверьте OEM.")
        else:
            guidance = ("Подтверждённого прямого каталога драйверов нет. "
                        "Проверяйте драйвер по модели ПК у OEM.")
        if not url and oem is not None:
            manufacturer = manufacturer or ("OEM: " + oem.manufacturer)
            url = oem.url
        result.append(DeviceDriverSource(name, version, manufacturer or "Не определён",
                                          device_id, url, guidance))
    return sorted(result, key=lambda entry: (entry.manufacturer.casefold(),
                                             entry.device.casefold(),
                                             entry.hardware_id.casefold()))
