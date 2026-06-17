param(
    [switch]$SignFiles
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "build_release.ps1") -NativeLauncher -SignFiles:$SignFiles
if ($LASTEXITCODE -ne 0) { throw "Native Oniflow release build failed." }

