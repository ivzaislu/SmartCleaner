"""Conservative, explainable driver update assessments for Windows devices.

Windows Update Agent (WUA) is the sole in-app automatic driver offer source.
Manufacturer assistants are linked, not scraped, queried through private APIs,
or launched as downloaded executables.
"""
from typing import NamedTuple
from smartcleaner.driver_sources import (
    DeviceDriverSource, official_device_sources, is_trusted_support_url,
)


class DriverAssessment(NamedTuple):
    device: str
    installed: str
    manufacturer: str
    hardware_id: str
    status: str
    offered: str
    origin: str
    support_url: str
    assisted_check_url: str
    explanation: str


def _identifiers(device):
    values = device.get("Identifiers") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        values = []
    return {v.strip().casefold() for v in
            [device.get("DeviceID"), device.get("HardwareID"), *values]
            if isinstance(v, str) and v.strip()}


def _numeric_version(value):
    """Accept only directly comparable dotted Windows file versions."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if not 2 <= len(parts) <= 4 or any(not x.isascii() or not x.isdecimal()
                                         or len(x) > 10 for x in parts):
        return None
    return tuple(int(part) for part in parts)


def compare_versions(installed, offered):
    """Return 1, 0 or -1 only for same-format version numbers; else None."""
    a, b = _numeric_version(installed), _numeric_version(offered)
    if a is None or b is None or len(a) != len(b):
        return None
    return (b > a) - (b < a)


def build_assessments(devices, offers, *, oem=None, partial=False):
    """Inventory-based assessments; never infer a manufacturer's 'latest'.

    An offer may be applicable by Windows Update policy without being a higher
    number in an OEM's own versioning scheme. Unknown comparisons stay unknown.
    """
    sources = official_device_sources(devices, oem)
    indexed = {}
    for item in devices:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("Name") or item.get("DeviceID") or "").strip().casefold(),
               str(item.get("Version") or "—").strip().casefold())
        indexed.setdefault(key, []).append(_identifiers(item))

    assessments = []
    for source in sources:
        key = (source.device.casefold(), source.installed.casefold())
        identifiers = indexed.get(key, [])
        applicable = []
        for offer in offers:
            identifier = getattr(offer, "hardware_id", "")
            if (identifier and isinstance(identifier, str) and
                offer.device.casefold() == source.device.casefold() and
                offer.installed.casefold() == source.installed.casefold() and
                any(identifier.strip().casefold() in ids for ids in identifiers)):
                applicable.append(offer)

        if partial:
            status = "INCOMPLETE"
            offered = "—"
            origin = "Windows Update (частичный результат)"
            explanation = ("Windows Update сообщил о неполной проверке. "
                           "Вывод о наличии/отсутствии обновлений делать нельзя.")
        elif applicable:
            offered_values = sorted({item.offered for item in applicable if item.offered != "—"})
            offered = ", ".join(offered_values) if offered_values else "—"
            status = "WUA_OFFER"
            origin = "Windows Update"
            explanation = ("Windows Update предложил применимый пакет. Это не "
                           "гарантирует самую новую версию у производителя. "
                           "Сравните версию и требования устройства.")
            if len(applicable) == 1:
                ordering = compare_versions(source.installed, applicable[0].offered)
                if ordering == 1:
                    status = "WUA_NEWER"
                    explanation = ("Windows Update предложил применимый пакет "
                                   "с большей сопоставимой версией. "
                                   "OEM-совместимость всё равно требует внимания.")
                elif ordering in (0, -1):
                    status = "WUA_NOT_NEWER"
                    explanation = ("Windows Update предложил применимый пакет, "
                                   "но номер версии не выше установленного. "
                                   "Это может быть другая ветка драйвера; "
                                   "автоматическая рекомендация отключена.")
        else:
            offered = "—"
            origin = "Производитель / OEM"
            if is_trusted_support_url(source.assisted_check_url):
                status = "VENDOR_ASSISTANT"
                explanation = ("Для устройства доступен официальный инструмент "
                               "проверки производителя. SmartCleaner не получает "
                               "от него версии напрямую и не запускает установку.")
            elif is_trusted_support_url(source.url):
                status = "MANUAL"
                explanation = ("Предложений Windows Update не найдено. "
                               "Свежесть драйвера у производителя не проверена.")
            else:
                status = "UNKNOWN"
                explanation = ("Официальный источник не определён. "
                               "Статус актуальности драйвера неизвестен.")
        assessments.append(DriverAssessment(
            source.device, source.installed, source.manufacturer,
            source.hardware_id, status, offered, origin,
            source.url if is_trusted_support_url(source.url) else "",
            source.assisted_check_url if is_trusted_support_url(source.assisted_check_url) else "",
            explanation))
    return assessments
