# 通用 Agent 工作合同

本文件只规定 Matt Pocock Skills 与 Superpowers 的调用权和协作边界。它不复制 Skill 库的内部流程，也不保存任何具体项目的架构、状态、参数或验收细节。

## 1. 显式路线：Matt

- Matt Pocock Skills 是本项目采用的顶层生命周期与任务组织方法，但不是常驻、自动运行的总指挥。
- 在 Codex 中，标记为 user-invoked 的 Matt Skill 只能由用户使用 `$skill-name` 显式启动。上游文档中的 `/skill-name` 在 Codex 中对应 `$skill-name`。
- 用户只需记住 `$ask-matt`。它是整个 Skill 库的路线图和入口路由器：判断当前情形适合哪条流程，推荐下一条显式命令，然后停止；它不自行执行工作，也不自动启动另一个 user-invoked Skill。
- 用户显式启动某个 Matt Skill 后，AI 忠实执行该 Skill。到达阶段边界时，AI 应说明本阶段结果和建议的下一条 `$skill-name`，等待用户显式启动，不得静默跨入下一阶段。
- 纯事实问答可以直接处理。AI 可以按各自触发条件自动使用 model-invoked Skill，但不得自动启动或冒充 user-invoked Matt 流程。
- Skill 是否已安装、是否可被模型自动选择和是否已被用户显式调用必须如实区分。用户通过 Skill 选择器发送 `[$skill-name](.../SKILL.md)`，或发送可由 Codex 解析的 `$skill-name`，即构成显式调用；AI 应读取该次调用精确指向的 `SKILL.md` 并执行。Skill 未列入 model-invoked 目录只表示它不能被自动选择，不得据此否定本次显式调用。只有既无用户显式调用、也无可解析 Skill 指针时，才报告入口不可用；不得自行搜索其他隐藏 Skill 来冒充调用。
- 不在本文件中固定或复制 Matt 的内部 Skill 清单、完整调用顺序或产物格式；这些内容以当前安装的 `$ask-matt` 和各 Skill 为唯一来源。
- 同一项工作只保留一条权威产物链。map、spec、tickets、tracker 和完成状态不得出现互相竞争的副本。

## 2. 自动执行与审查：Model-invoked Skills 与 Superpowers

- Model-invoked Skills 可以在当前用户任务或已显式进入的 Matt 阶段中，按照各自描述自动触发；用户无需记住或逐个点名它们。
- Superpowers 主要提供 TDD、系统化调试、验证和代码审查。它接受当前用户任务，或当前 Matt 决策、spec、ticket 作为输入，并把测试、诊断、评审结论和修改证据返回同一条权威产物链。
- Superpowers 不另建与当前工作竞争的顶层生命周期、spec、plan、tracker 或完成状态，也不自行改写已经确认的项目目标和关键取舍。
- 如果某个 Superpowers Skill 自带规划或交付步骤，只采用当前任务需要且不与显式 Matt 流程冲突的部分；需要改变阶段或路线时，停止并建议用户重新调用 `$ask-matt`。
- Superpowers 可以依据失败的测试或审查证据阻止“完成”声明；目标修改、风险接受和不可逆取舍仍由用户决定。

## 3. 事实、决定与项目规则

- AI 负责自行读取代码、文档、数据、历史和验证证据；用户负责目标、关键取舍、风险接受和不可逆决定。
- 项目事实以当前仓库的权威源码、数据和证据为准。进入显式 Matt 流程后，当前 Skill 负责组织这些事实与工作；Model-invoked Skills 和 Superpowers 负责所触发的执行与质量纪律。
- 具体项目的架构、约束、术语、验收标准和操作边界应放在该项目自己的权威文档或更贴近作用域的 `AGENTS.md` 中，不写入这份通用合同。
- 适用的上位指令与安全约束始终优先。用户当前决定与更局部的项目 `AGENTS.md` 或项目硬约束冲突时，暂停并请用户对齐；流程选择不明时建议 `$ask-matt`，不得由 AI 自行裁决。
- 不得用流程文档改写历史事实，也不得把候选、推断或描述性结果表述成已经验证的结论。

## 4. 阶段完成标准

用户显式进入 Matt 流程后，当前阶段只有同时满足以下条件才算完成：

- 当前显式调用的 Skill 已满足自身完成条件；
- 实际执行与用户确认的任务范围一致；
- 所需测试、验证和审查已有可定位证据；
- Model-invoked Skills 或 Superpowers 发现的阻塞问题已经解决，或明确交还用户决定；
- 按当前 Skill 规则，需要记录的结果、证据和剩余风险已经返回同一条权威产物链；
- AI 已说明本阶段结果及建议的下一条显式命令，并在 user-invoked 阶段边界停止等待用户。

## Agent skills

### Issue tracker

本仓库的任务与 spec 使用本地 Markdown，存放在 `.scratch/`。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五个本地状态标签。见 `docs/agents/triage-labels.md`。

### Domain docs

使用单上下文布局：根目录 `CONTEXT.md` 与 `docs/adr/`。见 `docs/agents/domain.md`。

### Architecture governance

实施 Ticket 选择架构或审查要求重开架构时，使用 `docs/agents/architecture-governance.md` 的风险分类、复杂度举证与停止规则；Ticket 只保留经证据说明且经用户确认的本票增量门禁。

### SOL implementation review

实施 Agent 报告冻结 Ticket 完成、准备实施后双轴审查或闭票时，使用 `docs/agents/sol-implementation-review.md`；先通过执行门，再由两名只读 Reviewer 做有界 Spec/Standards 审查。
