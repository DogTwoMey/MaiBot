<#
.SYNOPSIS
  Portable backup of user state across the unified MaiBot workspace.

.DESCRIPTION
  Packs the three components' user state into one timestamped tar.gz:

    * MaiBot main repo:           config/, data/, scripts/launcher.toml
    * Napcat Adapter submodule:   external/adapter/config.toml,
                                  external/adapter/data/
    * NapCat runtime:             runtime/napcat/config/
                                  (login tokens, onebot11_<QQ>.json, webui.json)

  Ephemeral / rebuildable directories are excluded by default
  (node_modules, napcat cache, tmp/temp, pycache, build artifacts).

  WAL-checkpoints both SQLite DBs (MaiBot.db + NapcatAdapter.db) before
  packing if sqlite3.exe is on PATH. Refuses to run if either DB is
  locked by a live Python process.

.PARAMETER IncludeLogs
  Include logs/ dirs from all three components. Default: off.

.PARAMETER IncludeNapcatCache
  Include runtime/napcat/cache/ (QQ chat/media blobs; large). Default: off.

.PARAMETER NoNapcatPlugins
  Skip runtime/napcat/plugins/. Default: plugins are included.

.PARAMETER NoAdapter
  Skip Napcat Adapter user state. Default: off.

.PARAMETER NoNapcatRuntime
  Skip runtime/napcat/ entirely. Default: off.

.PARAMETER Output
  Output file path. Default: backup/maibot-workspace-<timestamp>.tar.gz.

.EXAMPLE
  .\scripts\backup.ps1
  Default bundle. Stop launcher (bot/adapter/napcat) first.

.EXAMPLE
  .\scripts\backup.ps1 -IncludeLogs -IncludeNapcatCache
  Full archive including history logs and QQ cache (much larger).

.EXAMPLE
  .\scripts\backup.ps1 -Output D:\transfer\maibot.tar.gz
#>

[CmdletBinding()]
param(
    [switch]$IncludeLogs,
    [switch]$IncludeNapcatCache,
    [switch]$NoNapcatPlugins,
    [switch]$NoAdapter,
    [switch]$NoNapcatRuntime,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# 1. Resolve project root (parent of this script's dir)
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir '..')
Set-Location $projectRoot

Write-Host "[backup] Project root: $projectRoot" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 2. Required directories (MaiBot main)
foreach ($required in @('config', 'data')) {
    if (-not (Test-Path $required)) {
        Write-Host "[backup] ERROR: required '$required' not found in $projectRoot" -ForegroundColor Red
        exit 1
    }
}

# Optional components
$adapterRoot = 'external/adapter'
$napcatRoot  = 'runtime/napcat'
$includeAdapter = (-not $NoAdapter)          -and (Test-Path $adapterRoot)
$includeNapcat  = (-not $NoNapcatRuntime)    -and (Test-Path $napcatRoot)

if ($NoAdapter -or -not (Test-Path $adapterRoot)) {
    Write-Host "[backup] adapter: skipped (NoAdapter=$NoAdapter, exists=$((Test-Path $adapterRoot)))" -ForegroundColor DarkYellow
}
if ($NoNapcatRuntime -or -not (Test-Path $napcatRoot)) {
    Write-Host "[backup] napcat runtime: skipped" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# 3. Refuse if any SQLite DB is locked
function Test-FileLocked {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'None')
        $fs.Close()
        return $false
    } catch {
        return $true
    }
}

$dbsToCheck = @()
$dbsToCheck += @{ Path = 'data\MaiBot.db'; Owner = 'bot.py' }
if ($includeAdapter) {
    $dbsToCheck += @{ Path = 'external\adapter\data\NapcatAdapter.db'; Owner = 'adapter main.py' }
}

