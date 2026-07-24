# 配置第二个 Bot 人格操作指南

> 适用分支：`multi-bot`
> 适用配置模板：`8.14.12`
> 配置文件：`config/bot_config.toml`

## 1. 配置结果

完成本文配置后：

- 主账号继续使用现有 `[bot]` 和 `[personality]` 配置。
- 第二个账号根据自己的 `platform + account_id` 使用独立昵称、别名、人格和表达风格。
- 没有匹配到独立 Profile 的账号仍使用主账号的默认人格。

需要特别注意：Profile 只负责选择人格，不负责登录第二个 QQ，也不会自动启动第二个 NapCatQQ 或 Adapter。

## 2. 前置条件

开始前确认以下条件：

1. 当前代码位于 `multi-bot` 分支。
2. 已经知道两个 Bot 的真实账号：
   - 主账号，例如 `10001`。
   - 第二个账号，例如 `10002`。
3. 第二个账号的接入链能够向 MaiBot 上报 `self_id` 或 `account_id`。
4. 同一平台多账号使用支持账号级 `RouteKey` 的 Platform IO 驱动。

当前单实例 `start-all.bat` 会启动一组 NapCatQQ，默认 Adapter 插件也只维护一条传输连接。此时可以先准备第二人格配置，但第二人格不会生效，直到第二账号的入站和出站路由完成接入。

## 3. 备份配置

修改前复制一份：

```text
config/bot_config.toml
```

例如备份为：

```text
config/bot_config.toml.multi-bot-backup
```

不要修改 `src/config/official_configs.py` 代替运行配置，也不要修改配置模板来保存自己的账号密码或人格。

## 4. 确认配置版本

在 `multi-bot` 分支运行一次 `start-all.bat`，让项目按原有机制将配置升级到 `8.14.12`。正常情况下文件开头为：

```toml
[inner]
version = "8.14.12"
```

不建议手工只修改版本号。应让程序完成字段补全和旧配置备份。

## 5. 理解默认人格和第二人格

主账号继续读取两个已有配置段：

```toml
[bot]
qq_account = "10001"
nickname = "麦麦"
alias_names = ["麦"]

[personality]
personality = "你是麦麦，性格活泼，现在正在和群友聊天。"
reply_style = "回复简短自然，不要长篇大论。"
multiple_reply_style = []
multiple_probability = 0.0
```

第二人格写在 `[bot]` 内的 `profiles` 列表中。它不会读取默认 `[personality]`，而是使用 Profile 自己的字段。

## 6. 添加第二人格

在现有 `[bot]` 段中找到：

```toml
profiles = []
```

将其替换为：

```toml
profiles = [
    { platform = "qq", account_id = "10002", nickname = "小麦", alias_names = ["麦二", "小麦同学"], personality = "你是小麦，负责技术答疑。你说话理性、耐心，遇到不确定的信息会明确说明。", reply_style = "直接、准确，优先给出结论，再补充必要步骤。不要使用浮夸表达。", multiple_reply_style = ["只回答结论。", "使用简短的分点说明。"], multiple_probability = 0.2 },
]
```

完整结构示例：

```toml
[bot]
platform = "qq"
qq_account = "10001"
platforms = []
nickname = "麦麦"
alias_names = ["麦"]

profiles = [
    { platform = "qq", account_id = "10002", nickname = "小麦", alias_names = ["麦二", "小麦同学"], personality = "你是小麦，负责技术答疑。你说话理性、耐心，遇到不确定的信息会明确说明。", reply_style = "直接、准确，优先给出结论，再补充必要步骤。不要使用浮夸表达。", multiple_reply_style = ["只回答结论。", "使用简短的分点说明。"], multiple_probability = 0.2 },
]

[personality]
personality = "你是麦麦，性格活泼，现在正在和群友聊天。"
reply_style = "回复简短自然，不要长篇大论。"
multiple_reply_style = []
multiple_probability = 0.0
```

注意：

- 不要创建第二个 `[bot]`。
- `profiles` 必须位于 `[bot]` 段内，并放在下一个 `[xxx]` 配置段之前。
- `account_id` 必须是第二个 Bot 自己的 QQ 号，不是群号、联系人 QQ 或 `session_id`。
- `platform` 必须与适配器实际上报值完全匹配，QQ 通常为 `qq`。
- 同一个 `platform + account_id` 只能配置一次。
- `multiple_probability` 必须在 `0` 到 `1` 之间。

