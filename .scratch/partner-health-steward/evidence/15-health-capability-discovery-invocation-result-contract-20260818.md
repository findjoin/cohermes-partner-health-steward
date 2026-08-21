# 健康能力发现、调用与结果返回契约核验（Ticket 63）

日期：2026-08-18
目标：Partner Hermes v0.20.0，固定提交 [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)

## 1. 范围、方法与结论

本票只核验 Hermes 已有入口能做什么，不决定七项产品能力最终放到 Skill、Tool、Command 或自动流程中的哪一类，也不设计参数或返回结构。核验使用固定提交的官方源码、官方文档，以及 2026-08-16 至 2026-08-17 已获准取得的目标现场只读事实；没有安装或启用 Skill/Plugin、修改配置、调用健康能力、读取健康正文，或发送模型/微信请求。2026-08-18 的 SSH 复核因本机无法解析目标别名 `findjoin` 未取得新现场样本，因此不能把 2026-08-16/17 的现场状态冒充为 2026-08-18 实时状态。

**负向 CAN：目标版本提供了可承载未来实现的 Skill、Plugin Tool、Plugin Command、Cron Agent 和 Plugin 内部调用面，但没有一个基础接口天然同时保证“主人可发现、确定调用、返回真实业务结果、携带健康主人身份、写入正确历史、且不能绕过健康边界”。目标现场样本也没有健康 Plugin、健康 Tool/Command 或健康 Cron；现有 `medical` Skill 不是七项健康管家能力。**

这里必须分开六个事实：

1. **接口已注册**：名称和 handler 已进入进程内 registry。
2. **模型知道接口**：本轮选用的工具定义或 Skill 索引已放进模型上下文。
3. **主人能发现**：主人所在渠道有可见名称、帮助或明确入口。
4. **调用开始**：模型或显式命令已进入 handler。
5. **业务成功**：权威健康状态已按预期读取、提交、导出或删除。
6. **真实结果返回**：返回值忠实区分成功、失败与副作用不确定，而不是仅表示 handler 未抛错或发送接口已接受。

前一层不推出后一层；Hermes 的通用 registry 和字符串返回也不会替健康业务证明第 5、6 层。

## 2. 入口能力矩阵

| 入口 | 谁能发现 | 如何开始调用 | 返回与错误的真实语义 | 身份上下文 | 普通历史与日志 | 关键绕过边界 |
|---|---|---|---|---|---|---|
| profile/外部目录的普通 Skill | Agent 可通过索引和 `skills_list` 看到摘要；已安装的平面 Skill 可用 `/skill-name` 显式加载，但各渠道菜单可见性并非统一保证 | 主人显式 slash，或模型先 `skill_view` 再继续普通 Agent 回合 | 返回的是知识文档注入后的模型回答，不是受执行合同约束的健康业务结果 | 普通会话可带渠道上下文；Skill 文本本身不是授权主体或安全边界 | 走普通 Agent Session；加载、工具调用与回答进入 transcript/FTS，并可能进入普通 Memory 生命周期 | 模型可不加载、不遵循，或不用健康 Tool 而直接回答 |
| Plugin 注册的 Skill | 必须知道精确 `plugin:skill` 才能用 `skill_view`；它不进入平面 Skill 树，也不列入系统提示的可用 Skill 索引，没有内建主人发现面 | Agent 精确调用 `skill_view` | 同样只是文档内容，不是可执行/可提交结果 | 无额外可信主人身份 | 经普通 Agent 调用时进入普通 transcript | 不能承担唯一健康权威或 fail-closed 闸门 |
| 暴露给普通 Agent 的 Plugin Tool | 只有被选入本轮工具集时模型才看到 JSON schema；主人通常只看到自然语言能力，不等于看到 Tool 名称/schema | 模型自行选择 Tool；模型也可完全不调用 Tool并直接作答 | 标准路径返回 handler 的字符串；异常被转成 JSON 错误字符串。框架不知道该字符串是否代表已提交、未提交或副作用未知 | 标准桥接提供 task/session 等 Agent 上下文，但没有稳定的渠道主人 ID 参数合同 | assistant tool call、tool result 和最终回答进入 Session/FTS，可能进入 Memory；异常也可进日志 | 模型未选择 Tool；其他代码可绕过本轮工具集直接 dispatch |
| Plugin slash Command | 知道精确命令的主人可显式调用；部分原生平台可把 Plugin Command 加入命令面，但带必填参数的命令不一定进入菜单，渠道表现不同 | Gateway 在普通 Agent Session 创建前调用 handler，仅传 `raw_args` | truthy 结果转字符串回复；`None` 无回复；异常只记 warning 后继续。CLI/TUI 的 awaitable 解析有 30 秒等待，Gateway 分支直接 await，未使用该超时 | Gateway 先执行通用渠道/slash 访问检查，但 handler 不接收可信调用者身份，只收到原始参数 | 默认不写普通 Session/FTS/Memory；入站预览、异常、Plugin 自身和渠道仍可能留日志/内容 | 可绕过模型选择和普通 Session；通用 slash 授权不等于健康画像权利授权 |
| `ctx.dispatch_tool` / 直接 registry dispatch | 不提供主人发现面；Plugin 或其他进程内代码知道名称即可调用 | 以名称和 args 直接进入全局 registry | 取得同一个 handler 的字符串，但无 schema 校验；异常转错误字符串。相同 handler 不等于相同前置条件或相同业务结果合同 | Gateway PluginContext 没有 CLI parent agent；接口不传渠道主人身份 | registry 不自动写普通 Session/FTS/Memory；Tool/Plugin/异常日志和副作用仍未知 | 绕过本轮工具暴露、模型选择、标准参数桥接及常规 pre-tool/middleware；具体 handler 自己实现的检查除外 |
| Cron Agent / Plugin 内部自动流程 | Cron 由操作者配置，主人没有天然产品发现面；目标现场样本无任务 | Cron 启动新的 Agent 回合，或 Plugin 代码直接调用 handler/dispatch | 可取得模型回答或 handler 字符串；框架不保证与外部入口采用同一身份、闸门、幂等和失败语义 | Cron 没有当前对话主人身份；内部 direct dispatch 也没有 | Cron 有自己的任务/执行账本；普通 Agent 路径仍有会话记录，direct dispatch 本身不写普通 Session | 自动任务或其他 Plugin 可绕开主人交互授权；若共享 handler 未自校验，不能证明唯一健康权威 |

