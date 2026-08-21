# partner 健康管家自治版 v0.2

状态：**本地可运行验收版；生产部署 No-Go。** 本目录没有改动服务器、partner 真实 profile、default Hermes、x-ui 或 xray，也没有创建真实 cron 或健康数据。

## 1. 本版解决什么

本人一次性明确授权边界后，健康管家可在边界内自主完成四件事：

1. 判断一条已验证私聊是否包含可结构化的本人健康事实。
2. 判断本人是否明确表达了补水、作息收尾或久坐活动需要，并自主建立可逆任务。
3. 按证据、有效期、修订链和本人纠错逐步完善画像。
4. 从明确反馈中学习交互方式和提醒时间；不从沉默、回复速度或未回复中猜测。

“自主”不是让模型自由写数据库或自由建 cron。自主权由本人先授权，之后由确定性策略执行；模型只看到当前回合所需的最少字段和已执行动作回执。

## 2. 运行结构

| 组件 | 职责 | 不允许做的事 |
|---|---|---|
| `health-guard` | 急症、改药、诊断、群聊隐私和工具边界 | 不维护自治画像或自由改健康规则 |
| `health-autonomy` Gateway hook | 只接收经过 Hermes 实际授权检查的 partner Telegram 私聊，并绑定平台、本人、chat 与 message ID | 不信任群聊、内部事件、跨 sender 回放 |
| `HealthAutonomyStore` | SQLite 事务内执行授权、画像、偏好、任务、反馈、防重放、保留期和删除 | 不存原始聊天文本，不接受模型 SQL |
| 固定 dispatcher | 每 5 分钟运行一次 `no_agent` 脚本，核对 scheduler 注入的可信当前 job ID、本次执行/投递快照指纹、数据库受管 ID、持久化完整指纹和本人路由后合并到期任务 | 不调用模型，不生成自由文案，不跨渠道投递 |
| LLM | 解释确定性回执，完成非诊断性对话 | 不直接写私有库、不创建/修改健康 cron、不声称未执行动作 |

数据库目标路径为 `/root/.hermes/profiles/partner/private/health-autonomy-v02.sqlite3`。生产 Linux 必须验证目录为本人所有且 `0700`、数据库为本人所有且 `0600`，并拒绝符号链接；失败即拒绝启动。

## 3. 本人授权格式

只有女朋友本人在已验证的 partner Telegram 私聊中发送下面完整语句才生效：

Gateway 改写后的内部 slash 命令不是授权证据。执行前会以常量时间比较核对“本人当前可见消息”的哈希与解码后的完整授权文本；状态、暂停、恢复、关闭、删除也必须分别来自下文可见中文原句（可带一个句号）。直接发送内部 `/health-autonomy-safe ...` 或篡改改写载荷一律拒绝。

```text
确认开启健康管家自治模式：画像=开；交互学习=开；模型最小使用=开；自治类别=补水提示,作息收尾,久坐活动；补水提示时间=10:30,15:30；作息收尾时间=22:30；久坐活动时间=11:00,16:00；每日主动消息上限=3；最短间隔分钟=240；静默时段=23:00-08:00；时区=Asia/Shanghai；任务最长天数=30；数据保留天数=180；同时任务上限=3；单次调时上限分钟=30
```

每个参数的物理含义：

| 参数 | 含义与硬范围 |
|---|---|
| 画像 | 是否允许保存白名单结构化健康事实；关闭时相关文本零持久化、旧画像不再注入模型 |
| 交互学习 | 是否允许保存并使用本人明确表达的交互偏好；关闭时零持久化且旧偏好不再生效 |
| 模型最小使用 | 是否允许把当前动作、偏好和当前话题最多 4 个相关字段交给模型；v0.2 必须为开，确保动作有可见回执 |
| 自治类别 | 只允许补水提示、作息收尾、久坐活动；不包含服药、诊疗或联系人通知 |
| 各类别时间 | `Asia/Shanghai` 本地墙钟时间，每类最多两个，不能落在静默时段 |
| 每日主动消息上限 | 任意滚动 24 小时最多 1–5 条，不是自然日计数 |
| 最短间隔分钟 | 两条主动消息之间至少 60–720 分钟 |
| 静默时段 | 跨午夜或同日的禁止投递区间；到期任务推迟到静默结束，不补发洪峰 |
| 任务最长天数 | 单任务 1–30 天，且不能大于数据保留天数 |
| 数据保留天数 | 画像、观察、反馈、决策、任务和投递元数据 7–180 天；重授权缩短时追溯收紧 |
| 同时任务上限 | 同时活跃 1–3 个；重授权降低时超出的任务自动暂停 |
| 单次调时上限分钟 | 一次稳定调时最多 10–60 分钟 |

重授权可以收紧类别、时间、任务寿命、保留期和活跃任务数；旧授权会撤销。旧 Telegram 授权或控制消息即使重放，也不能重新开启、再次暂停或再次删除新状态。

## 4. 自治判断规则

### 画像

- 睡眠：只接受少量完整的本人肯定陈述，1 天有效。
- 过敏：只接受完整的本人肯定陈述；多过敏原拆成独立条目，否定、问句、引用、测试、假设、翻译和第三人称均不写入，最长 180 天。
- 医生意见：只记为“本人转述医生意见”，不记为系统诊断。
- 血压、血糖、心率、体温：必须同时有类型、数值、单位和当前/今日时间，并通过结构性物理范围检查；这不等于医学正常判断，7 天有效。
- 本人回复原始 Telegram 消息并说“不是我，是我妈”时，才沿精确 message lineage 失效该健康证据并暂停依赖任务；无 reply 锚点不修改。

