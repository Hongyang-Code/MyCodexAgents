# 决策价值评估入口

优化目标是风险与资金约束下、扣除适用费用后的决策价值，方向命中率只是诊断项。不能把方向卡直接当买入指令，也不能把CLI通过、少量命中或优于亏损基线称盈利。当前入口复用backtest.EventSimulator，未新建会计系统；本轮仅支持一个显式合成候选，无真实资金、市场搜索、LLM服务或自动交易。

## 立即运行的合成示例

在仓库根目录运行，output须是不存在的私有目录：

```bash
PYTHONPATH=FundPilot python -m fundpilot.decision_value --input FundPilot/examples/decision-value.synthetic.json --output /tmp/fundpilot-decision-value-demo
```

样例完全合成，producer=synthetic_fixture，不冒充真实LLM。初始1000、买费1%、卖费2%只是固定测试参数，不是渠道报价。候选显式买400、后卖100份；现金基线零收益，买持在同一首机会按相同风险上限买入。共同资产、窗口、机会价格、确认到账规则、估值记录和费用。末期不强平，不选择性扣假定清算费。

样例结果：候选账面终值约974.24，现金1000，买持约891.09。候选优于买持但亏损且未超过现金，改善标志为false，保留稳定版。这里只说明程序能保留反例；不推断市场策略优劣。

## 输入与决策模板

完整JSON schema以examples/decision-value.synthetic.json为可执行样例。mode必须synthetic，synthetic_rules_reviewed=true仅表示已审阅合成规则；不得将真实未知规则改名合成以声称实际收益。producer可为synthetic_fixture或actual_llm_on_synthetic_data，后者须由外部真实LLM在看评分前产出，并保存原文和真实冻结证据。程序不生成LLM判断。

顶层提供initial_cash、instrument、frozen_at、start/end、buy_rate/sell_rate、no_distributions_or_splits、evidence_refs及missing_evidence。risk固定max_exposure≤1、max_drawdown、max_cash_fees、no_leverage=true。冻结必须在窗口之前，输入原字节另行私有存档；本地文件时间声明不能证明真实事前冻结。

opportunities逐项给id、申请at、未来price、determined_at/published_at/confirmed_at/received_at。它们是共同合成执行环境，LLM决策阶段不得读取未来价格；账本仅在确认事件处理价格。marks为共同估值时刻at/nav，必须包含期末。没有证据不猜实际基金确认/到账或交易日。

decisions最多9条、同机会最多一条，必须显式给opportunity及action=buy/sell/hold，交易时给quantity（买入为含费现金，卖出为份额）；保留reason、no_action_counterfactual、cost_coverage_evidence、evidence_cutoff。所有信息截点不得晚于本批冻结时刻。

买入另需expected_gain_bps，为LLM可反驳的预期判断而非校准概率；unknown不能买入。程序仅比较其是否超过固定买卖费率和的保守粗门槛，不核实文字证据真实性，不能把自报预期当已证明收益。真实未来研究还须独立核对费用覆盖、不操作反事实、申赎限制及风险适用性。无需用户现在提供真实资产；个性风险未确认，只做合成约束测试。

## 指标与晋级

输出results.json及输入/结果哈希manifest.json，目录0700、文件0600。三种策略都输出净值路径变化、扣显式费用后的账面变化、现金费用、成交额/换手、共同估值点最大回撤、暴露、现金/冻结/应收/占用和未确认订单。净值已计入的管理等费用不重复扣。账面终值不等于可支取现金；估值点间风险未测，最大回撤不能声称连续路径上界。

候选只有同时优于现金和买持、并通过预先固定的回撤/暴露/费用门槛时，synthetic_value_improvement_and_risk_pass才为true。此布尔值仅是合成验收信息；promotion始终retain_stable_pending_unseen_validation。失败、不改善或证据不足均保留稳定版与反例，不自动更换配置，不遍历成本参数到有利值。

后续净收益能力改进须一次一候选，在冻结同本金/同机会/同费用的比较协议后，用未来未见样本验证，同时审查预设回撤、暴露、成本门槛、非重叠样本和不确定性。已见旧窗只能复盘，不能称OOS；过程改进和方向准确性不能代替净收益证据。跨运行预算沿用controlled-iteration，不因新CLI重置。

## 未支持范围

本入口拒绝非synthetic模式，不宣称已经支持真实基金决策收益评估或一般条件市场情景。真实总回报/分红、渠道费率、批次赎回费、开放日历、确认到账和个人风险证据未齐；这些缺口随结果保留。已有EventSimulator可处理经核实分红事件，但本小入口不另造该适配，含分红/拆分场景拒绝。现有原始NAV方向卡、历史90情景和前瞻9卡保持原样。
