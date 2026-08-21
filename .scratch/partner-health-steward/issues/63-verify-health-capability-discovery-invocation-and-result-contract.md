# 【CAN】核验健康能力发现、调用与结果返回契约

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确认首发健康管家的基础产品能力与不可妥协边界](53-confirm-foundational-product-capabilities-and-boundaries.md), [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md), [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md)

## Question

针对已确认的初始化健康管家、询问健康管家、更新健康画像、导出健康画像、设置管家行为、永久删除健康画像和查看运行状态七项首发能力，目标 Partner Hermes v0.20.0 的 Skill、Plugin Tool、Command、自动流程及 Agent 调用接口，真实提供、限制或缺失哪些“可发现、可调用、返回真实结果且不可绕过健康边界”的能力？只核验 CAN，不决定七项能力最终映射到哪类入口，也不设计 Skill/Tool 契约。

研究至少覆盖：Skill 的索引、加载、按需知识注入和主人可见发现语义；Plugin Tool/Command 的注册、名称冲突、参数 schema、调用者身份、自然语言选择、显式调用、内部 dispatch、返回值、错误和超时语义；自动流程或健康 Plugin 内部调用能否取得与外部入口一致的真实结果；哪些路径会写入普通 Session、Memory、全文索引或日志；主人和同一 Hermes Agent 分别能够发现和调用什么；模型未选择 Tool、直接调用 Command/Tool、自动任务或其他 Plugin 时，是否存在绕过主人身份、健康画像权利、诊断安全、失败关闭或唯一健康权威的路径；目标现场实际启用了哪些相关 Skill、Tool、Command 和 Plugin。

结论必须逐项区分官方保证、目标固定提交源码行为、目标现场只读事实、未证明项及需主人批准的实验，并明确“接口已注册、模型知道接口、主人能发现、调用开始、业务成功、真实结果返回”不是同一事实。不得安装或启用 Skill/Plugin、修改配置、调用真实健康能力、读取健康正文或发送模型/微信请求。产出带固定引用的 Markdown 证据并追加 `## Answer`；若既定入口目标缺乏受支持能力，先报告负向 CAN 并建立后继 TO 差距决定，不得直接选择 HOW 或静默缩小七项能力。

## Answer

负向 CAN：Hermes v0.20.0 有 Skill、Plugin Tool、Plugin Command、Cron Agent 和 Plugin 内部调用面，但没有一个基础接口天然同时保证主人可发现、确定调用、返回真实业务结果、携带健康主人身份、写入正确历史且不可绕过健康边界；目标现场 2026-08-16/17 的只读样本也没有健康 Plugin、健康 Tool/Command 或健康 Cron，现有 `medical` Skill 不是健康管家实现。2026-08-18 未取得新的现场快照，现场此刻是否变化仍属未证明。

普通 Skill 只是普通 Agent 的按需知识注入；Plugin Skill 不进入平面索引，须已知精确限定名。Plugin Tool 只有被暴露时模型才知道，模型可不调用并直接回答，标准调用及结果会进入普通 Session/FTS。Plugin Command 可显式调用且默认早于普通 Session，但只向 handler 传 `raw_args`，不自带健康 owner 身份或业务级成功/未知合同。`ctx.dispatch_tool`、Cron 和其他 Plugin 内部路径可绕过本轮工具选择与标准 Tool 桥接，不能仅以共享 handler 或 registry 无报错证明边界一致、业务成功或真实结果返回。

因此，初始化、询问、更新、导出、行为设置、永久删除和健康产品运行状态七项能力在当前现场均为未实现或未证明；Gateway/Cron 存活、接口注册、模型可见、调用开始或返回字符串都不能冒充相应产品能力。本票只闭合 CAN，不决定入口映射。完整入口矩阵、固定源码锚点、现场事实、留痕与绕过边界见[证据 15](../evidence/15-health-capability-discovery-invocation-result-contract-20260818.md)。
