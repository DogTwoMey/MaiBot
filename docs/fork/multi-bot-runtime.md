# 原生多 Bot 本地运行

## 布局

一个原生 Host 管理 MaiBot 和 MaiBot2 两个独立 worker；插件运行器也是独立子进程。这是上游的隔离模型，不是两个 Bot 共用一个 Python 解释器。

| 用途 | 路径 |
| --- | --- |
| 固定运行源码 | `D:\MaiBot\runtime\multi-bot-source` |
| 独立 Python 环境 | `D:\MaiBot\runtime\multi-bot-env` |
| 工作区与共享配置 | `D:\MaiBot\runtime\multi-bot-workspace\host` |
| 每 Bot 配置、数据、插件 | `D:\MaiBot\runtime\multi-bot-workspace\bots\<bot_id>` |
| 本次迁移与验证记录 | `D:\MaiBot\runtime\maintenance\multi-bot-20261112` |

运行源码是固定在 `d4d7271ff2f8ba52cd91e98134e301ade1ec81ff` 的独立 Git worktree。日常只维护此运行源码和工作区内两份插件。`D:\MaiBot` 根工作树的历史改动保留；MaiBot2 原工程按下文归档流程退役。不要清理正在使用的源码、环境或工作区目录；源码升级应先停机、备份工作区，再验证版本兼容性。

## 启动与停止

运行以下 BAT：

```bat
D:\MaiBot\start-multi-bot.bat
D:\MaiBot\stop-multi-bot.bat
```

启动入口调用 `D:\MaiBot\start-services.bat`，其中统一保存两个 SearXNG 服务及共享图像服务定义；随后复用 SnowLuma 启动器，再启动原生 Host。重复启动会检查现有 Host；8001/8101 是 Bot HTTP 占用检查，8096/8296 是 SnowLuma 的连接端口，不应阻止启动。

停止入口通过原生控制通道请求关闭，最多等待 90 秒，取得 Host 和所有 worker 的运行租约后才返回成功；超时会报错，不强杀。共享 SnowLuma、图像服务和 Docker 服务保留，避免影响其它调用方。

直接双击启动 BAT 可在独立终端中运行；关闭其终端会结束本次前台运行。本次部署由 Windows WMI 启动隐藏 BAT，进程祖先是 `WmiPrvSE.exe`，已跨工具调用和停启验证。启动输出保存在 `D:\MaiBot\runtime\maintenance\multi-bot-20261112\launch.log`。日志可能含一次性登录信息，仅限本机保存。

日常启停统一使用本页多 Bot BAT；原工程 `start-all.bat` 不作为多 Bot 工作区入口。

查询状态：

```bat
cd /d D:\MaiBot\runtime\multi-bot-source
D:\MaiBot\runtime\multi-bot-env\Scripts\python.exe -m src.cli.tool host status -d D:\MaiBot\runtime\multi-bot-workspace
```

## 一键重启全部 Bot

```bat
D:\MaiBot\restart-multi-all.bat
```

该入口先调用 `stop-multi-bot.bat` 等待 Host 和全部 worker 完整停止，再调用 `start-multi-bot.bat`。停止失败时立即返回原退出码，不启动新实例；启动入口的退出码也原样返回。`all` 指整个多 Bot 工作区，Bot 的期望运行状态保持不变；共享依赖服务沿用已有启动检查，不强制停止或重建。

可重复的批处理流程检查（使用临时替身入口，不重启真实 Bot）：

```bat
D:\MaiBot\runtime\multi-bot-env\Scripts\python.exe D:\MaiBot\scripts\check_restart_multi_all.py
```

## 再次同步配置

正常维护直接编辑工作区内各 Bot 的配置或使用 WebUI。仅在从备份/外部工程导入时使用同步脚本，必须通过 `--originals` 明确指定来源父目录（其下包含 `MaiBot` 或 `MaiBot2` 子目录）；默认只预览 MaiBot2：

```bat
D:\MaiBot\stop-multi-bot.bat
D:\MaiBot\sync-multi-bot-config.bat --originals "D:\MaiBot\imports"
D:\MaiBot\sync-multi-bot-config.bat --originals "D:\MaiBot\imports" --apply
D:\MaiBot\start-multi-bot.bat
```

同时同步两个来源：

```bat
D:\MaiBot\sync-multi-bot-config.bat --originals "D:\MaiBot\imports" --bot MaiBot --bot MaiBot2 --apply
```

同步范围：原工程的 `config/bot_config.toml`、`config/model_config.toml`、`data/custom_prompts`、已有插件的 `config.toml` 和内置插件配置。保留目标独有文件。插件目录尚未迁入时明确报错，先处理插件代码部署，不生成只有配置的假插件。

每次同步复用上游的共享网络设置、保留策略、模型目录迁移与配置事务：模型同名异义由上游重命名并修正任务引用；已存在的 Host 设置保留。执行前检查全部运行租约、解析 TOML、验证模型引用和来源文件稳定性，写入前备份，写入后逐文件回读校验。