## 3. 固定提交的逐项源码事实

### 3.1 Skill：可发现知识，不是强制业务入口

- 官方把 Skill 定义为按需加载的知识文档；平面安装的 Skill 可作为 slash command，普通自然语言也只是让 Agent **可能**选择相应 Skill。[Skill 定义、slash 与自然语言使用](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L7-L10) [slash 与自然语言路径](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L44-L80)
- 渐进发现是 `skills_list` 摘要到 `skill_view` 全文；不兼容当前平台的 Skill 可从系统提示、列表和 slash 面隐藏。[渐进发现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L111-L121) [平台过滤](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L160-L174)
- Plugin `register_skill` 使用限定名，并明确不加入平面 Skill 树和系统提示中的 `<available_skills>`；只能在知道精确限定名后由 `skill_view` 读取。[Plugin Skill 注册边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1108-L1147) [`skill_view` 的限定名分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L777-L966)
- Skill slash 会被改写后交回普通 Agent handler，而不是直接产生受验证的业务结果。[Gateway Skill slash 分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L14390-L14408)

所以，Skill 能让模型或知道名称的主人发现“如何做”，不能证明模型一定调用健康执行面，更不能防止普通模型直接生成貌似健康答案。

### 3.2 Plugin Tool：schema 可见不等于调用或业务成功

