# 健康模型上下文容量、token 计量与超限行为核验（Ticket 69）

日期：2026-08-18  
目标：Partner Hermes v0.20.0，固定提交 [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)

## 1. 范围、方法与直接结论

本票只回答 CAN：当前正式健康 Plugin `ctx.llm` 路线能否在发送前证明“本次最终请求一定装得下，并且任何截断或输出耗尽都能被识别”。核验使用固定提交的官方源码、OpenAI 与 JOJO 的公开一手文档，以及目标 Partner 现场的非敏感只读配置。现场核验没有读取或输出密钥、聊天、Session、日志或健康正文，没有改配置、切模型、触发 fallback、发送模型/微信请求或安装 canary。

**负向 CAN：不能。** 当前路线无法同时证明所有允许实际路线的共同上下文下限、与最终请求一致的 token 上界、真实输出预留，以及无静默截断的完成状态。决定性缺口不是“240,000 是否够大”，而是以下固定行为：

1. `ctx.llm(max_tokens=...)` 的公开参数在目标 `jojo` + `codex_responses` 路线中不会成为 wire 上的输出上限；
2. `complete_structured()` 构造的 `response_format` 不会被目标 Codex Responses 适配器透传；
3. Responses 的 `incomplete`、`failed`、`incomplete_details` 和 response id 在转回 chat-shaped 结果时被丢弃，`finish_reason` 被本地合成为 `stop` 或 `tool_calls`；
4. 流已有部分正文但缺少终态事件时，固定源码仍把它组装为 `completed`，随后对 Plugin 表现成 `stop`；
5. 现有 token 计算明确只是粗估，不是目标 tokenizer，也不是对中文、JSON、引用标识、图像和 provider 包装的已验证保守上界；
6. `ctx.llm` 的通用 `task=None` 没有 fallback 上下文下限筛选，JOJO 公开说明实际模型可按任务、上下文和策略变化。

因此，真实 canary 不是关闭本票所必需；一次或有限次成功请求也不能修复上述静态接口缺口，不能证明未来所有内部路线与故障切换。

## 2. 容量参数的物理含义

要形成调用前容量合同，至少必须同时有：

- `W_route`：某一条实际 provider/model/endpoint/内部上游路线能接收的**真实上下文窗口**。它不是模型营销名，也不是本地配置数字；其约束应明确输入、可见输出和 reasoning token 如何共享窗口。
- `W_min = min(W_route)`：本次调用允许到达的全部正常路由和故障切换路线中的**共同下限**。
- `I_wire`：最终 wire 请求被实际服务计入的输入 token，包括 `instructions`、会话消息、健康画像和其他附带信息、图片、工具/schema、角色与序列化包装，以及 provider 可能加入的隐藏包装。
- `I_upper`：对 `I_wire` 的可验证保守上界；使用的 tokenizer、图片规则与序列化版本必须和实际请求一致，或已证明永不低估。
- `O_reserve`：调用者保留给可见输出和 reasoning 的 token，且必须由 wire 参数或等价服务合同真正限制。

安全前提是 `I_upper + O_reserve <= W_min`，并且返回面能证明状态确实为完成。当前路线的 `W_min`、`I_upper`、`O_reserve` 和完成证明四项均未闭合；把现场 `context_length: 240000` 减去粗估输入不能得到安全预算。

## 3. 公开 API 语义与目标 relay 不能混同

OpenAI 官方 Responses 参考说明：`max_output_tokens` 是可见输出和 reasoning token 的共同上限；`truncation=auto` 会从对话开头丢弃输入项，`disabled`（默认）则在输入超窗时返回 400；输出耗尽可产生 `response.incomplete` 与 `incomplete_details.reason="max_tokens"`，usage 分开记录 input/output/reasoning token。[OpenAI Responses 官方参考](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal/delta?lang=curl)

这些只能说明 OpenAI 公共 API 的字段语义，不能证明 JOJO 兼容 relay 完整实现同一语义。目标适配器没有发送 `max_output_tokens` 或 `truncation`，而且即使服务端返回 `response.incomplete`，下游 Plugin 结果也看不到该状态。

JOJO 当前公开 FAQ 还说明：

