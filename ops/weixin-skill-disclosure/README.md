# default 微信 Skill 调用披露补丁

## 目标与范围

只为 default Hermes 的微信最终回复增加确定性 Skill 披露：

```text
🩺 本轮使用：健康管家（health-steward）
```

- 只认本轮真实 `skill_view` 的成功 JSON 结果。
- 只显示配置 allowlist 中的规范技能名与展示名。
- 不读取、不输出工具参数、Skill 正文、路径或健康内容。
- 未调用、失败、空回复、故意静默、执行失败或被中断时不显示。
- 只对 `weixin` 生效；配置默认关闭，partner 未配置即保持关闭。
- 在聊天记录持久化与标题生成之后追加，因此不进入 Hermes 对话历史或健康画像。
- 追加点位于 `TurnRunner` 返回前，覆盖普通回复和 `/queue` 第一条直接发送路径。

## 本地资产

- `run.patch`：针对服务器当前 `/usr/local/lib/hermes-agent/gateway/run.py` 的三处最小补丁。
- `run.py.before`：生成补丁时下载的精确生产基线。
- `run.py.after`：仅应用本功能后的候选文件，用于语法检查和差异审计。
- 实现模块：`.research/hermes-agent-server-baseline/gateway/skill_disclosure.py`。
- 测试：`.research/hermes-agent-server-baseline/tests/gateway/test_skill_disclosure.py`。

生成补丁时的生产基线 SHA-256：

```text
d71b3581412cc8988bdffe485db222dfe7628cd3f2992c533f22333870689dac
```

## 已完成验证

- `skill_disclosure.py`、本地基线 `run.py`、精确生产候选 `run.py.after` 均通过 `py_compile`。
- 7 项确定性测试通过：成功、失败/坏 JSON/未授权名称、去重稳定顺序、非微信、配置关闭、发送与静默/失败/中断门控。
- 生产补丁只有三处：建立本轮 collector、挂接 `tool_complete_callback`、在本轮最终结果返回前追加 UI 元数据。

## 部署状态

v1 于 2026-08-05 05:03 CST 部署。用户在获知外部 IP 代码传输边界后明确回复“允许上传并部署”。终审随后发现 incomplete/error 门控和极端历史 fallback 两个边界；default 的 `enabled` 已立即改回 `false`，所以当前微信披露实际关闭，不能把 v1 写成可验收版本。

- 备份目录：`/root/.hermes/backups/default-weixin-skill-disclosure/20260805-explicit-upload-deploy/`，权限 `0700`；其中 `config.yaml.pre` 权限 `0600`。
- `run.py` 部署前哈希与锁定基线完全一致；`git apply --check --whitespace=error-all` 通过后才应用。
- 部署后 `run.py` SHA-256：`fbd23b9337cee0f3c2c249f63860a06ff16231f8dc0ad77ef7d32270970389a5`。
- 部署后 `skill_disclosure.py` SHA-256：`9847df952ac2cfb493cd3661b3103683fd876a440a618bbfc5df8ea690cc810d`。
- 生产 Python 语法检查、`git diff --check` 和 7 项规则测试均通过。
- v1 曾解析为 `enabled=true`、`health-steward=健康管家`；生产无外发烟雾测试得到精确尾注，且参数/正文中的秘密哨兵没有进入输出。终审后当前配置为 `enabled=false`，allowlist 保留。
- default Gateway reload 后 PID 从 `101224` 变为 `106711`，于 05:03:49 CST 恢复 `active/running`，`NRestarts=0`。
- partner Gateway 保持原 PID `100959`、原启动时间 03:47:30 CST、`NRestarts=0`；partner 配置 SHA-256 前后均为 `235081c54bec2ac35d16f5ce93e41531d671226c780b7efba33a47046f9b27b4`。
- default Telegram 与 partner 微信的 disclosure 均实测为关闭；x-ui、xray、Skill 文件和 cron 未修改。

本地加固版已完成并经第二次只读终审通过：新增 `partial`、`completed is false` 与 `error` 失败门控；TurnRunner 只返回 `skill_disclosure_line` 元数据，普通路径在全部 transcript writes 之后追加，`/queue` 只修改发送用局部副本；第 8 项“成功加载后 partial/error”反例通过。对应资产为 `run-hardening.patch` 和 `run.py.hardened`。

加固版尚未上传：第二次外部 IP 传输被安全审查要求重新取得针对“终审修正版三个文件”的明确授权。取得授权并完成部署后，才由用户在 default 微信发送健康正例和非健康反例做端到端验收。
