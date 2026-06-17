param(
    [Parameter(Mandatory = $true)][string[]]$Paths,
    [string]$Subject = "CN=Oniven Test Signing"
)

$ErrorActionPreference = "Stop"
$Certificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date) } |
    Select-Object -First 1
if (-not $Certificate) {
    throw "Test signing certificate not found. Run create_test_signing_certificate.ps1 first."
}

foreach ($Path in $Paths) {
    $Resolved = Resolve-Path $Path
    $Result = Set-AuthenticodeSignature -FilePath $Resolved.Path -Certificate $Certificate -HashAlgorithm SHA256
    $Verified = Get-AuthenticodeSignature -FilePath $Resolved.Path
    if (-not $Verified.SignerCertificate -or $Verified.SignerCertificate.Thumbprint -ne $Certificate.Thumbprint) {
        throw "Signing verification failed for $Resolved. The expected Oniven test certificate was not applied."
    }
    if ($Verified.Status -notin @("Valid", "UnknownError", "NotTrusted")) {
        throw "Signing failed for $Resolved. Status: $($Verified.Status)"
    }
    Write-Host "Signed: $Resolved"
}

Write-Host "Self-signed files are intended only for private testing."
