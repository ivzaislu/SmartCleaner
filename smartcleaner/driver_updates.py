"""Compare local PnP drivers with applicable offers from Windows Update Agent."""

import re
from datetime import datetime
from typing import NamedTuple

from smartcleaner.windows_tools import powershell_rows


class DriverOffer(NamedTuple):
    device: str
    installed: str
    offered: str
    date: str
    title: str
    provider: str
    hardware_id: str


class DriverSearch(NamedTuple):
    offers: list[DriverOffer]
    checked_at: datetime
    partial: bool


DEVICE_INVENTORY = r"""
$drivers = @{}
Get-CimInstance Win32_PnPSignedDriver | ForEach-Object {
    if ($_.DeviceID) { $drivers[$_.DeviceID] = $_.DriverVersion }
}
Get-CimInstance Win32_PnPEntity | ForEach-Object {
    [pscustomobject]@{
        Name = $_.Name
        Version = if ($_.DeviceID) { $drivers[$_.DeviceID] } else { $null }
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
    }
}
"""


def compare_offers(devices, updates):
    by_identifier = {}
    for device in devices:
        for identifier in device.get("Identifiers") or []:
            if isinstance(identifier, str) and identifier:
                by_identifier.setdefault(identifier.casefold(), set()).add(
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


def check_driver_updates():
    if not (result := powershell_rows(UPDATE_OFFERS, timeout=300)) or result[0].get("ResultCode") not in (2, 3):
        raise OSError("Windows Update вернул неполный ответ без статуса.")
    devices = powershell_rows(DEVICE_INVENTORY) if len(result) > 1 else []
    return DriverSearch(compare_offers(devices, result[1:]), datetime.now().astimezone(),
                        result[0]["ResultCode"] == 3)
