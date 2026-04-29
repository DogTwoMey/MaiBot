# MaiBot 统一工作区 · 部署文档

> 一个仓库部署 MaiBot 主程序 + Napcat Adapter + NapCatQQ 三个组件。
> 适用对象：新机器首次部署、日常运维、从上游同步。

---

## 0. 本 fork 相对 upstream 的改动

以下是 `DogTwoMey/MaiBot` 相对 `Mai-with-u/MaiBot` 的新增/改造，日常维护时务必了解：

| 项目 | upstream 状态 | 本 fork 状态 |
|------|---------------|-------------|
| 仓库结构 | 单仓 MaiBot | 主仓 + 2 个 submodule：`external/adapter`（Napcat Adapter）、`external/napcat-src`（NapCatQQ 源码） |
| 启动方式 | 各仓单独跑 `python bot.py`、`python main.py`、`run.bat` | [scripts/launcher.py](../../scripts/launcher.py) 统一启停三件套（顺序启动 + 端口探活）|
| NapCat 发布 | 使用上游 release 二进制 | [scripts/build_napcat.py](../../scripts/build_napcat.py) 从源码构建到 `runtime/napcat/` |
| Python 运行 | 随意 | 强制用 uv 管理的 venv（`uv run --no-sync python ...`）|
| 初始化流程 | 手工 `pip install` + 手动拷 config | [scripts/bootstrap.py](../../scripts/bootstrap.py) 一键 clone 后初始化（submodule + upstream remote + uv sync + launcher.toml）|
| 上游同步 | 手工 `git merge upstream/main` | [scripts/sync_upstream.py](../../scripts/sync_upstream.py) 批量处理主仓 + 子仓 |
| PyCharm 运行配置 | 无 | [.run/](../../.run/) 下 9 个共享 run config（启动/停止/状态/构建/同步/apisource）|
| API Source 切换 | 手工改 model_config.toml | [apisource/manage.py](../../apisource/manage.py) + [.run/](../../.run/) 里预置 Aliyun/DeepSeek high 档 |

**不修改**的部分：bot.py / adapter main.py / NapCat 源码本身 —— fork 只改工程/部署层，业务代码维持与 upstream 一致以便合入。

合并上游的策略见 [merge_main_into_upstream_dev.md](merge_main_into_upstream_dev.md)。

---

## 1. 项目结构

```
MaiBot/                              # 主仓库（origin: DogTwoMey/MaiBot, upstream: Mai-with-u/MaiBot）
├── bot.py                           # 主程序入口
├── pyproject.toml / uv.lock         # MaiBot 的 uv 项目
├── config/                          # MaiBot 配置（bot_config.toml / model_config.toml / ...）
├── external/                        # 子仓库挂载点（submodule，各自独立 .git）
│   ├── adapter/                     # DogTwoMey/MaiBot-Napcat-Adapter (upstream: Mai-with-u/...)
│   │   ├── main.py
│   │   ├── config.toml              # ← 适配器配置（gitignored）
│   │   └── data/NapcatAdapter.db    # ← 适配器 SQLite（gitignored）
│   └── napcat-src/                  # DogTwoMey/NapCatQQ (upstream: NapNeko/NapCatQQ) —— 只做构建源码
├── runtime/                         # 运行时产物，整个 gitignored
│   ├── napcat/                      # build_napcat.py 的输出：NapCat 可运行的 shell
│   │   ├── launcher-win10.bat
│   │   ├── NapCatWinBootMain.exe, NapCatWinBootHook.dll, napcat.mjs, ...
│   │   └── config/                  # NapCat 登录态、插件、WebUI 配置（napcat_<QQ>.json 等）
│   └── launcher-logs/               # launcher 的 .pid 与隐藏模式日志
├── scripts/
│   ├── bootstrap.py                 # 一键 clone 后初始化
│   ├── build_napcat.py              # 编译 NapCat 源码 → runtime/napcat
│   ├── launcher.py                  # 统一启停三件套
│   ├── launcher.toml.example        # 配置模板（入库）
│   ├── launcher.toml                # 本机配置（gitignored）
│   └── sync_upstream.py             # 批量从 upstream 同步到 origin
└── docs/
    ├── fork/                        # 本 fork 专属文档（本文档所在目录）
    │   ├── deployment.md            # 本文档
    │   └── merge_main_into_upstream_dev.md  # 上游合并策略
    └── *.md                         # 上游原生文档（i18n/a_memorix/minimal-cross-platform 等）
```