- 包月对话公开地址是 `https://max.jojocode.com/v1`，`https://max2.jojocode.com/v1` 被列为包月生图地址；目标现场却把 `max2` 用作 `codex_responses` 对话首跳，因此这组组合没有在公开 FAQ 中取得对话容量合同；
- Codex 可能按任务、上下文和策略选择实际请求模型，用量按最终模型记录；
- 上下文能力由模型和上游服务决定，平台不能任意扩展。

见 [JOJO 官方 FAQ](https://docs.jojocode.com/faq)。这不能推出 JOJO 一定截断或一定不截断；它只证明不能用请求中的 `gpt-5.6-sol` 名称或 OpenAI 同名模型的公开窗口冒充目标 relay 全部实际路线的共同保证。

## 4. 固定提交的最终请求组装

`ctx.llm` 先把结构化候选格式构造成 `extra_body.response_format`，再调用内部 `call_llm(task=None, ...)`。[Plugin 结构化格式与内部调用](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L800-L918) 目标 `codex_responses` 路线随后进入 `_CodexCompletionsAdapter`，实际 wire 组装如下：

| 输入组成 | 固定源码实际行为 | 当前是否可准确计量 |
|---|---|---|
| 固定指令 | system 消息被抽成 Responses `instructions`；没有 system 时还会注入 `You are a helpful assistant.` | 会占输入，但 Plugin 没有暴露最终 wire token 计数 |
| 当前会话、健康画像和其他附带文本 | 非 system 消息经共享转换器进入 Responses `input` | 内容能进入 wire，但本地只有粗估，不是目标 tokenizer |
| 图片 | 随消息内容转换进 `input` | 本地按每图约 1,500 token 粗估，不能代表目标图像分块/尺寸/detail 规则 |
| 结构化候选 schema | Plugin 构造 `extra_body.response_format`；适配器只从 `extra_body` 读取 `reasoning`，没有读取或发送 `response_format` | 在当前目标 wire 上不计入输入，但同时意味着结构化输出约束并未下发 |
| tools/schema | 有 tools 时适配器另行传 tools | 若健康请求未来带 tools，仍需把最终 schema 与包装计入；当前没有统一计量合同 |
| provider/Hermes 包装 | 适配器发送 `model`、`instructions`、`input`、`store=False` 等字段 | 能看到 Hermes 侧结构，无法证明 relay/上游的隐藏包装与计费 tokenizer |
| 输出预留 | 目标适配器明确不发送 `max_output_tokens`；公开 `max_tokens` 也未被读取 | 没有可由 Plugin 设定并证明生效的 `O_reserve` |

固定依据：适配器把 system 与 replay messages 分离，并构造 `model`、`instructions`、`input`、`store=False`。[消息与 wire 主体](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L1046-L1103) 它明确省略 `max_output_tokens`，且处理 `extra_body` 时只取 `reasoning`。[输出上限与 extra_body](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L1104-L1144)

### 4.1 `max_tokens` 在目标路线不是输出上限

`_build_call_kwargs` 默认不保留 `max_tokens`，只对 Anthropic-compatible、Nous Messages、NVIDIA NIM、MoA reference 或 native Gemini 等特例保留。当前 `jojo` + `max2.jojocode.com` 不属于这些列明特例。[参数保留条件](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L7172-L7265) 即使其他路线带上该字段，源码在部分 provider 报参数错误时还会移除 `max_tokens` 与 `max_completion_tokens` 后重试。[移除并重试](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L8141-L8166)

目标 Codex adapter 自身也不把 chat-shaped `max_tokens` 翻译为 Responses `max_output_tokens`。所以在本路线中，调用 `ctx.llm(max_tokens=N)` 不能解释为“为输出真实预留 N token”，更不能据此计算输入安全上限。

### 4.2 结构化 response format 没有透传

Plugin 的 `complete_structured()` 确实创建 `json_schema` 或 `json_object` 形式的 `extra_body.response_format`，但 `_CodexCompletionsAdapter` 构造最终 `resp_kwargs` 时没有读取这一字段，只翻译 `extra_body.reasoning`。因此候选 schema 当前不占目标 wire 输入，同时也没有服务端结构化强制；Plugin 只能在返回文本后本地解析，不能把“本地解析成功”冒充 provider 按 schema 完整生成。

## 5. 超限、输出耗尽与完成状态

固定 `codex_runtime` 能识别 `response.completed`、`response.incomplete`、`response.failed`，也会暂存 usage、response id、`incomplete_details` 和 error。[终态事件与字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/codex_runtime.py#L856-L936) 但随后发生两次信号损失：

1. 流消费器把 `terminal_status` 初始设为 `completed`；若流没有终态事件但已产生部分正文，它不会报错，而是返回 `status=completed`。只有“无终态且完全无内容”才报错。[无终态流的归一化](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/codex_runtime.py#L956-L967) [部分内容仍返回 completed](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/codex_runtime.py#L1080-L1148)
2. auxiliary adapter 只提取正文、tool call 和 usage，再无条件生成 `finish_reason="stop"`（或 `tool_calls`），并把 `model` 设为本地请求模型；它没有携带 final status、`incomplete_details`、error 或 response id。[结果归一化](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L1384-L1442)

所以当前可观察行为是：

| 情形 | OpenAI 公共 Responses 语义 | 目标 Hermes/JOJO 当前可证明的事 |
|---|---|---|
| 输入超过窗口 | `truncation=disabled` 默认应 400；`auto` 会丢最旧输入 | 适配器没有显式发送 truncation；JOJO 是否完全等价未知；错误还可能进入 Hermes fallback，不能在调用前保证单一路线 |
| 输出上限耗尽 | 可返回 `response.incomplete` 与 `reason=max_tokens` | Plugin 看不到该状态；有正文时可能表现成普通 `stop` |
| 流中途断开且已有正文 | 官方完整请求应有终态事件 | 固定 Hermes 会把部分正文组装为 completed，再合成 `stop` |
| 服务端静默裁剪或隐藏包装 | usage 只能反映服务端最终报告 | 没有请求前 token 证明或内容完整性回执，不能从 usage 排除裁剪 |
| relay 改选实际模型 | 需服务端权威标识 | adapter 返回的是请求中的 model；JOJO 用量记录虽可事后显示最终模型，但不在 `ctx.llm` 结果合同中，也不是事前共同窗口保证 |

结论是：返回文本、非零 usage、`finish_reason=stop` 和 `model=gpt-5.6-sol` 均不足以证明输入未截断、输出完整或实际下游就是请求模型。

## 6. token 估算与上下文元数据不是容量合同

`model_metadata.get_model_context_length()` 优先直接采用正的 `config_context_length`，注释为“user knows best”；若其他探测均失败，默认回退到 256,000。[配置优先与解析顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/model_metadata.py#L2276-L2310) [未知模型的 256K 回退](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/model_metadata.py#L2730-L2753) 因此现场 240,000 是 Hermes 调度使用的操作者配置值，不是 JOJO/上游实时证明。

`estimate_tokens_rough()` 对 ASCII 用约 4 字符/token，对 CJK/Hangul/Kana 用约 1 codepoint/token；`estimate_messages_tokens_rough()` 对每张图片固定估约 1,500 token，并明确借用 Anthropic pricing model。[文本粗估](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/model_metadata.py#L2805-L2831) [图片粗估](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/model_metadata.py#L2833-L2847) 这套估算没有证明对目标 tokenizer、中文与 emoji 混合文本、JSON 转义、引用 ID、角色包装、图片尺寸/detail、工具/schema 和 relay 隐藏包装永不低估。

fallback 也没有补上共同下限：固定源码只有 `compression` task 设 64K 最低窗口；`ctx.llm` 使用 `task=None`，没有最低窗口。无法识别的候选还按“unknown — pass through”继续。[fallback 上下文筛选边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L4618-L4692) 容量、连接、限流、模型不兼容或无效响应可触发 fallback，顺序还可能进入主 Agent model safety net。[fallback 条件与顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L8363-L8455)

## 7. 目标现场非敏感只读事实

2026-08-18 06:23（Asia/Shanghai）只读采样确认：

- Hermes HEAD：`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；
- `hermes-gateway-partner.service`：`active`；
- 当前模型：provider `jojo`，model `gpt-5.6-sol`，API mode `codex_responses`，base URL `https://max2.jojocode.com/v1`；
- `model.context_length`：240,000；`auxiliary.compression.context_length`：240,000；
- 顶层 `fallback_model` 与 `fallback_providers` 未配置；
- 当前 provider definition 只列同一个 `gpt-5.6-sol` 与 `codex_responses` transport。

上述只证明当前 Hermes 可见的第一跳配置。顶层 fallback 未配置不等于 `ctx.llm` 内部 fallback 被禁用，也不等于 JOJO 内部模型/上游固定；240,000 也没有被现场请求或服务合同独立验证。本票没有读取任何 key、请求 header、聊天或健康正文。

## 8. 证据分层、未知与失效条件

| 分层 | 已闭合结论 |
|---|---|
| OpenAI 公共 API | Responses 公开的 max output、truncation、usage 与 incomplete 字段语义；仅适用于其公开合同，不能自动外推给 JOJO relay |
| JOJO 一手公开资料 | max/max2 的公开用途；实际模型可能按任务、上下文和策略变化；上下文受模型和上游限制；未给出目标组合的数值共同下限或 tokenizer 合同 |
| 固定提交源码 | 最终请求字段；`max_tokens`/`response_format` 不落到目标 wire；粗估与静态 context metadata；fallback 无通用下限；incomplete/failed 与缺失终态信号被丢失或归一化 |
| 目标现场只读事实 | 固定 commit、服务 active、名义 jojo/max2/codex_responses/gpt-5.6-sol、静态 240K、未配置顶层 fallback |
| 推论 | 因四个必要量无法同时证明，健康请求不能在调用前形成 fail-closed 容量合同；这不等于已证明 JOJO 必然截断 |
| 仍未知 | JOJO 该组合的真实最小窗口、全部内部路线、实际 tokenizer、图片计费、隐藏包装、超限/断流实现、最终模型和任何非公开合同 |

未来若形成正向容量事实，下列任一变化都必须使其自动失效并重新核验：Hermes commit 或 adapter 代码、profile/provider definition、provider/model/base URL/API mode/context_length、auth profile、auxiliary/fallback 配置、JOJO 路由或上游合同、instructions、消息序列化、图片 detail、tools/schema、reasoning/output 限制。仅改变模型显示名称或本地 240K 数字不得延续旧结论。

## 9. 为什么不需要真实 canary 才能解决本票

本票的负向结论由可重复的静态事实成立：输出 cap 未下发、structured format 未下发、终态被丢弃、粗估不是上界、通用 fallback 无共同下限。真实无健康正文请求最多能观察某一次路线的成功或错误，不能把这些接口缺口变成保证，也不能覆盖 JOJO 未选择的内部路线，所以本次不请求或执行 canary。

若未来要建立正向 CAN，最低测试也必须在先修复请求/结果合同后再做：用纯合成中英/JSON/引用 ID/图片 fixture 捕获最终适配后的请求结构；获得与该结构和实际上游一致的 tokenizer 或服务端 count 合同；对每条允许路线验证窗口两侧、明确输出耗尽、输入超限、`response.incomplete`、缺失终态流与 fallback；只记录 route fingerprint、token 数、终态、错误码和 fixture hash，不记录正文。有限 canary 仍不能替代上游共同下限与路由合同。

## 10. CAN 答案与下游约束

当前 Partner Hermes v0.20.0 的 `ctx.llm` **不能在发送前证明**“当前会话内容 + 健康画像 + 规则/知识等附带信息 + 序列化包装 + 输出预留”落在所有允许路线的有效共同窗口内，也**不能在返回后可靠证明**没有截断或输出耗尽。

因此 Ticket 50 必须继续失败关闭：只要健康诊断调用的最终 `I_upper + O_reserve <= W_min` 无法由受支持接口证明，就不得发送该诊断请求；不得依赖任意巨大余量、服务端报错、事后 usage/`stop`、局部材料裁剪或自动 fallback。后续 HOW 必须先补齐“最终请求可计量、真实输出 cap、结构化格式透传、完整终态保留、全部允许路线容量下限和配置指纹失效”这些能力，再讨论上下文组织策略。
