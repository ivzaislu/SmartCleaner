"""Compare local PnP drivers with applicable offers from Windows Update Agent."""

import re
import uuid
from datetime import datetime
from typing import NamedTuple

from smartcleaner.windows_tools import powershell_rows
from smartcleaner.driver_actions import DriverToken
from smartcleaner.driver_sources import official_device_sources
from smartcleaner.driver_discovery import build_assessments, compare_versions


class DriverOffer(NamedTuple):
    device: str
    installed: str
    offered: str
    date: str
    title: str
    provider: str
    hardware_id: str


class OEMSupport(NamedTuple):
    manufacturer: str
    model: str
    url: str


class DriverSearch(NamedTuple):
    offers: list[DriverOffer]
    checked_at: datetime
    partial: bool
    tokens: dict[DriverOffer, DriverToken] | None = None
    oem: OEMSupport | None = None
    sources: list | None = None
    assessments: list | None = None


DEVICE_INVENTORY = r"""
$drivers = @{}
Get-CimInstance Win32_PnPSignedDriver | ForEach-Object {
    if ($_.DeviceID) { $drivers[$_.DeviceID] = $_ }
}
Get-CimInstance Win32_PnPEntity | ForEach-Object {
    $driver = if ($_.DeviceID) { $drivers[$_.DeviceID] } else { $null }
    [pscustomobject]@{
        Name = $_.Name
        DeviceID = $_.DeviceID
        Version = if ($driver) { $driver.DriverVersion } else { $null }
        Provider = if ($driver) { $driver.DriverProviderName } else { $null }
        Identifiers = @($_.HardwareID) + @($_.CompatibleID)
    }
}
"""

UPDATE_OFFERS = r"""
$session = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'SmartCleaner'
$searcher = $session.CreateUpdateSearcher()
$searcher.Online = $true
$result = $searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Driver'")
$code = [int]$result.ResultCode
if ($code -ne 2 -and $code -ne 3) {
    throw "Windows Update Agent ResultCode: $code"
}
[pscustomobject]@{ ResultCode = $code }
for ($index = 0; $index -lt $result.Updates.Count; $index++) {
    $update = $result.Updates.Item($index)
    $date = if ($update.DriverVerDate) { ([DateTime]$update.DriverVerDate).ToString('yyyy-MM-dd') }
    [pscustomobject]@{
        Title = $update.Title
        Model = $update.DriverModel
        Provider = $update.DriverProvider
        HardwareID = $update.DriverHardwareID
        Date = $date
        UpdateID = [string]$update.Identity.UpdateID
        Revision = [int]$update.Identity.RevisionNumber
        IsBeta = [bool]$update.IsBeta
    }
}
"""


def _device_identifiers(device):
    identifiers = device.get("Identifiers") or []
    if isinstance(identifiers, str):
        identifiers = [identifiers]
    if not isinstance(identifiers, (list, tuple)):
        identifiers = []
    values = [device.get("DeviceID"), device.get("HardwareID"), *identifiers]
    return {v.strip().casefold() for v in values
            if isinstance(v, str) and v.strip()}


def compare_offers(devices, updates):
    by_identifier = {}
    for device in devices:
        if not isinstance(device, dict):
            continue
        for identifier in _device_identifiers(device):
            by_identifier.setdefault(identifier, set()).add(
                (device.get("Name") or "Неизвестное устройство", device.get("Version") or "—"))
    offers = []
    for update in updates:
        title = update.get("Title") or "Драйвер Windows Update"
        version = re.search(r"(?:^|\s+-\s+)(\d+(?:\.\d+){1,7})\s*$", title)
        hardware_id = update.get("HardwareID") or ""
        matches = sorted(by_identifier.get(hardware_id.casefold(), ()))
        # Some offers match internal applicability rules or multiple devices.
        # Preserve the WUA offer even if local inventory cannot map it.
        for device, installed in matches or [(update.get("Model") or "Устройство не сопоставлено", "—")]:
            offers.append(DriverOffer(device, installed, version[1] if version else "—",
                                      update.get("Date") or "—", title,
                                      update.get("Provider") or "—", hardware_id))
    return sorted(set(offers), key=lambda offer: (offer.device.casefold(), offer.title.casefold()))


