# Ticket128：隔离前提修正与继续执行授权

本票仍claimed；本记录不表示正式门、部署或主人验收通过。default尚未切换，真实模型POST、微信发送、主人初始化均未执行。

## 实际证据与分类

候选bdae15cd5c735a56e13885724f4048029da24abe的R5真实3.11原V07：inner403.545秒、parent406.095秒，1failure/0error/0skip，owned namespace清理确认。G02原637项、G03原12项全通过；G04原118项只有旧129V02一项error。未到G10或自然触发，没有实际timeout。原日志 `/tmp/dmit-connection-audit/formal-bdae15c-128-r5-v07.log`；gates-progress-readonly日志SHA256为7cf56ba0dc1b3523d562b96a4793f5639e77a7ae4dab341b2814ef8e36e0c88e。

root用同一真实3.11/原129V02/9557文件runtime，在private mount/IPC namespace内配对：无shm时ctx.Event→SemLock报FileNotFoundError（1error，0.033秒）；自有tmpfs后原测试1PASS/0failure/error/skip（0.043秒）。runtime字节保持，未读或更改真实profile/service。日志 `/tmp/dmit-connection-audit/ticket128-r5-original129-private-shm-probe.log`，SHA256 d9133bc9acdb83da2e558ca43f55130f868497bc1ae1dd3b5161e9c0ec34daf6。分类为verifier普通OS前提缺失，不是产品CAS缺陷，不改旧129。

原V06/V07第二个新run完整重跑前置；G01→G02实际receipt跨度344.464967832秒，至G04约400.114084037秒，含准备/hash/工件。原12秒canary观察与480秒整family限制不容纳此已测工作链。这是源码加同一原语实证，不称已发生timeout。

## 新冻结与双pre

独立verification checkpoint fd7e508b0438b4415842b948b2163aa61e5f7523 / tree 3c3abed3e8e768955ec7c43e8f356c5c20fe1d39，parent bdae。仅合同/test/helper三文件：自有64MiB、mode1777、nosuid/nodev/noexec shm；两处canary前置观察1200秒和提前失败传播；有限嵌套family时限5400/5520/5550/5610秒。生产local540、G11/ND12各300、普通观察12、join30、自然due+90/quiet65均未改。不缓存/省略前置或减少原测试。产品、唯一设计、raw、旧18保持；全部256原assert/fail保持，仅新增提前终止失败断言。

| 文件 | Git blob | SHA256 |
| --- | --- | --- |
| 合同 | b0be7a20a8f58fe841a289ac8222c7bdb915b675 | 2be97e3aed2f22b3cae39e1694db8aadab8f85ea6b2b1d330d5580126860afa8 |
| test | 11464f8d8575a44acf205e9ea19790b4b6449bcb | 7b469742e1f0fc99472d7987110733680e6f4c348ea48ded35e4717ce047e06a |
| helper | c01394874b87968e2298868431c64fa844a6fe1f | 6f213ef581b5bf9d0234caeeae0b6d639092ae37abfb5a55697217acba96c921 |

其余20份冻结字节保持；全23由root及fresh Standards核对。

- Fresh Spec PASS、无阻塞：`/tmp/health-steward-reviews/128-pre-fd7e508-spec-fresh.txt`，SHA256 11c1a29cdd181c9bacf76531fc984bb3c7ad005d7ecfd0830826c1675e5fa52b。
- Fresh Standards PASS、无阻塞：`/tmp/health-steward-reviews/128-pre-fd7e508-standards-fresh.txt`，SHA256 9d9ab9847bbeaa7937ce3edef905188364625fe79de3c061710db893d7275b75。

两轴同checkpoint/tree、只读fresh context，未读另一轴报告，未运行新helper完整门。Spec的unpushed为派发时输入；root随后确认findjoin/准确仓库admin+push/远端bdae，普通push bdae15c..fd7e508成功，源码身份未变。

## Root裁决与执行边界

接受该验证前提修正并继续同一范围执行，不新增产品决定。R5事后98份compileall、23冻结、122来源、9557 runtime完整性通过；只清理退役公共runtime/pinned副本，保留日志/来源/manifest/私有事实，default仍MainPID521/active/running。

从新clean/pushed候选正常重建，先原V07，再原123/118基线、119七门、root30、原full discover808同父进程一次及compileall/diff/完整性。七family实际展开且零failure/error/skip后才fresh双post。真实default prepare/run、G10/G11与主人原生初始化/同意/序列/反馈仍待证；技术授权不能代替主人，阶段A不能晋升full或诊断active。
