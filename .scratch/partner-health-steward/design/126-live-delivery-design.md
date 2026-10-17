# Ticket126 唯一增量设计候选：真实 iLink 与受控投递交接

状态：pre-code candidate，未冻结、未实施。产品基线为124/125/129已闭合的`58453bf`；独立验证权威root，合同`126-frozen-verification-contract.md`。本文件只承接同一Ticket126；不改变131的模型预算设计、130的自然语言入口或128的真实渠道批准。

## 权威、复用与事务

HealthCore仍是唯一业务写入者。复用当前加密store中的initialization challenge、source receipt、业务record、DeliveryOutboxState、effect/lease与终态；不创建transport DB、发送账本、旁路pending列表或另一套批准。现有OwnerDeliveryEngine和115/116的未知、纠正、撤销、删除及迁移规则保持。

生产单次发送链固定为：业务引用绑定 → 同Core中形成/提交既有outbox → prepare/claim → 发送前authorize重新核验 → 一次iLink请求 → complete写原effect/outbox → 读取Core交接投影 → native cursor。API成功只形成`accepted`层，不推断delivered、read或主人行动。

新增的持久信息仅是原typed facts内的必要关联：outbox引用哪条已提交业务/初始化challenge，以及source receipt交接到哪个原outbox。业务结果与该引用必须同成同败；若需要独立CAS补交接，仍由Core准备/提交/最终化原mutation，不能先ACK再补引用。不会复制caller正文、凭据或第二画像。

## 有限公开Module与构造

### `partner_health_steward.weixin_transport`

`WeixinTransportBinding(account_id: str, base_url: str)`为不可变公开绑定：account_id为明确iLink账户，base_url为明确canonical HTTPS源，无userinfo/query/fragment、备用源或运行时重定向。它不是批准，也不含token。与Core发送destination的partner/account不符时零请求。

`PinnedWeixinIngressTransport(binding, *, token: str, session_factory=None)`：

- `async connect() -> bool`
- `async get_updates(cursor: str) -> dict`
- `async acknowledge_cursor(cursor: str) -> None`
- `async disconnect() -> None`

connect创建由Ingress当前event loop拥有的session；disconnect关闭它。token只由受信配置注入内存，禁止repr/日志/工件保存，不自动QR登录或读别的profile。session_factory仅替换aiohttp HTTP session边界；生产默认创建自己的session，禁止跨loop复用。

`PinnedWeixinOwnerDeliveryAdapter(binding, authorization: dict, *, token: str, context_token_provider, session_factory=None)`实现既有`OwnerDeliveryWireAdapter.send(intent_wire, /) -> Mapping`。该对象只承接一个Core返回的授权包；send收到的旧115主人send_intent（或116独立contact wire）必须与该授权包完全相同，不能另传text/to/client_id。Bridge在authorize后逐attempt构造它。`context_token_provider(recipient_id)`只提供同账户的既有host私有context token资源，不决定收件人、正文或批准；缺token不做tokenless补发。真实配置可复用pinned ContextTokenStore，不能另存健康业务状态。

send是同步接口。Bridge通过`asyncio.to_thread`调用；send在自己`asyncio.run`的loop内为该attempt创建/关闭独立session，只调用一次pinned `_send_message`。不复用Ingress session，不从Core/socket handler阻塞回调网络或反向调用同一socket，避免事件循环/锁互等。HTTP替身factory也按同样生命周期提供session。

### `partner_health_steward.live_delivery`

`LiveWeixinDeliveryBridge(core_port, wire_adapter_factory, *, clock)`；`core_port.request`为当前三类CorePort客户端，factory签名为`factory(authorization: dict) -> OwnerDeliveryWireAdapter`，生产装配闭包只绑定上述固定WeixinTransportBinding、token/context资源和session_factory。clock返回aware UTC datetime，Bridge只把它转换成既有UTC观察字符串；Core仍用自己的当前时间判断授权。

公开`async send_committed(value: dict) -> dict`。它只提取下节闭集业务引用，通过Core绑定/授权取回正文；绝不发送value中传来的owner_reply、owner_result、disclosure正文、接收方或任意新文本。为兼容124输入，允许读取原`turn_result`/`disclosure`中的ID来组成引用，但这些内容不成为授权或payload来源。

生产返回：`{status, source_causal_id, handoff_complete, deliveries}`；status只可为`accepted/rejected/unknown/not-authorized`，deliveries为Core无正文投影列表。handoff_complete只能来自Core持久读回；网络结果或Bridge自己的字典不能创建这个事实。

