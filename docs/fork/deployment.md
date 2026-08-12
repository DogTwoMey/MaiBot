# MaiBot 统一工作区部署文档

> 一个仓库部署 MaiBot、默认 NapCat Adapter 插件与 NapCatQQ。
> 适用于新机器首次部署、日常启停、备份和上游同步。

## 0. 本 fork 的工程层改动

| 项目 | 本 fork 状态 |
|---|---|
| NapCat Adapter | 位于 `src/plugins/built_in/napcat_adapter/`，作为默认插件随 MaiBot 启动，不再维护独立进程、Python 环境或 Git 子模块 |
| NapCatQQ 源码 | `external/napcat-src` 子模块，构建产物写入 `runtime/napcat/` |
| 私有文档 | `docs/private` 子模块，设置 `update = none` |
| 初始化 | `scripts/bootstrap.py` 初始化子模块、同步主环境并创建启动器配置 |
| 启停 | `scripts/launcher.py` 统一管理 NapCat 与 MaiBot；Adapter 由插件运行时管理 |
| 备份 | `scripts/backup.ps1` 备份主程序、插件和 NapCat 用户状态 |

业务层的长期分歧见 [design_divergence.md](design_divergence.md)。

## 1. 项目结构

```text
MaiBot/
├── bot.py
├── pyproject.toml / uv.lock
├── config/
├── data/
├── plugins/                              # 用户安装的第三方插件
├── src/plugins/built_in/
│   ├── plugin_management/
│   └── napcat_adapter/                   # 随主程序发布的默认 Adapter 插件
│       ├── plugin.py
│       ├── _manifest.json
│       └── config.toml                   # 本机配置，受插件目录 .gitignore 保护
├── external/
│   └── napcat-src/                       # NapCatQQ 源码子模块
├── runtime/
│   ├── napcat/                           # NapCat 构建产物与登录状态
│   └── launcher-logs/
└── scripts/
    ├── bootstrap.py
    ├── build_napcat.py
    ├── launcher.py
    ├── launcher.toml.example
    ├── sync_upstream.py
    └── backup.ps1
```

主仓、`external/napcat-src` 和 `docs/private` 是各自独立的 Git 边界。Adapter 源码属于主仓，不再单独同步或提交指针。

## 2. 环境要求

| 工具 | 版本 | 用途 |
|---|---|---|
| Git | 近版 | 拉取主仓和子模块 |
| Python | 3.11+ | 运行 MaiBot 和工具脚本 |
| uv | 最新 | 管理主仓 Python 环境 |
| Node.js | 18+ | 构建 NapCatQQ |
| pnpm | 最新 | 构建 NapCatQQ workspace |
| Windows | 10/11 | 运行 NapCatQQ |

Adapter 使用主仓已有的插件 SDK、Pydantic 与标准库依赖，不再拥有独立 `requirements.txt`、`pyproject.toml`、`uv.lock` 或 `.venv`。

## 3. 新机器部署

```powershell
git clone --recurse-submodules git@github.com:DogTwoMey/MaiBot.git
Set-Location MaiBot

uv run python scripts/bootstrap.py --build-napcat
```

`bootstrap.py` 会同步主仓依赖、初始化仍在使用的子模块，并在缺失时从 `scripts/launcher.toml.example` 创建 `scripts/launcher.toml`。

## 4. 配置

### 4.1 MaiBot

- `config/bot_config.toml`
- `config/model_config.toml`
- `.env`

这些是本机运行配置，不应提交密钥或账号信息。

### 4.2 默认 NapCat Adapter 插件

配置文件为：

```text
src/plugins/built_in/napcat_adapter/config.toml
```

常用配置：

- `napcat_server.host` / `napcat_server.port`：NapCat OneBot WebSocket 地址。
- `chat.group_list_type` / `chat.group_list`：群聊名单策略。
- `plugin.enabled`：是否启用默认 Adapter。

插件由 MaiBot 的内置插件 Supervisor 加载。不要再创建 `external/adapter` Python 环境，也不要单独运行 `main.py`。

### 4.3 NapCatQQ

NapCat 用户状态位于 `runtime/napcat/config/`。确保 OneBot WebSocket 监听地址与 Adapter 插件的 `napcat_server` 配置一致。

### 4.4 启动器

`scripts/launcher.toml` 只配置 NapCat 与 Bot：

```toml
[paths]
napcat = "runtime/napcat"
bot_root = "."

[startup]
order = ["napcat", "bot"]
```

## 5. 启停

```powershell
# 启动 NapCat 与 MaiBot；Adapter 随 Bot 加载
uv run python scripts/launcher.py start

# 查看日志
uv run python scripts/launcher.py logs bot

# 停止
uv run python scripts/launcher.py stop
```

## 6. 日常维护

### 6.1 同步上游

```powershell
# 预览
uv run python scripts/sync_upstream.py

# 同步主仓与仍存在的子模块
uv run python scripts/sync_upstream.py --apply

# 仅同步 NapCatQQ 源码
uv run python scripts/sync_upstream.py --apply --only napcat-src
```

需要直接合并 MaiBot 上游时使用完整远端引用，避免同名本地分支歧义：

```powershell
git fetch upstream --prune
git merge --no-ff refs/remotes/upstream/main
git merge --no-ff refs/remotes/upstream/dev
```

### 6.2 重建 NapCatQQ

```powershell
uv run python scripts/build_napcat.py --clean
```

### 6.3 备份

```powershell
uv run python scripts/launcher.py stop
.\scripts\backup.ps1
```

默认备份主程序配置和数据、第三方插件、默认 Adapter 插件配置，以及 NapCat 登录状态。运行时构建产物和依赖环境不进入备份。

### 6.4 升级依赖

```powershell
uv sync --upgrade
pnpm -C external/napcat-src install
```

Adapter 已使用主仓环境，不再执行单独的依赖同步。

## 7. Git 与迁移规则

| 路径 | 入库 | 说明 |
|---|---|---|
| `src/plugins/built_in/napcat_adapter/` | 是 | 默认 Adapter 源码 |
| `src/plugins/built_in/napcat_adapter/config.toml` | 否 | 本机插件配置 |
| `external/napcat-src` | gitlink | NapCatQQ 源码子模块 |
| `runtime/` | 否 | 构建产物、日志、PID 与登录状态 |
| `scripts/launcher.toml` | 否 | 本机启动器配置 |
| `scripts/launcher.toml.example` | 是 | 启动器模板 |

从旧布局升级时，把 `plugins/maibot-team_napcat-adapter/config.toml` 或 `external/adapter/config.toml` 中仍需保留的选项迁移到内置插件配置。确认新插件正常运行后，旧目录只作为本地备份保留，不应重新加入主仓或启动流程。

## 8. 故障排查

### Adapter 未加载

1. 检查 `src/plugins/built_in/napcat_adapter/_manifest.json` 是否存在。
2. 检查插件配置中的 `plugin.enabled`。
3. 检查是否仍在 `plugins/` 下保留了同 ID 的旧 Adapter；重复插件 ID 会阻止安全加载。
4. 查看 Bot 日志中的 `plugin.maibot-team.napcat-adapter`。

### NapCat 无法连接

对照 NapCat OneBot WebSocket 监听地址与插件的 `napcat_server` 配置，并检查启动器配置中的 NapCat 路径。

### 子模块指针漂移

Adapter 已不是子模块。当前需要单独提交指针的只有仍使用 gitlink 的目录，例如：

```powershell
git add external/napcat-src
git commit -m "chore: update napcat source"
```
