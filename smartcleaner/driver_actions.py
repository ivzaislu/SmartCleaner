"""Windows Update Agent operations for a selected, identified driver update.

Only Windows Update/managed WSUS is allowed to download or install packages.
No arbitrary driver URLs or executable downloads are accepted. Installation
requires a separate explicit confirmation, even after download.
"""
import base64
import json
import os
import uuid
from typing import NamedTuple

from smartcleaner.windows_tools import powershell_rows


class DriverToken(NamedTuple):
    update_id: str
    revision: int


class DriverActionResult(NamedTuple):
    state: str
    reboot_required: bool
    message: str


def _is_windows():
    return os.name == "nt"


def _validate(offer, token):
    if not isinstance(token, DriverToken):
        raise ValueError("Select an identified update from a fresh WUA scan")
    try:
        update_id = str(uuid.UUID(token.update_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Invalid Windows Update identity") from exc
    if type(token.revision) is not int or not 1 <= token.revision <= 2**31 - 1:
        raise ValueError("Invalid Windows Update revision")
    title = getattr(offer, "title", None)
    hardware_id = getattr(offer, "hardware_id", None)
    provider = getattr(offer, "provider", None)
    if not all(isinstance(value, str) and 0 < len(value) <= 2048
               for value in (title, hardware_id, provider)):
        raise ValueError("Missing or invalid driver metadata")
    return {"update_id": update_id, "revision": token.revision,
            "title": title, "provider": provider, "hardware_id": hardware_id}


# Metadata is passed as encoded JSON; no untrusted strings are interpolated as
# PowerShell source. Re-search WUA for applicability before every action.
_SCRIPT = r"""
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
$session = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'SmartCleaner'
$searcher = $session.CreateUpdateSearcher()
$searcher.Online = $true
$search = $searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Driver'")
if ([int]$search.ResultCode -ne 2) {{ throw 'WUA scan is incomplete; update blocked' }}
$update = $null
for ($i = 0; $i -lt $search.Updates.Count; $i++) {{
    $candidate = $search.Updates.Item($i)
    if (([string]$candidate.Identity.UpdateID -eq [string]$request.update_id) -and
        ([int]$candidate.Identity.RevisionNumber -eq [int]$request.revision)) {{
        $update = $candidate
        break
    }}
}}
if ($null -eq $update) {{ throw 'Selected driver is no longer applicable; scan again' }}
if (([string]$update.Title -cne [string]$request.title) -or
    ([string]$update.DriverProvider -cne [string]$request.provider) -or
    ([string]$update.DriverHardwareID -ine [string]$request.hardware_id)) {{
    throw 'Driver metadata changed; scan again'
}}
if ($update.IsBeta -or $update.IsHidden -or $update.IsInstalled) {{
    throw 'Driver is beta, hidden, or already installed'
}}
if (-not $update.EulaAccepted) {{
    throw 'EULA_REQUIRED: accept license terms through Windows Update'
}}
if ($update.InstallationBehavior.CanRequestUserInput) {{
    throw 'Driver needs interactive setup; use Windows Update instead'
}}
$collection = New-Object -ComObject Microsoft.Update.UpdateColl
[void]$collection.Add($update)
{operation}
"""
_DOWNLOAD = r"""
if (-not $update.IsDownloaded) {
    $downloader = $session.CreateUpdateDownloader()
    $downloader.Updates = $collection
    $downloadResult = $downloader.Download()
    if ([int]$downloadResult.ResultCode -ne 2 -or
        [int]$downloadResult.GetUpdateResult(0).ResultCode -ne 2) {
        throw 'Windows Update could not download and verify the driver'
    }
}
if (-not $update.IsDownloaded) { throw 'WUA did not confirm the downloaded package' }
[pscustomobject]@{ State='DOWNLOADED'; RebootRequired=$false; Message='Downloaded by Windows Update' }
"""
_INSTALL = r"""
if (-not $update.IsDownloaded) { throw 'Download the driver through WUA first' }
$installer = $session.CreateUpdateInstaller()
$installer.Updates = $collection
$installResult = $installer.Install()
if ([int]$installResult.ResultCode -ne 2 -or
    [int]$installResult.GetUpdateResult(0).ResultCode -ne 2) {
    throw ('Windows Update installation failed (result=' + [int]$installResult.ResultCode + ')')
}
[pscustomobject]@{ State='INSTALLED'; RebootRequired=[bool]$installResult.RebootRequired; Message='Installed by Windows Update' }
"""


def _run_action(offer, token, operation):
    if not _is_windows():
        raise OSError("Driver download and installation are supported only on Windows")
    payload = _validate(offer, token)
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    script = _SCRIPT.format(payload=encoded,
                            operation=_DOWNLOAD if operation == "download" else _INSTALL)
    rows = powershell_rows(script, timeout=1800)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise OSError("Windows Update returned an unexpected response")
    row = rows[0]
    state = "DOWNLOADED" if operation == "download" else "INSTALLED"
    if row.get("State") != state or type(row.get("RebootRequired")) is not bool:
        raise OSError("Windows Update did not confirm a successful operation")
    return DriverActionResult(state, row["RebootRequired"], row.get("Message") or state)


def download_driver(offer, token):
    """Use the system Windows Update Agent to download, never to install."""
    return _run_action(offer, token, "download")


def install_driver(offer, token, *, confirmed=False):
    """Install an already downloaded WUA driver after user confirmation."""
    if confirmed is not True:
        raise PermissionError("Explicit installation confirmation is required")
    return _run_action(offer, token, "install")