### 实际装配

当前Hermes registry工厂继续只注册health_weixin。配置了明确`weixin_transport_binding`且没有显式注入的Ingress/Bridge时，受信装配使用config.token与当前profile的context资源创建上述真实Ingress和Bridge，不能返回旧probe或普通native WeixinAdapter。缺token/绑定/CorePort/context依赖失败关闭；不从default/partner别处补配置。

124已有的显式Python依赖注入仍是整个Ingress/Bridge的测试或受信组合Seam；不是JSON Gateway调用方可以提供的任意对象。真实生产工厂创建的Bridge必须执行完整Core交接协议。实际发布物继续由Publisher收集同版本源码；126不能靠本机checkout补import。

## 闭集业务引用与CorePort公开wire

仍只有`command/managed-read/controlled-effect`三个kind，interface仍为`health-entry-v1`。command及controlled-effect payload为`{interface, operation, payload}`，managed-read为`{interface, projection, payload}`；未知field/op/kind拒绝。

`command / delivery-bind`的payload固定为`{binding: reference}`，reference只支持：

| kind | 精确附加字段 | Core查验来源 |
|---|---|---|
|`committed-turn`|`source_causal_id, record_id, transition_id`|当前source receipt及其同一已finalized DailyTurnResult唯一回复；native重投alias须由Core证明|
|`initialization-disclosure`|`source_causal_id, workflow_id, disclosure_id, headers`|当前未同意challenge、真实第一事件的准入headers及明确init workflow绑定|
|`committed-safety`|`source_causal_id`|当前Core已提交116 safety result的原source/managed-command receipt，包含必要owner最低提示及已有contact intent引用；不编造现有Response没有的result_ref|
|`owner-outbox`|`intent_id`|现有复盘/task/lifecycle/owner-decision outbox，不是caller自造payload|
|`contact-alert`|`intent_id`|现有116已签发的唯一联系人alert/correction，不是owner发送|

无body/text/destination字段。`headers`沿124的11个公开header字段；Core重新做唯一owner/private/account/entrypoint准入，不能仅信workflow字符串。返回固定`{deliveries: [projection, ...], source_causal_id: str|null, handoff_complete: bool}`。

delivery projection固定无正文：`{intent_id, recipient_role, source_causal_id, current_layer, unknown_frozen, handoff_complete}`。recipient_role只可为`owner/support-contact`，current_layer沿既有outbox事实，非新的状态机。contact的intent_id沿116已公开alert/correction effect ID，Core仅在内部映射原outbox ID；不能把caller传入的ID直接当另一个outbox。整条source的handoff_complete只在所有必需的独立delivery均已Core持久确认时为true。

`controlled-effect / delivery-prepare` payload：`{intent_id, attempted_at_utc}`。Core精确选择该outbox已有effect，调用既有issue/prepare/claim；不能使用“任选当前唯一未决effect”。返回`{delivery, send_intent, intent, grant}`，后三项未获权或已有终态时为null；grant沿当前service的`session_id/lease_id/effect_id/intent_digest/generation/writer_fence`形状。Core内部时间/当前批准与route仍是判断权威，caller时间只作合规观察输入。

`controlled-effect / delivery-authorize` payload：`{intent_id, grant, attempted_at_utc}`。当前service从原`_effect_sessions`取出同一typed grant；重新核验current head/site/fence、exact effect、route generation、当前批准、payload digest和purpose。返回`{delivery, authorization}`；无权/已有终态时authorization为null。

authorization精确公开字段：`{purpose, recipient_role, account_id, intent_id, send_intent, payload, payload_digest, route_id, route_generation, execution}`。purpose仅为`owner-reply/initialization-disclosure/owner-outbox/contact-alert/contact-correction`；owner payload为`{text}`，contact payload为`{contact_alert}`且只含下节三项。account_id取当前Core admission policy；contact destination本身不含账户，不能猜账户或借另一个token。send_intent沿既有115 wire；contact沿既有116的`{destination, contact_alert}`，不把contact改装为owner。payload_digest为本次最小wire payload的canonical digest，Core还须独立核验原send_intent/outbox保存的业务payload digest；二者不是未经解释的强制相等。正文由Core从原事实解析，不能以Bridge提供的digest证明正文。

