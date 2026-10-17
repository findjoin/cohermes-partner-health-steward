# Ticket126 独立验证合同候选

状态：pre-code candidate，尚未冻结。Verification authority：root，独立于126设计/产品作者deployment_audit。当前124/125/129已按Evidence44/45闭合；唯一126设计为同checkpoint的`126-live-delivery-design.md`。本合同只承接Ticket126现有验收，不新建业务状态、批准或渠道事实。

## Characterization与继承绿灯

基线`58453bf`的全量785门和root14专项均绿色；真实pinned Base/registry、初始化/日常原子结果、current-head与三类CorePort可用。当前live Adapter只有注入transport，缺生产Ingress/单次发送/真实授权handoff；首次init身份包含batch cursor；Core outbox缺finalized daily reply及既有preconsent disclosure绑定；生产CorePort旧claim/terminal缺完整authorize/complete映射。现有125模型和130生产NL不由本票伪造。

pinned `_get_updates`/`_send_message`只做一次低层请求，高层native发送包含retry/tokenless fallback，不能复用。低层接口不提供delivered/read证据，本地client_id不是平台送达证明。所有网络、身份、正文和凭据均为离线合成；不读取实际用户配置或联系真实接收方。

## 五个有限验收门

| Gate | 最高接口可观察结果 | 独立现实错误/mutation |
|---|---|---|
|126-V01|生产Ingress/发送transport经真实pinned低层函数及网络边界替身执行；一次poll/一次send，不调用native高层dedup/batch/retry，exact destination/context/idempotency；超时/畸形/非明确成功为unknown，错误输出清洗；不伪造delivered/read。|包装类存在但无实际低层调用；隐藏重试/tokenless fallback/随机client_id；raw错误正文泄露；API无异常即补送达。|
|126-V02|真实Core/Plugin的preconsent challenge绑定实际唯一原生事件；同event换batch cursor/重启仍同workflow与唯一披露effect，仍uninitialized；只发送Core原有disclosure，任意caller文本/错route/非owner拒绝；独立匹配confirm才enabled。|以cursor作init identity；caller bridge即发送权；先enable再发披露；伪同意；重投生成新challenge/新发送。|
|126-V03|真实finalized daily结果在ACK释放正文前形成唯一outbox/授权handoff；只取Core exact正文/digest/当前route/fence，同source重放不第二send；accepted不蕴含delivered/read；发送前currentness失效零网络。|发送bridge caller回复；漏授权重验；ACK后复活正文；同batch重放双发；旧route/fence继续网络。|
|126-V04|同生产CorePort字节流及实际registry Adapter/发布包组合承接receive→prepare/claim/authorize→单次send→complete→cursor；重建保留exactterminal，可能已发/终态回交失败/重启未完成均unknown冻结，零自动重试；缺授权handoff不能越过cursor。|只测孤立transport/直接Core旁路冒充生产；bridge结果被丢弃；旧session伪complete；unknown重启重发；第四kind或任意RPC。|
|126-V05|真实当前唯一联系人与批准的最小警报经独立purpose链；只含可识别称呼、时间、固定求助语义，旧批准/错接收方零发送；unknown及纠正保持原意图和原次数边界。|普通owner发送冒充contact；症状/位置/诊断/原消息泄露；过期批准复活；unknown或纠正无界重试。|

门使用能够杀死上述现实错误的正向tracer及必要负向等价类，不做字段/故障笛卡尔积。具体公开API以唯一设计为输入后由本独立verifier编写；不能以private helper/SQL检查替代完整公开路径，不由实现者改门。

## 执行与冻结

Verifier候选`tests/test_ticket126_live_delivery.py`；命令`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket126_live_delivery -v`。正式V04继承123/124真实root/Python3.11 runtime、完整source fixture、实际pinned Git身份及实际Publisher包来源断言；环境缺失不能skip成完成。底层网络替身不拥有业务授权，数据fixture可复用111/112/115/116/123/124，旧冻结文件不改。

受影响回归保留111/112/115/116/118/123/124，最终完整discover零failure/error/skip、compileall与diffcheck。当前候选将记录产品缺失的明确预期红灯，不把ModuleNotFoundError、环境error或skip冒充预期红。对同一commit/tree新鲜Spec/Standards预审PASS并记录三件套blob后才允许生产编码。真实渠道与主人验收仍归128的target/release/run精确授权，不由此门证明。

## 公开接口与本次执行证据

