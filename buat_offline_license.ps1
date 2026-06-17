param(
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [string]$Name = "Oniflow User",
    [int]$Days = 0,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "work\gmfss-venv\Scripts\python.exe"
if (-not $Output) {
    $SafeName = ($Name -replace '[^A-Za-z0-9_-]', '-').Trim('-')
    if (-not $SafeName) { $SafeName = "user" }
    $Output = Join-Path $Root "generated-licenses\$SafeName-oniflow-license.json"
}
& $Python (Join-Path $Root "offline_license_admin.py") --device-id $DeviceId --name $Name --days $Days --output $Output
if ($LASTEXITCODE -ne 0) { throw "Offline license creation failed." }