execution只含`{lease_id,effect_id,intent_digest,generation,writer_fence}`，来自真实typed grant，不含session_id/capability。Bridge与当前RPC grant逐字段关联；session_id只作为service的会话引用，不混入正文或平台client_id。

`controlled-effect / delivery-complete` payload：`{intent_id, grant, result, observed_at_utc}`，result沿OwnerDeliveryTransportResult的`{status,result_ref,evidence_ref}`。Core用同session/grant执行原complete链；不能走旧generic terminal只写effect、不写outbox。返回`{delivery, source_causal_id, handoff_complete}`。过期/伪session、错lease/digest/fence拒绝，不能仅凭intent_id改终态。

`managed-read / health-entry-delivery` payload：`{intent_id}`，返回`{delivery: projection|null}`；只读原事实，可在complete响应丢失后证明原terminal；不补发。

`LiveHealthCoreOperations`继续拥有上述bind/read的Plugin入口；ProductionCoreService的同一controlled-effect handler承接三phase并使用原`_effect_sessions`，不会另建LiveOperations私有session表。preconsent、daily、safety/contact都必须经实际同一Core/Plugin；独立testport不能自证授权。

### Core必需的公开短方法（同时用于Service与真实业务fixture）

- `HealthCore.bind_live_delivery(reference) -> {deliveries, source_causal_id, handoff_complete}`。
- `HealthCore.prepare_live_delivery(intent_id, *, attempted_at_utc) -> {delivery, send_intent, effect_intent}`。这里effect_intent为真正typed `EffectIntent`或None；send_intent为上述公开wire或None，delivery为无正文投影。Service再调用原`claim_effect_execution(effect_intent)`；没有第二个claim实现。
- `HealthCore.authorize_live_delivery(intent_id, grant: EffectExecutionGrant, *, attempted_at_utc) -> authorization | None`。直连Core的合法调用与生产socket使用同一typed grant验证和purpose分支。
- `HealthCore.complete_live_delivery(intent_id, grant: EffectExecutionGrant, result: OwnerDeliveryTransportResult, *, observed_at_utc) -> {delivery, source_causal_id, handoff_complete}`。
- `HealthCore.live_delivery_status(intent_id) -> projection | None`。

Plugin以同名公开wrapper（增加`peer_id`）实施现有plugin peer/admission校验，不让Service读取私有SQL。Core的方法是实际生产必经路径，不为测试开放设置active/批准/联系人或替换store。116现有公开业务fixture可形成真实已批准contact后经过这些方法→同一wire Adapter→complete证明purpose；V04另经真正Service/socket/registry证明会话与装配，不能把direct fixture当已完成生产组合。

## 初始化第一事件与独立确认

workflow/disclosure/callback身份基于账户、owner、conversation、entrypoint、真实message_id及protocol timestamp；不含batch cursor、received_at或poll index。初始化缺稳定原生message_id时不猜一个可重放同意身份，失败关闭。重投同事件但cursor改变/重启仍lookup原challenge与原outbox；不会多次呈现披露。

第一条`/health-init`在原source receipt/challenge机制登记为无健康正文的披露来源，绑定当前已形成的disclosure；完成授权交接后有自身native cursor directive/terminal。当前124分支的`(None,False)`不能作为126完整交付，否则第一批永久阻塞后续确认。首次披露不产生owner_consent或first_hop_route_consent，不enable。

preconsent例外仅用于当前challenge、当前admission policy及同一owner route的固定披露。复用current head/fence/完整性/lease与原outbox，允许在尚无enabled settings时由Core从既有challenge+安装/admission绑定取得身份；不能伪造OwnerSettingsState为enabled、借用daily/task或让普通model/contact效果进入。route authority缺当前绑定时拒绝，不从caller猜测。

独立新原生确认仍要匹配当前workflow/disclosure和明确同意文本，经原prepare→commit→finalize才enabled。旧challenge、其他sender/route和body伪造均不能确认。确认事件与第一事件各自source/cursor事实不混写；重复确认不重复enable或创建新披露effect。

## ACK、正文释放与现有兼容

Daily/safety唯一回复先由Core从已提交结果绑定outbox。当前112的advanced receipt会释放daily正文，这条隐私规则不放宽；handoff前无权ACK，handoff后重投只读terminal及原ID，不重建正文或再调用transport。若原正文已按旧合同释放但没有既有合法handoff，明确unavailable，不能从Bridge传入的turn_result补回。

