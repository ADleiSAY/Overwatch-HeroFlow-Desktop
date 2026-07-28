$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$frontendPublic = Join-Path $root 'frontend\public'
$heroes = Join-Path $frontendPublic 'heroes'
$fontTarget = Join-Path $frontendPublic 'fonts'
New-Item -ItemType Directory -Force -Path $heroes | Out-Null
New-Item -ItemType Directory -Force -Path $fontTarget | Out-Null

$heroSource = Get-ChildItem -LiteralPath (Join-Path $root 'pic') -Directory |
  Where-Object { Get-ChildItem -LiteralPath $_.FullName -Filter '*.png' -File } |
  Select-Object -First 1
if ($heroSource) {
  Get-ChildItem -LiteralPath $heroSource.FullName -Filter '*.png' -File |
    Copy-Item -Destination $heroes -Force
}

$fontSource = Join-Path $root 'fonts\HarmonyOS Sans'
Copy-Item -LiteralPath (Join-Path $fontSource 'HarmonyOS_Sans_SC.ttf') -Destination $fontTarget -Force
Copy-Item -LiteralPath (Join-Path $fontSource 'HarmonyOS_Sans_Condensed.ttf') -Destination $fontTarget -Force
Write-Host "HeroFlow hero and font assets synced"
