param(
    [string]$Subject = "CN=Oniven Test Signing",
    [int]$Years = 3
)

$ErrorActionPreference = "Stop"
$Existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Select-Object -First 1
if ($Existing) {
    Write-Host "Existing test certificate: $($Existing.Thumbprint)"
    exit 0
}

$Certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject `
    -CertStoreLocation Cert:\CurrentUser\My -KeyAlgorithm RSA -KeyLength 3072 `
    -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears($Years)

Write-Host "Test code-signing certificate created."
Write-Host "Thumbprint: $($Certificate.Thumbprint)"
Write-Host "This certificate is for private testing only. Windows will not publicly trust it."

