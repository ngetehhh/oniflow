param(
    [switch]$NativeLauncher,
    [switch]$SignFiles
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "work\gmfss-venv\Scripts\python.exe"
$DependencySitePackages = Join-Path $Root "work\gmfss-venv\Lib\site-packages"
$IntegrityAdmin = Join-Path $Root "integrity_admin.py"
$Dist = Join-Path $Root "dist"
$LauncherDist = Join-Path $Dist "launcher-build"
$NativeDist = Join-Path $Dist "nuitka-launcher"
$ReleaseRoot = Join-Path $Root "release\Oniflow"
$PortableRuntime = Join-Path $ReleaseRoot "work\python-runtime"
$LauncherSource = Join-Path $Root "oniflow_launcher.py"
$IconPath = Join-Path $Root "assets\oniflow.ico"
$ReleaseDocuments = @(
    "VERSION",
    "HELP.md",
    "EULA.md",
    "PRIVACY.md",
    "THIRD_PARTY_NOTICES.md",
    "UPDATE_POLICY.md",
    "DISTRIBUTION_SECURITY.md",
    "RELEASE_CHECKLIST.md"
)

if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
    $DependencySitePackages = (& $Python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
    Write-Host "Using current Python runtime: $Python"
}
if (-not (Test-Path $IntegrityAdmin)) {
    throw "Owner-only integrity_admin.py is missing. Keep it local and outside public GitHub before building a signed release."
}
$BasePython = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
if (-not (Test-Path (Join-Path $BasePython "python.exe"))) { throw "Base Python runtime is missing." }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $LauncherDist
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $NativeDist
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $ReleaseRoot
New-Item -ItemType Directory -Force $ReleaseRoot | Out-Null
if ($NativeLauncher) {
    & $Python -m pip show nuitka *> $null
    if ($LASTEXITCODE -ne 0) { throw "Nuitka is missing. Run setup_native_build.ps1 first." }
    New-Item -ItemType Directory -Force $NativeDist | Out-Null
    & $Python -m nuitka --mode=onefile --windows-console-mode=disable --assume-yes-for-downloads `
        --output-dir=$NativeDist --output-filename=Oniflow.exe `
        --windows-icon-from-ico=$IconPath $LauncherSource
    if ($LASTEXITCODE -ne 0) { throw "Native Oniflow launcher build failed." }
    Copy-Item -Force (Join-Path $NativeDist "Oniflow.exe") (Join-Path $ReleaseRoot "Oniflow.exe")
} else {
    & $Python -m pip show pyinstaller *> $null
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller is missing. Install it before creating a standard release." }
    & $Python -m PyInstaller --noconfirm --clean --windowed --name Oniflow --distpath $LauncherDist --icon $IconPath $LauncherSource
    if ($LASTEXITCODE -ne 0) { throw "Oniflow launcher build failed. Close any running portable Oniflow instance and try again." }
    Copy-Item -Recurse -Force (Join-Path $LauncherDist "Oniflow\*") $ReleaseRoot
}

New-Item -ItemType Directory -Force (Join-Path $ReleaseRoot "work\GMFSS_Fortuna") | Out-Null
robocopy (Join-Path $Root "work\GMFSS_Fortuna") (Join-Path $ReleaseRoot "work\GMFSS_Fortuna") /E /XD ".git" "__pycache__" "temp" "vid_out" /XF "*.pyc" "*.pyo" | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Failed to copy the GMFSS backend." }
New-Item -ItemType Directory -Force $PortableRuntime | Out-Null
robocopy $BasePython $PortableRuntime /E /XD "__pycache__" "site-packages" "venv" /XF "*.pyc" "*.pyo" | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Failed to copy the standalone Python runtime." }
New-Item -ItemType Directory -Force (Join-Path $PortableRuntime "Lib\site-packages") | Out-Null
$PortableSitePackages = Join-Path $PortableRuntime "Lib\site-packages"
Copy-Item -Path (Join-Path $DependencySitePackages "*") -Destination $PortableSitePackages -Recurse -Force
$SitePackages = Join-Path $PortableRuntime "Lib\site-packages"
$PrunedRuntimePackages = @(
    "PyInstaller",
    "pyinstaller-*",
    "nuitka",
    "Nuitka-*",
    "ordered_set*",
    "zstandard*",
    "tensorboard",
    "tensorboard-*",
    "matplotlib",
    "matplotlib-*",
    "imageio_ffmpeg",
    "imageio_ffmpeg-*",
    "absl",
    "absl-*",
    "cyclonedx",
    "cyclonedx-*",
    "cryptography",
    "cryptography-*",
    "fontTools",
    "fonttools-*",
    "fsspec",
    "fsspec-*",
    "google",
    "grpc",
    "grpcio-*",
    "jinja2",
    "jinja2-*",
    "networkx",
    "networkx-*",
    "pygments",
    "pygments-*",
    "playwright",
    "playwright-*",
    "rawpy",
    "rawpy-*",
    "rich",
    "rich-*",
    "skimage",
    "scikit_image-*",
    "sympy",
    "sympy-*",
    "werkzeug",
    "werkzeug-*",
    "pip",
    "pip-*",
    "setuptools",
    "setuptools-*"
)
foreach ($PackagePattern in $PrunedRuntimePackages) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $SitePackages $PackagePattern)
}
$PrunedRuntimePaths = @(
    (Join-Path $PortableRuntime "include"),
    (Join-Path $PortableRuntime "Lib\site-packages\torch\include"),
    (Join-Path $PortableRuntime "Lib\site-packages\torch\share"),
    (Join-Path $PortableRuntime "Lib\site-packages\torch\test"),
    (Join-Path $PortableRuntime "Lib\site-packages\torch\utils\tensorboard")
)
foreach ($RuntimePath in $PrunedRuntimePaths) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RuntimePath
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $SitePackages "skvideo\datasets\data")
Get-ChildItem -Path $SitePackages -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like "*.dll.a" -or
        $_.Extension -in @(".lib", ".h", ".hpp", ".pxd", ".pyx", ".whl")
    } |
    Remove-Item -Force
