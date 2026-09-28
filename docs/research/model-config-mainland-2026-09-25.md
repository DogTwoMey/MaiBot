# MaiBot 中国大陆模型配置调研（2026-09-25）

## 结论

两套独立实例均采用 `high` 档，位于 `ultra` 下一档。华北 2（北京）百炼端点承担主要对话、规划、视觉、语音和向量任务；DeepSeek 官方端点承担思考回复及文本后备。保留两套实例各自的 DZMM 回复路由、服务商连接和密钥。

| MaiBot 任务 | 高档模型顺序 | 用途 |
| --- | --- | --- |
| `replyer` | Qwen3.7 Plus → Qwen3.8 Flash → DeepSeek V4.1 Flash 思考 → DeepSeek Flash 非思考 → DZMM | 优先稳定回复，保留现有按话题选模能力 |
| `planner` | Qwen3.8 Flash → DeepSeek Flash 非思考 | 工具规划，避免思考内容回传对工具链的额外要求 |
| `memory` / `mid_memory` | Qwen3.7 Plus / Qwen3.8 Flash | 长文本整理 / 常规记忆操作 |
| `utils` | Qwen3.7 Flash → DeepSeek Flash 非思考 | 高频轻任务 |
| `learner` / `expression_use` | Qwen3.8 Flash | 表达学习 |
| `vlm` | Qwen3.8 Flash → Qwen3.7 Plus | 图像理解 |
| `voice` | Qwen3.8 Omni Flash | 音频输入转写；实例的 ASR 总开关仍由 `bot_config.toml` 控制 |
| `embedding` | Qwen3.7 Text Embedding | 保持既有向量维度和存量数据兼容 |

## 定价依据

以下为人民币 / 百万 Token。百炼使用华北 2（北京）原价；DeepSeek 使用高峰价作为 MaiBot 的全天统计单价。实际账单以平台为准。

| 模型 | 输入 | 缓存命中输入 | 输出 | 位置 |
| --- | ---: | ---: | ---: | --- |
| Qwen3.7 Flash | 0.2 | 0.04 | 0.8 | 高频轻任务 |
| Qwen3.7 Plus | 2 | 0.4 | 8 | 主回复、记忆 |
| Qwen3.8 Flash | 0.8 | 0.1 | 2.7 | 工具、视觉、常规回复 |
| Qwen3.8 Max | 12 | 1.5 | 36 | `ultra` 可选，未分配到高档任务 |
| Qwen3.8 Omni Flash | 0.8 | 0.1 | 2.7 | 语音槽 |
| DeepSeek V4.1 Flash | 2 | 0.04 | 8 | 思考回复、文本后备 |
| DeepSeek V4 Pro | 9 | 0.3 | 27 | `ultra` 可选，未分配到高档任务 |

百炼的 Qwen3.7 Plus / Flash 采用首档上下文价格；更长请求可能进入更贵的阶梯。DeepSeek 的低谷价为表中高峰价的一半，但官方高峰时段按北京时间工作日及法定节假日变化，当前 MaiBot 的每日 `price_periods` 无法精确表示该日历，因此选全天高峰价，避免成本统计低估。

依据：[百炼模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)、[DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。

## 能力与接口

- DeepSeek V4.1 Flash 的正式模型 ID 为 `deepseek-flash`，支持图像输入、工具调用与思考模式；旧 V4 Flash 名称已是兼容别名。思考请求使用 `thinking.type=enabled` 和 `reasoning_effort=high`，不发送温度参数。依据：[模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision/)、[思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。
- Qwen3.8 Flash、Qwen3.7 Plus 支持图像与工具调用，适合在现有 Chat Completions 路径上复用。依据：[视觉模型](https://help.aliyun.com/zh/model-studio/vision-model)。
- Qwen3.8 Omni Flash 的音频输入走 Chat Completions `input_audio`，不是 `/audio/transcriptions`。MaiBot 适配器已按模型分流，支持 WAV、MP3 字节；格式不符会明确报错。依据：[Qwen Omni 接口](https://help.aliyun.com/zh/model-studio/qwen-omni)。

## 验证边界

2026-09-25 用两套实例各自的现有服务商连接做了隔离的合成请求：模型清单、Qwen3.8 Flash 工具调用与图像输入、Qwen3.7 Plus 文本、DeepSeek Flash 工具与思考模式，以及 MaiBot 音频适配器对合成 WAV 的 Omni 转写，均得到成功响应。没有发送实际群聊或私人角色内容。

两套实例当前 `[voice].enable_asr=false`；音频槽虽然已配置，实际 QQ 语音链路仍需在启用 ASR 后按真实音频格式验证。两套 bot 已分别通过项目启动器重启，WebUI `8001` / `8101` 均返回 HTTP 200。启动日志另显示插件加载失败数为 8 / 6，其中包含 Host 版本上限与当前 1.3.0 不匹配的插件；本次未改动插件。
