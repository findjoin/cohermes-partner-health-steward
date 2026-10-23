# Ticket128：R8实际loader通过与CorePort请求EOF修正

本票仍claimed；正式default未切换，真实模型POST、微信发送与主人初始化未发生。本记录不表示新门或部署通过。

R8精确ce6d9cc708aa8d6340168e83e9241edf70836b4c/treeb57acf63c37517fff33a90a4446e8db7e3348365，原87d24bd冻结、实际Python3.11、9557文件，closure sha256:98e9c376667a94bf5434699864cf24ab90701408918a6264dc698fa24a05ca74。原V02实际G01—G10及ND07均passed，七local组637/12/118/74/11/6/5均零failure/error/skip；已通过新actual-exe FD身份与loader的LiveHealthRuntime/knowledge0/诊断scope缺席三个断言，随后首次initialized managed-read在读取reply header时连接关闭。

原child524.229秒/1failure/0error/0skip，非timeout、operator cleanup confirmed。原始child stderr从owned /opt/t128ns-family-tc5_nkfa/data/original-test.stderr只读取出：/tmp/dmit-connection-audit/ticket128-r8-v02-original-child-stderr.log，2570字节，SHA2561055bb220ff67f9cc2e89e1484bd3b33fd4d11533424ed204bb501ab722e5c1e。取证JSON ticket128-r8-final-family-raw-readonly.json保留原report/cleanup/outer.stderr及各hash。最初formal-v02.log为0字节，不用作trace证据；父528.461秒仅来自实际toolstream，未冒称已封存parentraw。后续operator命令同时封存stdout/stderr，不改产品。

独立verification明确该首失败是verifier请求漏发EOF：原123服务先读完整单帧，再要求trailing EOF才dispatch。FramePort和内嵌kernel client sendall后直接recv，服务按原1秒边界超时返回关闭；真实CorePortClient/default RPC/原123合法client均half-close。仅两处各加shutdown(SHUT_WR)，不改Core；旧123迟到tail/never-half-close负向、64KiB/canonical/payload/peer/response/角色/timeout均保持，无重试。内嵌client属同因果源码缺口，未冒称本轮V05已失败。独立assessment /tmp/ticket128-r8-frame-protocol-assessment.md SHA25603a2d93ef32fc49a03a6d7bde5ce3fd0aaabf90328dc3d7603801acba35377ac。

新checkpointfd45cc5d32eac87566171d781588055d105c1f48 / treef07e3590cc1907c5a725af12cbcae63e833be066，parentce6d9cc。仅test两语句+合同事实段，二文件4insertions。design/raw/helper/旧18/全部产品不变，原7父方法、V07三世界及808计数结构不变。

- contract blob9d2ab07f80f98c70a86d9f1596d19370c78f3dae / SHA2562e4dd9f598050962bc10746ba6876649d7e5d633a155db65183ee5fd976af0ef。
- test blob13b164bb5cd665b70414136cb73c72e68793b951 / SHA256658c4f55ceac89d462196193f531de4437006b3e2750dbbbf4b0aa6214dd0146。

Fresh Spec PRE PASS、无阻塞：/tmp/health-steward-reviews/128-pre-fd45cc5-spec-fresh.txt，SHA25692c6f5ac9839f56f363598cbe57b52a2bbc9ab52c7041523f2c20236ded08703。

Fresh Standards PRE PASS、无阻塞：/tmp/health-steward-reviews/128-pre-fd45cc5-standards-fresh.txt，SHA256288ca835102ab10dcd53d7fdf9415c831d85e7fc53011b6de272edd7c4cd19d1。

两轴fresh只读同checkpoint、互不读另一轴；仅静态审查，不冒称实际新门通过。Root已核账号/exactorigin/正常前驱和无秘密diff，普通push ce6d9cc..fd45cc5至原分支成功；reviewer未自行联网核push。Root接受本次窄重冻，继续从最终clean/pushed同source正常构造实际3.11闭包，原V02、123/118、119七门、root30、原full discover808同父进程一次，compileall/diff/冻结/完整性全绿后才fresh双post和真实default/主人步骤。生产local540、G11/ND12各300及所有安全边界不变。

R8事后compileall98、冻结23、来源122、runtime9557全不变。无引用后仅退役该次公开input runtime/pinned，保留全部源/日志/manifest/私有事实。为完整验收容量，root另有意识退休已结束130final f21e8ad-r27及旧131-1fd554f/126-d86cb51-r61的公开runtime/pinned，均重核完整canonical manifest与无proc/mount引用，源/原通过日志/清单/结果保留，不改历史事实。构建seed、实际Hermes及健康资料保留。日志 ticket128-r8-retired-public-prune.log、ticket128-closed130-retired-public-prune.log、ticket128-old126131-retired-public-prune.log均位于/tmp/dmit-connection-audit/；正式default前后仍PID521/active/running。最新可用空间3715215360字节，仅是当次观测。
