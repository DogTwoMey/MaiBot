<#
.SYNOPSIS
  Create a portable backup of MaiBot user data for migration to another machine.

.DESCRIPTION
  Packs `config/` and `data/` (with ephemeral subdirs excluded) into a
  timestamped tar.gz in the project root. Before packing, checkpoints the
  SQLite WAL so the copy is consistent.

  Must be run while bot.py is NOT running. The script will refuse to continue
  if it sees python.exe holding a lock on data\MaiBot.db.

.PARAMETER IncludeLogs
  Also include the logs/ directory. Default: off.

.PARAMETER IncludePlugins
  Also include installed plugins under data/plugins/. Default: on.

.PARAMETER Output
  Output file path. Defaults to backup\maibot-backup-<timestamp>.tar.gz in
  the project root.

.EXAMPLE
  .\scripts\backup.ps1
  Produces backup\maibot-backup-20260423-153042.tar.gz

.EXAMPLE
  .\scripts\backup.ps1 -Output D:\transfer\maibot.tar.gz
#>

[CmdletBinding()]
param(
    [switch]$IncludeLogs,
    [switch]$NoPlugins,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

# 1. Resolve project root (parent of this script's directory)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir '..')
Set-Location $projectRoot

Write-Host "[backup] Project root: $projectRoot" -ForegroundColor Cyan

# 2. Sanity check: config + data must exist
foreach ($required in @('config', 'data')) {
    if (-not (Test-Path $required)) {
        Write-Host "[backup] ERROR: required directory '$required' not found in $projectRoot" -ForegroundColor Red
        exit 1
    }
}

# 3. Refuse to run if anyone has the DB open (rough heuristic)
$dbPath = Join-Path $projectRoot 'data\MaiBot.db'
if (Test-Path $dbPath) {
    try {
        $fs = [System.IO.File]::Open($dbPath, 'Open', 'Read', 'None')
        $fs.Close()
    } catch {
        Write-Host "[backup] ERROR: data\MaiBot.db is locked by another process." -ForegroundColor Red
        Write-Host "        Stop bot.py first, then re-run this script." -ForegroundColor Yellow
        exit 1
    }
}

# 4. WAL checkpoint (best-effort; skip silently if sqlite3 isn't on PATH)
$sqlite3 = Get-Command sqlite3.exe -ErrorAction SilentlyContinue
if ($sqlite3 -and (Test-Path $dbPath)) {
    Write-Host "[backup] Running WAL checkpoint..." -ForegroundColor Cyan
    & sqlite3.exe $dbPath "PRAGMA wal_checkpoint(TRUNCATE);" | Out-Null
} else {
    Write-Host "[backup] sqlite3.exe not found on PATH - skipping checkpoint." -ForegroundColor DarkYellow
    Write-Host "        (The .db-wal/.db-shm files will be copied as-is, which is safe but larger.)" -ForegroundColor DarkYellow
}

# 5. Figure out output path
if (-not $Output) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $projectRoot 'backup'
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }
    $Output = Join-Path $backupDir "maibot-backup-$stamp.tar.gz"
}

Write-Host "[backup] Output: $Output" -ForegroundColor Cyan

# 6. Build exclude list (passed via tar --exclude)
$excludes = @(
    'data/a-memorix/web_import_tmp',
    'data/a-memorix/web_import_reports',
    'temp',
    '**/__pycache__',
    '**/*.pyc'
)
if (-not $IncludeLogs) {
    $excludes += 'logs'
}
if ($NoPlugins) {
    $excludes += 'data/plugins'
}

# 7. Which top-level directories to include
$includePaths = @('config', 'data')
if ($IncludeLogs -and (Test-Path 'logs')) {
    $includePaths += 'logs'
}

# 8. tar.exe is available by default on Windows 10 1803+
$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if (-not $tar) {
    Write-Host "[backup] ERROR: tar.exe not found. Install Git for Windows or upgrade to Windows 10 1803+." -ForegroundColor Red
    exit 1
}

# 9. Run tar
$excludeArgs = $excludes | ForEach-Object { @('--exclude', $_) }
$tarArgs = @('-czf', $Output) + $excludeArgs + $includePaths

Write-Host "[backup] Packing $($includePaths -join ', ') ..." -ForegroundColor Cyan
& tar.exe @tarArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[backup] tar failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 10. Report size and done
$sizeMB = [math]::Round((Get-Item $Output).Length / 1MB, 2)
Write-Host ""
Write-Host "[backup] Done. $Output ($sizeMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "To restore on another machine:" -ForegroundColor Cyan
Write-Host "  1. Clone the MaiBot repo at the same commit" -ForegroundColor Gray
Write-Host "  2. cd into its root" -ForegroundColor Gray
Write-Host "  3. tar -xzf maibot-backup-XXX.tar.gz" -ForegroundColor Gray
Write-Host "  4. Install deps, build dashboard, then: python bot.py" -ForegroundColor Gray
