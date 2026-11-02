# Read-only. Run on the TARGET Windows PC, not on the PiKVM controller by mistake.
# Lists USB disks, their partitions and volume letters. Never initializes/formats.
[CmdletBinding()]
param([Nullable[int]]$DiskNumber = $null)
$ErrorActionPreference = 'Stop'
$pikvmUsbDisks = if ($null -ne $DiskNumber) {
    Get-Disk -Number $DiskNumber
} else {
    Get-Disk | Where-Object BusType -eq 'USB'
}
$pikvmUsbDisks | Select-Object Number, FriendlyName, BusType, OperationalStatus, IsOffline, IsReadOnly, PartitionStyle, Size
foreach ($pikvmUsbDisk in $pikvmUsbDisks) {
    Get-Partition -DiskNumber $pikvmUsbDisk.Number |
        Select-Object DiskNumber, PartitionNumber, DriveLetter, Type, Size
    Get-Partition -DiskNumber $pikvmUsbDisk.Number | Get-Volume -ErrorAction SilentlyContinue |
        Select-Object DriveLetter, FileSystemLabel, FileSystem, HealthStatus, Size, SizeRemaining
}
