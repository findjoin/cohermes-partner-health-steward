# Ticket 130 R2.7：初始化前普通分流兼容冻结

Evidence 66 的实际公开对照证明 130 的模型桥配置使初始化前普通消息绕过旧 live wrapper；它是实现兼容错误，不是放宽健康同意门的理由。旧精确 eff03ae 的 20／801／root30 绿色保留历史含义，未启动 post-review 或闭票。

独立 verification authority 仅修改原 V01 家族：在真实 Publisher／registry／AF_UNIX Core、模型桥已装配的同一生命周期中，初始化前唯一明确 ordinary 问候必须经真实 async handler 一次；随后明确健康消息仍被拒绝，普通计数不增、模型与健康发送为零、仍未初始化、两个 source 均无 receipt／daily turn。然后继续原披露、独立原生确认、五个模型 stage、唯一提交及所有后继观察。其余六家族与原 helper 时间协议不变；不增加状态、ledger、wire、批准或超时。

当前唯一冻结 checkpoint 为 **`2a347c91f7645fd656db9569f10ad63f1bf2e5bd`**，tree **`ffe13de7219d153450af7c254ecc75125c2831c0`**：

- 设计 `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`，原样保留。
- 合同 `fcaa70d0182f31500fd695079f95859b99f1f7c0`。
- verifier `6e1522e4e7e944dca379b0f8f2e0f12391d9ec09`。

仅两份 verifier-owned 文件变化，仍七家族、其余 16 份冻结 bytes 未变。身份 `/tmp/ticket130-r27-checkpoint.json`，有限 diff `/tmp/ticket130-r27.diff`；clean clone `/tmp/health-steward-130-r27-2a347c9-clean`，已普通推送。

root 对此 checkpoint 用全新隔离根 `/opt/hsv-7i66_gv9/formal-2a347c9-130-r27-pre` 与独立 verifier `/opt/t123v-5a44c7c4` 原样选择 V01 执行：**1 test／1 failure／0 error／0 skip，10.749s**；精确失败于新增 ordinary handler 转发等待。运行后 91 来源、18 冻结、7467 runtime 文件不变，closure `sha256:98d01159da3a2e9e96ba57e41ee0db60fd4b14de7a63cb085e100ebf924be822`。日志 `/tmp/dmit-connection-audit/formal-2a347c9-130-r27-pre-v01.log`；选择 runner 只识别此预期红，未改产品／测试 bytes／时限或运行时断言。该失败证明门杀当前错误，不是实施绿色。

fresh-context 双轴对同一精确 commit/tree 完成预审：Spec `/root/pre130_r27_spec` PASS、Standards `/root/pre130_r27_standards` PASS，均无 P0—P2 blocker／新增建议。报告分别为 `/tmp/health-steward-reviews/130-pre-r27-spec.txt` 与 `130-pre-r27-standards.txt`；两者只读核对实际预期红、原兼容边界、冻结身份、改动局部性及无产品修改。

root 现只授权原 Adapter 的最小 phase-aware 分流兼容修复，保留已启用时的 governed 模型链、原初始化／健康拒绝、held/unknown 不 fallback 及大记录一次固定续接。产品作者不得改冻结文件。完成仍须精确新版本原组件／全量／root 复核／编译与完整性、fresh post 双轴和 root 闭票；default 部署、真实接口和主人验收仍归 128，当前未执行。
