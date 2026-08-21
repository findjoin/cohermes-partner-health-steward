# 唯一 DMIT 主机采用两阶段受控生产 canary

> 状态：受控同机 canary 原则继续有效；ADR 0014 已取代其中 sidecar、独立账户和 sidecar-first 切换拓扑，具体部署门槛待新规格重写。

用户只有一台承载现有 partner Hermes 的 DMIT Linux，无法先在独立非生产主机运行真实 Hermes 薄集成。用户于 2026-08-09 明确接受 partner 可能短暂中断，并授权关键失败时立即回滚。因此运行时验收改为同机两阶段受控生产 canary，但不得把它描述成非生产验收。

阶段 A 不停止旧 `hermes-gateway-partner.service`：记录实时基线和回滚点，完成备份、全量离线测试、不可变 release 安装、账户/文件/systemd 静态隔离与固定 Job 配置检查。任一门槛失败即 no-go，不进入服务切换。

阶段 B 只在实施时授权仍有效且阶段 A 全部通过后执行：停止旧 partner，按 sidecar-first 顺序启动 `health-sidecar.service` 与受限账户下的新 partner，验证私有 socket、无 TCP、文件拒绝、两个固定 Job、微信链路和无内容审计。任一关键检查失败，停止新服务并恢复旧 partner。default Hermes、其他 profile、x-ui/xray、防火墙、网络代理和无关服务始终不在授权范围内。

由于真实 04:00 日检不能用手工调用替代，切换后的即时 smoke 与下一次 04:00 后的完整 Job smoke 分开报告；在后者通过前不得宣称最终验收完成或长期稳定。
