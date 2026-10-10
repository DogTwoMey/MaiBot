# 消息归属协议

适配器通过消息网关的 `update_state()` 声明接入的平台、机器人账号和路由作用域。
账号发现只发生在网关就绪声明中，普通消息不会新增账号或更改网关身份。
当前每个网关声明一条路由，多账号适配器可以声明多个网关。

`gateway.route_message()` 的消息字典使用以下顶层字段：

```json
{
  "platform": "qq",
  "account_id": "机器人账号ID",
  "scope": null,
  "message_id": "平台消息ID",
  "timestamp": "1791504000.0",
  "message_info": {
    "user_info": {"user_id": "发送者ID", "user_nickname": "发送者"},
    "additional_config": {}
  },
  "raw_message": [{"type": "text", "data": "你好"}]
}
```

- `account_id` 必须是非空字符串，表示本实例处理这条消息的机器人账号，与发送者 `user_id` 分开。
- `scope` 是可选字符串，没有作用域时省略或使用 `null`。
- 消息的 `platform/account_id/scope` 必须匹配所属网关已经声明的路由，否则 Host 拒绝消息。
- 归属字段通过内部消息、Hook、聊天流和出站消息保留，不再写入 `additional_config`。
- `additional_config` 继续用于平台专属信息，例如接收目标的 OpenID 和被动回复凭据。

旧版消息中的 `self_id`、`platform_io_account_id` 等别名，以及
`message_info/additional_config/route_metadata` 中的归属字段暂时兼容。
Host 在走旧路径时输出 WARNING，提示该特性将在下个版本移除，请及时迁移。
提供顶层 `account_id` 后，旧字段不再参与归属选择；正式字段为空或类型错误不会回退到旧字段。
旧格式恢复出的身份仍须通过网关声明校验，不能创建额外账号。
