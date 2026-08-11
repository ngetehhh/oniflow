param(
    [string]$AppRoot = "D:\Oniflow",
    [string]$SourceRuntime = "$PSScriptRoot\release\Oniflow\work\python-runtime"
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -AppRoot `"$AppRoot`" -SourceRuntime `"$SourceRuntime`""
    exit $process.ExitCode
}

if (-not (Test-Path -LiteralPath $SourceRuntime)) {
    throw "Clean source runtime was not found: $SourceRuntime"
}

if (Get-Process -Name Oniflow, python, pythonw -ErrorAction SilentlyContinue) {
    throw "Close Oniflow before repairing its runtime."
}

$InstalledRuntime = Join-Path $AppRoot "work\python-runtime"
if (-not (Test-Path -LiteralPath $InstalledRuntime)) {
    throw "Installed runtime was not found: $InstalledRuntime"
}

$BackupRoot = Join-Path $AppRoot "backups\python-runtime-before-repair-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

robocopy $InstalledRuntime $BackupRoot /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Runtime backup failed with robocopy exit code $LASTEXITCODE." }

robocopy $SourceRuntime $InstalledRuntime /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Runtime restore failed with robocopy exit code $LASTEXITCODE." }

$RuntimePython = Join-Path $InstalledRuntime "python.exe"
& $RuntimePython -c "import sys, cv2, numpy, skvideo.io, torch; print('Oniflow runtime OK:', sys.version.split()[0], torch.__version__, torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "The restored runtime did not pass validation." }

Write-Host "Oniflow runtime repaired. Backup saved to: $BackupRoot"