组件 = 三个独立 git 仓库：
- 主仓库 MaiBot
- `external/adapter` 子模块
- `external/napcat-src` 子模块（只是构建源码；真正运行的 shell 在 `runtime/napcat/`）

每个子模块 `.gitmodules` 里钉了 `branch = main`，`upstream` remote 通过 [scripts/bootstrap.py](../../scripts/bootstrap.py) 在首次部署时补齐，不随仓库发布。

---

## 2. 环境要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Git | 任意近版 | 拉代码、submodule |
| Python | 3.11+ | 运行 MaiBot/adapter/脚本 |
| **uv** | 最新 | 所有 Python 命令的入口（venv 管理） |
| Node.js | ≥ 18 | NapCatQQ 构建 |
| **pnpm** | 最新 | NapCatQQ workspace 构建 |
| Windows | 10/11 | NapCat 依赖 Windows 原生注入 |
| psutil（Python） | — | 由 `uv sync` 安装到 MaiBot 主 venv |

安装提示（首次）：
```powershell
# uv（官方安装器）
irm https://astral.sh/uv/install.ps1 | iex
# pnpm（若已有 Node）
npm install -g pnpm
```

> **运行原则**：所有 Python 命令必须用 `uv run python ...` 在 uv 构造的 `.venv` 中执行。主仓库和 `external/adapter` **各自**拥有独立 `.venv`。

---

## 3. 新机器部署（三步）

```powershell
# 3.1 克隆（带上 --recurse-submodules 自动拉两个 submodule）
rtk git clone --recurse-submodules git@github.com:DogTwoMey/MaiBot.git
cd MaiBot

# 3.2 一键 bootstrap：补 upstream remote + uv sync 主仓+adapter + 拷 launcher.toml
rtk uv run python scripts/bootstrap.py

# 3.3 构建 NapCat shell（需要先装好 Node.js 和 pnpm）
rtk uv run python scripts/build_napcat.py
```

或用一条命令替代 3.2 + 3.3：

```powershell
rtk uv run python scripts/bootstrap.py --build-napcat
```

[scripts/bootstrap.py](../../scripts/bootstrap.py) 幂等，可重复运行；[scripts/build_napcat.py](../../scripts/build_napcat.py) 会保留 `runtime/napcat/{config,cache,logs,plugins}` 下的用户状态不被覆盖。

---

## 4. 配置文件清单

所有用户状态都不入库（在各自 `.gitignore` 里）。首次部署需要你填的东西：

### 4.1 MaiBot 主程序

| 文件 | 说明 |
|------|------|
| [config/bot_config.toml](../config/bot_config.toml) | bot 主配置（监听端口等） |
| [config/model_config.toml](../config/model_config.toml) | LLM 模型配置 |
| `.env` | 环境变量（HOST/PORT 等；被 adapter 的 maibot_server 段引用） |

### 4.2 Adapter（`external/adapter/`）

| 文件 | 说明 |
|------|------|
| `config.toml` | 连接 NapCat/MaiBot 的 WS 参数、群白名单、debug 等级 |
| `data/NapcatAdapter.db` | 适配器 SQLite；会话状态 |
| `template/template_config.toml` | 模板（入库，不动） |

首次复制模板：
```powershell
Copy-Item d:/Toy/MaiBot/external/adapter/template/template_config.toml `
          -Destination d:/Toy/MaiBot/external/adapter/config.toml
