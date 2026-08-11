param(
    [Parameter(Mandatory=$true)][string]$FromVersion,
    [Parameter(Mandatory=$true)][string]$ToVersion,
    [Parameter(Mandatory=$true)][string]$OldReleaseDir,
    [Parameter(Mandatory=$false)][string]$NewReleaseDir = "release\Oniflow",
    [Parameter(Mandatory=$false)][string]$OutputDir = "installer-output"
)

$ErrorActionPreference = "Stop"

$OldRoot = Resolve-Path $OldReleaseDir
$NewRoot = Resolve-Path $NewReleaseDir
$OutRoot = New-Item -ItemType Directory -Force -Path $OutputDir
$StageRoot = Join-Path $OutRoot.FullName "patch-stage-$FromVersion-to-$ToVersion"
$ZipPath = Join-Path $OutRoot.FullName "Oniflow-Patch-$FromVersion-to-$ToVersion.zip"
$SumPath = Join-Path $OutRoot.FullName "Oniflow-Patch-$FromVersion-to-$ToVersion.sha256.txt"

if (Test-Path $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null

$changed = 0
$runtimeChanged = $false
Get-ChildItem -LiteralPath $NewRoot -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($NewRoot.Path.Length).TrimStart([char[]]'\\')
    $oldFile = Join-Path $OldRoot.Path $relative
    $copy = $true
    if (Test-Path -LiteralPath $oldFile) {
        $oldHash = (Get-FileHash -LiteralPath $oldFile -Algorithm SHA256).Hash
        $newHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        $copy = $oldHash -ne $newHash
    }
    if ($copy) {
        if ($relative -like "work\python-runtime\*") {
            $runtimeChanged = $true
            return
        }
        $target = Join-Path $StageRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        $changed += 1
    }
}

if ($runtimeChanged) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
    throw "The bundled Python runtime changed. Publish the full installer for this version instead of a patch update."
}

if ($changed -eq 0) {
    throw "No changed files found between $OldReleaseDir and $NewReleaseDir."
}

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal -Force
$hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
"$hash  $(Split-Path $ZipPath -Leaf)" | Set-Content -Path $SumPath -Encoding ascii

Write-Host "Patch created: $ZipPath"
Write-Host "Changed files: $changed"
Write-Host "SHA256: $hash"
