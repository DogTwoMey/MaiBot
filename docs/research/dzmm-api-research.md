# DZMM API 接入调研

核实日期：2026-09-13。范围：接口协议、模型清单、MaiBot 调用链与模型配置。

## 接口证据

| 接口 | 本次核实结果 | 接入含义 |
| --- | --- | --- |
| [GET v1/models](https://api.sillytraven.dev/api/ai/v1/models) | 无鉴权请求返回 200，共 45 项，OpenAI 模型列表格式 | 可用于 v1 模型发现 |
| [GET v2/models](https://api.sillytraven.dev/api/ai/v2/models) | 无鉴权请求返回 200，共 43 项，提供 id、name、context_window | 可确认标识符与上下文长度 |
| [POST v1/chat/completions](https://api.sillytraven.dev/api/ai/v1/chat/completions) | 使用现有 DZMM token、x-apex-neo-16k 和普通短消息返回 200，正文 OK，usage 为 9 输入 / 1 输出 token | 已验证该账户、该模型的非流式生成 |
| [POST v2/chat/completions](https://api.sillytraven.dev/api/ai/v2/chat/completions) | 空对象请求返回 400，SSE 错误为 model is required | 错误响应也可能是 SSE |

用户提供的 `temp/card-chat-v2.js` 是接口示例，作为协议资料读取，没有执行其中的生成请求。示例从环境变量 `DZMM_API_TOKEN` 读取 Bearer token，默认值是占位符。经用户确认后，本次使用现有 DZMM token 对新 v1 地址完成了普通短消息验证。

v2 示例请求包括 `model`、`style`、`user_name`、`user_id`、`conversation_id`、`request_id`、`card`、`context`、`messages`、`max_tokens`、`temperature`。角色卡包含 name、description、personality、scenario、first_message、system_prompt。示例通过 SSE 的 `choices[0].delta.content` 取增量文本，通过 `usage` 读取用量。

这些字段来自示例；是否必填、长度限制、计费口径、stream 参数行为及服务端会话留存规则仍待正式文档或鉴权测试确认。公开模型列表成功不等于生成权限有效。

补充验证：向 v1 发送不含密钥的普通短消息，指定 `x-apex-dash-0826-16k`、max_tokens=8、stream=false，接口返回 HTTP 400 与 `bad_request` 错误，没有取得生成结果。因此也不能仅凭 HTTP 状态码将这类错误归为 JSON 格式问题。

## 当前工程

两套实例均已配置 `DZMM`，地址是 `https://www.gpt4novel.com/api/xiaoshuoai/ext/v1`，别名 `dzmm-chat` 对应 `x-apex-neo-16k`。两套配置均存在密钥；本次通过 MaiBot 的现有 token 验证新 v1 地址，未修改实例的地址配置。

| 配置 | D:\MaiBot | D:\MaiBot2 |
| --- | --- | --- |
| 回复模型选择 | random | random |
| dzmm-chat 是否进入 replyer 池 | 是 | 否 |
| replyer temperature | 0.7 | 1.0 |

运行配置中的 DZMM 输入、输出价格均为 0。这是已有配置值，不能据此认定服务免费。

`apisource/dzmm/provider.py::_build_tier_mapping` 没有使用传入的 tier 区分模型，所有档位都把全部 chat 模型加入 replyer。`apisource/manage.py --provider all --tier ...` 会重建任务槽位；执行前应检查完整预览，避免覆盖实例已有候选模型安排。`random` 策略不会把列表顺序解释为质量优先级。

## Planner 到回复请求

1. `src/maisaka/builtin_tool/reply.py::get_tool_spec` 声明 planner 可以填写的 reply 参数；配置路由提示词后增加 `reply_model` 候选枚举，并提供模型与供应商对应关系。
2. reply 工具调用 `generate_reply_with_context`，传入本次 `reply_tool_args`。
3. `src/chat/replyer/maisaka_generator_base.py` 调用 `maisaka.replyer.before_request`，该 Hook 已提供 `task_name`、`model_name`、`reply_tool_args`。
4. Hook 返回的模型名进入 `LLMGenerationOptions`。`src/llm_models/utils_model.py` 在显式指定模型时只使用该候选；未指定时按任务模型池选择。

现有 `think_level` 参数在回复生成入口被丢弃，不是有效的模型分档入口。通用路由已复用上述模型选择机制实现，包含回复模型池校验，配置方法见 [回复供应商路由](reply-model-routing.md)。

## 上下文档位候选

公开列表没有能力评测、价格或速度数据，因此下面是同一 Dash-0826 系列的上下文容量划分，不是质量或价格评级。

| 本地候选档位 | 模型标识符 | context_window |
| --- | --- | ---: |
| low | x-apex-dash-0826-16k | 16000 |
| mid | x-apex-dash-0826 | 32000 |
| high | x-apex-dash-0826-64k | 64000 |
| ultra | x-apex-dash-0826-128k | 128000 |

这四个标识符均出现在本次 v1 与 v2 模型列表中。选择同一系列是为了减少容量比较中的变量，不代表其优于 Sigma、Pulse 等系列。模型名后缀不能替代真实元数据：例如 `x-apex-neo` 显示名称为 32K，而接口的 context_window 是 31000。

完整 v2 清单保存在 [dzmm-models-2026-09-13.json](dzmm-models-2026-09-13.json)，候选档位记录在 [dzmm-context-tiers.toml](dzmm-context-tiers.toml)。后者是研究用目录，不是可直接覆盖运行配置的文件。

## 接入与验收条件

MaiBot 的通用接入优先验证 v1，base_url 为 `https://api.sillytraven.dev/api/ai/v1`，模型发现为 `/models`。现有 OpenAI 兼容客户端可作为验证入口。v2 需要角色卡映射及 SSE 行为验证，不应仅替换 URL 就认定兼容。

已使用无私人上下文的普通短消息验证 token、Neo-16K 的非流式生成与实际 usage。Dash 各容量档位尚未进行带鉴权生成测试，价格、v2 生成及流式兼容性也仍待验证，不能把未知计费写成免费结论。

本次产出调研、候选目录及可配置的通用回复路由。两套运行配置、模型选择策略和服务进程均未修改。启用时分别配置各实例，保留它们的温度、模型池和凭据差异。