```

**关键字段**（参考现有值）：
- `[napcat_server].host/port` = `localhost` / `8095`，必须与 NapCat WS 监听一致
- `[maibot_server].host/port` = `localhost` / `8000`，必须与 bot `.env` 一致
- `[chat].group_list_type` + `group_list`：群聊白/黑名单

### 4.3 NapCat（`runtime/napcat/config/`）

首次运行 NapCat 会生成：
- `napcat_<QQ>.json` — OneBot WS 服务器端口、token
- `napcat_protocol_<QQ>.json` — QQ 协议伪装参数
- `onebot11_<QQ>.json` — OneBot 11 标准配置
- `webui.json` — WebUI 端口和密码

确保 `napcat_<QQ>.json` 里 OneBot WS 端口 = adapter 的 `napcat_server.port`（默认 8095）。

### 4.4 启动器（`scripts/launcher.toml`）

由 bootstrap 从 [launcher.toml.example](../../scripts/launcher.toml.example) 拷出。**必须修改**：

```toml
[napcat]
launcher  = "launcher-win10.bat"   # Win10 用这个；更新版 Windows 可用 launcher.bat
qq_number = "2460714978"           # 填你的 QQ 号；留空 "" 则扫码登录
extra_args = []                    # 额外 positional args 转发给 launcher bat

[adapter]
argv          = ["uv", "run", "python", "main.py"]
ready_port    = 18002              # adapter 监听端口；launcher 用它做就绪探测
ready_timeout = 30

[bot]
argv          = ["uv", "run", "python", "bot.py"]
```

> `qq_number` 取代了旧 `run.bat` 里硬编码的 `./launcher-win10.bat 2460714978`。空串走二维码登录，等价于老 `launcher-win10.bat` 不带参数调用。

---

## 5. 启动与停止

所有命令从 MaiBot 根目录执行。

```powershell
# 启动（默认：三个独立 cmd 窗口各显各的日志）
rtk uv run python scripts/launcher.py start

# 只起某个组件
rtk uv run python scripts/launcher.py start adapter

# 启动但隐藏某个组件的窗口（输出走到 runtime/launcher-logs/<name>.log）
rtk uv run python scripts/launcher.py start --hide napcat
rtk uv run python scripts/launcher.py start --hide napcat --hide adapter

# 停止（反向顺序：bot → adapter → napcat）
rtk uv run python scripts/launcher.py stop
rtk uv run python scripts/launcher.py stop adapter

# 重启
rtk uv run python scripts/launcher.py restart
rtk uv run python scripts/launcher.py restart bot --hide bot

