# Ticket 130：资源修复与大记录正式失败

本记录只保存已发生的执行事实，不是实施后审查、部署或闭票结论。Ticket 130 保持 claimed；冻结 R2.6 与全部 18 份冻结文件未变。

## 精确候选与隔离执行

- 产品 commit `950f8b9d7703c5abc18d1fc43484dd5d56f46032`，tree `de531f7d23bec4e9e803ccdb011f4f892d76bdc2`，普通推送；其资源生命周期改动仅在 `host_authority.py` 与 `production_core_service.py`。
- clean source `/tmp/health-steward-130-950f8b9-clean`；隔离根 `/opt/hsv-7i66_gv9/formal-950f8b9-130-r26`，独立 verifier `/opt/t123v-732bc129`。
- 原实际 Python 3.11 runtime 共 7467 个文件，closure `sha256:724cf2b0a265945a4d1f15a197b864c3142487a90261ce0ef620853046e8cba4`；91 份 tracked Python 来源、18 份冻结 bytes、pinned Git 与四份原 dirty fingerprints 均通过准备校验。
- 冻结 checkpoint `fb97e5e656b4ebe29d7b1dfce25c24d6ce58ed46`；130 design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`、contract `5134e3a1f137bf24fe0acdcfc0aa50a43117214d`、test `19ba1c10dbf2de199c751c1f454569fced2091ed`。

## 资源 blocker 的复核

原 121／123 service／runtime 14 门在同一隔离版本通过：14 tests，0 failure/error/skip，30.676s，日志 `/tmp/dmit-connection-audit/formal-950f8b9-130-r26-authority-service.log`。

root 独立观察 `/tmp/ticket130-fd-950f8b9-independent-result.json` 与 `/tmp/ticket130-fd-950f8b9-observe-v2-remote.log` 使用原 nofile 1024、未强制 GC、未修改产品或 verifier：原 fixture 自然离域、两次真实 Service healthy close 与重复 close、五条已测失败启动路径均归还全部本调用拥有的 descriptor；caller 借入的 head/key、私有文件身份及 bytes、公共健康 digest 不变。真实在途 AF_UNIX request 被阻塞时，原两秒 drain timeout 保留全部在用 Core、authority pins、socket 与线程；原 request 完成并再 close 后回到基线。首次 observer 因未初始化时读取 Core daily_state 正确被拒绝，原脚本／日志保留；v2 改用原 Store public read 作额外 absence oracle，未改变冻结测试。

这只关闭 Evidence 64 中已复现的资源生命周期 blocker，不等于全部执行门绿色；任意 OS thread-start／close syscall 故障未注入，未宣称其覆盖。

## 原正式 130 门仍有失败

原样 components 执行中的 130 为 **7 tests，6 pass／1 failure，0 error/skip，238.405s**，日志 `/tmp/dmit-connection-audit/formal-950f8b9-130-r26-components.log`。失败是 V07 accepted 分支在 `seed-large-*` 的实际 native cursor bounded observation 未达到；export 尚未开始。V01—V06 通过，其余 V07 负例继续执行。后继 126／131／124 与 full801、root30、postcheck 没有作为该失败版本的完成门执行，不启动双轴 post-review。

额外只读计时观察保留原产品、原 verifier 与原两秒 RPC 时限。单独 V07 和一次原顺序七门的观察重跑分别通过，但四个大记录 advance 最大为 1.771s 与 1.866s；这些是观察结果，不能覆盖或改称原正式失败为绿色，也没有捕获原失败 turn 的精确 durable 状态。现有证据支持接近时限的脆弱性，尚不能把原失败归因写成已经证实的单一原因。

## 后续处置范围

仅在原冻结合同内评估局部拆短：对 Core 自行编码确认的大 record command，先完整完成原 complete-turn finalization、公开全部事实与持久 typed result，再把原 126 bind 留到下一短 advance。首调用不能停在 evidence-finalized：该状态只是 durable draft，公开 daily_state 仍是旧版；改门接受零事实或提前发布事实均不允许。Bridge／Adapter 只对严格同来源、已知最终成功投影做一次固定续接，未知或第二次未取得 handoff 则停止且不 ACK。原时限、唯一 CAS、authority/currentness、模型阶段数、冻结与旧小记录语义保持。

这项修复在本记录时仍待实现和精确新版本全套执行，不能以计时预测或观察重跑代替。default `/root/.hermes`、root 用户级 `hermes-gateway.service`、真实模型／微信、主人初始化与 partner 均未改动或调用。
