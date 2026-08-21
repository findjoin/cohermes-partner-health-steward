# 医疗安全规则来源

核验日期：2026-08-04。

本文件只记录安全分流规则的来源，不作为诊断知识库。插件采用保守的高置信关键词组合；它不能覆盖全部急症，也不能替代临床评估。

| 规则 | 物理含义 | 权威来源 |
|---|---|---|
| 胸部危险信号 | 胸痛/胸闷伴冷汗、呼吸困难、晕厥、放射痛或活动加重时提示立即急救/急诊 | 国家卫生健康委 2024-11-21 新闻发布会：https://www.nhc.gov.cn/xcs/c100122/202411/81a60171b43d43ff98cc6110d65a4136.shtml ；WHO 心血管疾病事实页：https://www.who.int/news-room/fact-sheets/detail/cardiovascular-diseases-(cvds) |
| 卒中危险信号 | 突发面部下垂、单侧无力或言语异常时按急症处理 | WHO Stroke：https://www.who.int/news-room/fact-sheets/detail/stroke ；无锡市卫生健康委 FAST 说明：https://wjw.wuxi.gov.cn/doc/2023/10/30/4095102.shtml |
| 严重过敏 | 过敏背景下出现喉头/舌部肿胀、喘息、呼吸困难、紫绀或晕厥时按急症处理 | 国家卫生健康委 WS/T 810—2022：https://www.nhc.gov.cn/fzs/c100048/202212/7dc002f6d6734cb18cff1516e309157a/files/1733125352022_70121.pdf |
| 心理危机 | 高自伤/自杀风险需要快速危机干预；中国统一心理援助热线为 12356 | 国家卫生健康委 12356 通知：https://www.nhc.gov.cn/yzygj/c100068/202412/49a1a65386cd4be582d4702fd0926ee8.shtml ；心理援助热线技术指南：https://www.nhc.gov.cn/jkj/c100063/202101/74ada48ed1cd4e7f93c39db57cff0b4b.shtml |

## 已知边界

- 文本规则会误报或漏报，尤其是语音转写错误、隐晦表达、方言、图片和非中文输入。
- Hermes 插件异常默认 fail-open；本发布用启动前注册探针处理可检测的装载异常，但未知运行期语义仍不是医疗器械级硬闸门。
- 高置信 Telegram 文本会在 Gateway runtime wrapper 阶段直接回复并跳过 LLM；语音需先完成 STT，仍走 turn 级防御。
- 规则扩展必须先增加反例和注入测试，不允许模型自行发布。
