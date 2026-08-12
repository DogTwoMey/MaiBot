# 两个不同人格 MaiBot 的维护方案

> 调研日期：2026-06-21
> 适用仓库：`DogTwoMey/MaiBot` 当前工作树，以及 `Mai-with-u/MaiBot`、`NapNeko/NapCatQQ` 上游
> 本文讨论的是两个具有不同昵称、人格提示词、表达风格、记忆和学习结果的 Bot，而不只是两个 QQ 登录账号。

## 结论

当前最稳妥的方案是：**使用同一个代码版本或容器镜像，运行两套彼此隔离的 MaiBot 实例；每套实例连接自己的 NapCat 账号，并拥有独立的配置、数据库、日志、插件配置和记忆目录。**

MaiBot 主线已经支持按 `platform + account_id + scope` 路由消息，也会把账号维度纳入聊天流 ID。这解决了“同一平台多个账号应当回复到正确链路”的基础问题，但没有解决“一个进程内存在两套人格”的问题。当前昵称、人格提示词、模型配置、数据库、插件目录和大部分学习状态仍然是进程级全局状态。

因此：

- 两个 QQ 账号共享同一人格：核心层已经具备大部分基础，适配器仍需完善多连接实例管理。
- 两个 QQ 账号分别使用不同人格：当前应运行两个 MaiBot 实例。
- 在一个 MaiBot 进程中原生维护两个完整人格：需要进行多租户级重构，不是配置层修改。

## 调研基线与当前演进

### 2026-06-21 调研快照

调研时的版本状态：

| 组件 | 当前状态 |
| --- | --- |
| 本 fork 主仓 | `0886e7f9`，2026-06-18 |
| 官方 MaiBot `main` | `42c210fa`，2026-06-18 |
| 官方 MaiBot `dev` | `72322e9a`，2026-06-18 |
| 当前 `external/adapter` | `b1839004`，2026-04-26，仍是独立进程版 |
| 官方 NapCat Adapter `main` | `f7f0b4b`，2026-05-20，已经迁移为插件版 |
| 当前 `external/napcat-src` | `8a3faf64`，2026-06-17 |
| 官方 NapCatQQ `main` | `5c18a625`，2026-06-20 |

上述表格是历史调研快照。当前 fork 已完成插件化迁移：

- 已移除 `external/adapter` 子模块和独立进程启动链。
- [`src/plugins/built_in/napcat_adapter`](../../src/plugins/built_in/napcat_adapter/) 是随主程序发布的默认 `MessageGateway` Adapter 插件。
- Adapter 使用主仓依赖和插件运行时，不再单独同步版本、安装依赖或维护 `.venv`。

### 与多账号相关的上游改动

