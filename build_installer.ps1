param(
    [switch]$SignFiles
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CompilerCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Compiler = $CompilerCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Compiler) {
    throw "Inno Setup 6 is not installed. Install it, then run build_installer.ps1 again."
}

& (Join-Path $Root "work\gmfss-venv\Scripts\python.exe") (Join-Path $Root "release_audit.py") (Join-Path $Root "release\Oniflow")
if ($LASTEXITCODE -ne 0) { throw "Release security audit failed. Rebuild the portable package first." }

& $Compiler (Join-Path $Root "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed." }

$Installer = Get-ChildItem (Join-Path $Root "installer-output") -Filter "Oniflow-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $Installer) { throw "Compiled installer was not found." }

if ($SignFiles) {
    & (Join-Path $Root "sign_oniflow.ps1") -Paths @($Installer.FullName)
}

$Checksum = Get-FileHash $Installer.FullName -Algorithm SHA256
$ChecksumLine = "$($Checksum.Hash)  $($Installer.Name)"
Set-Content -Path (Join-Path $Root "installer-output\SHA256SUMS.txt") -Value $ChecksumLine -Encoding ascii

Write-Host "Installer created in installer-output."
