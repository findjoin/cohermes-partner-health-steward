# 健康模型路由与实际接收方事前锁定核验（Ticket 57）

## 1. 范围与证据纪律

- 本报告只回答 CAN：在既定“同一个 Partner Hermes、正式健康 Plugin、不新增独立 Agent、LLM Gateway 或健康专用 provider 入口”边界内，目标 Hermes v0.20.0 是否已经提供一条正式且实际可用的模型调用路线，同时满足普通历史隔离与实际接收方事前锁定。它不选择 HOW，也不修改既定 TO。
- 固定源码为 Hermes Agent v0.20.0 / tag `v2026.8.3`，commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)。目标现场版本、名义 provider/endpoint/API mode 继承自同日已经完成只读现场核验的 [Ticket 56 证据](10-health-data-plane-tools-and-interfaces-20260817.md)，本票没有再次读取目标配置文件、凭据或正文。
- JOJO relay 只采用其公开一手站点与帮助中心；没有用第三方测评推断其下游或留存。搜索和核对的公开页面包括 [JOJO Code 官方主页](https://home.jojocode.com/)、[官方 FAQ](https://docs.jojocode.com/faq)、[官方状态码说明](https://docs.jojocode.com/status)和[官方支持页](https://docs.jojocode.com/support)。
- 本次没有读取 secret、聊天、Session、日志或健康正文，没有安装依赖、修改目标、重启服务，也没有发送模型或微信请求、探测凭据池或注入 fallback 故障。

## 2. 直接结论

**负向结论：目标 Hermes v0.20.0 与当前 JOJO relay 路线中，不存在一条已验证、受支持且实际可用的接口，能够同时满足“健康正文不进入普通 Session/Memory/FTS/通用日志”和“任何正文离开本机前锁定 provider、endpoint、Hermes fallback 以及 relay 的全部下游接收方”。**

最小不可满足原因只有两层：

1. Hermes 正式 Plugin 中，`ctx.llm` 是官方支持的 out-of-band 模型入口；它不自动建立普通 Session，但 API 不暴露 endpoint、禁用 fallback、route preview 或发送前最终接收方回调，而且官方明确由宿主管理通常的 fallback。[官方支持入口与职责](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L7-L13) [公开参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L176-L213) [宿主管理 fallback](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L354-L378)
2. 当前名义 endpoint 是 JOJO relay，而 JOJO 自己的公开页面说明平台使用“智能故障转移和动态模型路由”，FAQ 还说明平台按最终收到并结算的模型记录用量；这些一手页面没有给出请求发送前可查询并强制允许的下游集合，也没有公开覆盖请求正文的留存期限、删除或不训练承诺。[JOJO 官方主页](https://home.jojocode.com/) [JOJO 官方 FAQ](https://docs.jojocode.com/faq)

这不是“再发一次真实请求就能闭合”的未知。成功请求只能证明某次名义 endpoint 接受并返回，不能证明未被选择的 Hermes fallback、relay 动态路由候选、所有真实下游或各方留存政策。故本票可以以负向 CAN 解决；后续必须创建 TO-CAN 差距决策，不能直接回到 Ticket 49 选择 HOW。

## 3. 候选调用面的逐项核验

| 候选调用面 | 是否自动进入普通历史 | 是否提供受支持模型调用 | 能否发送前锁定全部接收方 | 判定 |
|---|---|---|---|---|
| Adapter 在标准 handler 前自行处理 | Hermes 核心尚未创建普通 Session | 自身没有模型入口 | 不适用 | 可作入站隔离点，不是模型路线 |
| Plugin slash command | 固定源码在创建 Session 前直接执行 | Command 自身不调用模型 | 不适用 | 可作可发现入口；需要模型时仍须另选正式模型接口 |
| `ctx.dispatch_tool` | registry 自身不写 Session/FTS | 只分发 Tool，不是模型 completion | 不适用 | Tool 的副作用和日志仍需另控，不能替代模型路线 |
| `ctx.llm` | out-of-band，不自动创建普通 Session/FTS/Memory | **是，正式 Plugin 模型接口** | **否** | 满足历史隔离的 Hermes 默认部分，但不满足接收方闸门 |
| 普通 Agent / 模型调用 Plugin Tool | user、assistant、tool call/result 进入 Session/FTS，并可能进入 Memory | 是 | 普通 request middleware 可观察名义 provider/base URL，但不闭合 relay 下游；fallback 仍存在 | 因普通历史硬条件直接排除 |
| `register_auxiliary_task` | 只注册配置槽位，本身不执行请求 | 没有向 Plugin 暴露 completion 方法 | 配置可带 `base_url`，但不等于调用前接收方证明或禁用 fallback | 不能冒充第二个正式 Plugin 模型接口 |
| 直接导入 `agent.auxiliary_client.call_llm` | 可由自写代码避开 Session | 私有内部函数，不是 `PluginContext` 支持合同 | 虽有 `base_url` 参数，固定源码仍可能 fallback；`stream=True` 的特殊分支也不是 `ctx.llm` 公开能力 | 按 Ticket 问题明确排除，不能把“可导入”冒充“受支持” |
| 新建 Python `AIAgent`、本地 API server 或自带 provider SDK | 可另做成无普通 Session | 属于另一 Agent、LLM Gateway 或独立 provider/auth 路线 | 仍须自行证明 endpoint、fallback 和外部接收方 | 与已解决 Ticket 47 边界冲突，本票不采用 |

普通历史与 command/direct dispatch 的固定依据见 [Ticket 56 第 4 节](10-health-data-plane-tools-and-interfaces-20260817.md#4-哪些入口会进入普通历史)。目标 `PluginContext` 只把 `ctx.llm` 暴露为宿主管理的模型 facade；`dispatch_tool` 进入 Tool registry，`register_auxiliary_task` 只登记带 provider/model/base_url 等字段的配置槽位，没有返回模型 client 或 call 方法。[`PluginContext.llm`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L339-L370) [`dispatch_tool`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L604-L634) [`register_auxiliary_task`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1066-L1151)

## 4. `ctx.llm`、endpoint 与 fallback 的实际合同

### 4.1 正式 `ctx.llm` 能锁定什么

- Plugin 的信任配置可以允许或限制 `provider`、`model`、`agent_id` 与 auth `profile` override；这是对 Plugin 可请求的**名义 Hermes 路由标识**的控制，不是 endpoint 或下游接收方允许表。[信任闸门](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L280-L344)
- `complete()` / `acomplete()` 没有 `base_url`、`disable_fallback`、`fallback_policy`、`route_preview`、`recipient_allowlist` 或 pre-send callback 参数。它们把请求交给内部 `call_llm(task=None, provider=..., model=...)`；调用结果中的 provider/model 与 audit 是事后归因。[公开调用签名](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L622-L676) [`call_llm` 接线](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L919-L1008)
- `purpose` 会进入 `agent.log` 的 INFO 审计行。只要 Plugin 把健康正文、姓名或症状放进 `purpose`，就会污染通用日志；因此 `ctx.llm` 的“无普通 Session”不等于端到端无通用日志，且不存在框架级健康正文日志防泄漏保证。[官方 audit 说明](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L389-L407)

### 4.2 私有 auxiliary client 也没有可继承的禁用 fallback 合同

固定 `call_llm` 私有函数确实接受 `base_url`、`api_key` 与 `api_mode`；但这不在 `ctx.llm` 公开参数中。更重要的是，非流式调用遇到认证、支付/额度、连接、限流、模型不兼容或无效响应时会计算 `should_fallback`。即使显式选了 provider，容量类错误也绕过显式 provider 闸门；顺序可进入 task fallback、主 Agent 模型或自动发现候选，并把同一 messages 交给候选端点。[私有函数签名](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L8439-L8522) [fallback 条件与顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L9014-L9125)

因此下列说法都不成立：

- “`provider='jojo'` 已经禁止 fallback”；
- “Plugin 允许的 provider 列表就是正文可能到达的 endpoint 列表”；
- “结果里报告 provider/model 就证明发送前已经获得主人同意”；
- “直接 import 私有函数并传 `base_url`，就变成 Hermes 正式支持的健康调用接口”。

普通 Agent 的 request middleware 和 `pre_api_request` 位于普通 conversation loop 内，每次请求可看到当前名义 provider/base URL；但该路线先进入普通 Session 生命周期，而且 middleware/Hook 不是 `ctx.llm` 的调用链，所以不能拼成同时满足两项硬条件的路线。[普通 Agent request 路径](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L2220-L2288) [`ctx.llm` 独立调用链](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L919-L1008)

## 5. 目标现场与 JOJO relay 一手边界

### 5.1 目标现场已验证

同日 Ticket 56 的只读现场核验已确认：

- Partner Hermes 固定 commit 为 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；
- 名义 provider 为 `jojo`；
- 名义 endpoint 为 `https://max2.jojocode.com/v1`；
- API mode 为 `codex_responses`；
- 没有发送真实请求，因而没有把 endpoint 配置冒充实际下游证明。

这些是本机发送请求前可见的**名义第一跳**，不是 relay 后面的所有接收方。Ticket 56 还已确认目标没有健康 Plugin 或已接线的专用 route gate；本票未更改现场。

JOJO 当前公开 FAQ 把 `https://max.jojocode.com/v1` 列为包月对话地址，把现场所用的 `https://max2.jojocode.com/v1` 列为包月生图地址。[JOJO 官方 FAQ](https://docs.jojocode.com/faq) 因此本报告只能确认目标配置了 `max2` 与 `codex_responses`，不能把该组合的对话用途、支持合同或下游路线写成 JOJO 官方已经证明；它可能来自未公开配置或合同，但本次没有这类一手证据。

### 5.2 relay 自己公开了什么、没有公开什么

JOJO 一手公开资料能支持的正向事实是：

- 官方把自身描述为 API Gateway，并宣传“智能故障转移和动态模型路由”；
- 官方 FAQ 说明平台用量记录以“最终收到并结算的模型”为准；
- 官方状态说明使用“上游满载”“上游短时波动”“当前分组没有可用通道”等术语，证明 relay 与模型服务之间还存在平台选择的上游/通道层。[JOJO 官方主页](https://home.jojocode.com/) [FAQ](https://docs.jojocode.com/faq) [状态码说明](https://docs.jojocode.com/status)

在本次核对的公开一手页面中没有找到：

- 给定请求在发送前返回全部候选及最终下游法律实体/endpoint 的接口；
- 可由客户强制的下游允许表或“禁止动态路由/故障转移”参数；
- 请求正文、输出、错误日志和用量记录各自的保留期限、删除范围或不训练承诺；
- 下游变化时向健康画像主人重新征得同意的技术回调。

缺少这些公开证明不能写成“JOJO 一定违规或一定保留正文”；它只意味着当前无法把 JOJO relay 写成已经满足既定健康数据接收方事前知情同意。真实请求、DNS/TLS 观察或返回模型字段也不能补出合同、法律实体和未被选择的候选集合。

## 6. 证据分层

| 分层 | 结论 |
|---|---|
| Hermes 官方保证 | `ctx.llm` 是 Plugin 支持的 out-of-band 模型接口；公开 override 仅 provider/model/agent/profile；宿主管理 fallback 和审计 |
| Hermes 固定源码 | `ctx.llm` 下沉到 private auxiliary client；没有 endpoint/禁 fallback/preflight 参数；容量等错误可绕过显式 provider 并尝试其他候选；普通 Agent 与 `ctx.llm` 调用链分离 |
| 目标现场已验证 | commit、名义 `jojo`、`max2.jojocode.com/v1`、`codex_responses`；无健康 Plugin 或接收方闸门；本票继承同日只读 Evidence 10 |
| JOJO 一手公开资料 | relay 宣传动态模型路由/故障转移并按最终模型记用量；公开页面未给出下游允许表与正文留存合同 |
| 仍未知 | 某次请求真正选中的 JOJO 上游、全部候选、各方日志/留存/训练政策、非公开商务或数据处理合同、目标凭据池运行时可选组合 |
| 需主人另行批准 | 任何模型请求、fallback 故障注入、读取凭据或正文、改变 provider/fallback/config、安装 canary、修改 Hermes 或网络出口；但这些实验也不能单独证明 relay 的合同与全部候选 |

## 7. 对当前 Map 的约束

Ticket 49 不能把以下任一项写成已验证 HOW 输入：

- `ctx.llm` 已禁止 fallback；
- `jojo` 这个 provider 名称已经等于全部健康数据接收方；
- `max2.jojocode.com` 这个第一跳 endpoint 已经等于最终模型处理方；
- 事后 audit、用量记录或真实 canary 能替代发送前接收方知情同意；
- Plugin 直接导入 private client、另建 Agent/API server 或自行持有 provider key 仍符合已解决的单 Hermes 正式模型能力边界。

按 Map 的固定顺序，下一步必须是独立的 TO-CAN 差距决策：由主人决定是保持现有接收方承诺并扩大允许的技术路线，还是修改产品承诺；在该决定前不能认领 Ticket 49，也不能静默以“只披露 JOJO relay”替代“实际接收或处理健康资料的一方”。本报告不替主人选择差距如何关闭。