重复同步同一输入、且尚未启动 worker 时应显示 `changed_files: 0`。启动后，上游可能补充新版本字段、迁移内置插件设置并更新配置版本；再次从旧工程全量复制时出现配置差异是正常的，下一次启动仍由原生升级器处理。

这个入口只刷新配置和自定义提示词，不重新覆盖数据库、向量索引、插件运行状态、插件代码或独立环境。工作区产生的新业务数据继续保存在各 Bot 目录中。原工程的模板源码改动也不由配置同步脚本发布。

## 配置回退

同步返回的 `backup` 目录位于 `D:\MaiBot\runtime\multi-bot-workspace\host\backups\config-sync-*`，包含 `originals.json`。先停止 Host，再恢复指定备份：

```bat
D:\MaiBot\stop-multi-bot.bat
D:\MaiBot\runtime\multi-bot-env\Scripts\python.exe D:\MaiBot\scripts\multi_bot_workspace.py restore-config --backup "完整的 backup 目录"
D:\MaiBot\start-multi-bot.bat
```

恢复会验证目标范围，并先保存当前内容作为反向备份；仅撤回该批次修改和新增的配置文件。备份含私有配置，不应上传或提交。

如需回退整个部署：先停止 Host 并备份当前工作区，再从完整归档恢复相应版本的代码、环境和数据。保留工作区新增业务数据，不把升级后的数据库直接覆盖回旧版本。归档内绝对路径和链接面向原始位置；改路径恢复时须先完成路径重定位。

## 验证与当前边界（2026-11-12）

- 两个 worker 均达到原生 `running`，属于同一个 Host；启动幂等、完整优雅停机、再次启动均已验证。
- 当前两个 Bot 使用 `restart_policy=never` 进行试运行；worker 异常退出时会保留失败状态，需处理错误后手动启动。
- Host 模式接口返回 HTTP 200，未登录访问 Bot 列表返回 HTTP 401，鉴权保持启用。
- 275 个来源配置/提示词文件校验未变；复制时为 15 个 SQLite 文件执行一致性备份与完整性检查。
- 两个原始主数据库仍为 schema 46，运行副本为 schema 52，`quick_check=ok`。
- 核心插件各加载 1 个；扩展插件分别加载 21/25 个，加载失败均为 0。兼容模式警告不等同于每项插件业务已验收。
- QQ 客户端未登录，两适配器对 8096/8296 重连；尚未验证真实 QQ 收发。
- Docker 不可用，两个 SearXNG 容器尚未启动；本地图像服务健康检查通过。
- 运行日志出现 MaiLove 目标聊天流歧义（需明确 `account_id`、`scope`）以及表情标签模型输出解析错误，需分别排查，不能据 Host 就绪宣称业务全部通过。

可重复的配置同步、幂等、来源保护及备份恢复检查：

```bat
D:\MaiBot\runtime\multi-bot-env\Scripts\python.exe D:\MaiBot\scripts\check_multi_bot_workspace.py
```

检查使用临时工作区和本机已有配置，不启动 Bot、不发送 QQ 消息，也不改动两个来源工程。

## 单工程维护与 MaiBot2 归档

- 古米：`D:\MaiBot\runtime\multi-bot-workspace\bots\693cb32ac4c14a35b13ff6802680185d`。
- 德蕾琪娜：`D:\MaiBot\runtime\multi-bot-workspace\bots\d466847572bc4b57a2843864362b242f`。
- 两份 `plugins` 各保留独立 Git 历史、未提交文件和配置；在对应实例的插件目录维护，不跨实例覆盖。
- 德蕾琪娜的人格资源保存在其实例目录的 `runtime\persona_identity`，插件配置、索引 JSON 和 editable 安装路径已重定位。
- 两个运行数据库不被旧数据库覆盖；迁移前一致性快照和检查记录位于 `D:\MaiBot\runtime\maintenance\consolidate-maibot2-20261112`。
- 原 MaiBot2 全量归档：`D:\MaiBot\backups\MaiBot2-20261112-1530\MaiBot2.zip`。归档包含私有人格、记忆、凭证和 Git 数据，仅限本机保存；本机 Git 排除已覆盖 backups。
- `manifest.json` 保存文件 SHA-256、空目录与 reparse 链接目标；`verification.json` 校验压缩包内全部文件；`retirement-verification.json` 记录来源复核及业务数据恢复测试。
- 经用户确认，仅允许排除 5 个无权限读取的历史 pytest 临时目录，完整相对路径列于退役核验记录。不得将这些目录宣称为已完整备份。
- 退役状态（2026-11-12）：241,994 个源文件哈希复核通过，4,811 个链接目标已记录；实际恢复 1,568 个业务文件，15 个 SQLite 检查通过。经批准的 5 个测试临时目录已通过管理员限定清理删除，`D:\MaiBot2` 已不存在。两个 Bot 从本页工作区正常运行。

- 两项既有每日维护任务已切换到共享核心与上述两份插件路径，统一重启入口，原调度、状态与通知偏好保持不变。
