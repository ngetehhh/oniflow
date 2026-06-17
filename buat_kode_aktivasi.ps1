param(
    [Parameter(Mandatory = $true)]
    [string]$Code,

    [int]$Days = 30,

    [int]$Devices = 1
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "work\gmfss-venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Oniflow Python environment was not found: $Python"
}

& $Python (Join-Path $Root "activation_admin.py") create --days $Days --devices $Devices --code $Code