使用唯一设计的WeixinTransportBinding、PinnedWeixinIngressTransport/PinnedWeixinOwnerDeliveryAdapter、LiveWeixinDeliveryBridge与Core公开短方法。V01网络替身只在session HTTP层，真pinned低层序列化/POST执行；contact业务digest和wire payload digest故意不同，避免把两层混为一谈。V02/V04 child经过真实registry选择，产品所有已加载模块须来自父ProductionCoreService同一Publisher内容寻址release的Plugin包，父Core来自sealed runtime；第三方aiohttp.ClientSession是唯一network替身，不能patch产品helper或Core成功结果。V04的handoff值来自实际Core complete及managed delivery投影，不从本地发送结果自证。

V04包含实际socket reply→send已观察accepted→仅丢失CorePort complete请求→不给cursor→关闭/重建同持久Core→原attempt转unknown并冻结，零第二发送。受信fixture只改变网络是否回交，不伪造业务终态。V05沿真实116公开配置/批准/接收危险来源形成safety managed receipt和contact intent；同一Core必经短方法形成主人固定模板及最小联系人授权、完整回交与纠正。该direct业务fixture不冒充已完成contact真实socket/目标验证，socket/session公共装配另由V04证明；真正主人配置与渠道留128。

编码前命令`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket126_live_delivery -v`为5个明确prerequisite failure，0error/skip（`/tmp/ticket126-precode-red.log`）；产品Module未实现，因此新增内部路径未执行。新测试compile PASS、diffcheck PASS。继承绿灯为已闭票Evidence44/45的785全量与14专项；另由独立implementation_audit在`/tmp/ticket126-contact-characterization.py`实际运行116公开accepted/response-loss/replay/pause/correction及中断后的attempted→unknown保留，日志同目录，不涉及实际用户或网络。唯一design和三件套需同commit/tree新鲜双轴预审后才冻结。

## 编码前有界修订：真实Adapter失败交接与安全引用

`2ef6271` fresh Spec/Standards指出三个已声明验收的验证缺口，未重开架构：原V04失败回交只测Bridge而未杀死Adapter吞结果继续ACK；原V05只测直接Core安全binding，未杀死实际Adapter因缺turn_result丢弃safety；原V03在prepare前就使head失败，未证明发送前authorize重新读当前性。

本修订保持五门与设计不变：V04实际registry/生产Bridge/同socket/真pinned低层送出一次后，仅丢弃delivery-complete请求，观察Core与后继poll cursor都不前进，再重建同Core确认unknown冻结/零重发；V03先观察真实prepare/claim grant，再使合成current-head网络依赖不可用，继续authorize且零发送；V05增加实际registry Adapter+生产Bridge的安全引用抽取tracer，输入为真正Plugin接收危险消息的Response，owner模板与现有contact intent各自经过Core公开短方法授权/终态。

V05的verifier RPC只封装JSON-value和临时session映射，所有typed EffectIntent、EffectExecutionGrant、authorize结果与handoff都直接来自同一个真实Core；不制造grant/批准/active/业务成功，不持网络锁发消息，不声称这条fixture就是生产AF_UNIX服务。真实Service/ACL/同版本发布路径与session失效仍由V04独立验证。新helper包含在同一个verifier文件的冻结blob中；它不是生产替代实现或第二业务权威。

另修正正向transport授权fixture的owner/contact route：分别与原OwnerWeixinDestination.route_id和既有contact destination.route_id一致，wire payload digest与原业务digest仍故意分层，避免要求生产接受自相矛盾的route。Session替身接受真实aiohttp的默认trust_env=False，不把显式写默认参数作为额外实现要求；仍拒绝打开环境代理和HTTP重定向。

修订门仍为5个明确缺公开Module prerequisite failure，0error/skip（`/tmp/ticket126-precode-red-r2.log`），compile/diffcheck PASS。独立helper的既有116 probe/read/receive smoke已执行，新增126短方法尚无产品实现，未声称新增内链绿色。修订后只复核上述缺口/fixture一致性，原已审范围不重新开放。

## 实施阶段有界验证补齐：持久unknown的exact cursor交接

原设计第106行明确“持久unknown可形成终态交接”。产品作者在精确cd5bcb3公开Core smoke发现unknown/handoff_complete=true后native_cursor_directive仍为None；root独立重跑复现，日志 `/tmp/t126-root-unknown-ack-reproduction.log`。这是既有126-V04的现实边界缺口，不扩模型／健康写入权限、不重新设计unknown状态。旧V04仅证明重启unknown、无重发与handoff=true，未杀死全局UNKNOWN总门把该条已终态来源ACK永久卡住的错误。

