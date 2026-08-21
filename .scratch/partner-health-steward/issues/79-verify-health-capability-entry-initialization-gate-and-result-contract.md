# 【CAN】核验健康能力入口、初始化门禁与真实结果返回能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md)

## Question

在当前目标 Partner Hermes 的受支持扩展面中，Skill、Plugin Tool/Command、自然语言入口和内部 dispatch 分别能够怎样让主人或同一 Hermes 发现并调用初始化、询问、更新、导出、行为设置、删除、运行状态和健康任务相关能力；注册成功、模型可见、主人可发现、调用开始、业务提交、真实业务结果和主人实际收到能否被明确区分？

本票特别要证明初始化是否存在一个可查询、不可被普通聊天或其他入口旁路的产品门禁：初始化完成前健康管家不分类健康消息、不读取或写入画像、不形成证据、任务、诊断、危险处理或健康接收事实；初始化必须向主人说明健康资料范围、每日复盘、任务自动化、主动支持、当前首跳接收方、通知选择和主人数据权利，并把明确同意、时区、基础偏好和初始画像作为一个完整初始化结果。只有该结果整体成立后才启动健康合同，部分完成或中断不得冒充启用；初始化前由基础 Hermes 处理的内容以后也不得自动倒填为健康画像、证据或任务。初始化后，各入口又必须汇入同一画像、证据、任务、数据权利和安全边界，不能因模型未选择某个 Tool 或 Skill 而绕过。

本票只调查候选入口及其事实边界，不决定四项职责是否恰好实现成四个 Skill，也不选择 Skill/Tool/Command 映射。文档、注册表或一次返回字符串不能证明产品结果；目标现场调用与受管状态变化证据、失败和结果未知边界必须分开记录。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C02。

本票重建[【CAN】核验健康能力发现、调用与结果返回契约](63-verify-health-capability-discovery-invocation-and-result-contract.md)的当前问题边界，加入初始化硬闸门、开放任务和四项职责，但不继承旧“七个入口即完整产品”的范围假设。

## Answer

完整证据见[《健康能力入口、初始化门禁与真实结果返回能力》](../evidence/20-health-capability-entry-initialization-gate-result-contract-20260820.md)。本票继承[【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md)在 2026-08-20 的同一现场指纹，并重新核验固定提交与当前工作树候选；没有重复读取现场凭据、聊天或健康正文，没有安装或启用组件、调用模型或微信、发送消息、重启服务或制造故障。

当前正式 Partner 没有 ordinary/user/project 健康 Plugin、没有 profile Plugin manifest、没有业务 Cron，也没有可查询的健康初始化状态。Telegram 与 Weixin 仍同时 configured，CLI/chat、Cron、`send` 和内部 dispatch 等代码入口仍存在；所以现场既没有“只有完整初始化后才启动”的健康门禁，也没有任何一项受管健康能力已经通过真实结果或主人到达验证。Gateway 存活、Skill 文件数、Plugin 清单或接口代码存在均不能补出这些产品事实。

Hermes v0.20.0 的固定合同确有可组合入口原语：普通 Skill 与 Plugin Skill提供按需知识，Plugin Tool/Command 可注册执行入口，Plugin Platform 可接管渠道，Plugin 或 Cron 可内部调用。但它们不天然形成统一健康合同：模型可以不选 Tool；Command 只接收 `raw_args`；direct dispatch 不经过普通 Agent Tool 桥接；Cron 没有当前对话主人上下文；`pre_gateway_dispatch` 不处理 internal event，且 Plugin 加载、Hook、Middleware 与该分流 Hook 的异常默认会继续基础流程。因而必须分别证明资产加载、接口注册、模型可见、主人可发现、调用开始、权威业务提交、真实结果返回和主人实际收到，前一层不推出后一层。

当前工作树中的历史候选也不能作为正向答案。候选 `health-steward` Plugin只注册每日复盘、到期任务派发、只读投影与 Weixin Platform，没有初始化 Skill、Tool 或 Command；Weixin ingress 只识别“启用健康记录”两句短语并保存 recording consent，状态实现明确允许已启用但画像尚不存在，时区与主动联系状态以后由空画像默认值产生。它没有把资料范围、每日复盘、任务自动化、主动支持、首跳接收方、通知选择、主人权利、明确同意、主人确认的时区与偏好及初始画像形成一个完整初始化结果；viewer、恢复码与旧 Telegram 合同也已被现行 TO 取代，不能整体继承。

结论是：**当前基座具备继续实现与调查所需的扩展空间，但 C02 所要求的独立可发现初始化入口、部分或中断不启用、初始化前零健康效果且不倒填、初始化后所有入口与四项职责汇入同一受管边界，以及真实业务结果与主人实际到达，均尚未实现或未证明。** 这项负向 CAN 足以闭合本调查，但不降低 TO，也不选择四项职责是否恰好实现成四个 Skill，或 Skill、Tool、Command、Platform 的最终映射。唯一微信准入、受管状态正确性、任务生命周期、主人权利、运行三态与非诊断问答质量继续由各自后继 CAN 证明；真实模型、微信和故障实验须在有候选实现且另行获准后进行。
