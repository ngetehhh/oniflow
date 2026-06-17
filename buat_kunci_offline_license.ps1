$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PrivateDir = Join-Path $Root "private"
$AssetsDir = Join-Path $Root "assets"
$PrivatePath = Join-Path $PrivateDir "offline-license-private.json"
$PublicPath = Join-Path $AssetsDir "offline-license-public.json"

if (Test-Path $PrivatePath) {
    throw "Private key already exists. Delete it manually only if you intentionally want to invalidate all existing licenses."
}

New-Item -ItemType Directory -Force $PrivateDir, $AssetsDir | Out-Null
$Rsa = [System.Security.Cryptography.RSA]::Create(3072)
$Parameters = $Rsa.ExportParameters($true)
$Public = @{
    modulus = [Convert]::ToBase64String($Parameters.Modulus)
    exponent = [Convert]::ToBase64String($Parameters.Exponent)
}
$Private = @{
    modulus = [Convert]::ToBase64String($Parameters.Modulus)
    exponent = [Convert]::ToBase64String($Parameters.Exponent)
    private_exponent = [Convert]::ToBase64String($Parameters.D)
}
[System.IO.File]::WriteAllText($PublicPath, ($Public | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($PrivatePath, ($Private | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
Write-Host "Public key: $PublicPath"
Write-Host "PRIVATE KEY: $PrivatePath"
Write-Host "Back up the private key securely. Never send it with Oniflow."

