# Ticket 125 冻结验证合同候选

状态：pre-code candidate，尚未冻结。独立 verification authority：implementation_audit Agent。基线 `19417da`；唯一实施设计为同目录 `125-production-model-design.md`。本合同只验证既有 Ticket 125 增量，不创建新的产品状态、批准或知识权威。

## 已执行 characterization

在不含真实配置/资料的 `/tmp` 独立副本执行 `python3 -m unittest tests.test_ticket119_integration tests.test_ticket113_strict_port -v`：39 PASS，0 skip/error。现有 nonsynthetic profile 无条件 `capacity-unavailable`，39 个绿灯不证明生产模型可调用。真实 target 的配置容量、模型名称和调用样本均不得作为共同窗口下界。

## 验证接口

`model_adapter.ProductionModelAdapter`、`ProfileBoundInputMeasurementStrategy` 和 `load_governed_knowledge_artifact` 使用唯一实施设计中的公开签名。一个正向 tracer 必须通过真实 `HealthPlugin.execute_strict_health_model` 与 Core exact effect grant；生产计量经过 `StrictHealthLLM.canonical_copy/preflight`，不能只测 Adapter 的自我检查。底层 `transport.send(body)` 是唯一离线替身；它提供绑定 route，但不拥有准入、效果、知识或诊断权威。

## 四个有限门

| Gate | 验证结果 | 杀死的现实 mutation |
|---|---|---|
| 125-V01 | nonsynthetic fixture profile 的离线批准依据精确 hash-bound；最终 Responses body 的 schema、model、store、stream、输出预留与输入内容均与请求一致；计量覆盖完整 canonical wire；真实 Core grant 恰好允许一次调用且 canonical_copy 不丢策略。 | 把真实 profile 标 synthetic；只量 messages 漏 schema；普通 helper 删除 schema；未授权或重复模型调用；copy 丢失受信计量 |
| 125-V02 | 无计量依据的生产 profile、过期证据、route/config 漂移、声明低于完整 wire 与容量不足在调用前失败关闭且零 send；没有真实窗口依据的目标配置保持不可用。 | 240000 配置或任意 approved 布尔值被当下界；忽略过期、route 或最终 wire；Adapter 静默提高已授权请求上界 |
| 125-V03 | completed/incomplete/failed 从 raw 实际 metadata 分层形成；缺 model/usage/terminal、timeout、SSE 只有 delta/EOF 时 unknown；实际模型漂移/fallback/工具不能产生候选；每次效果最多一次 send，Core unknown 后同 grant 不重复执行。 | requested 回填 actual；delta 冒充终态；API 无错冒充 completed；缺失 usage 写成测得0；自动修复/重试/fallback |
| 125-V04 | 固定 owner-independent publication 重算成精确 release，精确 digest 装配；篡改、额外 owner/context 字段拒绝，过期或治理不足返回既有 KnowledgeGap；staged 不自动激活。 | 相信 caller release/hash；给治理缺口补 approved；把主人信息掺入离线更新入口；知识装配变成诊断激活 |

Verifier fixture 的容量依据、批准引用、模型和内容明确属于离线合成事实；绿色结果不是 G10 或 G11 的目标证据。不测试字段笛卡尔积，每个等价类必须杀死上表一个独立实际错误。既有 Ticket 113 strict/authority/knowledge 门原样回归。

## 命令和冻结条件

候选测试：`tests/test_ticket125_partner_model.py`。

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket125_partner_model -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket113_strict_port tests.test_ticket113_authority_integration tests.test_ticket113_knowledge -v
```

生产实现不存在时四门必须明确红灯，不能 skip 成功。编码前由独立 Spec/Standards 对同一 commit/tree 预审，记录设计、合同与 verifier blob 后才冻结。冻结后实施者不得改本合同或测试；需要修订时交回 verification authority 并形成新的 checkpoint。

真实模型调用、秘密、目标 profile、健康数据和 transcript 不进入测试、Git、聊天或日志。真实共同容量、上界依据和 target/release/config-bound 批准仍是 G10/G11 外部前提；缺失时产品必须保持不可用，而不是改测试使其通过。