# 查看隐藏模式的日志
rtk uv run python scripts/launcher.py logs napcat --tail 200
```

**启动顺序**（`[startup].order` 配）：`napcat` → `adapter` → `bot`，中间用 TCP 端口探活做就绪门槛（`ready_port` / `ready_timeout`）。

**探活规则**（默认全部关闭，fire-and-forget）：
- 三个组件的 `ready_port` 默认都是 `0` —— `launcher.py start` 依次 spawn 三个窗口，不等任何一个就绪，三个 cmd 窗口几乎同时出现
- 各组件自己有 retry 逻辑：adapter 连不上 bot/napcat 会循环重连，bot 连不上 adapter 不影响自身启动
- 如需重新启用探活（比如想让 adapter 在 NapCat 真正 listen 后再启动），把 `[napcat].ready_port` 改回 `8095` + `ready_timeout = 30` 即可；当探活的进程中途退出，launcher 会立即短路不再死等

**管理员权限**：NapCat 必须以管理员身份运行（QQ 进程注入需要）。launcher 提供两种路径：

| 策略 | 配置 | 行为 |
|------|------|------|
| **让 launcher 自己提权（默认）** | `[napcat].elevate = true` | 若当前非 admin，launcher 主动调用 Windows `ShellExecuteEx('runas')` 弹 UAC 起 NapCat，返回真实的 admin PID，`stop/status` 照常工作 |
| **外层已经是 admin** | `[napcat].elevate = false` | 完全跳过提权逻辑；需要你用"以管理员身份运行" 启动 PyCharm 或终端后再跑 launcher |

⚠️ 绝对**不要**用 `elevate = false` 从非 admin shell 启动 —— 届时 `launcher-win10.bat` 会自己再次 `Start-Process -Verb runAs` 弹出一个独立 admin 窗口，launcher 追踪不到真正干活的 PID，`stop` 也杀不到它。症状就是看到控制台输出 `Please run this script in administrator mode.`。

---

## 5.1 PyCharm 运行配置

仓库在 [.run/](../../.run/) 下内置了 9 个即用的 PyCharm Run Configuration（PyCharm / IntelliJ 系会自动发现该目录）。首次使用需要做一次解释器绑定：

### 步骤一：把 `.venv` 绑为项目解释器（**必须是 Virtualenv 类型，不要选 uv 类型**）

1. **File → Settings → Project: MaiBot → Python Interpreter**
2. 齿轮图标 → **Add Interpreter → Add Local Interpreter → Select existing**
3. **Type 选 Virtualenv Environment**（⚠ 不要选 uv）
4. Interpreter 填 `D:/Toy/MaiBot/.venv/Scripts/python.exe`（`uv sync` 创建的 venv）
5. 确认 `.run/` 里 run configs 的 `Use specified interpreter` 指向该 SDK
6. 可把旧的 "uv (MaiBot)" SDK 移除，防止误选

> **为什么不选 uv 类型**：PyCharm 的 uv 解释器每次 Run 都包一层 `uv run <python> <script>`，uv 默认要 `uv sync` 一次 —— 当前仓库有在跑的进程持有 `.venv/Lib/.../_rust.pyd` 时，sync 会失败（`Access Denied`）。
>
> 选 Virtualenv 类型则 PyCharm 直接调 `.venv\Scripts\python.exe`，零 sync 干扰。依赖管理仍用 uv（手动 `rtk uv sync` 即可），两者互不冲突。

（可选）给 `external/adapter/` 单独添加一个 Project 或把它作为独立 module 指向 `external/adapter/.venv/Scripts/python.exe`——如果你要在 PyCharm 里直接 debug adapter 源码。日常启停不需要。

### 步骤二：在 Run/Debug Configurations 下拉里就能看到下列条目

| Run Config | 等价命令 | 用途 |
|------------|---------|------|
| `Bootstrap` | `scripts/bootstrap.py` | 首次部署后一键补 upstream + uv sync |
| `Build NapCat` | `scripts/build_napcat.py` | 构建 NapCat shell |
| `Launcher: Start All` | `scripts/launcher.py start` | 启动三件套，开 3 个 cmd 窗口 |
| `Launcher: Stop All` | `scripts/launcher.py stop` | 按反向顺序停 |
| `Launcher: Restart All` | `scripts/launcher.py restart` | 停后重启 |
| `Sync Upstream` | `scripts/sync_upstream.py --apply` | merge + push 主仓和所有子仓 |
| `ApiSource: Aliyun High` | `apisource/manage.py --provider aliyun --tier high --apply` | 把阿里云 high 档写入 `config/model_config.toml` |
| `ApiSource: DeepSeek High` | `apisource/manage.py --provider deepseek --tier high --apply` | 把 DeepSeek high 档写入配置 |

**注**：没预置单组件启动（Bot/Adapter/NapCat Only）、`--clean` 重建 —— 需要时在 PyCharm 里 **Copy Configuration** 改 `Parameters` 即可，保持 `.run/` 清爽。

所有配置都以 `$PROJECT_DIR$` 为工作目录，开启 `EMULATE_TERMINAL=true`（输出带颜色），环境变量 `PYTHONUNBUFFERED=1`（日志实时）。

### 需要 debug MaiBot 本体

上面的 `Launcher: Start All` 适合日常启动，但**不是 debug 入口**——它派生子进程到独立 cmd 窗口，PyCharm 拦不到断点。如需 debug：

1. 手动用 `Launcher: Start NapCat Only` + `Launcher: Start Adapter Only` 起前置两件
2. 对 `bot.py` 直接建一个 **Python** run config：
   - Script path: `$PROJECT_DIR$/bot.py`
   - Working dir: `$PROJECT_DIR$`
   - Interpreter: 项目 `.venv`
3. Debug 这个 config 即可命中 bot 侧断点。adapter 同理——在 `external/adapter/main.py` 上建一个 run config，解释器指向 `external/adapter/.venv/Scripts/python.exe`。

### 自定义参数

最方便的方式是在 PyCharm 里 **Run → Edit Configurations → Copy Configuration** 一份出来再改 `Parameters`。例如想要 `start --hide napcat --hide adapter`，直接改参数即可。改好的配置会落到 `.idea/workspace.xml`（你个人的），不影响 `.run/` 里的共享版本。

### 关于 `.run/` 目录的仓库策略

[.run/](../../.run/) 现在入库，方便多机共享 PyCharm 运行配置。

---

## 6. 日常维护

### 6.1 从上游同步

```powershell
# 干跑：看每个仓库 upstream 领先了几个 commit
rtk uv run python scripts/sync_upstream.py

