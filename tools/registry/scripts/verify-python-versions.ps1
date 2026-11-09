<#
.SYNOPSIS
  Runs the whole test suite of tools/registry on other Python versions, isolated from the machine's Python and from the working tree.

.DESCRIPTION
  * Copies tools/registry to a fresh temporary directory (never runs from the working tree; machine-local data is copied only if -WithLocal is given).
  * Uses `uv` to provide each requested interpreter in a private, temporary install directory (UV_PYTHON_INSTALL_DIR) and runs
    `python -B -X utf8 -W error -m unittest discover -s tests -t .` with it. The suite uses only the standard library, so nothing else is installed.
  * DOWNLOADS the interpreters (python-build-standalone, from github.com/astral-sh via uv; roughly 30-40 MB each). Run it only with the owner's consent.
  * Writes one log per version to -LogDir and exits non-zero if any run fails. Does not touch git, the working tree or the registry data.

.EXAMPLE
  .\verify-python-versions.ps1 -Uv C:\path\to\uv.exe -Versions 3.12,3.13 -LogDir C:\path\to\logs
#>
param(
    [Parameter(Mandatory = $true)][string]$Uv,
    [string[]]$Versions = @("3.12", "3.13"),
    [Parameter(Mandatory = $true)][string]$LogDir,
    [switch]$WithLocal,
    [string]$WorkspaceRoot = ""
)
$ErrorActionPreference = "Stop"
$src = Resolve-Path (Join-Path $PSScriptRoot "..")
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("clxreg-pyverify-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp, $LogDir -Force | Out-Null
$copy = Join-Path $tmp "registry"
Copy-Item -Recurse -Path $src -Destination $copy
Get-ChildItem -Path $copy -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
if (-not $WithLocal) { Remove-Item -Recurse -Force (Join-Path $copy "local") -ErrorAction SilentlyContinue }
$env:UV_PYTHON_INSTALL_DIR = Join-Path $tmp "pythons"
$env:UV_CACHE_DIR = Join-Path $tmp "uv-cache"
if ($WorkspaceRoot) { $env:CLX_WORKSPACE_ROOT = $WorkspaceRoot }
$failed = 0
foreach ($v in $Versions) {
    $log = Join-Path $LogDir "python-$v.log"
    Push-Location $copy
    try {
        & $Uv run --no-project --isolated --python $v python --version *> $log
        & $Uv run --no-project --isolated --python $v python -B -X utf8 -W error -m unittest discover -s tests -t . -v *>> $log
        if ($LASTEXITCODE -ne 0) { $failed++; Write-Host "Python ${v}: FAILED (see $log)" } else { Write-Host "Python ${v}: OK (see $log)" }
    } finally { Pop-Location }
}
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
exit $failed
