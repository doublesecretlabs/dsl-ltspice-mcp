# Builds a standalone dsl-ltspice-mcp-<arch>.exe with PyInstaller.
# The exe matches the machine it's built on: run it on an x64 PC for the x64
# build and on a Windows ARM PC for the ARM64 build.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Build output goes to a local folder (PyInstaller and numpy don't work
# reliably from network drives); the finished exe is copied to .\dist.
param(
    [string]$BuildDir = "$env:LOCALAPPDATA\dsl-ltspice-mcp-build"
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Keep the build venv on local disk; PyInstaller scans every installed file.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $BuildDir 'venv'
$env:UV_LINK_MODE = 'copy'
uv sync --dev
if (-not $?) { throw "uv sync failed" }

$python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
$machine = & $python -c "import platform; print(platform.machine())"
$arch = if ($machine -match 'ARM64|aarch64') { 'arm64' } else { 'x64' }
$name = "dsl-ltspice-mcp-$arch"
$work = Join-Path $BuildDir 'work'
$dist = Join-Path $BuildDir 'dist'

& $python -m PyInstaller --noconfirm --clean --onefile --console `
    --name $name `
    --distpath $dist --workpath $work --specpath $work `
    --paths (Join-Path $PSScriptRoot 'src') `
    --add-data "$(Join-Path $PSScriptRoot 'src\dsl_ltspice_mcp\data\symbols.json');dsl_ltspice_mcp\data" `
    (Join-Path $PSScriptRoot 'src\dsl_ltspice_mcp\__main__.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'dist') | Out-Null
Copy-Item (Join-Path $dist "$name.exe") (Join-Path $PSScriptRoot 'dist') -Force
Write-Host "Built dist\$name.exe"
