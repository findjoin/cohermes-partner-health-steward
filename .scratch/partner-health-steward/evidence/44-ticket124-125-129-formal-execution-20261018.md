# Ticket124/125/129 实施执行门

已测干净 source commit `bb239ec9e5a80766ebed454e00bf67ed1c5e8139`；产品 commit `6c49739d8a277afaa1adc52137d88290153fdc59`。随后 metadata-only `b761986c7e8c7e4ecd60cac39c3521ccabe2d25d` 的全部83个Python文件与已测source逐字相同，工作树干净，已普通push。不得把不同commit身份混写为同一。

## 环境与命令

DMIT euid0 / Python3.11.15；只用隔离 root `/opt/hsv-7i66_gv9/formal-bb239ec` 和新完整verifier `/opt/t123v-7b86f86e`。复用未改的 sealed `/opt/hsv-7i66_gv9/formal-6c49739/runtime`，39个产品文件逐字匹配；真实pinned Git commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`。未访问真实配置、健康正文、模型、微信或partner服务。

以现存SSH只读key内存加载 helper执行 `formal-bb239ec-full.sh`：runtime `python3 -I -B`，只为tests注入独立namespace，产品必须来自sealed runtime；124child必须来自真实Publisher发布包，123 runtime来源断言及118原白名单child保留。先124四门，全部通过才unittest discover全部test*.py。120 Linux门用原Git tree/blob对象和显式隔离cwd；未改旧门或产品函数。

## 结果

- Ticket124：4/4 PASS，4.276秒，0failure/error/skip。
- full discover：785/785 PASS，191.738秒，0failure/error/skip，含125四门、129六门及旧118/119/120/121/122/123。
- root随后独立运行同环境124/125/129：14/14 PASS，6.061秒，0failure/error/skip；闭包再次不变。
- 同Python3.11标准 `compileall` 对runtime产品、完整verifier tests/tools：83个pyc均写新source外部cache，PASS；本机外部cache compileall亦PASS。
- 83个source文件及7462个runtime文件逐项后验未变；closure `sha256:97b1acffc27855313a9a91eed1682b0b3bc32b9f5d02fe07cfda9cdc15af0ca4`。
- 最新124/125/129共9个冻结blob精确匹配各Ticket authority；`git diff 19417da HEAD --check` 和工作树diffcheck PASS，工作树无修改或未跟踪文件。

## 可定位材料

- `/tmp/dmit-connection-audit/formal-bb239ec-full.sh` SHA256 `9f5d2bb69880ef49507b5117b035a3613feb31597777cac525291d28a5aa8fdc`。

- `/tmp/dmit-connection-audit/formal-bb239ec-full-results.log` SHA256 `f9c87789de59cf7e927ae39fa49ac4de8c61f03008e8e9123841e4fe60745d66`。

- `/tmp/dmit-connection-audit/formal-bb239ec-postcheck.sh` SHA256 `264ff8f6b0467a2c03d063bb8f0ba3eb0bf56ef467703d1ed1a7d60d5846b068`。

- `/tmp/dmit-connection-audit/formal-bb239ec-postcheck.log` SHA256 `53471ac780f99e351603f053c69d887469a43faefa4b1675791b1980fa67dc35`。

- `/tmp/dmit-connection-audit/root-final-component-recheck.sh` SHA256 `33b25e2533e75fcfb8e6c75d27d3d7ead6c6ec4238ab1a0da483fa4cca25313c`。

- `/tmp/dmit-connection-audit/root-final-component-recheck.log` SHA256 `93fe455d45f271627ce877dcf3f51455ba9b9b4bc904fe5c5d801e928fa6cdd9`。

- `/tmp/dmit-connection-audit/formal-bb239ec-source-manifest.json` SHA256 `1ffe0dc1614a7cc7f5d7ea9ac62128750487984a54a96f40d325427eeac6dd45`。

- `/tmp/dmit-connection-audit/formal-bb239ec-frozen-blobs.json` SHA256 `f7961c5aaae1e829a19f38ead532609a9e8ea8193cf8a6b78da832bb5cdd2a8d`。


远端完整结果在同隔离source的 `logs/formal-{124,full-discover}.log`、`formal-results.json`、`closure-after-tests.json`、`final-postcheck.json`；source archive SHA256 `3e45b1b6d0afc6b88e0eabe8d324c021ed8ef1ef2b95c1aac7448f25c0a10c8b`。

这些仅证明离线组件与集成回归；不代表126真实Transport、130生产NL、131ND预算、128上线或主人验收已完成。执行门全绿后才启动同一最终commit/tree有界Spec/Standards实施后审查。
