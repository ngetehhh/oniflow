param(
    [switch]$InstallBuildTools
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "work\gmfss-venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Oniflow Python environment is missing." }

& $Python -m pip install --upgrade nuitka ordered-set zstandard
if ($LASTEXITCODE -ne 0) { throw "Nuitka installation failed." }

if ($InstallBuildTools) {
    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $Winget) { throw "winget is unavailable. Install Visual Studio 2022 Build Tools manually." }
    & $Winget.Source install --id Microsoft.VisualStudio.2022.BuildTools --exact `
        --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    if ($LASTEXITCODE -ne 0) { throw "Visual Studio Build Tools installation failed." }
}

Write-Host "Nuitka is ready."
Write-Host "Run '.\setup_native_build.ps1 -InstallBuildTools' if Visual Studio C++ Build Tools are not installed."
Write-Host "Then build with '.\build_native_release.ps1'."

