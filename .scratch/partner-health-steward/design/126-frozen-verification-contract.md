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
