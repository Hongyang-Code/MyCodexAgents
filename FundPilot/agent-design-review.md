# 外部 Agent 设计对照与本次取舍

核查日期：2026-10-23。来源为官方仓库、提交和方法文档；主分支链接可变化，未声称固定其 HEAD。仅采纳工程思想，没有复制外部实现、安装框架或复现宣传收益。项目内原有架构研究见 architecture.md。

| 参考 | 采纳、已有或暂不采用 | FundPilot 落点与边界 |
| --- | --- | --- |
| [FinRobot V2 步骤定义](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/finrobot/engine/pipelines/step.py)、[流水线](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/finrobot/engine/pipelines/runner.py)、[权益研究](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/finrobot/engine/pipelines/equity_research.py) | 采纳显式步骤依赖和失败传播的设计方向；不搬入股票估值工作流 | 本项目自行实现 invalidate_derived，将拒绝的费用传播到依赖的净收益/排名/摘要；尚未接入生产编排，调用者须完整声明依赖 |
| [TradingAgents 方向性修复](https://github.com/TauricResearch/TradingAgents/commit/a4acd8a17450e1d1baf2611da78bf156d15332f9) | 采纳不强迫方向的原则 | 证据不足为 abstain，和有证据的不操作分开；不以角色投票形成概率 |
| [TradingAgents vintage 修复](https://github.com/TauricResearch/TradingAgents/commit/8b7ece8a3e04550ea84e99210eea070d65918c65)、[未成熟决策修复](https://github.com/TauricResearch/TradingAgents/commit/30d42abd5d7132a74307b5f961cfb9715b319346) | 原有可得时间过滤、pending 结算已有；新增事件版本契约补缺口 | 不改 NavRecord、回顾性隔离层和冻结90情景；不把外部修复测试当本项目已通过 |
| [TradingAgents 配置](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/default_config.py)、[新闻分析](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/analysts/news_analyst.py) | 按用途挑选信息、限制运行预算；暂不增加常驻多角色辩论 | 信息按 P0/P1/P2 决策用途组织，缺预期/暴露不靠模型补造，不新增付费源、SDK或密钥 |
| [Anthropic 简单可组合工作流](https://www.anthropic.com/research/building-effective-agents) | 采纳小函数和明确停止条件；不为形式引入编排框架 | 标准库证据检查与重试决策函数，确定性校验失败不循环 |
| [OpenAI 工作流评估](https://developers.openai.com/api/docs/guides/agent-evals)、[使用边界与批准](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals) | 采用验收与权限边界作为检查方向；现有独立分支/Draft/部署批准规则保留 | 本次只本地合成回归与手动结构检查，不声称已启用外部评估服务或生产防护 |

收益有效性、来源真实性、账户适用费率和实时暴露不能由这些参考证明。采纳标准是能否减少具体失效路径，而非项目热度或角色数量。资金、风险、费用、确认到账、私有存储和授权边界以本项目规则为准。
