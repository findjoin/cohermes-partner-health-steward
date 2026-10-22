# Ticket126 最终窄修复执行证据

本页在2026-10-22整理此前已完成的执行结果，不改写原运行时间或历史失败。精确产品commit `d86cb51223b7b9c31af7b30c9fd73036595aa6b4` / tree `f42edf12c12de85521cdef20a9ed060dc6951976`；root独立干净detached来源 `/tmp/health-steward-126-d86cb51-clean`，已为普通推送分支的ancestor。该来源不包含尚未实现的130候选测试。

## 冻结权威与修复

唯一冻结权威是[Evidence54 R6.1](54-ticket126-safety-independence-refreeze-20261018.md#r61保留一般unknown的局部pause样例修正)：checkpoint `687961d8c0aca7b907e90b5fa8e7383a093e07f0` / tree `e9fd998710bdb9404139f1f6c901952ffc8c61fe`，design `4a6ec81c94edab252936815cf0fc98925def3d0f`、contract `4cf76b06ba455ee6034d8a5cb961d431cefbd18b`、verifier `f971bb6a058945eeaab6daae5bebabda81d89c86`。

产品仅在原Core claim接缝增加同一已提交安全事实／来源、唯一原主人durable unknown及当前独立批准contact的窄例外；不同来源、其他未决效果、非terminal/model均不满足条件。当前性、writer fence、key、lease acquisition及readback保持。原主人unknown不重试，contact可独立接受并通过原safety.correct形成一次纠正；没有排序依赖、新账本或一般unknown写入权限。

## 独立执行门

正式隔离根 `/opt/hsv-7i66_gv9/formal-d86cb51-126-r61`，verifier `/opt/t123v-d5602712`。完整87个tracked Python文件来源archive SHA256 `2d16604a01167817a58a8458a280b536c7861349e105920a06b407333014b3bd`；父产品-I/-B加载sealed安装包，真实root/Linux/Python3.11.15、AF_UNIX peer/ACL、真实Publisher registry。旧118白名单子fixture与父安装产品明确区分，未补丁产品成功或importlib.util。真pinned Git `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`、9240对象及四个来源指纹核验通过。

| 执行组 | 结果 | 用时 |
| --- | --- | --- |
| tests.test_ticket126_live_delivery | 5/5 | 31.246s |
| tests.test_ticket131_nondiagnostic_budget | 4/4 | 1.087s |
| tests.test_ticket124_live_entry | 4/4 | 4.111s |
| tests完整discover | 794/794 | 227.271s |
| root独立124/125/129/131/126专项 | 23/23 | 38.295s |
| 标准compileall及memory compile | 87/87 | PASS |

所有测试均0failure/error/skip。原样命令、结构化结果及日志保存在 `/tmp/dmit-connection-audit/formal-d86cb51-126-r61-{full-results.log,root-postphase.log,execution-evidence.json,audit.md,metadata.json,frozen-blobs.json}`；root独立源码核验 `/tmp/ticket126-root-d86-final-identity.json`。source87、冻结15、runtime7464在full、root复核及外部cache compileall后逐字未变，闭包 `sha256:8d6998134eb8ef0599965ab3b740f91c9e2f8f104991fc866c4862025cffa150`。diff19417da..d86、clean detached及pushed ancestor均通过。

只使用合成渠道HTTP替身；未部署、未执行真实JOJO推理、微信或联系人发送、主人初始化或验收。正式结果只属于精确d86及本页冻结权威，不能冒充130或128完成。
