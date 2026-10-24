# 上游原生流程与完整组合对照协议

版本 wiring-v1；当前仅冻结离线接线合约，真实效果对照/专项调用与融合候选授权待核实，不因本文件允许执行。稳定定义按提交冻结，旧七天历史与全部失败原样保留。工程跑通不等于模型效果或投资达标。

## 单位与冻结输入

比较单位是完整组合，不设三只资产总上限；单批新增精读/验证目标最多三只不截断全部已确认持仓。共用原有持有批次、可用现金、申购冻结、赎回冻结和应收，未知身份/权重/穿透信息保留unknown及覆盖日期。10/20/50合成资产只验证容量，不模拟真实账户收益。共享市场/政策证据及分层暴露摘要可减少逐基金重复模型调用，不把逐标的评级相加称全局最优。

真实运行前私有冻结：组合全清单/覆盖与日期、代码/份额/渠道、原持有批次、基金/底层暴露、现金利息证据、所有来源原字节SHA256、公布/版本/抓取/已知时间、历史窗口、模型可知快照或unknown、稳定代码及上游SHA、各臂配置、每次提示与工具边界、失败规则和唯一评价。已有已看历史一律reused_development/non-OOS，保留参数记忆污染；不换窗、删失败或重采样找赢家。公开仓库只放此通用合约和合成夹具，真实材料与授权原话只私有保存。

## 原生流程与可执行路径

| 臂 | 真实复用和边界 | 离线已观察调用数 |
| --- | --- | --- |
| FundPilot冻结稳定图 | 原固定TradingAgents bull/bear/research_manager三节点、状态、interrupt/SQLite；按单目标API，完整组合输入与逐基金输出绑定仍需明确冻结 | 原图3份响应；不是已验证完整组合优化 |
| TradingAgents固定GraphSetup | 原四分析师并行、bull/bear/manager、Trader、三风险讨论者和Portfolio Manager，原路由及PortfolioContext/恢复指纹；未运行产品包装器的记忆/结算/认证 | 无工具调用、每节点一次：12；只选一个原生分析师仍为9。工具/格式/重试会增加 |
| FinRobot V2 equity_research | 原create_sub_agents五角色、8步Pipeline、critical/StructuredValidator/deterministic/derived_keys；不自写角色提示替代 | 严格基金缓存实际在data_collection触发财务契约缺口，已运行1次TestModel后中止；成功总数unknown |
| FinRobot V2 IC memo | 原5步Pipeline，原DCF/LBO确定性核心及门禁保留 | 无重试名义4个模型步骤；实际基金缓存在financial_analysis前提中止，观察1次TestModel，不能当4次成功 |

TradingAgents上述计数来自一次篮子载体的合成接线，不证明原按目标ticker的工具已能处理N维基金配置。若逐资产独立重跑，成本会成倍增加，不能偷偷扩额。FinRobot失败是当前原生股票财务前提与受控基金NAV缓存不匹配的执行证据，不推断整个项目永远不能适配基金；不可伪造revenue/EBITDA或以固定规则代替其LLM后宣称已测。

实际入口（各依赖独立venv，固定源码在checkout外可读，输出父目录0700且文件不存在）：

```bash
PYTHONPATH=FundPilot /private/ta-venv/bin/python -m fundpilot.comparison_wiring \
  --arm tradingagents-native --upstream /private/tradingagents \
  --synthetic-fixture --output /private/research/new-ta-wiring.json
PYTHONPATH=FundPilot PYDANTIC_AI_NO_BANNER=1 /private/fr-venv/bin/python -m fundpilot.comparison_wiring \
  --arm finrobot-native --upstream /private/finrobot \
  --synthetic-fixture --output /private/research/new-fr-wiring.json
```

