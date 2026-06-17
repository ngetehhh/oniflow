param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$BundledPython = "C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\anime_vfi.py" @Arguments
} elseif (Test-Path $BundledPython) {
    & $BundledPython "$PSScriptRoot\anime_vfi.py" @Arguments
} else {
    throw "Python 3.11 atau lebih baru belum terpasang."
}

exit $LASTEXITCODE
