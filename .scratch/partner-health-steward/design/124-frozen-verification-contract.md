# Ticket 124 验证合同候选

状态：pre-code candidate，尚未冻结。Verification authority：独立 implementation_audit Agent。产品基线：整合提交 `19417da`；本文件不改变 Ticket、Spec 或 ADR 的产品语义。候选可在编码前双轴预审前修订；冻结后产品实施者不得修改本文件及 verifier-owned 测试。

## Characterization 与边界

现有 Ticket 123 已有受 release/runtime 约束的生产 Core、AF_UNIX 及三类 CorePort。当前 `hermes_host` 的 connect 只执行 118 握手 tracer，没有逐条 poll、回复、cursor 或恢复生命周期；生产组合根未装配 admission/init/daily Skill runtime。Ticket 111/112 的初始化与日常原子行为已经工作，是继承的绿色基线。

只在既有 `command | managed-read | controlled-effect` 内增加固定健康入口操作。最高验证接口为 `LiveHealthCoreOperations.dispatch`、`ProductionCoreService` 的既有 start/endpoint/close 与 `live_runtime` 装配，以及真实 pinned Hermes lifecycle 中的 `LiveHealthWeixinAdapter`。测试可以注入 transport、current-head 和时钟；不注入业务成功、跳过 Core、修改生产 helper 或增加测试专用放行。

实际采用的模块、构造与 exact wire 以同一 checkpoint 的 124 实施设计为准。已协商的公开接口：

- `LiveHealthCoreOperations(plugin, *, current_generation: Callable[[], int], wake_current=None)`；公开 `dispatch(kind, payload)`，内部可有固定 `handle_command/managed_read`。
- `ProductionCoreService(binding, *, current_head, live_runtime=None)`；`None` 保持 123 staged 行为，typed runtime 必须与已验证 release 资产相符。
- `LiveHealthWeixinAdapter(config, *, core_port=None, ingress_transport=None, delivery_transport=None)`；公开 `connect(is_reconnect=False)`、`poll_once()`、`wake_current()`、`disconnect()` 及 pinned `send` 方法。
- CorePort command 固定 `{interface: health-entry-v1, operation, payload: 操作字典}`；managed-read 固定 `{interface: health-entry-v1, projection, payload: 投影字典}`。preflight 的 payload 只有 headers，返回 `allowed/current_generation/initialization_phase/reason_code`；初始化/业务状态 payload 为空。cursor directive 由固定 `health-entry-cursor-directive` 投影读取，ack 真实发生后才 `native-cursor-result`。不接受候选讨论中的扁平 shape。未知字段及任意 method/path 不形成业务调用。

## 四个有限验收门

| Gate | 可观察结果与现实 mutation | 最高验证接口 |
|---|---|---|
| 124-V01 | 未初始化时只允许显式 health-init；披露、主人实际准入的同意来源、prepare/commit/finalize 及当前状态读回形成一次初始化。没有实际消息同意时 caller 的布尔值不启动；初始化后合法健康来源产生现有 Core 结果。杀死“Adapter 假装完成初始化／绕过真实同意／第二业务真相”。 | 真实 HealthCore + HealthPlugin，经公开 LiveHealthCoreOperations |
| 124-V02 | live runtime 在同一生产 Core/Plugin 装配；固定入口请求实际越过 AF_UNIX 字节流；缺失/错绑资产在接受业务前拒绝，未知操作不可成为任意 RPC；不破坏 123 staged、ACL、peer、release 闭包。杀死“直调测试对象冒充生产装配／caller 任意方法访问”。 | ProductionCoreService.start/endpoint/close + 三类 CorePort |
| 124-V03 | pinned registry 唯一注册 health_weixin，实际注册的 factory 在显式 admission_policy 配置下创建 Live Adapter，满足 pinned lifecycle；header preflight 在 item_list/text 访问前拒绝准入外来源；同文不同消息不合批、不按正文静默去重；健康内容不进入普通 handler/Memory。杀死“只注册旧探针再直接测独立 Live 类／复用 native dedup/batch/memory 前置路径”。 | pinned plugin registration/factory + LiveHealthWeixinAdapter 接收生命周期 |
| 124-V04 | cursor 只在 Core 确认的 directive 下 acknowledge 并回交，未知时不越过该 cursor、不重复外发；相同来源重放和重新连接仍维持同一业务身份；wake 只唤醒当前 Core、disconnect/co-stop 后不处理下一条。杀死“先推进游标／恢复补做业务／失去 Core 后继续”。 | Adapter + verifier-owned RPC/ingress/delivery transport，真实 Core tracer |

每门只使用能杀死独立现实错误的正向 tracer 与必要负向等价类。不按字段或故障点做笛卡尔积；不以测试方法数量代替充分性。

## 执行与诚实边界

候选 verifier：`tests/test_ticket124_live_entry.py`。命令：

```text
PYTHONDONTWRITEBYTECODE=1 TICKET118_PINNED_HERMES_SOURCE=/path/to/verified-pinned-source TICKET123_RUNTIME_ROOT=/path/to/current-runtime /path/to/current-runtime/bin/python3 -m unittest tests.test_ticket124_live_entry -v
```

V02 包装既有 123 fixture，在临时目录中发布自洽的实质合成 Skill 资产与 current successor，并通过真实 AF_UNIX 交换；不修改 123 冻结文件、运行库或产品方法。V03/V04 child 在临时 Hermes home 中导入真实 pinned Base/registry，用离线 transport 排队驱动实际 connect 接收。123 完整生产服务门仍需其已冻结 Python 3.11 runtime 与 Linux 环境，缺少环境不能被 skip 包装成完成。产品缺失的编码前形状为 4 个明确 prerequisite failure，0 error/skip。

测试不访问真实 AWS、模型、微信、主人或联系人，不读取健康资料、普通历史、凭据或目标配置。所有通道与正文均为 verifier 合成输入。pinned 原生 iLink 无法证明 delivered/read 时，测试不要求或伪造该事实；真实投递留给 126，真实目标绑定与主人验收留给 128。

编码前预审必须针对同一 commit/tree，记录已继承绿灯、预期红灯、设计/合同/verifier blob。冻结候选未通过双轴前不授权产品编码。