另支持finrobot-ic-native。CLI只暴露synthetic_fixture，封闭缓存和模型替身边界明确替换，实际导入原工厂/图/管线/检验器；不发SDK推理或市场请求。输出有提示/消息哈希、原生阶段、失败、网络尝试、actual_llm_requests=0、effect_comparison_performed=false。股票工具不作为基金真实证据；现有FinRobot锁定安装快照与TradingAgents Linux约束分别使用，均固定Apache 2.0源码，不混装、不读取密钥/桌面账户。

## 总预算可行性与待审选择

拟议所有方案合计最多12模型请求、12主要来源尝试；失败、审校和允许的重试共用总额，不是每基金或每臂12。尚未把拟议值记成已批准新预算；旧unknown不改0。全三臂默认原生流程仅FundPilot3+TradingAgents12即超总额，FinRobot还未过基金数据门槛，不能称已公平运行。

待审的最小两臂方案是FundPilot3与TradingAgents原生单分析师配置9（总12），但这是明确不等调用数的流程成本对照；不得伪称严格等调用资源的结构因果优势。须先冻结完整组合载体/工具适配和相同模型能力，且用户接受该资源差异。另一候选FinRobot IC名义4调用有望与稳定3装入总额，但当前基金财务前提阻塞，未列为可执行真实效果臂。不能删除上游风险/检验节点来挤预算又称原生完整流程，也不能给FundPilot更多采样后宣称结构好。

若要求严格等调用上限且完整原生流程，当前总额不足；保持pending，列未测臂及准确原因，向主任务提交具体可审方案，不自行扩额或换run_id。真实模型能力、原生认证或宿主桥接尚须明确；FinRobot原生SIWC支持本批未核实，不推定必须买API或自行取令牌。

## 唯一固定评价与失败

所有流程先冻结每基金/组合可检验判断（含来源、反证、失效条件、未知/弃权）和显式配置，再读取相同后续数据统一评价。判断方向、概率与资金配置分开，弃权不算命中或零损失。模型精确版本未知如实记录；工具/输入/输出/时间、失败与超限全部私有留存。阶段资格缺失保留pending；没有客观量纲的事实/反向解释/可证伪性只列证据，不编综合分。

同起始组合与同窗口：现金零收益基线、买持、trend20、相同初始权重被动组合、同风险预算/暴露对照。分开基金投资比例、可用/闲置现金、冻结资金/应收及权益/利率/汇率等底层风险；多只基金也可能重叠。现金零收益是必要基线，不是合格投资方案；有现金利息或低风险资产收益须真实来源，不默认零风险。未知预期收益不填0。

统一报告条件/已核实净成本总组合回报、与同窗CPI之差、单位化回撤、暴露、换手、现金拖累、资金占用、弃权率和机会成本。未知价NAV、申请/确认/到账、节假日/QDII、逐批自然日A/C费率、限购暂停、分红拆分与NAV内费用处理一致；证据不完整只作条件模拟，不能称可执行收益。低暴露不对满仓基准后称结构优越，不预设80%现金，也不强迫80%/90%最低仓位；高投入和既定风险门槛冲突就判未达标，不无限调参。

只进行一次预先登记比较；相同风险/权重对照用同冻结路径归因，不追加择优试验。结构融合须先有外部真实优胜证据，再提出单机制候选、冻结一次评价且获得专项授权；旧七天占用不删除。研究/工程改善与投资资格分别判断，单窗历史胜出不够替换投资稳定版。12个月不亏95%、严格超全国CPI90%的单侧95%下限和单位化最大回撤5%不改，项目未完成、无现实指导/前瞻/交易。

## 静态参考与未实现

主任务提供的Qlib EnhancedIndexingOptimizer审阅指出失败回退可能移除换手约束，输出还截断归一化；FinRL StockPortfolioEnv的成本字段不证明step已真实扣费，且无场外确认到账。RD-Agent研究/实现/反馈循环仍未安装执行。本批未实跑这些项目，不声称已复用；不新增RL训练或收费服务。后续若复用优化器，必须按原始全部硬约束后验严格校验，不自动放宽换手/费用/冻结/风险限制，跟踪误差不是最大回撤保证。
