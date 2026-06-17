$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "work\gmfss-venv\Scripts\python.exe"
$LanAddress = (
    Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.InterfaceAlias -notmatch "VMware|Virtual|Loopback"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress
)

if (-not (Test-Path $Python)) {
    throw "Oniflow Python environment was not found: $Python"
}

Set-Location $Root
$SecurePassword = Read-Host "Create an admin dashboard password for this server session" -AsSecureString
$PasswordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
try {
    $env:ONIFLOW_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordPointer)
    Write-Host ""
    Write-Host "Local dashboard: http://127.0.0.1:8765/admin"
    if ($LanAddress) {
        Write-Host "Friend access on the same network: http://${LanAddress}:8765"
    }
    Write-Host "Keep this window open while friends use Oniflow."
    Write-Host ""
    & $Python (Join-Path $Root "activation_server.py") --host 0.0.0.0 --port 8765
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPointer)
    Remove-Item Env:ONIFLOW_ADMIN_PASSWORD -ErrorAction SilentlyContinue
}
