# 02 - 建 sidecar 垂直骨架

**What to build:** 让 partner 适配层能够通过私有 Unix socket 与独立 health-sidecar 写入并读回一条加密状态，形成后续所有健康行为共享的上层验收入口。  
**Blocked by:** None - can start immediately

**Status:** resolved

- [x] sidecar 作为独立进程启动，并且只通过 Unix domain socket 接受请求，不监听 TCP。
- [x] partner 适配层能够完成一次授权的写入和读回往返，未授权调用失败关闭。
- [x] 持久状态和备份以加密形式保存，模型请求和普通 Hermes 配置中不出现数据密钥。
- [x] 建立可控时钟、LLM、资料下载、消息发送和密钥管理替身，测试不依赖真实网络或真实时间。
- [x] 主要验收测试从 partner 适配层入口驱动，只观察 sidecar 响应、可授权查询和审计结果，不断言内部表结构。
- [x] sidecar 的最小能力接口足够深，后续 ticket 能在不新增平行存储或第二测试入口的情况下扩展。

## Answer

已完成 sidecar 独立进程、Unix socket 授权边界、加密状态与备份、逐记录密钥、可控依赖端口、adapter 读写/audit seam，以及明文状态拒绝和崩溃残留防护。当前本机全量测试 202 项通过、9 项因 Windows 缺少 AF_UNIX 跳过；Linux 受限账户、socket owner 和真实部署仍需部署验收。