# Fixed trusted OEM *support portal links*, not automatic OEM download sources.
# Do not build download URLs from device names or execute vendor installers.
OEM_PORTALS = (
    (re.compile(r"^dell(?:\s|$)", re.I), "Dell", "https://www.dell.com/support/home"),
    (re.compile(r"^(?:hp|hewlett.packard)(?:\s|$)", re.I), "HP", "https://support.hp.com/drivers"),
    (re.compile(r"^lenovo(?:\s|$)", re.I), "Lenovo", "https://pcsupport.lenovo.com/"),
    (re.compile(r"^(?:asus|asustek)(?:\s|$)", re.I), "ASUS", "https://www.asus.com/support/download-center/"),
)

OEM_INVENTORY = r"""
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model
"""


def oem_support(manufacturer, model):
    """Return a recognized official support portal, not a driver update."""
    if not isinstance(manufacturer, str) or not isinstance(model, str):
        return None
    name = manufacturer.strip()
    model = model.strip()
    if not name or not model or len(name) > 250 or len(model) > 250:
        return None
    if name.casefold().startswith("microsoft") and model.casefold().startswith("surface"):
        return OEMSupport("Microsoft Surface", model,
                          "https://support.microsoft.com/en-gb/surface/drivers-firmware/download-drivers-and-firmware-for-surface")
    for pattern, vendor, url in OEM_PORTALS:
        if pattern.search(name):
            return OEMSupport(vendor, model, url)
    return None


def detect_oem():
    rows = powershell_rows(OEM_INVENTORY)
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return oem_support(rows[0].get("Manufacturer"), rows[0].get("Model"))


def _tokens_for_offers(devices, updates):
    """Enable download only for unambiguous, non-beta WUA update identities."""
    tokens = {}
    ambiguous = set()
    for row in updates:
        if not isinstance(row, dict):
            continue
        try:
            update_id = str(uuid.UUID(row["UpdateID"]))
            revision = row["Revision"]
            if type(revision) is not int or revision < 1 or row.get("IsBeta") is not False:
                continue
            token = DriverToken(update_id, revision)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        hardware_id = row.get("HardwareID")
        if not isinstance(hardware_id, str) or not hardware_id.strip():
            continue
        if not row.get("Provider") or not row.get("Title"):
            continue
        # Do not expose an update action for an unmatched WUA offer: Windows
        # Update may apply it by internal policy, but the UI cannot safely
        # assert which specific device will be affected.
        matching = [d for d in devices if isinstance(d, dict)
                    and hardware_id.strip().casefold() in _device_identifiers(d)]
        if len(matching) != 1:
            continue
        for offer in compare_offers(matching, [row]):
            # If numeric versions are truly comparable and the WUA offer is
            # not newer, present the information but disable "Update".
            if compare_versions(offer.installed, offer.offered) in (0, -1):
                continue
            if offer in tokens and tokens[offer] != token:
                ambiguous.add(offer)
            else:
                tokens[offer] = token
    for offer in ambiguous:
        tokens.pop(offer, None)
    return tokens


def check_driver_updates():
    result = powershell_rows(UPDATE_OFFERS, timeout=300)
    if (not isinstance(result, list) or not result or not isinstance(result[0], dict)
            or type(result[0].get("ResultCode")) is not int
            or result[0]["ResultCode"] not in (2, 3)):
        raise OSError("Windows Update вернул неполный ответ без статуса.")
    updates = result[1:]
    # Enumerate ALL devices even when Windows Update has no newer packages.
    devices = powershell_rows(DEVICE_INVENTORY)
    if not isinstance(devices, list):
        raise OSError("Не удалось прочитать инвентаризацию устройств.")
    try:
        oem = detect_oem()
    except (OSError, ValueError, TypeError, KeyError):
        oem = None
    offers = compare_offers(devices, updates)
    partial = result[0]["ResultCode"] == 3
    return DriverSearch(offers, datetime.now().astimezone(), partial,
                        _tokens_for_offers(devices, updates) if not partial else {},
                        oem, official_device_sources(devices, oem),
                        build_assessments(devices, offers, oem=oem, partial=partial))