独立verifier仅在V04补两条同因果tracer：实际registry Adapter／生产Bridge／pinned HTTP替身在唯一send响应超时后，由真实Core持久unknown并确认handoff，仍能持久推进其exact source cursor，重投零第二发送；原complete丢失并重建后，未知终态读回真实handoff，再经原cursor指令及结果短调用推进该条cursor，旧session仍拒绝。HTTP替身只改变网络是否返回，不伪造Core终态或ACK。未知投递的原intent/unknown_frozen及禁止重发语义保留。

独立正式旧门在精确cd5bcb3为5run、3fail、0error/skip（V01/V05绿，V02/V04 connect与V03 submitted为已覆盖产品错误），未运行full794。新V04内部unknown ACK路径尚未经过最高接口执行；局部公开Core复现只证明缺口，不声称修订门已绿。新verifier编译／diff通过后，须同一checkpoint fresh有界双轴审查并更新精确合同／测试blob，才允许修复此unknown ACK缺口；设计blob不变，原三项已覆盖实现错误仍可按原门修复。五门数量及原旧冻结门不变，最终完整794全量仍必需。

## 实施阶段有界夹具修正：真实release摘要

上节记录的精确cd5bcb3旧门5run、3fail、0error/skip及未执行full794仍为实际结果；其中V03的产品错误归因在此更正。真实Core已完成prepare／authorize／单次send，complete调用生产DynamoDBCurrentHead释放实际执行租约时，123默认复用的122 `_ScriptedDynamo`只识别`sha256:release`与`sha256:different-release`两个人工占位摘要，真实Core操作摘要触发`StopIteration`，被生产边界正确处理为`HeadUnknown`，所以bridge返回submitted／handoff=false。独立诊断见`/tmp/dmit-connection-audit/formal-126-integrationcd5-diagnose2.log`；不能为此修改生产摘要、放宽unknown、伪成功或更改旧122／123冻结文件。

本修正只在126 verifier定义`_ReleaseCapableDynamo`，经123既有`client_factory`接缝供`_service`使用。非release事务委托原有替身；release边界保存真实请求，检查lease_id／holder／unreleased／同一operation ownership，以及同一事务中的guard contains和仅删除该effect，全部条件满足后才原子写入真实`released_operation_digest`并移除活动租约。拒绝不修改记录／活动集合；不改摘要、不制造Core授权／终态／handoff，不改生产helper或旧冻结门。R3的unknown ACK断言及五个验收方法全部不变，设计不变。

局部独立characterization使用实际HealthCore／Plugin与生产DynamoDBCurrentHead：真实初始化、证据阶段、model effect intent／typed grant／实际观察报告及effect.result经过该边界，得到accepted终态并原样存储71字符SHA256操作摘要；同操作重放只读恢复，异操作owner被HeadConflict拒绝。另验证lease_id、holder、已released、异operation owner、缺active effect、错误DELETE六类条件均原子拒绝。命令`python3 -I -B /tmp/ticket126-r4-fixture-characterization.py`，日志`/tmp/ticket126-r4-fixture-characterization.log`。这是局部租约／终态链与夹具语义证明，未执行新最高socket／Publisher／Adapter五门或full794，不声称其已绿；须同一新checkpoint进行仅此夹具修正的fresh有界双轴复审后再正式执行。

## 实施阶段有界拒绝观察修正：故意非法binding的EOF

R4正式冻结后的精确`6752fad`新sealed runtime执行126五门为5run、1fail、0error/skip、27.487秒：V01／V03／V04／V05绿，含真实release摘要与R3 unknown ACK；V02已完成真实披露及一次发送，但在两个故意非法binding的负例处，实际Publisher包`_CorePortClient.request`按既有严格帧合同抛出固定`_HostVerificationFailure("core-frame-truncated")`，原verifier误按123另一transport helper的`None`拒绝面观察而未捕获。Service对非法binding关闭连接是正确拒绝，不修改生产客户端／Service使其伪成功或放宽帧。131／124专项及full794尚未启动；源87／冻结15／运行环境7464文件的失败后哈希守卫均通过。证据`/tmp/dmit-connection-audit/formal-6752fad-126-131-{full-results,postfailure-guard}.log`。

本R5候选仅在两个故意非法输入的调用周围捕获具体`_HostVerificationFailure`，并断言唯一允许的固定EOF原因及异常不包含caller正文／非owner输入；正常连接、披露、后续查询、重放与独立确认路径不捕获异常。原无handoff拒绝断言保留，显式accepted业务结果仍拒绝；每个负例后证明无新send、真实查询仍可读且初始化仍uninitialized。设计、产品、R3 unknown ACK及其余验收不变，旧122／123冻结文件不改。

