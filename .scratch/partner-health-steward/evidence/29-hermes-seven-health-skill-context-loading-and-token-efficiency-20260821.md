# Hermes 七个健康 Skill 的文档分层、加载与 token 成本核验（Ticket 100）

## Answer

核验对象是正式 Partner 所固定的 Hermes Agent `v0.20.0` / commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)，并结合 2026-08-20 的 Partner 只读现场证据。当前 Hermes `main` 的官方 Skills 与 Skill-authoring 页面只用于确认上游现行方向，不能把其后续接口反推给目标版本：[当前 Skills 文档](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md)、[当前官方 Skill-authoring Skill](https://github.com/NousResearch/hermes-agent/blob/main/skills/software-development/hermes-agent-skill-authoring/SKILL.md)。本报告不选择最终入口、加载器、Hook、Tool、存储或上下文注入 HOW。

**结论：Ticket 100 的统一十二栏适合作为七个 Skill 的产品设计审查表，但不适合要求七份运行时 `SKILL.md` 逐栏、等长、重复展开。** Hermes 的稳定发现首先取决于唯一规范名、短而有区分力的 `description` 与清晰的 `When to Use`；职责执行需要在主文档中保留选择边界、最小输入类别、步骤、候选输出、交回、禁止写入和停止条件。共享结构、长规则、示例与解释应只保存一次并按需加载；画像、证据、任务、设置等主人动态状态不得写入 `SKILL.md`。统一栏目本身不能保证模型稳定选择或运行时失败关闭。

### 一、TO、CAN 与 HOW 的边界

- **TO 可以确认：**七个能力的主人目的、友好名与规范名、应当和不应当选择的场景、每项职责完成后必须产生的候选结果、主人可见失败结果、哪些个人状态不得由 Skill 自行修改，以及“只有获得本次必要且当前的业务投影才能形成结果”。
- **本报告确认的 CAN：**Hermes 怎样把 Skill 摘要放入系统提示、怎样全文加载、普通 Skill 与 Plugin Skill 的发现差异、slash 与 `skill_view` 的正文位置、`pre_llm_call` 的注入位置及其失败语义，以及这些路径的输入成本。
- **HOW 才能选择：**七个 Skill 放在 profile Skill 还是 Plugin Skill、总路由是否依赖模型自然选择、动态上下文由哪一条受管路径取得和注入、共享规则由何种 loader 读取、怎样证明实际版本和失败关闭。下面的分层建议是可执行的文档约束，不替代这些选择。

### 二、统一十二栏如何落到 Hermes `SKILL.md`

目标版本官方格式要求 YAML frontmatter，并把正文组织为 `When to Use`、`Prerequisites`、`How to Run`、`Quick Reference`、`Procedure`、`Pitfalls`、`Verification`；官方还明确建议把 scripts、references、templates 放到各自支持目录，而不是全部塞进主文档。[目标版本 `SKILL.md` 格式与 authoring 标准](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/CONTRIBUTING.md#L423-L475) [正文顺序、体量目标与 supporting files](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/CONTRIBUTING.md#L565-L613)

因此，十二栏应作为完整性检查，运行正文压缩为以下层次：

| Ticket 100 审查内容 | 运行时放置建议 | 物理作用 |
|---|---|---|
| 规范名、版本 | frontmatter 的 `name`、`version` | 形成稳定标识；版本仍需由未来部署清单证明实际生效 |
| 友好名、主人目的、A/B/C 角色 | 标题与 2–3 句简介 | 让模型理解主人侧能力，不承担路由发现的全部责任 |
| 选择条件、明确不选择、启用前提 | `description` 的首要触发语句 + `When to Use` | `description` 进入常驻 Skill 索引；`When to Use` 只在全文加载后可见 |
| 必需、可选、禁止的上下文 | 主文档保留**类别、缺失行为和禁止项**；字段表与共享结构按需引用 | 避免正文携带个人数据，同时让职责在上下文缺失时停止 |
| 处理规则与依赖顺序 | 精简 `Procedure` | Skill 被实际加载后指导本轮处理 |
| 候选结果、交回 `health-steward` | 精简“Return contract”或并入 `Procedure` | 规定候选输出和交接，不把模型文字冒充权威提交 |
| 不得修改的权威对象 | 主文档的短硬约束 | 每次加载都必须可见，不应藏在可选参考文件中 |
| 失败、无法确认、停止条件 | `Pitfalls` + 明确 Stop 条款 | 避免缺资料时继续猜测 |
| 主人可见实际使用披露 | 主文档一条结果义务；共享措辞只引用一次 | Skill 文本只能规定义务，不能证明本次确实使用 |
| 共享产品规则版本 | 主文档只保留规则 ID/最低兼容版本 | 避免七份复制同一规则；实际解析和版本核验留给 HOW |
| 验证 | `Verification` | 验证 Skill 的选择/输出合同；不能把文档测试冒充健康业务验收 |

不建议把“七个 Skill 都必须有十二个同名 H2”当作 Hermes 合规要求。官方解析器真正用于发现的是 frontmatter 和 `description`；正文栏目是给模型加载后的执行说明。目标源码将系统提示中的 `description` 限制为 60 个字符，超长时只保留前 57 个字符再加省略号；新 Skill 的创建校验也明确要求触发信号必须在这一窗口内。[描述截断](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/skill_utils.py#L833-L855) [新 Skill 的描述校验与物理理由](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skill_manager_tool.py#L570-L618)

这意味着七个健康 Skill 若名称相近、描述都只写“管理健康信息”，会损害选择；应让每个 `description` 在最前面给出互斥的触发对象，例如“识别并整理主人新提供的个人健康资料”与“依据已准入证据更新画像”，而详细排除条件再放 `When to Use`。具体中文文案属于后续撰写和验证，不在本 CAN 中替 Ticket 100 定稿。

### 三、发现、选择和全文加载的真实路径

1. **普通自然语言。**目标版本在系统提示中放入一个紧凑 Skill 索引，其中包含可见 Skill 的名称和短描述，并指示模型匹配后调用 `skill_view`；这提高选择概率，但最终仍由模型判断，不能证明一定选择正确 Skill。[索引构建与内容](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/prompt_builder.py#L1584-L1607) [模型选择指令和 `<available_skills>`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/prompt_builder.py#L1836-L1864) 系统提示只有名称/描述，不会常驻七份全文。
2. **`skills_list` → `skill_view`。**`skills_list` 返回最小的名称、描述和分类；`skill_view(name)` 返回该 Skill 的完整 `SKILL.md`，并列出可进一步请求的 references/templates/scripts；`skill_view(name, file_path)` 才读取一个具体支持文件。[最小列表](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L786-L849) [全文、linked files 与按文件读取](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L1293-L1406) [返回全文与 linked-files 目录](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L1408-L1477)
3. **显式 `/skill-name`。**slash 路径内部调用 `skill_view`，然后把完整 Skill 正文连同主人指令组装成一条模型可见消息；它能确定“这份文档被加载”，不能证明 Plugin 业务 handler、权威写入或最终回复已经成功。[slash 的全文装载](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/skill_commands.py#L192-L229) [正文和支持文件提示被组装进消息](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/skill_commands.py#L271-L371)
4. **Plugin Skill。**目标版本 `register_skill` 生成 `plugin:skill` 限定名，并明确不进入平面 Skill 树或系统提示索引，只能显式加载；因此它不能单独满足“主人自然说健康问题，Hermes 自动发现七个职责”的目标。[Plugin Skill 注册合同](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1217-L1260) 此路径在目标版本只返回注册的单一 `SKILL.md` 且 `linked_files` 为 `null`，不能未经验证就套用普通 Skill 的 `references/` 渐进加载能力。[Plugin Skill 返回](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L855-L959)
5. **`auto_skill`。**对固定 commit 全树进行精确源码检索，没有名为 `auto_skill` 的符号或配置项；目标官方 Skills 格式也未列出该字段。因此本目标上不能把 `auto_skill` 写成已存在的稳定调用机制。当前 `main`、后续 issue 或更新版本中出现的同名概念若要采用，必须重新做版本差异 CAN，不能归因给 Partner v0.20.0。

### 四、上下文稳定性和 token 成本

Hermes 的渐进披露方向适合七个职责，但前提是**主文档短而自足、共享长内容不重复、动态状态另行按本轮目的投影**：

- 系统提示持续承担的是 Skill 名称和短描述索引；七份 `SKILL.md` 正文只在实际加载后进入模型输入。[官方渐进披露说明](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L130-L140)
- 第一次 `skill_view` 或显式 slash 会放入完整正文。若四个职责各复制相同画像结构、安全规则、任务结构和披露模板，那么一次依赖链加载多个 Skill 时，相同文字会随加载份数重复进入输入。成本随实际加载正文长度和数量增加；本报告不虚构具体 token 数，因为目标 provider/tokenizer 的保守计数合同尚未建立。[目标容量与 token 计量缺口](16-health-model-context-capacity-token-accounting-overflow-20260818.md)
- 目标版本会在同一 task 中对未变化的重复 `skill_view` 返回短 stub，但不同 Skill 的首次全文、显式 slash 正文和压缩后重载仍存在；这个去重不能消除七份文档之间复制的共享规则。[重复 view 去重及压缩后重载](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/skills_tool.py#L1803-L1927)
- 因而应把**每项职责每次都必须看到**的短约束留在主文档；把共享数据结构、长安全说明、完整示例和边缘场景保存在单一权威来源，由需要它的回合按需取得。若 HOW 选择普通 profile Skill，可利用 `references/`；若选择 Plugin Skill，必须另证共享 loader，因为目标 Plugin Skill 没有普通 linked-files 合同。
- 主人画像、证据卡、任务状态、设置值和本轮消息不是程序性知识。把它们写进 `SKILL.md` 会造成版本陈旧、跨会话泄漏、难以行使纠正/删除权，并让 Skill 全文每次重复携带个人数据。`SKILL.md` 只能声明“需要哪类最小投影、版本/新鲜度要求、缺失时如何停止”，不能保存动态值。

`pre_llm_call` 在目标版本能把 Plugin 返回的文本追加到当前 user message，而不是系统提示；回调异常会被记录后继续，注入正文还可能进入普通会话的 API-bound 内容。因此它证明 Hermes 有逐轮上下文承载面，但不能单独证明健康上下文隔离、正确版本、最小化或失败关闭，也不能在本 TO 中直接选为最终路线。[目标 Hook 表与失败语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L188-L204) [目标逐轮注入调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/turn_context.py#L1051-L1103) 当前官方 `main` 仍将其描述为追加到 user message，并明确不是 system prompt；这只是上游方向旁证，不替代目标源码：[当前 Hook 文档](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md#pre_llm_call)。

### 五、当前 Partner 现场边界

2026-08-20 的一手只读现场表明：Partner 仍是固定 commit 加五个 dirty 路径；普通 Plugin enabled 清单为空，profile `plugins/` 没有 manifest，健康 Plugin 未部署；profile 虽有 80 个 `SKILL.md`，管理视图只列出 7 个 local enabled 项，默认 root home 中存在的旧 `health-steward` 也不在 Partner profile 的 Skill 路径。因此目前没有现场证据证明七个健康 Skill 已安装、已被当前 Partner 发现、能自动选择或获得任何健康上下文。[当前 Partner 基线、Plugin 与 Skill 现场证据](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#answer)

### 六、给 Ticket 100 的最小充分结论

1. 可以确认统一十二栏作为七个 Skill 的**产品完整性审查表**。
2. 不应确认“十二栏必须逐项原样展开成七份运行文档”。运行 `SKILL.md` 应贴合 Hermes 原生结构，并把路由信号放进短 `description` 与 `When to Use`。
3. 每份主文档必须保留自己的触发/不触发、上下文类别与缺失行为、步骤、候选结果、交回、禁止写入、停止和验证；这些是职责稳定性的最低自足信息。
4. 共享规则、结构细节和长示例只保存一次并按需加载；动态主人状态永远不写入 Skill。具体共享 loader 与动态上下文注入路径属于 HOW，并必须基于本报告的普通 Skill/Plugin Skill差异选择。
5. 文档结构可以提高模型选择和执行准确性，但不能单独保证稳定调用。稳定调用还需要后续 HOW 对总入口、实际 Skill 加载、上下文版本、失败关闭和主人可见实际使用建立运行时证明。
6. 目标 v0.20.0 没有可据以确认的 `auto_skill` 机制，当前 Partner 也没有部署七个健康 Skill；实现前不得把设计文档描述成当前能力。

自检：本报告只有一个 `## Answer`；使用固定官方提交、官方当前页面和既有一手现场 Evidence；没有读取凭据或健康正文，没有修改 Ticket、Map、CONTEXT 或实现；没有选择最终 HOW，也没有给出未经目标 tokenizer 证明的 token 数。
