# Ticket131 正式隔离执行证据

## 精确产品与来源

产品、完整verifier与发布构建source均来自已推送的 `1fd554f3543cc16be98759a54e5a470c042c28fc`，tree `50e8d285e59d520fb896b6a7d451ad65b175acf9`。独立干净detached Git checkout `/tmp/health-steward-131-1fd554f-clean`；没有从并行126编辑树采样。此历史checkpoint包含旧785加131新增4个门，共789；126随后添加的5门尚未纳入该commit，本证据不声称126或当前794全量通过。126完成后须另建当前精确正式快照全量回归。

新建DMIT隔离root `/opt/hsv-7i66_gv9/formal-1fd554f-131`，verifier `/opt/t123v-389131ab`，runtime为该root的 `runtime`。root/Python3.11.15，`-I -B`；父进程产品从封印runtime导入，测试namespace只指向同commit verifier；旧118白名单child fixture与真实Publisher子进程边界如实区分。84个Python source包含所有 `__init__.py`。真实pinned Hermes commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 由9240个实际Git对象及四个冻结源码hash核对，不使用当前全局dirty checkout。

## 执行门

- 原样131冻结四门：4/4，1.112s，0failure/error/skip。
- 原124入口四门：4/4，4.499s，0failure/error/skip。
- 同一精确commit完整discover：789/789，205.731s，0failure/error/skip。
- 标准compileall：84个pyc，cache置于封印runtime外；84个source不变。
- 旧124/125/129九个冻结blob与131三个冻结blob共12个，执行前后精确相同。131三件套权威见Evidence46，不修改旧门。
- 7462个runtime文件执行前后不变，完整封印摘要 `sha256:6ae3dcf9f4f043b80c4ef0e9d5950a441ab9ed615b38ee7c82ce47b4835ed989`。
- root独立重跑全部18个组件门（旧14加131四门）：18/18，7.371s，0failure/error/skip，12个冻结blob及封印闭包再次不变。
- root另在精确干净checkout重跑131四门：4/4，2.252s；核对精确commit/tree、三冻结blob、clean状态、已推送分支包含该commit及 `git diff 19417da 1fd554f --check`。

## 可定位命令与记录

构建器 `/tmp/dmit-connection-audit/build_formal_snapshot.py` 对精确干净checkout生成 `formal-1fd554f-131-prepare.sh`。使用既有 `dmit_isolated.py` 依次执行同tag的 `full.sh`、`postcheck.sh`；root独立执行 `component-recheck.sh`。它们只构造新隔离设施，不修改default/partner profile或已有sealed runtime。

- `/tmp/dmit-connection-audit/formal-1fd554f-131-full-results.log`
- `/tmp/dmit-connection-audit/formal-1fd554f-131-postcheck.log`
- `/tmp/dmit-connection-audit/root131-formal-component-recheck.log`
- `/tmp/dmit-connection-audit/formal-1fd554f-131-{source-manifest,frozen-blobs,script-manifest}.json`
- `/tmp/ticket131-root-clean1fd-component-check.log`
- `/tmp/ticket131-root-clean1fd-identity.json`

所有模型、来源、接收方与网络边界均为合成／离线替身；真实Core、同一effect journal、原公开诊断源门和原型化业务提交实际执行。没有读取真实凭据、配置或健康资料，没有模型推理、微信／联系人发送、服务切换、部署、主人初始化或产品验收。本证据仅为131执行门；两轴实施后审查与root元数据闭票另行记录。