R5尚未冻结。允许对精确6752产品字节加候选verifier的全新隔离快照做provisional最高V02／必要五门characterization，须单独标明候选Git身份及未冻结边界；该证据不替代fresh有界双轴审查后的正式五门／full794。此时不启动full794，也不声称R5正式门已绿。

首个未冻结候选`cde88eb`的provisional五门为5run、1fail、0error/skip、38.360秒：EOF修正已通过，init-form的两个非法binding均正确拒绝，正常查询仍uninitialized且无第二发送；其余四门绿。后继init-confirm因合成时间矛盾未启用：共享native时间`1787520000000`实际为2026-08-23T21:20:00Z，原confirm仅加1秒，仍早于fixture真实披露时刻2026-08-24T00:00:00Z。Core严格要求披露早于protocol_timestamp及received_at，没有产品缺陷。证据`/tmp/dmit-connection-audit/formal-126-r5-provisional-cde88eb-{components-only,postfailure-guard}.log`；未执行full794，源87／候选身份15／运行环境7464文件均未变化。

R5第二个样例修正仅把V02 init-confirm的合成protocol timestamp明确设为2026-08-24T00:00:01Z，不改共享native fixture／生产顺序检查／其他四门。局部真实Core／Plugin公开流程已验证旧protocol时间在received_at也晚于披露时仍被`health-init-disclosure-order-invalid`拒绝；protocol=00:00:01Z且received_at=00:00:02Z时可依原prepare／commit／finalize启用，日志`/tmp/ticket126-r5-confirmation-order.log`。最高入口中received_at仍由真实Adapter取当前接收时间并由未放宽的Core同一严格顺序门检查，不能用修改生产检查或自动同意换绿。此样例修正仍须新干净候选provisional五门观察及R5有界双轴审查后正式冻结。


## R6：独立安全投递的owner unknown故障补齐

精确837按R5冻结后的正式126五门/131四门/124四门、full794及root23全部绿色，source87/冻结15/runtime7464/编译闭包均通过，实施后Spec PASS。然而Standards源追踪发现设计第112行“任一路失败不抑制另一路”的现实边界未被V05覆盖：旧V05始终先把owner提示完成为accepted，只对contact模拟unknown。报告未执行重现；root随后在真实837 Core/Plugin/116当前已批准contact fixture独立执行公开bind→prepare→claim→authorize→complete，owner结果为unknown且该delivery持久handoff=true；接续同来源contact prepare仍有真实intent，claim却为None。证据 `/tmp/ticket126-owner-unknown-contact-repro.py` 与同名.log；实际bound列表虽contact在先，原公开合法owner-first路径和两路独立义务不能用排序约定替代。整体handoff=false此时是正确的，因为contact尚未完成，不将它误判为owner终态丢失。

本有界补门只在原V05等价类加入owner-response-lost=true/contact-known，沿同原execute/真实Core/当前批准路径证明owner unknown不抑制contact单次发送及原当前纠正；并再次读回原owner unknown_frozen且prepare不产生新send。旧accepted-owner/accepted-contact与accepted-owner/unknown-contact两类及其他四门保持，唯一设计/旧116/122/123冻结文件不变；不新增门ID、批准ledger、联系人、网络重试或一般UNKNOWN写入权限。纯局部公开repro已真实执行，修订完整V05及新产品修复尚未执行，不借旧794宣称本次已通过。产品作者不得改本测试/合同；须同一新干净checkpoint fresh有界Spec/Standards通过后才允许仅修同已committed safety source的独立投递重叠。之后仍重跑原五门/794/23/编译/完整性及仅原finding的实施后双轴复核。


同一R6门补一个独立负向等价类：owner unknown之后，用原116公开safety.evaluate形成另一来源、当前同联系人且批准有效的contact，真实bind/prepare仍有intent，但claim必须拒绝、零contact网络。该负例杀死直接删除non-contact过滤或放行任意unknown的修复，不要求字段笛卡尔积。root已局部表征该来源可在owner unknown后由真实公开安全路径形成（`/tmp/ticket126-owner-unknown-contact-after-isolation.log`）；正式修订门仍未执行。只有同一committed safety fact/source的原主人提示未知终态可以形成极窄例外，原一般UNKNOWN/模型/不同来源阻断不变。
