# Ticket130 全量门发现的私有资源生命周期缺口

精确干净产品 `364943e9845b7019095d49e6e02e89649ef59c92` / tree `07b032e6cd14a70dcdb71d07be28d3f460961fc8` 已普通推送，在fresh DMIT隔离 `/opt/hsv-7i66_gv9/formal-364943e-130-r26` 原样执行R2.6组件20/20通过：130七门233.254秒、126五门35.160秒、131四门1.147秒、124四门4.895秒，全部零failure/error/skip。随后同一快照全量801项为 **0 failure、7 errors、0 skip，379.085秒**，不能闭票或开始实施后双轴。原始日志 `/tmp/dmit-connection-audit/formal-364943e-130-r26-components.log`、`formal-364943e-130-r26-full.log`；远端完整原log `logs/formal-full-discover.log` 保留。

root只读提取完整错误索引 `/tmp/dmit-connection-audit/formal-364943e-130-r26-fd-error-index.log`：V05、V06及V07五个subcase均包含 `Too many open files`；真实session文件句柄soft/hard limit为1024/1048576，没有提高limit。两轮执行的source91、frozen18、runtime7467均未改变，closure `sha256:9734755c4c0214b873ffc439984164d2d2e72c198f65f4cd1ac9b3637aed8cb3`；组件绿色不能代替全量错误。

独立verification实际同sealed Python3.11对照 `/tmp/ticket130-fd-lifecycle-observe-remote.sh/.log` 证明：原123 fixture临时writer/key遗留5个FD；真实Service每轮start→healthy probe→close仍净增10个，重复close和对象回收无效；资源构造后socket_mode验证失败也净增10个。仅诊断释放fixture自己的5个pin不改变真实Service的authority/key/healthy结果，但Service每轮仍增10个，故不是仅测试清理错误。产品作者独立本地纯合成 `/tmp/ticket130-fd-public-observe.py/.log` 用weakref确认provider对象全已释放，key/writer/execution每轮仍分别增2/3/5；`/tmp/ticket130-fd-core-close-observe.py/.log` 真实public Core组合healthy→Core.close.complete/Store.close后每轮仍增10个。上述观察均没有真实profile、网络或健康正文。

root将此全量已复现的产品错误退回既有authority/service生命周期内最小修复，owned仅 `host_authority.py` 与 `production_core_service.py`。提供幂等自有资源关闭，Service在正常关闭和各启动失败阶段收束其自己创建的三个authority；保留Core/session→Store→authority顺序、drain timeout仍在使用资源及调用方借用head边界。底层pin/dir失去owner引用时的安全资源兜底需先处理构造失败fd=None，防止double-close；不销钥、不写业务/批准/状态、不提高limit、不强制gc、不改冻结fixture或拆全量规避。

R2.6唯一design/contract/test及其余18冻结身份保持Evidence63，不重开架构、不新增测试家族。修复仍须正常/重复/失败及FD再利用的实际资源证据、适当既有回归、精确新提交的fresh完整执行、root复核、实施后双轴及闭票；当前没有宣称修复或新全量通过。真实部署与主人验收仍归128。
