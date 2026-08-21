# 【CAN】核验辅助诊断、医学知识与安全边界能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md)

## Question

在已核验的目标 Hermes 扩展面内，健康问答和辅助诊断能否获得最小必要的当前个人证据、保持 AI 判断与主人提供的医生诊断分离、使用可追溯医学知识、询问缺失事实，并在急症、自伤和危险用药情形下优先安全升级且不擅自调整处方药？核验可用的模型调用、知识来源、工具和安全控制边界，只报告 CAN 事实，不选择实现方案。

## Answer

目标 Hermes v0.20.0 支持 Plugin 自行构造最小输入并发起独立、结构化的模型调用，也支持 Tool、Skill、Platform Adapter 以及带 URL 的通用网页搜索与提取。这些正式扩展面足以保留专用健康路径的实现空间，但 JSON Schema 只约束输出形状，URL 只标识资料位置；二者都不能证明医学判断正确或来源可信。

Hermes 原生没有个人健康证据语义、AI 判断与主人转述医生诊断的领域分离、可信医学来源策略、诊断质量保证、急症/自伤/危险用药分类器或处方建议边界。普通 Agent 可以不调用工具而直接输出文字建议；通用 Hook、Middleware 与输出转换在异常时还可能继续原路径。因此 Skill、提示词、工具权限或现成 Hook/Middleware 均不能单独充当不可绕过、失败关闭的医疗安全闸门。

正式 Plugin Adapter 与插件自有处理代码仍可在普通 Agent 前承接最小证据选择、结构化诊断、受控知识入口和生成至发送的安全处理，所以当前不创建 TO-CAN 差距票，也不缩小已确认的诊断目标。这只是基于支持扩展合同的可行性判断；后续 HOW 仍须选择具体权威与强制路线，真实模型的辅助诊断质量必须在后续产品级验收中证明。

2026-08-16 的只读现场核验确认：Partner 当前只有通用模型/搜索工具与 community `medical` Skill，没有健康 Plugin、可追溯医学来源库、受控辅助诊断流程或健康安全闸门。该 Skill 明确禁止诊断，与当前 TO 冲突；其急症检查只覆盖少量英文子串且存在缺少 `sys` 导入的执行缺陷，用药样例也没有可信来源和完整覆盖，不能作为产品能力或验收证据。完整源码、现场事实、CAN 矩阵、参数物理含义与差距触发条件见 [辅助诊断、医学知识与安全边界能力核验](../evidence/06-diagnostic-reasoning-knowledge-safety-capabilities-20260816.md)。

## Comments

### 2026-08-17 — 继承权威说明

本票关于 Hermes 扩展面、医学语义缺失和安全闸门缺失的基础 CAN 原样继承；`## Answer` 不回写。关于具体医学来源与强制工具是否足以直接进入 HOW 的过程判断，现由 [【CAN】核验医学知识来源、检索接口与安全强制工具](59-verify-medical-knowledge-and-safety-enforcement-tools.md) 和 [【TO】决定医学来源缺口下是否保留辅助诊断目标及上线边界](60-decide-medical-source-gap-boundary.md) 接续并取代。