# merge + push 所有仓库（主仓 + 两个 submodule）
rtk uv run python scripts/sync_upstream.py --apply

# 仅同步 adapter
rtk uv run python scripts/sync_upstream.py --apply --only adapter

# 用 rebase 而非 merge
rtk uv run python scripts/sync_upstream.py --apply --rebase
```

同步 submodule 后，主仓会显示 submodule 指针前进，提交：

```powershell
rtk git -C d:/Toy/MaiBot add external/adapter external/napcat-src
rtk git -C d:/Toy/MaiBot commit -m "chore: bump submodules"
rtk git -C d:/Toy/MaiBot push
```

### 6.2 NapCat 重建

上游 NapCatQQ 更新后：

```powershell
# 1. sync napcat-src submodule 到 upstream
rtk uv run python scripts/sync_upstream.py --apply --only napcat-src

# 2. 重新构建；--clean 会清掉旧产物（但保留 config/cache/logs/plugins）
rtk uv run python scripts/build_napcat.py --clean
```

### 6.3 依赖升级

```powershell
# MaiBot 主仓
rtk uv -C d:/Toy/MaiBot sync --upgrade
# Adapter
rtk uv -C d:/Toy/MaiBot/external/adapter sync --upgrade
# NapCat 源（pnpm）
pnpm -C d:/Toy/MaiBot/external/napcat-src install
```

### 6.4 切换 LLM 服务商（apisource）

[apisource/manage.py](../../apisource/manage.py) 可把预设的 provider + tier 合并进 `config/model_config.toml`。每次 apply 会自动备份当前 config（带时间戳后缀）。

**合并规则**（重要）：
- `[[api_providers]]` / `[[models]]`：按 provider 归属合并，不覆盖其它 provider（切 DeepSeek 不会删掉已有的 Aliyun `api_key` 和模型清单）
- `model_task_config` 各功能位（replyer / planner / utils / ...）：**独占替换**。本 provider 覆盖的 slot 会被**完全替换**为本 provider 的模型，绝不与其它 provider 混用 —— 换完 provider 后该功能位只调本次指定的模型，不会偷偷 fallback 到旧的
- Provider 不涉及的 slot（如 DeepSeek 不管 voice/embedding/vlm）：**原样保留**，换 chat provider 不会误伤已配好的语音/嵌入

```powershell
rtk uv run python apisource/manage.py --provider aliyun   --tier high --apply
rtk uv run python apisource/manage.py --provider deepseek --tier high --apply
```

终端会打印 `[apply] <slot> 替换剔除: [...]` 告诉你每个功能位丢掉了哪些旧条目，供核对。

可用 tier：`low / mid / high / extreme / free`（aliyun 五档齐全；deepseek 按模板生成）。

仓库只内置了 `high` 档的 4 个 PyCharm run config（Aliyun / DeepSeek × Apply / DryRun）。需要其他档位时在 PyCharm 里 **Copy Configuration** 改 `Parameters` 里的 `--tier high` 为目标 tier 即可。

---

## 7. 目录与 gitignore 规则

| 目录/文件 | 入库？ | 说明 |
|-----------|--------|------|
| `external/` | 以 submodule 条目形式入库 | `.gitmodules` 管理 |
| `external/adapter/config.toml` | 否 | 由 adapter 仓的 `.gitignore` 忽略 |
| `external/adapter/data/` | 否 | 同上 |
| `runtime/` | 否 | 主仓 `.gitignore` 已排除整个目录 |
| `scripts/launcher.toml` | 否 | 主仓 `.gitignore` 已排除 |
| `scripts/launcher.toml.example` | 是 | 模板随仓库走 |
| `.run/` | 是 | PyCharm 共享运行配置，随仓库走 |
| `.idea/` | 否 | PyCharm 私有工作区 |

---

## 8. 故障排查

### 8.1 NapCat 的 QQ.exe 残留

`launcher.py stop napcat` 只杀 launcher bat 启动的进程树。QQ.exe 通过 DLL 注入启动，可能残留：

```powershell
Stop-Process -Name QQ -Force -ErrorAction SilentlyContinue
```

或直接用 NapCat 自带的 `runtime/napcat/KillQQ.bat`。

### 8.2 Submodule 指针漂移

子模块内 checkout 新 commit 后，主仓 `git status` 会显示 `modified: external/adapter (new commits)`。**必须** `git add external/adapter && git commit` 才会记录这个指针，否则 push 上去别人 pull 不到新版本。

### 8.3 `_rust.pyd: 拒绝访问 (os error 5)` / 其他 `Access Denied`

症状：bot 或 adapter 启动时在 cmd 窗口里打印 `failed to remove file ... _rust.pyd: 拒绝访问` 然后立刻退出。

原因：有孤立的旧 Python 进程（上次启动残留）还占着 `.venv` 下的 DLL；`uv run` 默认启动时要同步环境，尝试替换该文件失败。两个成因：

1. launcher 的 PID 文件指向的 cmd 已退出，但孙子进程 python 还活着 —— `stop` 杀不到它
2. `uv run` 每次运行都会 `uv sync` 一次（哪怕 lockfile 没变），启动更慢且和在跑的 Python 抢文件

项目现已：
- 默认使用 `uv run --no-sync` 调 Python（见 [launcher.toml](../../scripts/launcher.toml) 的 `[adapter].argv` 与 `[bot].argv`），绕过启动时 sync
- 依赖变化时手动跑 `rtk uv sync` 即可

应急清理：
```powershell
# 找到并杀掉残留的 MaiBot Python
Get-Process | Where-Object { $_.Path -like '*MaiBot*' -and $_.ProcessName -eq 'python' } | Stop-Process -Force
# 清理陈旧 PID 文件
Remove-Item d:/Toy/MaiBot/runtime/launcher-logs/*.pid -Force -ErrorAction SilentlyContinue
```

### 8.4 NapCat admin 窗口启动后报 `ERR_MODULE_NOT_FOUND: Cannot find package 'express'`

原因：`runtime/napcat/` 下缺 `node_modules/`。NapCat 的 `napcat.mjs` 在运行时 import `express`、`ws` 等 —— 这些是 vite 构建不打进 bundle 的外部依赖。

修复：现 [scripts/build_napcat.py](../../scripts/build_napcat.py) 构建末尾会自动跑 `npm install --omit=dev` 填充 `runtime/napcat/node_modules/`。如果是老构建产物，补一次即可：

```powershell
cd d:/Toy/MaiBot/runtime/napcat
npm install --omit=dev --no-audit --no-fund
```

或跑一次完整重建：`rtk uv run python scripts/build_napcat.py --clean`。想跳过 node 依赖安装（已有 cache）：加 `--no-runtime-deps`。

### 8.5 NapCat 管理员窗口弹出但 `'launcher-win10.bat' 不是内部或外部命令`

原因：UAC 提权后的 cmd 默认工作目录是 `C:\Windows\system32`，`ShellExecuteEx` 的 `lpDirectory` 在跨 UAC 边界时被 Windows 安全策略忽略。[scripts/launcher.py](../../scripts/launcher.py) 的 `start_napcat` 已把 `cd /d "<napcat path>"` 显式嵌入 cmd 参数修复此问题。若仍出现，检查 `[paths].napcat` 是否正确指向有 `launcher-win10.bat` 的目录。

### 8.6 adapter 启动后立刻退出

多半是 `config.toml` 缺失或 `[napcat_server].port` 与 NapCat 实际端口不匹配。先看 `runtime/launcher-logs/adapter.log`（隐藏模式）或 adapter 的 cmd 窗口输出。

### 8.7 bootstrap 跑失败

- `uv` 找不到：先装 uv 并确保在 PATH 里
- submodule 没拉下来：手动跑 `git submodule update --init --recursive`
- upstream 已存在：bootstrap 会跳过这一步（幂等）

### 8.8 跨平台

launcher 的"三个 cmd 窗口"行为依赖 Windows 的 `CREATE_NEW_CONSOLE`，非 Windows 环境下退化为在当前终端前台运行（且 NapCat 本身只支持 Windows）。

---

## 9. 相关文档

- [merge_main_into_upstream_dev.md](merge_main_into_upstream_dev.md) —— main ⇄ upstream/dev 合并策略
- 上游原生文档索引见 [docs/README.md](../README.md)