1. 2026-03-20，MaiBot 引入完整的 Platform IO 中间层。`RouteKey` 明确定义了 `platform`、`account_id` 和 `scope`，发送驱动也按该键绑定：
   - [上游提交 `04f260e5`](https://github.com/Mai-with-u/MaiBot/commit/04f260e5)
   - [本地 `RouteKey` 实现](../../src/platform_io/types.py)

2. 2026-03-23，聊天流 ID 开始纳入 `account_id` 和 `scope`。同一群、同一用户通过两个 Bot 账号接入时，可以形成不同的 `session_id`：
   - [上游提交 `0c508995`](https://github.com/Mai-with-u/MaiBot/commit/0c508995)
   - [本地会话 ID 实现](../../src/common/utils/utils_session.py)

3. 2026-04-03，官方 NapCat Adapter 上传完整插件化实现，使用 MaiBot `MessageGateway` 接入：
   - [上游提交 `89671c4`](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter/commit/89671c4)
   - [当前插件入口](../../src/plugins/built_in/napcat_adapter/plugin.py)

4. 插件版 Adapter 会从 NapCat 的 `self_id` 获取账号，向 Host 上报 `account_id`，并把 `self_id`、`connection_id` 写入入站路由元数据：
   - [运行状态上报](../../src/plugins/built_in/napcat_adapter/runtime_state.py)
   - [入站路由构造](../../src/plugins/built_in/napcat_adapter/runtime/router.py)

5. NapCatQQ 当前仍围绕单个运行时的 `selfInfo.uin` 工作，但配置文件按 UIN 分开保存，例如 `napcat_<uin>.json` 和 `onebot11_<uin>.json`。这有利于在同一台机器启动多个账号实例，但不代表一个 NapCat 进程同时承载多个已登录账号：
   - [NapCat per-UIN 配置实现](https://github.com/NapNeko/NapCatQQ/blob/5c18a62530d87dbadf53d267002894faa6ca7e90/packages/napcat-webui-backend/src/api/NapCatConfig.ts#L91-L110)
   - [OneBot per-UIN 配置实现](https://github.com/NapNeko/NapCatQQ/blob/5c18a62530d87dbadf53d267002894faa6ca7e90/packages/napcat-webui-backend/src/api/OB11Config.ts#L19-L22)

### 上游尚未解决的边界

账号级路由与人格级隔离是两个不同问题。目前仍有以下单例或全局状态：

- `bot.nickname`、`personality.personality`、`reply_style` 来自同一份全局配置；Prompt 构造直接读取 `global_config`：[人格配置](../../src/config/official_configs.py)、[Prompt 构造](../../src/chat/replyer/maisaka_generator_base.py)。
- 主配置与模型配置固定读取项目根目录下的 `config/bot_config.toml` 和 `config/model_config.toml`：[配置路径](../../src/config/config.py)。
- SQLite 固定为项目根目录下的 `data/MaiBot.db`：[数据库路径](../../src/common/database/database.py)。
- 日志默认写入当前工作目录的 `logs/`：[日志路径](../../src/common/logger.py)。
- 插件版 NapCat Adapter 的配置模型只有一个 `napcat_server`，一个插件实例只维护一个传输连接：[插件配置](../../src/plugins/built_in/napcat_adapter/config.py)。
- Host 的消息网关运行状态以 `plugin_id + gateway_name` 标识驱动；同一个网关重复上报另一个账号时，会替换现有驱动，而不是自然增加第二条实例路由：[网关驱动注册](../../src/plugin_runtime/host/supervisor.py)。

## 方案总览

| 方案 | 人格隔离 | 数据隔离 | 资源占用 | 改造成本 | 运维风险 | 建议 |
| --- | --- | --- | --- | --- | --- | --- |
| A. 两个容器/服务实例，共用同一镜像 | 完整 | 完整 | 较高 | 低 | 低 | 生产环境首选 |
| B. 同一主机两个项目根目录、两个进程 | 完整 | 完整 | 较高 | 低 | 中 | 当前 Windows 部署首选 |
| C. 单进程，通过插件按账号注入不同人格 | 部分 | 很弱 | 低 | 中 | 高 | 仅适合实验 |
| D. 单进程原生多人格重构 | 可完整 | 可完整 | 较低 | 很高 | 中至高 | 长期架构方案 |
| E. 两个进程共享同一个数据库或数据目录 | 不可靠 | 无 | 中 | 表面低 | 极高 | 不应采用 |

## 方案 A：两个容器或系统服务，共用同一镜像

### 结构

```text
同一个 MaiBot 版本/镜像
├─ maibot-persona-a
│  ├─ bot_config A / model_config A
│  ├─ data A / logs A / plugins config A
│  └─ napcat-a（QQ A）
└─ maibot-persona-b
   ├─ bot_config B / model_config B
   ├─ data B / logs B / plugins config B
   └─ napcat-b（QQ B）
```

可以共享的只有不可变代码、镜像层、LLM 服务端点、代理服务和只读知识库。配置卷、数据库卷、记忆目录、插件数据与 NapCat 登录态必须分开。

### 优点

- 人格、昵称、表达风格、群聊 Prompt、模型选择和插件配置完全独立。
- `MaiBot.db`、A-Memorix、表达学习、黑话学习、人物关系和图片缓存不会串人格。
- 一个 Bot 崩溃、升级失败或 QQ 掉线，不会直接拖垮另一个 Bot。
- 两个实例可以使用同一镜像标签，减少“代码版本不同但配置看起来相同”的排障成本。
- 可以先升级其中一个实例做金丝雀验证，再升级另一个。

### 缺点

- MaiBot、插件 Runner、NapCat 和模型客户端各运行两份，内存与后台任务约为双份。
- WebUI、消息服务、NapCat OneBot WS 和 NapCat WebUI 都要分配不同端口。
- 需要维护两套密钥、备份、健康检查和日志采集配置。
- 当前 fork 没有现成的双实例 Compose 文件，需要补充部署编排。

### 适用场景

- 长期运行。
- 两个人格必须严格避免互相污染。
- 希望独立升级、独立停机或为两个人格使用不同模型预算。

## 方案 B：同一台 Windows 主机使用两个项目根目录

这是当前 fork 最容易落地的方式。两个实例可以来自同一个 release 包、同一个 Git commit 的两个工作目录，或者两个 Git worktree，但运行时根目录必须不同。

### 为什么不能直接从同一目录启动两次

当前代码把以下路径绑定到项目根目录或当前工作目录：

- `config/bot_config.toml`
- `config/model_config.toml`
- `data/MaiBot.db`
- `logs/`
- `plugins/*/config.toml`

仅修改监听端口后从同一目录启动两个 `bot.py`，两个进程仍会读取同一人格、写同一 SQLite 和插件数据。这不是有效的人格隔离，还可能引发数据库锁竞争、配置热更新互相影响和日志混写。

### 推荐目录

```text
D:\MaiBotDeploy\
├─ persona-a\        # 固定到同一个 release/commit
│  ├─ config\
│  ├─ data\
│  ├─ logs\
│  ├─ plugins\
│  └─ runtime\napcat\
└─ persona-b\
   ├─ config\
   ├─ data\
   ├─ logs\
   ├─ plugins\
   └─ runtime\napcat\
```

示例端口规划：

| 端口用途 | 人格 A | 人格 B |
| --- | ---: | ---: |
| MaiBot 消息服务 | 8000 | 8100 |
| MaiBot WebUI | 8001 | 8101 |
| NapCat OneBot WS | 3001 | 3101 |
| NapCat WebUI | 6099 | 6199 |

实际端口应以当前配置模板和本机占用情况为准；关键要求是每个监听端口唯一。

### 优点

- 不需要先改 MaiBot 主程序。
- 与现有 [`scripts/launcher.py`](../../scripts/launcher.py) 的三组件部署思路一致，容易调试。
- 两套实例仍可以固定在同一个 commit，代码升级流程清晰。
- 适合当前以 Windows NapCat shell 为中心的部署。

### 缺点

- 文件级隔离弱于容器，启动脚本写错目录时可能操作到另一实例。
- 两份工作目录、插件目录和 Python 环境会占用更多磁盘。
- Git worktree 配合 submodule、构建产物和本地插件仓库时管理复杂；不熟悉 worktree 时，两个独立 release 目录更稳妥。
- 当前单实例 launcher 需要复制配置或扩展为多 profile 编排。

### 适用场景

- 目前这套本地 Windows 部署。
- 希望尽快上线第二人格，同时保留清晰的人工排障能力。

## 方案 C：单进程，通过插件按账号注入不同人格

做法是让两个 QQ 接入链路都进入一个 MaiBot 进程，然后在 Prompt Hook 或消息预处理 Hook 中根据 `account_id`、`scope` 或真实 `session_id` 注入不同人格提示词。

### 能做到什么

- 两个账号使用不同的临时人格描述、回复语气或群聊说明。
- 复用同一个模型客户端、插件 Runner 和数据库。
- 资源占用低于两个完整实例。

### 无法可靠解决什么

- `global_config.bot.nickname` 仍只有一个值，内置 Prompt、工具返回、自我识别和发送者信息可能出现人格 A 的名字。
- `personality` 和 `reply_style` 的大量读取点不经过单一可替换 Hook。
- 人物信息、表达学习、黑话、长期记忆和插件状态仍在同一数据库/目录中；即使聊天流 ID 按账号区分，也不能证明所有学习与查询路径都具有账号命名空间。
- 插件版 Adapter 当前只有一条连接。复制插件并修改 manifest ID 可能获得两个网关驱动，但固定 API 名称、插件配置和公开能力可能发生冲突，且上游没有把这种部署作为稳定接口承诺。
- 独立进程版与插件版混用，理论上可以形成两条接入链路，但旧 Adapter 不完整携带账号路由元数据，也没有覆盖完整的双人格测试。

### 评价

这是“两个账号看起来语气不同”的实验方案，不是“两个独立人格”的维护方案。除非可以接受记忆串线、名字偶发错误和升级后 Hook 失效，否则不应投入长期运行。

## 方案 D：把单个 MaiBot 进程重构为原生多人格宿主

如果长期目标是用一个进程管理大量 Bot 身份，可以在现有 Platform IO 基础上继续实现多租户人格层。

至少需要完成以下改造：

1. 配置从单例改为列表或映射，例如 `bots[bot_id]`，每项包含账号绑定、昵称、人格、回复风格和模型策略。
2. 引入稳定的内部 `bot_id`。不要直接把 QQ 号当作所有平台的主键；QQ 号只是 `bot_id` 的一个平台账号绑定。
3. 从入站 `RouteKey.account_id/scope` 解析 `bot_id`，并把它加入每次 Planner、Replyer、Tool、Hook 和发送上下文。
4. Prompt 构造不得再直接读取全局 `global_config.bot/personality`，而应读取当前 `BotRuntimeContext`。
5. 数据库中所有人格相关数据增加 `bot_id` 维度，包括聊天流、人物关系、记忆、表达、黑话、统计、工具记录和插件状态。
6. A-Memorix 和其他文件型数据目录按 `bot_id` 分区，或在索引键中加入 `bot_id`。
7. MessageGateway 运行状态从 `plugin_id + gateway_name` 扩展到网关实例维度，使一个插件可以注册多条 `account_id/scope` 路由。
8. NapCat Adapter 配置改为连接列表，每个连接拥有独立 transport、heartbeat、action response pool、API 路由和 `connection_id`。
9. 公开 NapCat API 调用必须显式选择目标账号；不能由“当前唯一连接”隐式决定。
10. 增加跨账号回归测试：同一个群、同一个用户同时向两个 Bot 发言时，Prompt、记忆查询、消息发送和 API 调用都必须命中正确人格。

### 优点

- 一个 Host 可以复用模型连接池、公共缓存、插件代码和监控入口。
- 适合未来管理多个平台、多个账号和大量人格。
- 账号级路由基础已经存在，不需要重写全部消息链路。

### 缺点

- 改造范围覆盖配置、Prompt、数据库、插件 SDK、适配器和 WebUI，不是局部功能。
- 数据迁移和兼容成本高，任何漏掉的全局状态都会造成隐蔽的人格污染。
- 上游当前没有提供稳定的多人格配置模型，自维护分支会持续承担合并成本。

### 适用场景

- 计划长期托管三个以上人格。
- 双实例资源消耗已经成为实际瓶颈。
- 有能力维护数据库迁移、SDK 协议和 Adapter 分支。

## 方案 E：两个进程共享数据库或数据目录

不应采用。

即使两个进程使用不同端口和不同 `bot_config.toml`，共享 `data/MaiBot.db` 仍存在以下问题：

- 当前表结构没有统一、强制的 `bot_id` 租户键。
- SQLite 多进程写入容易产生锁竞争，后台迁移和清理任务也可能重复执行。
- 人物信息、表达、黑话、记忆和统计可能在没有人格边界的情况下互相读取。
- 两套配置可能对同一数据执行不同的清理、学习或升级逻辑。

如果两个人格需要共享知识，应共享一个明确的只读知识源、MCP 服务或外部检索服务，而不是共享 MaiBot 的运行数据库。需要共享的记忆应通过显式导出、审核和导入完成。

## 推荐实施方案

### 当前阶段

采用方案 B；如果后续迁移到容器，再转换为方案 A。

1. 从同一个 commit 生成两份运行目录，禁止两个实例直接共用当前开发工作树。
2. 为两个人格分别维护：
   - `bot.nickname`、`bot.qq_account`、`bot.alias_names`
   - `personality.personality`、`reply_style`、群聊/私聊 Prompt
   - `model_config.toml`
   - `data/MaiBot.db`
   - A-Memorix 数据目录
   - `plugins/*/config.toml` 与插件数据
   - NapCat 登录态、OneBot 配置与端口
3. 两套实例都优先使用插件版 NapCat Adapter。独立进程版 Adapter 只作为当前 fork 的兼容路径，不再为第二人格扩展多连接逻辑。
4. 使用同一个发布版本升级两套实例，但分批执行：先备份并升级次要人格，观察消息收发、记忆和插件，再升级主要人格。
5. 健康检查和日志必须带实例标签，例如 `persona=a`、`persona=b`，避免只依赖端口判断故障来源。

### 可以共享的资源

- 同一个 Git commit、release 包或容器镜像。
- 同一个 LLM/OpenAI-compatible 服务端点，但 API key 和限额最好可分别统计。
- 只读提示词模板仓库；实例启动时复制为自己的配置，不在运行时共同写入。
- 只读知识库或外部 MCP 服务。
- 监控、日志聚合、备份程序和更新脚本。

### 必须隔离的资源

- QQ/NapCat 登录态与 OneBot WS 端口。
- MaiBot 主配置和模型配置。
- `data/MaiBot.db`。
- A-Memorix、表达、黑话、图片、缓存和插件数据。
- WebUI session、监听端口和日志目录。
- 插件配置文件；即使插件代码版本相同，也不要共用可写配置目录。

## 维护成本控制

为了避免双实例演变成两套不可合并的手工部署，建议把“代码”和“运行状态”分开管理：

- 代码只维护一个版本源，两个人格都引用同一 release 标识。
- 人格差异只保存在各自的配置和数据备份中，不在代码分支中硬编码。
- 为两套配置维护一份不含密钥的差异清单，明确哪些字段允许不同，其他字段升级时同步。
- 插件版本使用统一清单；插件配置根据人格分别维护。
- 备份必须能独立恢复单个人格，恢复测试不要一次同时覆盖两个实例。
- 上游同步后重点回归 `Platform IO`、`SessionUtils`、Prompt 构造、数据库迁移、插件 Runtime 和 NapCat Adapter。

## 最终决策

对于“额外维护一个 QQ 子账号，并让它拥有不同人格”的目标：

> **选择两个独立 MaiBot 运行实例，代码版本相同，所有可写状态隔离。当前 Windows 环境使用两个项目根目录最直接；生产化后使用两个容器/系统服务更稳。**

不要因为 Platform IO 已经支持 `account_id`，就把“多账号路由”误判为“多人格隔离”。单进程多人格只有在 Prompt、数据库、记忆、插件状态和适配器连接全部引入 `bot_id` 后，才适合作为正式能力。
