$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root 'frontend\src-tauri\binaries'
$work = Join-Path $root 'build\sidecar'
$python = Join-Path $root '.venv\Scripts\python.exe'
$picData = "$(Join-Path $root 'pic');pic"
if (-not (Test-Path $python)) { $python = 'python' }
New-Item -ItemType Directory -Force -Path $out | Out-Null

& $python -m PyInstaller --noconfirm --clean --onefile --name backend `
  --add-data $picData `
  --distpath $out --workpath (Join-Path $work 'backend') --specpath $work `
  (Join-Path $root 'backend\main.py')
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name overlay `
  --distpath $out --workpath (Join-Path $work 'overlay') --specpath $work `
  (Join-Path $root 'overlay.py')

if ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64') {
  Move-Item (Join-Path $out 'backend.exe') (Join-Path $out 'backend-x86_64-pc-windows-msvc.exe') -Force
  Move-Item (Join-Path $out 'overlay.exe') (Join-Path $out 'overlay-x86_64-pc-windows-msvc.exe') -Force
}
Write-Host "HeroFlow sidecars created in $out"
