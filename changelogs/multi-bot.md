# Multi-Bot 功能变更日志

> 分支：`multi-bot`
> 实现提交：`c44760d49c61846bc6aac1916f426d621659c959`
> 配置模板版本：`8.14.12`
> 日期：2026-06-23

## 用户感知功能

### 按账号配置独立 Bot 身份

- 新增 `bot.profiles` 配置，可通过 `platform + account_id` 为不同机器人账号设置独立昵称、别名、人格描述、基础表达风格和备用表达风格。
- 同一 MaiBot 进程接收多个账号的消息时，Planner 和 Replyer 会根据当前聊天流携带的账号路由选择对应身份。
- 没有匹配到独立配置的账号继续使用原有 `[bot]` 与 `[personality]` 默认配置，现有单 Bot 部署无需调整。
- 配置中的平台名会自动转换为小写，账号 ID 会去除首尾空白。
- 同一 `platform + account_id` 出现重复配置时会直接拒绝加载，避免同一账号的人格选择结果不确定。

### 提及和自身消息识别

- Bot 昵称与别名提及检测改为使用当前接收账号的身份，不再始终使用默认 Bot 名称。
- `@Bot` 组件解析会优先使用当前路由账号对应的昵称。
- 自身消息识别支持同一平台的多个 Bot 账号，历史恢复时能正确区分用户消息和 Bot 已发送消息。
- 查询消息并排除 Bot 消息时，会过滤所有已配置账号，不再只过滤每个平台的单个默认账号。

### 回复和展示

- Planner 系统提示词使用当前账号的昵称、别名和人格。
- Replyer 使用当前账号的昵称、人格、基础表达风格、备用表达风格和随机风格概率。
- Focus 模式唤醒提示、内置回复工具结果和写回聊天历史的 Bot 名称使用当前账号身份。
- 出站消息会继承聊天流的 `account_id`，发送者昵称也使用当前账号配置。
- WebUI 聊天广播中的 Bot 显示名称会随账号身份变化。

## 配置示例

以下内容加入现有 `[bot]` 配置段。每个对象必须填写 `platform` 和 `account_id`：

```toml
[bot]
nickname = "麦麦"
alias_names = ["麦"]

profiles = [
    { platform = "qq", account_id = "10001", nickname = "麦麦", alias_names = ["麦"], personality = "你是麦麦，性格活泼。", reply_style = "回复简短自然。", multiple_reply_style = [], multiple_probability = 0.0 },
    { platform = "qq", account_id = "10002", nickname = "小麦", alias_names = ["麦二"], personality = "你是小麦，负责技术答疑。", reply_style = "直接、准确，优先给出结论。", multiple_reply_style = ["只回答结论。"], multiple_probability = 0.2 },
]
```

路由匹配是精确匹配。上例中只有 `platform = "qq"` 且接收账号为 `10002` 的聊天流会使用“小麦”身份。

## 兼容性

- 默认 `profiles = []`，不改变已有单 Bot 行为。
- 未新增数据库表或迁移，不改变现有 `session_id` 算法。
- 没有修改实际 `config/bot_config.toml`；运行本分支时，现有配置会按项目原有机制升级到模板版本 `8.14.12`。
- 配置热重载后，新的身份配置会在后续 Prompt 构建和消息发送时生效。

## 使用前提

- 入站适配器必须向 MaiBot 上报真实接收账号，字段可以是 `platform_io_account_id`、`account_id`、`self_id` 或 `bot_account`。
- 同一平台多账号应使用支持账号级 `RouteKey` 的 Platform IO 插件驱动。
- legacy 发送驱动仍是每个平台单账号模型，不能单独承担同平台多账号发送。

## 当前限制

本功能提供的是“账号级身份与人格 Prompt 选择”，不是完整的多租户隔离：

- 多个 Bot 仍共享数据库、人物信息、记忆、表达学习、黑话学习、图片缓存和统计数据。
- 多个 Bot 仍共享模型配置、插件实例、插件配置和进程生命周期。
- `chat`、模型策略和绝大多数非身份配置仍是全局配置。
- 如果需要严格隔离记忆、学习结果、插件状态和故障域，应继续使用多个 MaiBot 实例。

完整实现与边界说明见 [Multi-Bot 技术设计](../docs/fork/multi-bot-technical-design.md)。

## 验证结果

- Ruff 检查通过。
- 相关 Python 文件语法编译通过。
- 新增 5 个配置与解析测试，全部通过：
  - 精确匹配账号身份。
  - 未匹配路由回退默认身份。
  - 拒绝重复账号路由。
  - 配置模板可正确写出身份列表。
  - WebUI 配置 Schema 包含身份字段。
