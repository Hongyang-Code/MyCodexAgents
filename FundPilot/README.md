# FundPilot

可审计的个人场外基金研究工程。当前为 **研究基础版，未正式部署**。它包含可运行的账本、研究和安全原语，尚未形成自动完整市场研究服务或经过验证的投资策略。没有真实下单能力，不保证收益。

## 快速试运行

需要 Python 3.11+；当前基础代码仅使用标准库。以下命令在仓库根目录执行：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -v
PYTHONPATH=FundPilot python -m fundpilot smoke --output /tmp/fundpilot-new-test
PYTHONPATH=FundPilot python -m fundpilot deployment-status
```

smoke 路径必须不存在；全部资产和日历均为合成样例。输出测试账本、冻结预测、静默判定、SHA-256 快照及本地恢复回执。它不联网、不通知、不下单、不初始化真实账户。

## 文件与能力

- AGENTS.md / workflow.md：完整目标流程与边界。
- architecture.md：TradingAgents、Qlib、FinRobot、FinRL 一手资料调研。
- fundpilot/ledger.py、portfolio.py：追加事件与持仓投影。
- market.py：经过核查的行情导入、时间与来源检查。
- research.py：基线预测、交易日结算、点时过滤、经验审查。
- backtest.py：显式历史交易事件重放内核，不自动推导真实规则。
- risk.py：保守建议闸门；上游证明尚需真实核实，不是完整风险预测模型。
- notifications.py：持久通知意向、去重、发送状态；不直接发消息。
- runner.py：输入驱动的每日编排、失败/部分状态、幂等恢复与成功发布回执；不自带生产资料、审校或存储适配器。
- storage.py：私有快照校验/安全恢复；云端上传及版本条件替换由已授权工具执行。
- VALIDATION.md：实际测试、真实数据范围和未验收项。

## 时间与上线

每日计划时间为北京时间 21:30（Asia/Shanghai），例配置保留 production_enabled=false。此时间是启动时间，不保证每只基金净值已公布。周末也检查旧预测、状态和必要风险，不生成虚构交易日行情。周/月复盘默认只保存；具体日程待部署阶段确认。

先审核独立分支 PR，再由用户批准正式部署。上线还需确认真实持仓、投资期限、可承受亏损和限制，核实相关基金费用/申赎/分红规则，接通实际资料获取及审校，验证云端独立执行恢复和平台静默。未过这些闸门不能创建正式运行任务或声称已上线。不要把已存在的 NewsChaser/ResearchHotspotFollow 自动任务改名复用。

## 隐私

真实资料不放 Git。采用 checkout 外私有 Library 快照和版本化 HEAD；临时工作目录不是持久存储。FundPilot/.gitignore 仅作补充防护，提交前仍须逐文件审计。不能把真实资产替换进合成测试后提交。

首次使用可提供截图；自动识别结果要保留置信度、原始证据和待核对项。当前代码接收核对后的结构化字段，未宣称具备已验收的 OCR。风险参数和资产未知时只做非个性化研究。
