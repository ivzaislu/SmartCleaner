"""Windows diagnostics and reversible cleanup entry point."""

import os

from smartcleaner.quarantine import Quarantine
from smartcleaner.windows_tools import command_report, filesystem_report, powershell_rows


class SmartCleanerDelete(Quarantine):
    """Manual cleanup through the shared quarantine."""


class SystemDiagnostics:
    @staticmethod
    def get_drive_health():
        if os.name != "nt":
            import psutil
            return [{"device": disk.device, "mountpoint": disk.mountpoint,
                     "smart_status": "Данные SMART недоступны"}
                    for disk in psutil.disk_partitions(all=False)]
        return powershell_rows("""
            Get-PhysicalDisk | ForEach-Object {
                $disk = $_
                $counter = $null
                try { $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop } catch {}
                [pscustomobject]@{
                    Model = $disk.FriendlyName
                    Media = [string]$disk.MediaType
                    Bus = [string]$disk.BusType
                    Size = $disk.Size
                    Health = [string]$disk.HealthStatus
                    Temperature = $counter.Temperature
                    Wear = $counter.Wear
                    PowerOnHours = $counter.PowerOnHours
                }
            }
        """)

    @staticmethod
    def check_system_integrity():
        if os.name != "nt":
            return False, "Проверка SFC доступна в Windows."
        return command_report("sfc.exe", ["/verifyonly"], 1800)

    @staticmethod
    def check_component_store():
        if os.name != "nt":
            return False, "Проверка DISM доступна в Windows."
        return command_report("Dism.exe", ["/Online", "/Cleanup-Image", "/CheckHealth"], 300)

    @staticmethod
    def check_filesystem(mountpoint):
        if os.name != "nt":
            return False, "Проверка CHKDSK доступна в Windows."
        return filesystem_report(mountpoint)
