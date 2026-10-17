# Ticket 131 独立冻结验证合同候选

状态：pre-code candidate，尚未冻结。Verification authority：implementation_audit；唯一设计为 [131-nondiagnostic-operational-budget-design.md](131-nondiagnostic-operational-budget-design.md)。131承接ADR0024的明确主人选择，不把本地预算或离线fixture写成服务端容量证明、真实JOJO调用、G10/G11通过、部署或主人验收。

## 已观察基线与最高接口

闭票基线`58453bf`保留125严格profile／计量、113 strict request／typed候选与Core授权、116真实诊断源门。131新增模式固定为`non-diagnostic-operational-budget`、purpose=`non-diagnostic-health`，当前仅承接唯一设计中的固定NonDiagnosticCandidate回答schema。未来130的固定阶段／schema关系不在本票预建。

最高验证接口为既有`StrictModelRequest` codecs、`StrictHealthLLM`、`ProductionModelAdapter.execute`、`HealthPlugin.execute_strict_health_model`及原`effect.request/result`、Core已提交model report／daily结果，以及真实`HealthPlugin.health_operation("diagnosis.prepare",...)`。只使用设计声明的两个新concrete value／strategy和公开schema getter；不冻结私有helper、SQL、内部字段布局，不注入业务成功。

预算wire独立且无共同容量或tokenizer证明字段；ND request沿同一class使用明确新shape，不把byte计量写进旧token字段。最终canonical UTF-8 JSON wire固定65536bytes，输出预留固定2048tokens。预算／LLM公开无I/O说明与ND报告留存精确同一八字段，固定`context_guarantee=not-provided`及“不提供共同上下文保证”；completed不能移除。旧strict request/report wire与digest不改变。

## 四个有限验收门

| Gate | 最高公开链与可观察结果 | 杀死的现实错误 |
|---|---|---|
| 131-V01 | ND预算／request规范往返与canonical copy；无grant零调用；真实Core准入、evidence阶段、exact intent／grant经过生产Adapter只有一次attempt；实际最终wire与公开byte计量相等，typed候选经原pipeline、effect终态、日常prepare/commit/finalize；Core report读回保留固定说明，移除声明的自洽伪report拒绝，重复完成不推进head或模型调用。 | 把预算伪装严格容量、只在内存展示说明、绕grant、caller替换观察报告、直接模型文本写业务、第二次效果／提交 |
| 131-V02 | 依据公开固定schema独立序列化：精确65536bytes可用，加一byte及UTF-8／转义膨胀超限拒绝；固定预算／保证字段不可升额；ND/strict codec混搭、低报wire bytes、无策略／错误策略、owner-decision与route代际漂移、到期在send前停止。 | 只计消息或字符、不算wrapper/schema、截断凑预算、240000混入token字段、错绑定或失效仍调用 |
| 131-V03 | raw incomplete/failed保实际终态与response/model/usage绑定；缺actual/usage、非ND结构、超时均无候选且只有一次send；在途到期保completed/incomplete/failed，completed以operation-budget-expired拒候选，真实Core终态仍能记录；unknown经同一Core冻结、再执行零新增调用／无cursor。 | completed被误作完整上下文证明、补造actual model、丢真实attempt、旧expiry假not-started/unknown、未知后自动重试 |
| 131-V04 | 真实116公开链先以旧strict能力完成合成验收激活并证明诊断model-ready／执行正向成立；同一Core权威栈换ND预算后，安全／知识／证据／route及active scope仍有效，真实diagnosis.prepare明确rejected且无新intent／request／effect或调用。 | 只靠schema名字或UI隐藏诊断、被staged／缺资产遮住的假负例、ND预算借full/BMI源操作取得权限 |

门按独立现实mutation取必要等价类，不做字段笛卡尔积，不把方法数量当充分性。原诊断scope仍由116合成验收获得，绝不直接设置active或生产放行。typed候选与确定性回复链保留，预算不是任意schema注册器。现有strict模式的诊断／grant和报告完整性继续由未修改的冻结回归约束。

## 执行、诚实边界与返修

verifier-owned文件为`tests/test_ticket131_nondiagnostic_budget.py`。命令：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket131_nondiagnostic_budget -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket125_partner_model tests.test_ticket113_strict_port tests.test_ticket116_integration -v
```

本票全部离线；transport只是边界fake，Core、Plugin、effect、证据阶段、typed日常提交与诊断源门是真实实现。request／raw body均为合成非医疗fixture；不读运行配置、凭据、健康资料、partner或真实联系人，不联网模型。公共说明和已提交report的绿灯仅证明“可公开／记录”，不声称真实主人已看到；130／128仍须在实际展示中保留这项限制。

发送前已失效要零网络调用；Core写durable attempt marker后Adapter才发现expiry的竞争，沿唯一设计保守unknown，不能伪造Core能证明从未尝试。候选内容不夹带声明metadata；声明沿原report.digest、effect ref、request与model authority digest绑定，不新增ledger。

独立已继承绿灯：125四门、113 strict port及116合计48/48通过，42.315s，0skip，日志`/tmp/ticket131-inherited-green.log`。编码前新四门均为明确NonDiagnosticOperationalBudget prerequisite failure，0error/skip，日志`/tmp/ticket131-precode-red.log`。compile及diff-check通过不代表内部新链已执行；产品实现后须运行这四门及设计指定的原冻结回归，正式runtime／全量由根统一验证。

旧125三件套、113和116冻结文件不修改。编码前须将同一设计、合同、verifier blobs绑定同一commit/tree接受fresh Spec／Standards预审；通过后才冻结与产品编码。具体可复现缺口交回本verification authority修订候选并建立新checkpoint，产品作者不能修改门或静默扩大范围。
