# FundPilot

可审计的个人场外基金研究工程。当前为 **研究基础版，未正式部署**。它包含可运行的账本、研究和安全原语，尚未形成自动完整市场研究服务或经过验证的投资策略。没有真实下单能力，不保证收益。

研究主体是大模型结合检索证据、新闻/政策/市场与基金暴露形成条件性预测和复盘；固定数值规则用于基线比较，程序承担校验、会计费用和评分。当前已实现的规则实验与工程测试不代表 LLM Agent 效果验证，尚无成熟结果支撑 LLM 预测有效性；真实 LLM 研究记录与 mock 工程测试分账。不要求用户训练模型，也不因本定义新增模型服务、密钥或付费。

## 快速试运行

基础代码需要 Python 3.11+，仅使用标准库。固定TradingAgents桥接另需隔离依赖；当前公开版本约束和实跑环境为Linux/Python 3.12，安装及完整手工流程见[上游适配](upstream-adaptation.md#干净-linux-安装)。基础3.11验证不等于上游依赖已在3.11验证。以下命令在仓库根目录执行：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -v
PYTHONPATH=FundPilot python -m fundpilot smoke --output /tmp/fundpilot-new-test
PYTHONPATH=FundPilot python -m fundpilot deployment-status
```

smoke 路径必须不存在；全部资产和日历均为合成样例。输出测试账本、冻结预测、静默判定、SHA-256 快照及本地恢复回执。它不联网、不通知、不下单、不初始化真实账户。

## 文件与能力

- AGENTS.md / workflow.md：完整目标流程与边界。
- research-collaboration.md：证据研究、LLM预测、独立评估的最小接口与私有复盘闭环；角色定义不表示生产服务已部署。
- controlled-iteration.md / iteration_control.py / durable_budget.py：受控研究校验及桥接入口的SQLite原子操作预留；未知旧用量拒绝新动作，不计量平台token或提供跨机器锁。
- architecture.md：TradingAgents、Qlib、FinRobot、FinRL 一手资料调研。
- fundpilot/ledger.py、portfolio.py：追加事件与持仓投影。
- information-policy.md / information.py：按用途的信息需求、事件时间与版本、预期差可比性和缺证据弃权；本地检查，尚未接入生产编排。
- market.py：经过核查的行情导入、时间与来源检查。
- research.py：基线预测、交易日结算、点时过滤、经验审查。
- backtest.py：显式历史交易事件重放内核，不自动推导真实规则。
- risk.py：保守建议闸门；上游证明尚需真实核实，不是完整风险预测模型。
- notifications.py：持久通知意向、去重、发送状态；不直接发消息。
- runner.py：输入驱动的每日编排、失败/部分状态、幂等恢复与成功发布回执；不自带生产资料、审校或存储适配器。
- storage.py：私有快照校验/安全恢复；云端上传及版本条件替换由已授权工具执行。
- llm-loop.md / fundpilot/llm_loop.py：真实LLM卡先冻结、再用已核验NAV离线评分的小型CLI；不生成LLM判断，不证明投资效果。
- decision-value.md / fundpilot/decision_value.py：复用会计内核的显式合成决策净价值比较CLI，含现金与买持基线；不支持真实执行收益声明。
- conditional-value.md / fundpilot/conditional_value.py：独立只读的真实历史NAV与显式LLM分配条件估值，区分期末NAV、假设清算和现金；不放宽原事件门禁。
- VALIDATION.md：实际测试、真实数据范围和未验收项。
- history-batch.md：本地证据驱动的回顾性研究CLI、预测/72个固定策略情景及私有审计包；合成验证不代表真实半年研究已完成。

- [固定上游基金研究适配](upstream-adaptation.md)：实际TradingAgents节点、当前LLM桥接与SQLite检查点；有限历史诊断，未通过投资验收。

## 时间与上线

每日计划时间为北京时间 21:30（Asia/Shanghai），例配置保留 production_enabled=false。此时间是启动时间，不保证每只基金净值已公布。周末也检查旧预测、状态和必要风险，不生成虚构交易日行情。周/月复盘默认只保存；具体日程待部署阶段确认。

先审核独立分支 PR，再由用户批准正式部署。上线还需确认真实持仓、投资期限、可承受亏损和限制，核实相关基金费用/申赎/分红规则，接通实际资料获取及审校，验证云端独立执行恢复和平台静默。未过这些闸门不能创建正式运行任务或声称已上线。不要把已存在的 NewsChaser/ResearchHotspotFollow 自动任务改名复用。

## 隐私

真实资料不放 Git。采用 checkout 外私有 Library 快照和版本化 HEAD；临时工作目录不是持久存储。FundPilot/.gitignore 仅作补充防护，提交前仍须逐文件审计。不能把真实资产替换进合成测试后提交。

首次使用可提供截图；自动识别结果要保留置信度、原始证据和待核对项。当前代码接收核对后的结构化字段，未宣称具备已验收的 OCR。风险参数和资产未知时只做非个性化研究。


## 当前历史研发入口

按AGENTS.md的当前阶段，只开展历史研究与模拟，现实指导和前瞻运行禁用。真实开源节点桥接及命令见[upstream-adaptation.md](upstream-adaptation.md)，12个月固定门槛与私有CLI见[historical-acceptance.md](historical-acceptance.md)，工程实跑见[CLOUD-VERIFICATION.md](CLOUD-VERIFICATION.md)。

原有短期数值评分不替代年度资金验收。资格声明必须回查证据，缺日历、份额/渠道规则、完整费用、CPI或独立样本时保持pending。项目执行状态与研究档案只在私有存储，不从README推定服务正在运行。


## 历史证据到当前 LLM 的最小路径

1. 按[干净Linux安装与合成验收](upstream-adaptation.md#干净-linux-安装)安装固定上游，先用synthetic_fixture验证传输，不能标成真实模型。
2. 在checkout外准备私有历史公开证据和经审阅的预算种子；真实unknown保留null，失败及旧候选原记录不清零。用`budget-init`初始化共享账本，再用`start`冻结输入、生成第一份请求。
3. 宿主读取每份request中的完整prompt，交给当前已授权LLM实际生成；记录原文、真实生成时间和模型身份，以`actual_current_llm`保存响应，再用新进程`resume`。共bull、bear、manager三份；脚本不会自动登录、调用API或替用户完成模型生成。
4. 查看最终`result.json`及同目录的输入/请求/响应/receipt/graph.sqlite；按[冻结、恢复和验收出口](upstream-adaptation.md#冻结恢复和验收出口)保存并校验私有检查点。条件判断尚须来源/估值日历映射，不能直接拿图输出冒充已合格评分卡。
5. 12个月资格与固定标准由[历史验收工具](historical-acceptance.md)判定；材料不足pending。合成通过、三份响应或短窗回测不证明投资达标，不启现实指导、前瞻或交易。