Copy-Item -Force (Join-Path $Root "anime_vfi.py") (Join-Path $ReleaseRoot "anime_vfi.py")
Copy-Item -Force (Join-Path $Root "anime_vfi_gui.py") (Join-Path $ReleaseRoot "anime_vfi_gui.py")
Copy-Item -Force (Join-Path $Root "offline_license.py") (Join-Path $ReleaseRoot "offline_license.py")
Copy-Item -Force (Join-Path $Root "runtime_security.py") (Join-Path $ReleaseRoot "runtime_security.py")
Copy-Item -Force (Join-Path $Root "config.json") (Join-Path $ReleaseRoot "config.json")
Copy-Item -Force (Join-Path $Root "activation_config.json") (Join-Path $ReleaseRoot "activation_config.json")
Copy-Item -Force (Join-Path $Root "update_config.json") (Join-Path $ReleaseRoot "update_config.json")
New-Item -ItemType Directory -Force (Join-Path $ReleaseRoot "assets") | Out-Null
Copy-Item -Force (Join-Path $Root "assets\oniflow-logo.png") (Join-Path $ReleaseRoot "assets\oniflow-logo.png")
Copy-Item -Force (Join-Path $Root "assets\oniflow.ico") (Join-Path $ReleaseRoot "assets\oniflow.ico")
Copy-Item -Force (Join-Path $Root "assets\offline-license-public.json") (Join-Path $ReleaseRoot "assets\offline-license-public.json")
$ReleaseConfigPath = Join-Path $ReleaseRoot "config.json"
$ReleaseConfig = Get-Content $ReleaseConfigPath -Raw | ConvertFrom-Json
foreach ($Profile in @("gmfss_anime", "gmfss_live_action")) {
    $ReleaseConfig.$Profile.command[0] = "{project_root}\work\python-runtime\python.exe"
}
$ReleaseConfigJson = $ReleaseConfig | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($ReleaseConfigPath, $ReleaseConfigJson, [System.Text.UTF8Encoding]::new($false))
$ProtectedPythonFiles = @("anime_vfi.py", "anime_vfi_gui.py", "offline_license.py", "runtime_security.py")
foreach ($ProtectedFile in $ProtectedPythonFiles) {
    $SourcePath = Join-Path $ReleaseRoot $ProtectedFile
    $BytecodePath = [System.IO.Path]::ChangeExtension($SourcePath, ".pyc")
    & (Join-Path $PortableRuntime "python.exe") -c "import py_compile; py_compile.compile(r'$SourcePath', cfile=r'$BytecodePath', doraise=True)"
    if ($LASTEXITCODE -ne 0) { throw "Failed to protect $ProtectedFile." }
    Remove-Item -Force $SourcePath
}
foreach ($Document in $ReleaseDocuments) {
    Copy-Item -Force (Join-Path $Root $Document) (Join-Path $ReleaseRoot $Document)
}
New-Item -ItemType Directory -Force (Join-Path $ReleaseRoot "tools") | Out-Null
Copy-Item -Force (Get-Command ffmpeg).Source (Join-Path $ReleaseRoot "tools\ffmpeg.exe")
Copy-Item -Force (Get-Command ffprobe).Source (Join-Path $ReleaseRoot "tools\ffprobe.exe")
$PreviousBytecodeSetting = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = "1"
& (Join-Path $PortableRuntime "python.exe") -c "import cv2, numpy, skvideo.io, torch; print('Standalone runtime OK:', torch.__version__, torch.cuda.is_available())"
$env:PYTHONDONTWRITEBYTECODE = $PreviousBytecodeSetting
if ($LASTEXITCODE -ne 0) { throw "Standalone runtime validation failed." }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $ReleaseRoot "logs")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $ReleaseRoot "user_settings.json")
Get-ChildItem -Path $ReleaseRoot -Directory -Recurse -Force -Filter "__pycache__" |
    Remove-Item -Recurse -Force
if ($SignFiles) {
    & (Join-Path $Root "sign_oniflow.ps1") -Paths @((Join-Path $ReleaseRoot "Oniflow.exe"))
}
& $Python $IntegrityAdmin $ReleaseRoot
if ($LASTEXITCODE -ne 0) { throw "Signed integrity manifest creation failed." }
& $Python (Join-Path $Root "release_audit.py") $ReleaseRoot
if ($LASTEXITCODE -ne 0) { throw "Release security audit failed." }
Write-Host "Portable release created at release\Oniflow"
