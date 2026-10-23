# Ticket 130：精确执行绿色与初始化前普通分流缺口

本记录保存两类同时成立的事实：`eff03ae` 的 R2.6 执行门全绿；补充公开链对照发现原门未覆盖的兼容回归。因此不启动实施后双轴、不闭票、不部署。

## 精确 R2.6 执行

- 产品 commit `eff03aed380f936904c3482206c1ece836b9b19f`，tree `299f2c7deb1ce9a7d657ec47f5c6aa7128456c9b`；工作树干净且已普通推送。
- clean clone `/tmp/health-steward-130-eff03ae-clean`；实际隔离根 `/opt/hsv-7i66_gv9/formal-eff03ae-130-r26`、独立 verifier `/opt/t123v-bdbc3929`。实际 root／Python 3.11.15，源码 archive SHA-256 `35000cfda2f5d9cbe1f5037e51612e2c07619b92b75320b8cd85df498be030e4`。
- 原组件 20/20：130 七门 233.781s、126 五门 36.603s、131 四门 1.126s、124 四门 4.443s；原全量 **801/801，491.425s**；root 原独立 **30/30，279.373s**。全部 0 failure/error/skip。
- 实际 compileall 91、tracked Python 来源 91、冻结文件 18 均通过且 bytes 未变；runtime 7467 files、closure `sha256:f0baf4f0f70099853369a24ce51841d21ca0a898b0ac871be67540764e9e76b1` 未变。原 R2.6 checkpoint `fb97e5e656b4ebe29d7b1dfce25c24d6ce58ed46` 的设计／合同／测试身份保持。
- 原始本地日志统一前缀 `/tmp/dmit-connection-audit/formal-eff03ae-130-r26-`，分别为 `components.log`、`full.log`、`root30.log`、`postcheck.log`；同隔离根 logs 保存完整实际执行。

这些结果证明大记录／导出及原资源泄漏场景在此版本通过，不能倒改 Evidence 64／65 的旧失败，也不能证明未覆盖的实际路径正确。

## 新兼容回归的公开对照

root 源码核查后，独立 verification authority 用 `/tmp/ticket130-preinit-ordinary-routing-characterization.py` 与同名 `.log` 实际复现：同一个真实未初始化 Ticket124 Core／Plugin、同 owner／同普通合成消息，通过 `LiveHealthCoreOperations` 调用：

- `receive-weixin` 返回 `accepted / ordinary-hermes-route`；
- `governed-receive` 返回 `rejected / initialization-required`，`next_stage=None`、空 refs。

两条路径均保持 uninitialized、无 SourceReceipt、原 Store daily digest 不变；明确健康控制仍由旧 receive 路径正确拒绝。这里不是要放宽健康初始化或模型批准。

实际因果：130 的 `LiveHealthWeixinAdapter._process` 仅按 model bridge 存在选择 governed 分支，初始化前也会调用 `HealthPlugin.receive_governed_weixin` 的历史 `_receive_weixin` 门；从而绕过旧 124 `live_entry_receive_weixin` 特意保留的初始化前 coarse ordinary 分流。默认部署将装配 model bridge，所以普通消息不能抵达原 handler。旧 124 正向没有 model binding；130 V01 直接开始 health-init，故当前 801 绿色不能杀死该错误。

## 处置与范围

按 architecture-governance 的“未覆盖但可复现且直接违反既有验收”处置，verification authority 仅在原 V01 家族补真实已装配模型桥时的初始化前普通分流一次，以及明确健康消息仍拒绝／模型与健康发送及事实为零；随后原初始化与全部后继观察保持。仅 130 contract／verifier 两份文件由独立权威窄幅重新冻结，设计不变、七家族不变；fresh 同 checkpoint 双轴预审后，才授权产品最小兼容修复。不得把它藏入 128，也不得因旧门绿色直接进入 post-review。

128 仍只保存下游产品输入。default `/root/.hermes`、root 用户级 `hermes-gateway.service`、真实模型／微信与主人初始化均未操作；partner 保持不触碰。
