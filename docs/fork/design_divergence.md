# Fork 设计分歧 · Design Divergence

> 本文档记录 `DogTwoMey/MaiBot` 相对 `Mai-with-u/MaiBot` 在**业务/代码层面**的长期设计分歧。
> 工程/部署层面的差异见 [`deployment.md §0`](deployment.md#0-本-fork-相对-upstream-的改动-工程层)。
>
> **读者**：
> - 在本 fork 上做二次开发的人 — 了解哪些模块不能假设跟上游一致
> - 处理 upstream 合并的人 — 每次 sync 前先扫此文档，避免主动改造被 upstream 的新提交静默撤销
> - 向 upstream 贡献 PR 的人 — 判断哪些改动是"公共收益"可回传，哪些是 fork 专属不适合上游

---

## 🗂 索引

| 编号 | 分歧点 | 涉及模块 | 状态 |
|---|---|---|---|
| [D1](#d1-后端存储路径抽象pathutils) | 后端存储路径抽象 (path_utils) | `src/common/utils/path_utils.py` + 使用点 | 已落地 |
| [D2](#d2-webui-静态资源源) | WebUI 静态资源源（本地 dist only） | `src/webui/app.py` | 已落地 |
| [D3](#d3-提及--talk_value-低频时保活) | @/mention 在 talk_value 低时的保活 | `src/maisaka/runtime.py` | 已落地 |
| [D4](#d4-kv-cache-命中率日志revert) | KV cache 命中率日志 (长期 revert) | `src/maisaka/chat_loop_service.py` | ⚠️ 每次 sync 都会被撤销 |
| [D5](#d5-孤儿-tool-call-运行时兜底) | 孤儿 tool_call 的运行时兜底 | `src/maisaka/chat_loop_service.py` + `history_utils` | 已落地 |
| [D6](#d6-talk_value-精度) | `talk_value` 配置精度 0.01 | `src/config/official_configs.py` | 已落地 |
| [D7](#d7-group-chat-rules-可视化-hook) | Talk Value Rules 可视化 Hook | `dashboard/src/routes/config/bot/hooks/` | 已落地 |
| [D8](#d8-apisource-切换与计费模板) | APISource 切换脚本与计费模板 | `apisource/` | 已落地 |
| [D9](#d9-插件-v1v2-manifest-兼容层) | 插件 v1→v2 manifest 兼容层 | `src/plugin_runtime/manifest_compat/` | 已落地 |
| [D10](#d10-deepseek-v4-flash-payload-补丁) | DeepSeek v4-flash payload 修复 | `src/llm_models/` | 已落地 |
| [D11](#d11-bot-级-user-id-感知) | Bot 级 user_id 感知（同 id 不同名问题） | `src/maisaka/runtime.py` | 已落地 |
| [D12](#d12-启发自-fork-但上游已官方支持的项) | 启发自 fork、但上游已官方支持的项 | 多处 | 合并时需转用上游方案 |
| [D13](#d13-合并时需特别注意的-convergent-bug-修复) | 合并时需特别注意的 convergent bug 修复 | — | 每次 sync 检查 |

---

## D1: 后端存储路径抽象（path_utils）

**起因**：上游在 `data/emoji/<hash>.jpg` 这类路径上采取"绝对路径入库"的策略，数据库里存的是 `D:\Toy\MaiBot\data\emoji\xxx.jpg`。这让数据**不能跨机器/容器/CWD 迁移** —— 换一台机器就必须批量改数据库。

**fork 方案**：新建 [`src/common/utils/path_utils.py`](../../src/common/utils/path_utils.py)：

- `to_stored_path(absolute_path) -> str`：入库前把项目根替换为项目相对路径（`data/emoji/xxx.jpg`）
- `resolve_stored_path(stored_path) -> Path`：读取时按当前项目根解析回绝对路径

**接入点**：
- [`src/webui/routers/emoji/routes.py`](../../src/webui/routers/emoji/routes.py)（5 个使用点）
- [`src/common/data_models/image_data_model.py`](../../src/common/data_models/image_data_model.py)
- [`src/common/utils/utils_file.py`](../../src/common/utils/utils_file.py)
- [`src/emoji_system/emoji_manager.py`](../../src/emoji_system/emoji_manager.py)

**⚠️ 合并风险**：upstream 周期性会独立改 emoji 相关的路径计算（如修正 `PROJECT_ROOT` 的 parent 链、新增 `_resolve_existing_emoji_path` 本地 helper）。自动合并会**留下两套机制共存**，需要在每次 sync 后手工巡检 `emoji_system/emoji_manager.py` 是否还有 `Path(raw).absolute().resolve()` 之类绕过 path_utils 的调用。

---

## D2: WebUI 静态资源源

**起因**：上游的 `src/webui/app.py::_resolve_static_path` 默认走 `maibot-dashboard` pip 包（发行版策略），本地仓库的 `dashboard/dist` 被注释掉。本 fork 的工作流是**必须在本地 build dashboard**（新 UI 在 dev 分支跑，而不是等官方包发版）。

**fork 方案**：彻底改写 `_resolve_static_path`：
```python
def _resolve_static_path() -> Path | None:
    # 仅使用仓库本地 dashboard/dist（由 pnpm build 产出），不再回退到 maibot-dashboard pip 包。
    base_dir = _get_project_root()
    static_path = base_dir / "dashboard" / "dist"
    if static_path.is_dir() and (static_path / "index.html").exists():
        return static_path
    return None
```

**同时清理**：
- 删除 `_DASHBOARD_PACKAGE_NAME` / `_MANUAL_INSTALL_COMMAND` 常量
- 删除 3 处"`pip install maibot-dashboard`"warning（与本 fork 策略相悖，会误导用户）

**⚠️ 合并风险**：upstream 已在后期官方支持通过 `MAIBOT_WEBUI_USE_LOCAL_DASHBOARD` 环境变量切换本地 dist。合并时建议改方案：**采 upstream 框架但默认 `True`**，这样同时兼容"不想 build 的人显式关掉走 pip 包"。

---

## D3: 提及 @ 在 talk_value 低频时的保活

**起因**：上游 `talk_value` 机制把主动发言概率拉到很低（例如 0.03）时，@ bot 的消息进入 Heart Flow 后会受 `trigger_threshold` 和历史回复延迟影响——**首次 @ 可能等几十秒才被处理，甚至永远不被处理**。

**fork 方案**：在 [`src/maisaka/runtime.py`](../../src/maisaka/runtime.py) 新增 `_force_next_timing_continue` 状态机：
- 被 @ / 显式提及 → `_arm_force_next_timing_continue(reason)` 预置 flag
- `_schedule_message_turn_if_needed` 首先检查 flag，直接唤醒消息轮；**绕过** trigger threshold 和延迟限制
- Timing Gate 调用时 `_consume_force_next_timing_continue_reason()` 消费 flag，视为 `continue`

**与 upstream 的协作**：upstream 在 `d32be474 / 500d5c11` 里给 Timing Gate 加了"非法工具重试 → no_reply"兜底。两套路径**完全正交**——fork 的短路发生在 Gate 调用**之前**，upstream 的兜底发生在 Gate 内部。合并时保持两者并存。

---

## D4: KV cache 命中率日志（**长期 revert**）

**起因**：upstream 在 `src/maisaka/chat_loop_service.py` 里加了 `_log_prompt_cache_usage` 静态方法和对应调用，每次 LLM 请求后打印 `Maisaka KV cache usage - hit_rate=X%` 一行 INFO。这在聊天高峰期会严重刷屏，信息噪声价值低于实用价值。

**fork 决策**：永久性删除方法定义 + 调用点（commit `eea6c6ef` 首次 revert）。

**⚠️ 这是 sync 过程中最容易被静默撤销的修改**：
- upstream 没把它删，每次上游有 `chat_loop_service.py` 改动时，auto-merge 会**把 `_log_prompt_cache_usage` 再次拉回来**
- 历史上已经发生过两次：首次 merge 后忘记再次 revert，下次才发现；第二次在 dry-run 期间确认存在
- **每次合并后必做检查**：
  ```bash
  grep -n "_log_prompt_cache_usage" src/maisaka/chat_loop_service.py
  ```
  **应返回空**。若有命中，手动删除方法定义（~26 行）和调用点（~6 行）。

---

## D5: 孤儿 tool_call 的运行时兜底

**起因**：OpenAI / 阿里云严格要求每个 `assistant.tool_calls` 必须有后续 `role=tool` 响应，否则 400 `tool_call_ids did not have response messages`。MaiBot 在上下文裁剪 / 打断 / 超时 / reply 工具后插入 bot 发言等路径都可能留下孤儿 tool_call。

**fork 方案**：在 `chat_loop_service.py` 发送前兜底：
1. `_enforce_tool_result_adjacency(messages)` — 把散落的 `role=tool` 响应重排紧贴各自的 assistant
2. `_prune_orphan_tool_calls(messages)` — 清除没有响应的 tool_call
3. [`src/maisaka/history_utils.py::normalize_tool_result_order`](../../src/maisaka/history_utils.py) — 历史入上下文时同步做一次排序

**设计理念**：
- 运行时兜底 ≠ 上游缺失。upstream 倾向于"发生时修业务上游路径"，fork 倾向于"在调用 LLM 前绝对保证格式正确"——兜底是**最后一道防线**
- 与 upstream 新引入的 `drop_leading_orphan_tool_results`、`sync_discovered_deferred_tools_with_context` 等没有冲突

---

## D6: `talk_value` 配置精度

**起因**：上游默认 `step: 0.1`，对本 fork 常用的 `0.01 / 0.03 / 0.05` 低频场景不够细。

**fork 方案**：[`src/config/official_configs.py`](../../src/config/official_configs.py) L170-177 中将 `ChatConfig.talk_value` 的 `json_schema_extra.step` 改为 `0.01`，文档字符串也加了"精度 0.01"。

**影响**：dashboard 的 slider 可以精调到 0.01。

---

## D7: Talk Value Rules 可视化 Hook

**起因**：上游的 `ChatTalkValueRulesHook` 是一个 JSON 纯文本编辑器。本 fork 添加了一个可视化版 [`TalkValueRulesVisualHook.tsx`](../../dashboard/src/routes/config/bot/hooks/TalkValueRulesVisualHook.tsx)（320 行），用图形化方式编辑群聊 talk_value 规则。

**接入**：[`dashboard/src/routes/config/bot.tsx`](../../dashboard/src/routes/config/bot.tsx) 中 `ChatTalkValueRulesHook` → `ChatTalkValueRulesVisualHook`。

**⚠️ 合并风险**：每次 upstream 在 `bot.tsx` 里增删 hook 导入 / hook 列表，auto-merge 很可能把 Visual Hook 替换回去。合并后检查：
```bash
grep -n "ChatTalkValueRulesVisualHook\|ChatTalkValueRulesHook" dashboard/src/routes/config/bot.tsx
```
应只见 Visual，不见 `ChatTalkValueRulesHook`。

---

## D8: APISource 切换与计费模板

**起因**：上游的 `model_config.toml` 是一锅端的文件，切换 LLM 供应商（Aliyun / DeepSeek / 自建）需要手工编辑；计费配置没有按"档位"组织的模板。

**fork 方案**：[`apisource/`](../../apisource/) 目录：
- `apisource/_common.py` / `apisource/manage.py` — 供应商切换主调度
- `apisource/aliyun/{provider.py, manage.py, tiers/*.toml, response_cn_*.json}` — 阿里云百炼
- `apisource/deepseek/{provider.py, models.toml}` — DeepSeek

使用：
```bash
uv run python apisource/manage.py --provider deepseek --tier high --apply
```

**为什么不上游化**：apisource 目录内容包含各家供应商的私有 API 契约细节、计费价格（会变动），作为工程层维护更合适。

---

## D9: 插件 v1→v2 manifest 兼容层

**起因**：upstream 在 plugin runtime 做了 manifest v1 → v2 的迁移，但没提供兼容层——旧插件直接不能加载。本 fork 的自写插件有些还是 v1 格式。

**fork 方案**：[`src/plugin_runtime/manifest_compat/`](../../src/plugin_runtime/manifest_compat/) 4 个文件（920+ 行）+ [`scripts/migrate_plugin_manifests.py`](../../scripts/migrate_plugin_manifests.py) 迁移工具。

- `base.py` / `registry.py` — v1/v2 manifest 的基础抽象和注册
- `v1_to_v2.py` — 自动转换逻辑

**合并策略**：upstream 自己对 plugin_runtime 有改动时，检查 `capabilities/` 和 `runner/` 下是否有 signature 变动影响 `manifest_compat`。

---

## D10: DeepSeek v4-flash payload 修复

**起因**：main 的 `ce232b39` + `6ef70171` 修复了两个 DeepSeek 问题：
- `utils` 调用 deepseek-v4-flash 时 payload 报错
- deepseek-v4-flash 的 payload 里某些字段需要特判

**fork 方案**：在 [`src/llm_models/utils.py`](../../src/llm_models/utils.py) 和 [`src/llm_models/model_client/openai_client.py`](../../src/llm_models/model_client/openai_client.py) 里添加模型名匹配分支。

**是否要上游化**：这些是供应商私有兼容层，可以尝试推给 upstream，但 upstream 未必维护 `deepseek-v4-flash` 的 full support。保持 fork 本地。

---

## D11: Bot 级 user_id 感知

**起因**：同一个 user_id 在不同时段的昵称可能不同（改名），上游只按昵称 + 群卡片识别人物，会把"改名前的 A"和"改名后的 A"当成两个人。

**fork 方案**：`src/maisaka/runtime.py` 在构造 `SessionMessage` 时额外传 `user_id=user_info.user_id`，下游消息处理 / 人物识别使用该字段做主键。

**是否要上游化**：值得，但需要协调 adapter 侧同步传递 user_id。

---

## D12: 启发自 fork、但上游已官方支持的项

这些项当初在 fork 侧做了主动改造，后来 upstream 用类似思路或更好方案官方化了。**下次合并时应当切换到上游方案**，避免长期维护两套：

| 分歧点 | fork 当前做法 | upstream 已有方案 | 建议行动 |
|---|---|---|---|
| 本地 dashboard/dist | 永远本地 only | `MAIBOT_WEBUI_USE_LOCAL_DASHBOARD` 环境变量 | 采 upstream 框架，把 `_is_local_dashboard_enabled()` 默认改 True |
| webui session-scope 修复 | 手工 `data = [...]` 搬进 `with get_db_session()` | upstream 独立做过一次同义修复 | 已切到 upstream（convergent fix） |
| `EmojiResponse.format` / `usage_count` | 自己用 `os.path.splitext` | upstream 用 `Path(x).suffix` | 已切到 upstream |
| Emoji 删除 `image.emotion` fallback | fork 自改 | upstream 同时做过 | 已切到 upstream |

---

## D13: 合并时需特别注意的 convergent bug 修复

**这些是 fork 和 upstream 都触到的静默 bug，upstream 已修但 fork 需跟进**：

| 文件 | Bug | upstream 修复 |
|---|---|---|
| `src/maisaka/runtime.py` L120 | `ExpressionConfigUtils.get_expression_config_for_chat` 的返回值顺序**是 `(expr_use, expr_learn, jargon_learn)`**，但 fork 侧（继承自较早 upstream）用的是 `(expr_use, jargon_learn, expr_learn)`——**表达学习开关和黑话学习开关一直互换** | upstream 已修。合并时必须跟 upstream |

**每次合并后的验证命令**：
```bash
grep -n "ExpressionConfigUtils.get_expression_config_for_chat" src/maisaka/runtime.py
# 应返回：expr_use, expr_learn, jargon_learn（正确顺序）
```

---

## 🧭 合并前必做清单

每次 `sync_upstream.py` 或手动 `git merge upstream/main` **之前**先跑一次：

```bash
# 1. 预合并冲突扫描
git fetch upstream
git merge-tree $(git merge-base main upstream/main) main upstream/main \
  | grep "^changed in both" | wc -l

# 2. 预览有哪些本 fork 关键文件被 upstream 动了
git diff --name-only $(git merge-base main upstream/main)..upstream/main | grep -E \
  "runtime.py|chat_loop_service.py|app.py|official_configs.py|path_utils|emoji_manager"
```

**合并后**必做：

```bash
# 1. KV cache 日志是否被带回来（D4）
grep -n "_log_prompt_cache_usage" src/maisaka/chat_loop_service.py  # 应空

# 2. ExpressionConfig 顺序（D13）
grep "expr_use.*=.*ExpressionConfigUtils" src/maisaka/runtime.py    # 应见 expr_learn, jargon_learn 顺序

# 3. Visual Hook 接回（D7）
grep -n "ChatTalkValueRulesHook" dashboard/src/routes/config/bot.tsx  # 应只见 Visual 版本

# 4. 本地 dist 策略（D2）
grep -n "pip install maibot-dashboard" src/webui/app.py  # 应空

# 5. 孤儿 tool call 兜底（D5）
grep -n "normalize_tool_result_order\|_enforce_tool_result_adjacency" src/maisaka/chat_loop_service.py  # 应在

# 6. path_utils 接入点（D1）
grep -n "resolve_stored_path\|to_stored_path" src/webui/routers/emoji/routes.py  # 应至少 5 处
```

---

## 📦 与本文档协同的资源

- **日常合并记录**（private submodule）：[`docs/private/reviews/`](../private/reviews/)
- **部署文档**：[`docs/fork/deployment.md`](deployment.md)
- **上游资源**：README 中的 [上游 links](../../README.md#-upstream-resources--官方资源)
