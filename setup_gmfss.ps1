param(
    [string]$Python = "C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Repo = Join-Path $Root "work\GMFSS_Fortuna"
$Venv = Join-Path $Root "work\gmfss-venv"

if (-not (Test-Path $Python)) {
    throw "Python tidak ditemukan: $Python"
}

if (-not (Test-Path $Repo)) {
    git clone --depth 1 https://github.com/98mxr/GMFSS_Fortuna.git $Repo
}

if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
& $VenvPython -m pip install cupy-cuda12x matplotlib opencv-python rawpy scipy scikit-video scikit-image tqdm tensorboard lpips gdown tkinterdnd2 customtkinter psutil
& $VenvPython -m pip install "pillow>=12.2.0" "setuptools>=78.1.1,<82"
& $VenvPython -m pip check

Copy-Item (Join-Path $Root "config.example.json") (Join-Path $Root "config.json") -Force

Write-Host ""
Write-Host "Dependensi selesai dipasang."
Write-Host "Unduh model Union anime dari tautan Model Zoo GMFSS_Fortuna."
Write-Host "Ekstrak folder train_log ke: $Repo"