- `register_tool` 保存名称、schema、handler 和 toolset；跨 toolset 名称冲突须显式 override/operator 允许，同一 toolset 的后注册项则没有同等冲突拒绝语义。[Plugin Tool 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L377-L428)
- registry 只把本轮选择且可用的 Tool 定义交给模型；注册本身不证明模型知道。本轮模型若返回零个 tool call，conversation loop 直接把文本作为最终回答。[模型无 Tool 调用时直接回答](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L6488-L6494)
- 标准 Agent Tool 路径先把 assistant tool call 持久化，再执行 Tool，并把结果续入 transcript。[Tool 调用与执行顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L6211-L6287)
- registry 的直接 dispatch 不执行 JSON schema 校验；handler 异常被捕获、记录并转为 JSON 错误字符串。handler 正常返回字符串只证明调用层拿到了字符串，框架没有权威健康状态可据以确认业务提交。[registry dispatch](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/registry.py#L673-L735)

因此，Tool schema 对模型可见、模型发出 tool call、handler 返回非错误字符串，仍分别只是第 2、4 层和接口返回；它们都不能单独证明第 5、6 层。

### 3.3 Plugin Command：可显式调用，但没有健康身份和结果合同

- Command 注册只允许 `handler(raw_args)`，与内建命令冲突会拒绝；Plugin 命令存入按名索引，没有携带调用者对象的 handler 签名。[Command 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L503-L550)
- Gateway 在进入 Plugin Command 前已做普通渠道授权与 slash 访问判断；但真正执行时只把命令后的原始字符串交给 handler。[Gateway 通用授权](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13397-L13465) [slash 访问判断](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13901-L13960) [Plugin Command 执行](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L14374-L14389)
- Command truthy 返回值被 `str()` 化；空值不回复；异常只记录 warning。Gateway 对协程直接 await；Plugin manager 中的 30 秒 awaitable helper 用于同步 CLI/TUI 调用点，不能当作 Gateway 命令超时保证。[Command helper 与 30 秒边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L2147-L2218)
- Plugin Command 能进入部分原生平台命令面，但带必填参数的命令可被菜单过滤；所以“已注册”也不等于各渠道主人都能从菜单发现。[命令表与平台菜单过滤](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/commands.py#L382-L553)

通用渠道 allowlist/pairing 只证明消息来自获准使用 Hermes 的会话，不提供健康画像 owner、代理授权、删除权或紧急诊断权限。Command 若要修改健康状态，必须由其实现自行建立这些事实；v0.20.0 的 Command 接口没有替它完成。

### 3.4 直接调用与自动流程：可复用 handler，但不能假定合同等价

- `ctx.dispatch_tool(name, args)` 直接进入全局 registry；Gateway 下没有 CLI parent agent，调用参数中也没有渠道主人身份。[Plugin direct dispatch](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L553-L578)
- 标准 Agent Tool 桥接才负责本轮工具选择、参数桥接、tool request/execution middleware 与 pre-tool 路径。直接 registry dispatch 不经过该桥接。因此，“内部调用了同一 Tool handler”只证明代码复用，不能证明身份、schema、审批、日志、失败关闭与外部调用一致；Tool handler 内部另行实施的强校验不受此结论否定。
- Cron 任务在独立的新 Agent 会话运行，原生 Cron 只提供调度和执行账本，不自动取得健康档案当前状态或当前对话主人的身份；恢复后的 `success`、`failed`、`unknown` 也是调度层结果，不是七项健康业务的真实结果。[Cron 执行与恢复语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273)

## 4. 普通 Session、Memory、全文索引与日志

| 路径 | 固定源码默认行为 | 不能据此承诺的事 |
|---|---|---|
| Skill 或模型选择 Plugin Tool 的普通 Agent 回合 | Session 保存 user、assistant、tool call、tool result 和实际 API 内容；FTS 索引正文及 Tool 字段；普通 Memory 生命周期可能再处理这些会话 | 不能承诺健康正文与普通聊天隔离 |
| 已识别的 Plugin Command | 在普通 Session 创建前返回，不自动写普通 Session/FTS/Memory | 不等于零留存；入站消息预览、异常、渠道、Plugin 自有日志仍可能保存内容 |
| `ctx.dispatch_tool` | registry 自身不创建或追加普通 Session | Tool 副作用、Plugin 日志、异常日志和外部系统留存仍未知 |
| Cron Agent | 有 Cron 任务/执行账本；若走 Agent，会形成相应 Agent 执行内容 | 不等于主人普通对话历史，也不等于健康产品审计账本 |

普通 Session 的持久化字段和 FTS 范围见[官方 Session 存储文档](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27)及[消息/API 内容字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)。Gateway 的普通 Session 创建与 transcript 保存见[Session 创建点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L15168-L15168)和[transcript 保存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L16798-L16850)。Gateway 还会记录入站消息预览，因此 Command 早于 Session 不代表参数不会进日志。[入站日志点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L15149-L15152)

## 5. 七项首发能力的当前 CAN

| 首发能力 | 目标 Hermes/现场当前提供的真实业务能力 | 不能冒充真实结果的信号 |
|---|---|---|
| 初始化健康管家 | **未提供。** 没有健康 Plugin、初始化状态或已验证入口 | Skill 已加载、Command/Tool 已注册、handler 返回文本 |
| 询问健康管家 | **未提供。** `medical` Skill 可辅助普通模型，但不是健康管家权威档案问答，也不强制经过诊断安全路径 | 模型生成了看似合理的健康回答 |
| 更新健康画像 | **未提供。** 没有权威健康画像实现或已验证提交结果 | Tool/Command 无异常、返回“已更新”字符串 |
| 导出健康画像 | **未提供。** 没有健康画像或已验证导出物/交付 | 创建文件、发送接口接受或模型给出摘要 |
| 设置管家行为 | **未提供。** 没有健康产品配置状态、owner 授权或生效证明 | 修改普通提示、Skill 文本或返回“设置成功” |
| 永久删除健康画像 | **未提供。** 没有健康档案删除实现、身份/权利检查或覆盖范围证明 | handler 返回成功、删除单个文件或不再显示 |
| 查看运行状态 | **未提供健康产品状态。** Hermes/Gateway/Cron 有局部运行信号，但现场没有健康核心、健康任务或主人状态面 | Gateway 存活、Cron ticker 正常、命令可响应 |

这七个结论都是当前实现的负向 CAN，不是降低产品目标。基础接口仍有承载实现的空间，但实现后的每项能力还必须用其权威状态和副作用证据证明真实结果；本票不决定入口映射。

## 6. 目标现场只读事实

2026-08-16/17 已获准现场证据显示：

- `/usr/local/lib/hermes-agent` 的 HEAD 为固定提交 `3c27eb...`，但工作树有与健康能力无关的现场定制；不能把脏工作树笼统称为官方发行原样。
- `hermes plugins list --plain` 没有 `enabled` 项，profile `plugins/` 下没有 `plugin.yaml`；因此没有已启用健康 Plugin，也没有由其注册的健康 Tool/Command。
- profile 只有 `skills/medical/SKILL.md` 这一项相关知识资产；它不是健康管家实现。
- `hermes cron list` 为 `No scheduled jobs.`；没有健康自动流程。
- 没有可识别的健康产品持久状态或主人状态面。

上述现场原始采样方法与物理含义固定在[目标 Hermes 扩展基线](02-target-hermes-extension-baseline-20260816.md#2-目标现场基线)和[调度、投递与状态现场证据](04-scheduling-delivery-recovery-runtime-status-capabilities-20260816.md#6-目标现场事实)。本票没有取得 2026-08-18 新快照，所以“此刻仍未变化”属于未证明项。

## 7. 证据分层与未证明项

| 层级 | 已闭合内容 |
|---|---|
| 官方保证 | Skills 是按需知识；Plugins 可注册 Tool/Command/Skill；Cron 有调度与执行账本；Session 保存普通 Agent transcript |
| 固定提交源码行为 | Plugin Skill 的隐藏索引边界；Tool/Command 注册、选择、返回、错误与超时路径；normal Tool 与 direct dispatch 的不同桥接；Session/FTS 写入点 |
| 目标现场只读事实 | 2026-08-16/17 固定 HEAD 与脏改范围；无 enabled Plugin、健康 Tool/Command、健康 Cron；只有 `medical` Skill；无健康产品状态面 |
| 未证明 | 2026-08-18 实时现场是否变化；任何未来健康实现的真实提交/回读/导出/永久删除；主人身份传播；微信入口发现；异常、超时和副作用未知态；外部留存；自动与外部调用结果等价 |
| 需主人批准的实验 | 安装/启用 canary Plugin 或 Skill、改配置、发送模型/微信、调用写入或删除能力、读取健康正文、制造超时/崩溃/重复投递。以上均未执行 |

## 8. CAN 答案

Hermes v0.20.0 **能提供扩展入口，不能现成提供七项健康能力的端到端发现、调用和真实结果合同**。普通 Skill 能被索引或显式加载，但只是普通 Agent 的知识注入；Plugin Tool 只有被暴露时模型才知道，模型可以不调用，且正常调用/结果进入普通 Session；Plugin Command 可由知道名称的主人显式调用并绕开普通 Session，但只接收 `raw_args`，不自带健康主人身份，异常与 Gateway 超时也没有业务级确定性；`ctx.dispatch_tool` 和自动/其他 Plugin 路径能够绕过本轮工具选择及通用桥接，因而不能仅靠注册表证明健康边界不可绕过。

目标现场证据中七项健康能力全部尚未实现或未证明。任何后续入口只有在分别证明主人可发现、确定调用、权威业务状态、真实结果、身份/权利/诊断安全、失败关闭、历史隔离和旁路收敛后，才能从“可承载”提升为“产品能力可用”。本票不选择 HOW。