## 7. 可选：为主账号也建立显式 Profile

默认配置已经能服务主账号，一般不需要为主账号添加 Profile。如果希望两个账号都集中写在 `profiles` 中，可以这样配置：

```toml
profiles = [
    { platform = "qq", account_id = "10001", nickname = "麦麦", alias_names = ["麦"], personality = "你是麦麦，性格活泼。", reply_style = "回复简短自然。", multiple_reply_style = [], multiple_probability = 0.0 },
    { platform = "qq", account_id = "10002", nickname = "小麦", alias_names = ["麦二"], personality = "你是小麦，负责技术答疑。", reply_style = "直接、准确。", multiple_reply_style = [], multiple_probability = 0.0 },
]
```

Profile 精确匹配优先于默认配置。

## 8. 启动和重载

保存配置后，可以继续使用：

```text
restart-all.bat
```

配置监视器通常可以热重载 `bot_config.toml`，但首次配置第二人格时建议完整重启，便于同时验证配置加载、账号连接和 Platform IO 路由。

当前脚本只能管理一组外置 NapCatQQ 和 Adapter。要由同一份 `start-all.bat` 管理两个账号，还需要先完成 Launcher 多实例和账号级 Adapter 路由支持。不要仅复制启动命令并让两个旧 Adapter 同时连接 MaiBot，否则可能出现消息串线或两个账号重复发送。

## 9. 验证第二人格是否生效

### 9.1 检查账号路由

在 Adapter 或插件日志中确认第二账号已经注册，例如出现类似信息：

```text
platform=qq account_id=10002
```

如果日志里始终没有第二账号的 `account_id`，人格配置不会命中。

### 9.2 分别发送测试消息

向两个账号分别发送：

```text
你叫什么名字？请简单介绍自己。
```

预期结果：

| 接收账号 | 预期人格 |
| --- | --- |
| `10001` | 默认“麦麦”人格 |
| `10002` | Profile 中的“小麦”人格 |

### 9.3 检查聊天流

同一个用户或群分别通过两个 Bot 账号产生消息时，应形成不同的真实聊天流，因为 `session_id` 已包含 `account_id`。如果两个账号共用同一个聊天流，说明适配器没有正确上报账号路由。

### 9.4 检查出站账号

第二人格生成的回复必须由 `10002` 实际发出。如果 Prompt 显示“小麦”，但消息由 `10001` 发出，说明入站人格选择已经生效，但出站 Platform IO Driver 没有按 `account_id` 绑定。

## 10. 常见问题

### 第二账号仍使用默认人格

检查：

1. `account_id` 是否写成字符串并与实际 `self_id` 一致。
2. `platform` 是否与适配器上报值一致。
3. 入站消息 `additional_config` 是否包含 `self_id`、`account_id`、`platform_io_account_id` 或 `bot_account`。
4. 配置是否保存到了当前运行目录的 `config/bot_config.toml`。

### 第二账号没有启动

Profile 不负责启动账号。需要单独配置第二个 NapCatQQ 和对应 Adapter/MessageGateway 连接。

### 两个账号同时发送相同回复

这是出站连接没有账号级路由，或者两个旧 Adapter 都收到了同一条广播消息。应停止第二个旧 Adapter，完成 Platform IO 多驱动接入后再测试。

### 启动时报“重复路由”

检查 `profiles` 中是否重复出现：

```text
platform = qq, account_id = 10002
```

删除重复项，不要依赖列表顺序覆盖。

### 两个人格的记忆或学习结果混在一起

这是当前功能边界。账号级 Profile 只隔离身份 Prompt 和聊天流，不隔离数据库、人物、表达、黑话、插件状态或 A-Memorix。需要完整隔离时应运行两个 MaiBot 实例。

### 前端无法编辑 Profile

当前 WebUI 已能读取 Profile Schema，但复杂对象数组尚无编辑器 Hook。请直接修改 `config/bot_config.toml`。

## 11. 回滚

要停用第二人格，将 Profile 删除并恢复：

```toml
profiles = []
```

然后执行 `restart-all.bat`。这不会删除历史聊天流或数据库数据，只会让后续请求重新使用默认人格。

## 12. 相关文档

- [Multi-Bot 技术设计与实现说明](multi-bot-technical-design.md)
- [Multi-Bot 功能变更日志](../../changelogs/multi-bot.md)
- [两个不同人格 MaiBot 的维护方案](multi-persona-deployment.md)
