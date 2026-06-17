$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot "work\gmfss-venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    throw "Environment GMFSS belum tersedia. Jalankan setup_gmfss.ps1 terlebih dahulu."
}

Start-Process -FilePath $Python -ArgumentList "`"$PSScriptRoot\anime_vfi_gui.py`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
