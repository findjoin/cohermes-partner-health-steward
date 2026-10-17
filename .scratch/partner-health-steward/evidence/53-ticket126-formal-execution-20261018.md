# Ticket126 精确837正式执行证据

Reviewed source `837ac4dba1ca6024ca81e3bdbab5f2193344f878` / tree `c178e4e7fb64b7cca2d5ba2591f5aa817864ea7d`。真实干净detached source `/tmp/health-steward-126-r5-837ac4d-clean`，已普通推送分支的ancestor；root核对19417da..837 diffcheck、全部15冻结文件及当前主线同文件未变。产品41个Python文件与6752逐字相同；唯一冻结权威是[Evidence52](52-ticket126-refusal-and-confirm-time-refreeze-20261018.md)，不是后继130候选或预期红门。

## 新隔离运行环境

新根 `/opt/hsv-7i66_gv9/formal-837ac4d-126-final`，运行环境 `runtime`，独立verifier `/opt/t123v-56c639d1`。从同一clean commit完整87个tracked Python文件（含产品/tests/tools/__init__）形成archive，SHA256 `ab382ed0edf15679d1cacb571ad94f87ace5745add1c6fd59f17ef74e6ee80f2`。父产品从sealed安装包以-I/-B加载；真实root/Linux/Python3.11.15，真实importlib.util，实际AF_UNIX/peer/ACL及Publisher child来源断言未改。旧118 whitelist子进程的源码fixture与父产品明确区分，没有函数/产品成功补丁。

Hermes pinned Git `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，9240真实Git对象，core.autocrlf=true checkout；hermes_cli/plugins.py、platform_registry.py、gateway/run.py、weixin.py四个冻结指纹均验证。公共依赖复制1457文件，产品运行环境总7464文件；不复制实际profile、配置、凭据、聊天或健康正文。真实网络只在测试HTTP边界用合成替身，不执行JOJO推理或实际微信/联系人发送。

## Root执行门

| 原样命令分组 | 结果 | 用时 |
| --- | --- | --- |
| tests.test_ticket126_live_delivery | 5/5；0failure/error/skip | 28.993s |
| tests.test_ticket131_nondiagnostic_budget | 4/4；0failure/error/skip | 1.173s |
| tests.test_ticket124_live_entry | 4/4；0failure/error/skip | 4.500s |
| tests完整discover | 794/794；0failure/error/skip | 217.721s |
| root独立124/125/129/131/126专项 | 23/23；0failure/error/skip | 36.139s |
| 标准compileall（产品/tests/tools） | PASS，87pyc，cache在运行闭包外 | 完成 |

正式runner `/tmp/dmit-connection-audit/formal-837ac4d-126-final-full.sh`；root独立复核/标准编译/证据收集依次使用同prefix的`-root-postphase.sh`。前者日志 `-full-results.log`，后者 `-root-postphase.log`；结构化证据 `-execution-evidence.json`，root源码独立校验 `/tmp/ticket126-root-final-source-identity.json`。全部运行在新正式快照，不把R5 provisional5/5或历史失败改写成当前正式结果。

## 完整性

full后和root独立复核/标准编译后，source87、冻结15、runtime7464文件全部逐字不变。memory compile87及标准compileall87均通过。闭包始终 `sha256:93fe8f4591fd2b058a8f29320032ffe512d27e2e354507648bd1fc8730e9105b`。三件套仍为设计 `4a6ec81c94edab252936815cf0fc98925def3d0f`、合同 `f824e8c2d2b00586c592edc1533ca5a03342813d`、测试 `a4d9b67366f3b0e52528f3c9f43562a6e50c80c7`；其余12项与已闭124/125/129/131权威一致。

上述结果是精确837的实现证据，不是当前后来650/130候选的全量通过，也不是真实部署/初始化/G10/G11或主人可用性验收。联系人仅合成当前批准；accepted只证明接口接受，不补写delivered/read。首轮Spec PASS、Standards原P2及R6返冻结由Evidence54记录，最终修复执行及实施后结论另记；未通过前不闭票；真实模型/微信/部署归128，受控NL/实际主人操作/导出附件归130，full医学许可/审核仍归127。