foreach ($db in $dbsToCheck) {
    if (Test-FileLocked $db.Path) {
        Write-Host "[backup] ERROR: $($db.Path) is locked by another process." -ForegroundColor Red
        Write-Host "        Stop $($db.Owner) first (rtk uv run python scripts/launcher.py stop), then retry." -ForegroundColor Yellow
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 4. WAL checkpoint both DBs
$sqlite3 = Get-Command sqlite3.exe -ErrorAction SilentlyContinue
if ($sqlite3) {
    foreach ($db in $dbsToCheck) {
        if (Test-Path $db.Path) {
            Write-Host "[backup] WAL checkpoint: $($db.Path)" -ForegroundColor Cyan
            & sqlite3.exe $db.Path "PRAGMA wal_checkpoint(TRUNCATE);" | Out-Null
        }
    }
} else {
    Write-Host "[backup] sqlite3.exe not on PATH - skipping checkpoints (still safe, just larger)." -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# 5. Output path
if (-not $Output) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $projectRoot 'backup'
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }
    $Output = Join-Path $backupDir "maibot-workspace-$stamp.tar.gz"
}
Write-Host "[backup] Output: $Output" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 6. Build include/exclude lists
$includePaths = @('config', 'data')
# launcher.toml is tiny but critical — bring it if the user has one.
if (Test-Path 'scripts/launcher.toml') {
    $includePaths += 'scripts/launcher.toml'
}

if ($includeAdapter) {
    if (Test-Path "$adapterRoot/config.toml") { $includePaths += "$adapterRoot/config.toml" }
    if (Test-Path "$adapterRoot/data")        { $includePaths += "$adapterRoot/data" }
    if ($IncludeLogs -and (Test-Path "$adapterRoot/logs")) {
        $includePaths += "$adapterRoot/logs"
    }
}

if ($includeNapcat) {
    if (Test-Path "$napcatRoot/config")                  { $includePaths += "$napcatRoot/config" }
    if ((-not $NoNapcatPlugins) -and (Test-Path "$napcatRoot/plugins")) { $includePaths += "$napcatRoot/plugins" }
    if ($IncludeNapcatCache   -and (Test-Path "$napcatRoot/cache"))   { $includePaths += "$napcatRoot/cache" }
    if ($IncludeLogs          -and (Test-Path "$napcatRoot/logs"))    { $includePaths += "$napcatRoot/logs" }
}

if ($IncludeLogs -and (Test-Path 'logs')) {
    $includePaths += 'logs'
}

$excludes = @(
    'data/a-memorix/web_import_tmp',
    'data/a-memorix/web_import_reports',
    'temp',
    '**/__pycache__',
    '**/*.pyc',
    '**/*.pyo'
)

# ---------------------------------------------------------------------------
# 7. tar.exe
$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if (-not $tar) {
    Write-Host "[backup] ERROR: tar.exe not found. Install Git for Windows or upgrade to Win10 1803+." -ForegroundColor Red
    exit 1
}

$excludeArgs = $excludes | ForEach-Object { @('--exclude', $_) }
$tarArgs = @('-czf', $Output) + $excludeArgs + $includePaths

Write-Host ""
Write-Host "[backup] Packing:" -ForegroundColor Cyan
foreach ($p in $includePaths) { Write-Host "          + $p" -ForegroundColor Gray }
Write-Host ""

& tar.exe @tarArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[backup] tar failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------------------
# 8. Report
$sizeMB = [math]::Round((Get-Item $Output).Length / 1MB, 2)
Write-Host ""
Write-Host "[backup] Done. $Output ($sizeMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "To restore on another machine:" -ForegroundColor Cyan
Write-Host "  1. git clone --recurse-submodules git@github.com:DogTwoMey/MaiBot.git" -ForegroundColor Gray
Write-Host "  2. cd MaiBot" -ForegroundColor Gray
Write-Host "  3. tar -xzf maibot-workspace-XXX.tar.gz" -ForegroundColor Gray
Write-Host "  4. uv run python scripts/bootstrap.py --build-napcat" -ForegroundColor Gray
Write-Host "  5. uv run python scripts/launcher.py start" -ForegroundColor Gray
