# 05 — 建立受控医学资料库与按需核验

**What to build:** 让健康管家能够从固定权威来源建立、更新和查询有版本与标签的资料卡，同时限制抓取、存储和外部内容对系统动作的影响。

**Blocked by:** 02 — 建立 sidecar 最小纵向骨架

**Status:** resolved

## Answer

Ticket 05 is implemented in the sidecar source-library seam. The implementation
provides whitelist enforcement, configurable vetted guideline hosts, six fixed
normalized tag categories, review intervals and declared-validity precedence,
current-card lookup with whitelist-only on-demand fetching, explicit
verification-unavailable results, untrusted-content isolation, encrypted raw
cache and bounded metadata, serial daily scanning with root-domain pacing, and
reference-aware cleanup. Source query and scan are exposed through the
PartnerHealthAdapter to the Unix-socket server. Cleanup failures fail closed,
persist the actually deleted paths, and account for undeletable blobs for a
later retry.

Verification: 11 source-library tests pass with 1 Windows AF_UNIX skip; the
full partner-health-steward suite passes 218 tests with 10 environment skips;
compileall passes. Linux restricted-account/socket-owner deployment remains an
environment-level follow-up and is not claimed by this Windows run.

- [ ] 自动发现、更新和按需读取仅允许国家卫健委、中国疾控中心、WHO、美国 CDC、NICE 和经审核的医学专业指南来源。
- [ ] 资料卡记录来源、版本哈希、关键摘录、复查状态和六类固定标签，标签值先做同义归并再创建规范值。
- [ ] 公共卫生预警、临床指南和一般健康教育分别按 7、180、365 天复查，来源声明更短有效期时优先采用。
- [ ] 当下医学问题优先使用未过期资料卡；没有合适卡时才读取白名单来源，无法读取时明确表示未能核验。
- [ ] 外部网页、PDF 和摘录始终作为不可信数据，其内容不能调用工具、写入画像或创建任务。
- [ ] 资料更新不能自动成为个人事实，只能使任务前提失效、触发重评估或产生一次证据补全问题。
- [ ] 原文缓存 200MB、索引元数据 100MB、单文档 5MB、关键摘录 8KB 的限制均可从外部行为验证。
- [ ] 每次日检最多下载 20 份、并发 1、同域名间隔至少 1 分钟；超量候选留待后续。
- [ ] 清理只删除未被当前结论或未完成任务引用的最久未使用原文；引用和关键摘录保留，必要时拒绝新下载。
