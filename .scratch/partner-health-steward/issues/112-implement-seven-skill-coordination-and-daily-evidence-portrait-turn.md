# 112 - 实现七 Skill 协调与日常证据画像处理

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [111 - 实现唯一准入与主人初始化](111-implement-unique-admission-and-owner-initialization.md)

**What to build:** 初始化成功后，让健康、混合或无法确定的消息经过一次粗分流进入 `health-steward`，由它按目的取得最小上下文并协调七个 Skill。一次普通健康 turn 应能产生受管证据候选、画像修订或明确缺口，经过 core 的唯一权威提交后返回一份主人回复和真实 Skill 使用披露。

**Blocked by:** 111 - 实现唯一准入与主人初始化

- [ ] `health-steward` 是唯一健康协调者；`health-settings` 处理主人控制意图；四个 B 类 Skill 只返回目的限定候选、缺口或无合格资料。
- [ ] 每个 Skill 只取得当前目的所需的最小只读上下文；缺项时停止并返回缺口，不补猜、不截断后继续、不扩大读取。
- [ ] Plugin/core 证明必需 Skill 的实际动作、版本和因果关系后才记录最小使用事实并追加系统披露；未使用 Skill 不显示。
- [ ] `health-evidence` 的个人证据、通用知识和任务过程证据不可互换；每张权威卡只承载一个可独立判断主张，画像和任务只引用同一张卡。
- [ ] `health-portrait` 只能基于已提交证据形成六域当前视图；六域显示预算、三类证据、四类关系、近期明细、受保护例外和滚动摘要遵循 `CONTEXT.md` 与最新 TO。
- [ ] core 原子提交证据/画像业务事实和回复意图，Plugin 适配唯一主人回复；Skill、模型草稿和候选不得直接写库、发送或完成任务。