### 任务

- 只接受少量完整的本人意图句，例如“我总忘记喝水”或“请提醒我喝水”。项目、测试、引用、翻译、否定和第三人称不建任务。
- 最多每 7 天新增 1 个自治类别；同类任务不重复创建；任务有 review/expiry/max-runs。
- “今天别提醒”“晚点提醒”“太频繁”“不要提醒我喝水”均可由本人直接改变已绑定任务；多任务且未指明类别时不猜。
- 调时必须同方向至少 3 次、跨至少 2 个本地日期、距离上次调整至少 7 天；出现相反反馈时不自动调。

### 交互方式

- “回复短点/详细点、温柔一点/直接一点、一次只问一个”立即成为显式偏好。
- 短版补水提示仍保留“如有医生限水要求，请按医嘱”，安全限定语不能被风格偏好裁掉。
- 不把沉默、未回复、回复快慢或模型印象当成偏好证据。

## 5. 控制与删除

本人私聊控制语句：

```text
健康管家状态
暂停健康管家自治模式
恢复健康管家自治模式
关闭健康管家自治模式
删除我的健康管家数据
```

暂停/关闭后，固定 dispatcher 仍运行但只做无投递的到期清理；数据库状态门保证不输出。删除会 `secure_delete`、清表并 `VACUUM`，再删除 dispatcher。只保留：

- 与本人路由和 message ID 绑定、由随机密钥生成的不透明 HMAC 防重放值；不含动作、时间、身份或健康内容。
- 删除时间和各表删除条数审计；不含身份和健康内容。

## 6. 已验证与未解决边界

本地单元/集成测试覆盖：未授权零写入、群聊/主体隔离、schema 损坏与权限失败关闭、原消息重放、删除原始字节残留、画像正反例、精确纠错、scope 关闭、任务限流、静默/滚动 24 小时、反馈学习、并发单次派发、多任务合并、cron 完整指纹和最小上下文。

本地 Hermes 源码镜像 `.research/hermes-agent/cron/scheduler.py` 已加入必要的 core 适配：父 scheduler 先清除继承值，再以不可由 job 字段覆盖的 `HERMES_CRON_JOB_ID` 注入实际调用者 ID，并用 `HERMES_CRON_JOB_FINGERPRINT` 绑定随后控制最终投递的同一内存 job 快照。dispatcher 会把该快照指纹与重新读取的唯一合法持久化 job 比较；缺值、ID 不同、快照与持久化记录不同、第二个脚本/prompt 引用、route HMAC 或任一完整指纹不匹配时均零输出并隔离。这样避免“校验恢复后的合法记录，却按 tick 旧恶意快照投递”的 TOCTOU。真实服务器仍未应用和验收该 patch，因此生产不能运行此 dispatcher。

生产仍为 **No-Go**，原因不是功能缺失，而是权限边界尚未达到承诺：partner Agent 与插件目前运行在同一个 Unix 用户下。模型可借助动态拼接、glob 或代码执行绕开字符串级 `pre_tool_call`，直接访问必须对该用户可写的私有数据库；同样，Hermes CLI/API/Dashboard 的其它 cron 写入口还没有在 core 层统一关闭。

推荐的生产修复路线是把健康存储与调度策略移到独立 Unix 用户的 sidecar，只向 partner Gateway 暴露窄、带主体绑定和幂等键的 IPC；不推荐靠继续增加字符串黑名单。完成 sidecar、锁定真实 Hermes commit、验证 busy/idle/重启/cron 路由后，才能转为 Go。

最终本地回归为 **161/161 通过**。其中包括真实穿过 Hermes `run_job(no_agent)` 与 `run_one_job/_deliver_result` 的核心验收：父进程已有伪造 job ID 时仍由实际调用者覆盖；数据库损坏或 dispatcher 内部异常时返回 `[SILENT]`；持久化 job 合法但实际运行快照被改投攻击者时，Telegram 投递为 0 且数据库 dispatch 记录为 0，完全一致的快照才向本人投递一次。隔离与内部故障只向 Unix syslog 写入不含路径、异常正文和健康内容的元数据事件；数据库锁定、权限拒绝和 journald 可见性仍须在 Linux staging 复验。

## 7. 本地验收命令

```powershell
python -m py_compile ops\partner-health-steward\plugin\health-autonomy\autonomy.py ops\partner-health-steward\plugin\health-autonomy\__init__.py ops\partner-health-steward\scripts\health_autonomy_dispatch.py
python -m unittest discover -s ops\partner-health-steward\tests -v
```

## 8. 本地隔离试用

试用器只使用系统临时目录中的虚拟主体、虚拟私聊和模拟时钟，不联网、不建立真实 cron，也不读取或修改 partner/default profile。请只输入虚构测试数据：

```powershell
python ops\partner-health-steward\scripts\health_autonomy_trial.py start
python ops\partner-health-steward\scripts\health_autonomy_trial.py say --text "我总忘记喝水"
python ops\partner-health-steward\scripts\health_autonomy_trial.py advance 90
python ops\partner-health-steward\scripts\health_autonomy_trial.py status
python ops\partner-health-steward\scripts\health_autonomy_trial.py destroy
```

`advance` 推进模拟的上海时间并运行一次确定性 dispatcher；`destroy` 只删除经过路径校验的系统临时试用目录。试用成功只验证产品交互和状态机，不改变生产 No-Go。