生产Bridge必须await Core complete/readback。已知accepted/rejected或持久unknown可形成终态交接；形成intent但还未授权/完成不被当发送成功。complete可能丢失时先exact read；无法证明就不给cursor推进，重启按原effect/outbox恢复unknown，绝不重新网络发送。发送与Core回交之间崩溃保留原attempt/unknown冻结。

LiveAdapter不能吞掉Bridge的not-authorized/unavailable、异常或畸形返回。真实生产Bridge的缺失/false handoff_complete阻止ACK；原124显式注入的整个Bridge seam仍保持既有accepted/unknown返回兼容，不能把该兼容输入当生产Core证明。新增门必须经过真实生产组合证明实际网络结果不会越过Core交接。旧111/112/115/116/118/123/124冻结测试不改。

## 最小联系人与安全主人提示

只承接Core现有提交的116 safety/alert/correction。source meta.branch为safety时不能因为没有meta.turn_result就丢掉owner_result；Bridge交Core查同一committed safety result，绑定owner最低提示和已存在的contact意图。owner提示和contact终态各自独立，任一路失败不抑制另一路。

支持联系人只接受现有明确`method_kind=weixin_user`，method_value为非空Weixin ID；电话或其他方法不强转to。当前唯一contact/version/批准/route必须在authorize前仍有效。payload仅`owner_recognizable_name/event_time/fixed_urgent_help_request`，或既有最小纠正语义；不含症状、诊断、位置、原消息、证据或画像。固定render不是自由文本拼接入口。unknown及纠正次数沿116，不创造备用联系人或自动重试。

## iLink 可观察终态与凭据边界

只复用真实pinned低层`_get_updates/_send_message`，不实例化native高层dedup/batch/retry/tokenless-fallback链。getupdates超时沿pinned空batch/原cursor；发送只允许一个POST，client_id取Core幂等identity并作固定无随机映射，不以平台可能幂等作为重试许可。不自动拆分/截断Core授权正文或以多个新client_id补发，超过可承载边界时在调用前失败。redirect禁止，session不使用环境代理切源；HTTP异常/原始响应正文不得进入错误输出。

明确ret/errcode成功只记accepted；明确业务拒绝可记rejected；响应丢失、超时、非HTTP成功/畸形/未能确证的终态为unknown。result_ref/evidence_ref只是不含正文的本次观察引用，不是delivered/read证明。getupdates游标没有单独远程ACK接口，acknowledge_cursor只承接Core允许的下一poll cursor，本地不另持久化sync_buf；不伪称服务端送达证明。

真实token/context/account资源、当前target/release/run、网络批准和canary归128；本票所有凭据/消息/联系人/HTTP替身均合成。既有DMIT整机旧快照限制不由Transport冒充解决。

## Characterization、复杂度与有限验证

- 已有绿灯：Evidence44/45全量785、真实root/3.11、真实pinned Git与Publisher包、四项124入口及125/129都已闭合。
- 差额：Plugin.controlled_effect已有authorize/send/complete，但service旧phase只claim/terminal；Core owner binding只认识task/review、lifecycle/decision；未初始化settings/claim门拒绝披露；live `_headers`把cursor纳入初始化workflow，第一init无可推进receipt；live只认turn_result；bridge结果没有交接门。以上是现行直接链差额，不能以wrapper存在冒充完成。
- pinned来源固定`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`：`weixin.py:399`_api_post，`:447`_get_updates，`:468`_send_message，`:1765–1860`高层retry/tokenless不复用；`:1196–1198`当前账户/token/base_url资源名。原源码HTTP错误包含raw[:200]，新Adapter必须清洗，不读实际配置作characterization。
- 新增权威状态0；新持久ledger0；新增payload业务关联保留在原Core facts；新增公开Module仅固定网络Adapter及Bridge，CorePort kind仍3。session、factory和授权包只是既有边界的单次内存资源，不形成后台队列或新恢复框架。
- 独立root按合同五个有限outcome gate持有测试：单次真pinned低层、preconsent真实事件、daily/safety交接与currentness、同socket/registry/restart unknown、唯一contact最小payload。维持旧回归与full零skip；不按field数量扩门。

只有同checkpoint的唯一设计、独立合同/测试和fresh Spec/Standards通过后才实现。若要求第二账本、取消正常正文释放/同意/unknown、或把不支持contact方法宣称可发，带具体证据返回顶层；本票不自行改变产品决定或闭票。
