<#
.SYNOPSIS
  用于迁移的一站式备份脚本，打包所有不在版本控制下的配置、数据与产物。

.DESCRIPTION
  将以下组件的用户态打成一个带时间戳的 tar.gz：

    ▸ 核心配置    config/（bot_config.toml, model_config.toml 等）
    ▸ 运行数据    data/（MaiBot.db, a-memorix/, images/, emoji/ 等）
    ▸ 用户插件    plugins/（第三方插件代码 + config.toml + data/）
    ▸ 启动器配置  scripts/launcher.toml
    ▸ API 源产物  apisource/*/output/, apisource/aliyun/response_cn_*.json
    ▸ Adapter     external/adapter/config.toml + data/
    ▸ NapCat      runtime/napcat/config/ + plugins/
    ▸ 前端产物    dashboard/dist/（可选，-IncludeDist）
    ▸ 私有文档    docs/private/（可选，-IncludePrivateDocs）
    ▸ 日志        logs/（可选，-IncludeLogs）
    ▸ 杂项        .env, eula.confirmed, privacy.confirmed

  可重建目录默认不包含（.venv, node_modules, napcat 缓存, __pycache__）。

  打包前自动对 SQLite 做 WAL checkpoint（需 sqlite3.exe 在 PATH）。
  若数据库被进程占用会拒绝运行——请先停止服务。

.PARAMETER IncludeLogs
  包含 logs/ 目录（所有组件）。默认关闭。

.PARAMETER IncludeDist
  包含 dashboard/dist/（前端构建产物，可 npm run build 重建）。默认关闭。

.PARAMETER IncludePrivateDocs
  包含 docs/private/（私有文档子模块）。默认关闭。

.PARAMETER IncludeNapcatCache
  包含 runtime/napcat/cache/（QQ 媒体缓存，体积大）。默认关闭。

.PARAMETER NoNapcatPlugins
  跳过 runtime/napcat/plugins/。

.PARAMETER NoAdapter
  跳过 Napcat Adapter 用户态。

.PARAMETER NoNapcatRuntime
  跳过 runtime/napcat/ 整体。

.PARAMETER NoPlugins
  跳过 plugins/ 目录（MaiBot 第三方插件）。

.PARAMETER Output
  输出路径。默认 backup/maibot-workspace-<时间戳>.tar.gz。

.EXAMPLE
  .\scripts\backup.ps1
  默认备份（核心配置 + 数据 + 插件）。需先停止服务。

.EXAMPLE
  .\scripts\backup.ps1 -IncludeLogs -IncludePrivateDocs -IncludeDist
  完整归档，含日志、私有文档与前端产物。

.EXAMPLE
  .\scripts\backup.ps1 -Output D:\transfer\maibot.tar.gz
#>

[CmdletBinding()]
param(
    [switch]$IncludeLogs,
    [switch]$IncludeDist,
    [switch]$IncludePrivateDocs,
    [switch]$IncludeNapcatCache,
    [switch]$NoNapcatPlugins,
    [switch]$NoAdapter,
    [switch]$NoNapcatRuntime,
    [switch]$NoPlugins,
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

# launcher.toml — 统一启动器配置（QQ 号、端口等）
if (Test-Path 'scripts/launcher.toml') {
    $includePaths += 'scripts/launcher.toml'
}

# MaiBot 第三方插件（代码 + 各插件 config.toml + data/）
if ((-not $NoPlugins) -and (Test-Path 'plugins')) {
    $includePaths += 'plugins'
}

# .env 环境变量文件
if (Test-Path '.env') {
    $includePaths += '.env'
}

# 合规确认标记
foreach ($marker in @('eula.confirmed', 'privacy.confirmed')) {
    if (Test-Path $marker) { $includePaths += $marker }
}

# apisource 生成的产物（模型注册表、API 探测缓存等）
foreach ($providerDir in (Get-ChildItem -Path 'apisource' -Directory -ErrorAction SilentlyContinue)) {
    $outputDir = Join-Path $providerDir.FullName 'output'
    if (Test-Path $outputDir) {
        $includePaths += ($outputDir | Resolve-Path -Relative) -replace '\\','/'
    }
    # aliyun 的 response_cn_*.json 缓存
    $responseFiles = Get-ChildItem -Path $providerDir.FullName -Filter 'response_cn_*.json' -ErrorAction SilentlyContinue
    foreach ($f in $responseFiles) {
        $includePaths += ($f.FullName | Resolve-Path -Relative) -replace '\\','/'
    }
    # price.md 等手动维护的辅助文件
    $priceMd = Join-Path $providerDir.FullName 'price.md'
    if (Test-Path $priceMd) {
        $includePaths += ($priceMd | Resolve-Path -Relative) -replace '\\','/'
    }
}

# Adapter 用户态
if ($includeAdapter) {
    if (Test-Path "$adapterRoot/config.toml") { $includePaths += "$adapterRoot/config.toml" }
    if (Test-Path "$adapterRoot/data")        { $includePaths += "$adapterRoot/data" }
    if ($IncludeLogs -and (Test-Path "$adapterRoot/logs")) {
        $includePaths += "$adapterRoot/logs"
    }
}

# NapCat 运行时用户态
if ($includeNapcat) {
    if (Test-Path "$napcatRoot/config")                  { $includePaths += "$napcatRoot/config" }
    if ((-not $NoNapcatPlugins) -and (Test-Path "$napcatRoot/plugins")) { $includePaths += "$napcatRoot/plugins" }
    if ($IncludeNapcatCache   -and (Test-Path "$napcatRoot/cache"))   { $includePaths += "$napcatRoot/cache" }
    if ($IncludeLogs          -and (Test-Path "$napcatRoot/logs"))    { $includePaths += "$napcatRoot/logs" }
}

# 前端构建产物
if ($IncludeDist -and (Test-Path 'dashboard/dist')) {
    $includePaths += 'dashboard/dist'
}

# 私有文档子模块
if ($IncludePrivateDocs -and (Test-Path 'docs/private')) {
    $includePaths += 'docs/private'
}

# 日志
if ($IncludeLogs -and (Test-Path 'logs')) {
    $includePaths += 'logs'
}

$excludes = @(
    'data/a-memorix/web_import_tmp',
    'data/a-memorix/web_import_reports',
    'data/playwright-browsers',
    'plugins/hello_world_plugin',
    'plugins/emoji_manage_plugin',
    'plugins/__init__.py',
    'temp',
    '**/__pycache__',
    '**/*.pyc',
    '**/*.pyo',
    '**/.venv',
    '**/node_modules'
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
$itemCount = $includePaths.Count
Write-Host ""
Write-Host "[backup] 完成！$Output ($sizeMB MB, $itemCount 个路径)" -ForegroundColor Green
Write-Host ""
Write-Host "迁移恢复步骤：" -ForegroundColor Cyan
Write-Host "  1. git clone --recurse-submodules <your-fork-url>" -ForegroundColor Gray
Write-Host "  2. cd MaiBot" -ForegroundColor Gray
Write-Host "  3. tar -xzf maibot-workspace-XXX.tar.gz" -ForegroundColor Gray
Write-Host "  4. uv sync                              # 重建 Python 虚拟环境" -ForegroundColor Gray
Write-Host "  5. cd dashboard && npm install && npm run build && cd .." -ForegroundColor Gray
Write-Host "  6. uv run python bot.py                 # 或使用 JetBrains 启动配置" -ForegroundColor Gray
