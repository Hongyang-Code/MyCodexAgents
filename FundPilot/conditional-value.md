# 历史固定分配的条件估值

此独立只读入口接受外部LLM已冻结的显式资金分配与真实历史NAV，比较现金、同资金等权买持和LLM主方案。不生成方案、不把方向卡转订单、不调参。mode必须retrospective_conditional，拒绝其他模式；原decision_value的synthetic门禁及事件账本核验要求不变。

缺真实费率、分红、渠道或确认到账证据时，不能把假设标成verified=True传给实际事件内核。因此本入口只做固定份额条件估值，不输出真实成交/实际净收益或OOS结论。原始NAV不是总回报，条件分红/拆分假设可能影响分配和现金两端。已知分红/拆分事件冲突直接拒绝，未知仍明确记录。

## 可运行命令

所有真实输入输出放在仓库外。输出目录必须不存在：

```bash
PYTHONPATH=FundPilot python -m fundpilot.conditional_value \
  --protocol /private/protocol.json --protocol-sha256 <冻结协议原字节SHA256> \
  --decision /private/decision.json --nav /private/nav.csv \
  --sources /private/sources.json --output /private/conditional-result
```

先由真实LLM在独立上下文从固定信息包产出分配并私有冻结，另由评估者固定费用/窗口/来源及其哈希后运行。protocol.frozen_at是真实协议冻结时间，必须不早于decision.frozen_at，不倒填到历史。协议含所有输入原字节哈希；CLI先核对再计算。哈希不证明LLM未看过结果或管理员无法修改记录。历史包、参数记忆和更大项目已见结果仍使本研究非盲、非OOS。

## 输入 schema

**decision.json**：

- decision_kind=explicit_llm_allocation，producer=actual_llm；合成测试只能如实用synthetic_fixture。
- model_ref、prompt_version、真实frozen_at、带时区information_cutoff；entry_date/end_date必须与协议完全一致，不允许评分时改冻结持有窗口。
- rationale、no_action_counterfactual、cost_coverage_assessment，evidence_refs非空列表；保留原LLM判断与缺口，不伪造费用覆盖。
- initial_cash十进制字符串，与协议完全相同；allocations为每个完整基金/份额标识到“含买费投入金额”字符串的映射，零分配也必须列出；cash_amount为保留现金。三者严格守恒，不自动归一化。

该入口评估显式模拟分配，并不授予买入权限；未知预期收益或文字假设不授权真实操作，也不因条件结果自动晋级。真实LLM前瞻建议仍需原协议的风险与费用证据。

**protocol.json**：

- mode=retrospective_conditional；真实frozen_at；input_sha256对象含decision、nav、sources三份原文件SHA256。
- funds：1到3个完整基金/份额标识；initial_cash字符串。
- entry_date、end_date为YYYY-MM-DD；valuation_dates为包含首尾的严格递增共同估值日列表，至少两个；valuation_dates_evidence_ref指向所用日期覆盖证据。入口日须晚于截点原时区日期，不从weekday推断市场日历。
- risk：max_exposure（0到1，非零）、max_drawdown（0到1）、max_cash_fees（非负）均为字符串，no_leverage=true。等权基线以本金×max_exposure等分于全部funds，余款保留现金；三策略完全共用价格/费用/窗口。
- unknown_evidence对象：fees、distributions、confirmation、receipt、channel逐项写实际缺口或条件限制，不能为空。
- known_distribution_events、known_split_events：必须明确提供空列表，表示“没有已知冲突”，不表示已证明不存在；有已知事件则本小入口拒绝，不能删除事实来运行。
- assumptions：见下表，任何费用/到账字段缺失不默认0或已到账。

| assumptions字段 | 明确值与语义 |
| --- | --- |
| no_cash_distributions_and_no_splits | true，仅条件假设，真实状态仍unknown |
| entry_price_rule | entry_date_nav_hypothesis，仅假设入口NAV计价 |
| exit_price_rule | end_nav_same_price_hypothesis，期末同NAV清算估值假设，不是未知价赎回成交 |
| costs | 每基金对象，buy_rate、exit_rate为明确小于1的非负十进制费率；buy_fee_basis=net，即投入/(1+buy_rate)；holding_period_condition写明固定费率适用的假设及证据不足 |
| entry_confirmation_dates | 每基金明确假设申购确认日期或null；null为未知 |
| exit_application_dates（可选） | 省略表示全部未知；若提供，必须恰好覆盖funds，每项为日期或null。显式日期须等于本入口冻结的end_date，匹配end_nav_same_price_hypothesis；不能改用较早/较晚的申请日来选择更有利的费用档。此约束仅适用于本条件估值入口，不是所有真实基金的统一交易规则。 |
| exit_confirmation_dates | 每基金明确假设赎回确认日期或null；不早于出口NAV日及申购确认日 |
| exit_receipt_date | 明确假设到账日期或null；有日期须晚于窗口末且不早于所有已给赎回确认日；null不补到账 |

持有自然日仅按假设赎回确认日减假设申购确认日输出；任一未知则null。绝不把20个估值日当20个自然日，也不按估值行数自动跨30日费率门槛。产品确认/支付期限不等于特定渠道到账承诺；此入口不推断这些规则。

**nav.csv**列：fund,date,nav,source_id,retrieved_at,known_available_at。NAV为正有限十进制；日期YYYY-MM-DD，时间必须真实且带时区，known不得早于retrieved或晚于协议实际冻结时间。每基金必须覆盖全部valuation_dates，不填补、不插值；重复行拒绝。可含额外历史行，只有冻结窗口参与估值。

**sources.json**数组（1到12条）：每条含id、公开HTTPS url、snapshot_sha256、snapshot_kind（raw_http/tool_extracted_text/structured_summary）、真实retrieved_at、known_available_at、reviewed=true。snapshot_sha256必须指向实际捕获的表示，摘要哈希不能改称HTTP原件；原件私有保留。程序验证字段和整个来源文件哈希，源内容与审阅声明真实性仍由评估者核查。

## 输出含义

results.json及manifest.json均私有保存（目录0700、文件0600）。manifest记录四份输入与输出SHA、源捕获元数据、条件及实际评估时间；不生成网络请求或真实账本事件。

每策略daily_curve给逐估值日账面资产、相对初始变化、现金、逐基金条件NAV价值、确认状态未知/待确认的经济暴露、已假设确认价值、总敞口、资本占用及假设买费。每日都带条件标签与缺证据。入口费从同一初始本金扣除；管理等NAV内费用不重扣。模型从入口日起计算假设经济暴露，待确认份额没有变成已核实份额；缺确认不抹掉价格风险。

pre_liquidation_nav_mark为期末持仓NAV估值，未扣假设退出费。liquidation_scenario另列扣退出费的条件资产、退出费、假设退出款、总费用、含退出成交额、含退出费回撤和风险门槛。它只是假设同NAV清算的折价估值，不是已经下单/确认的应收。available_cash_at_window_end始终只有未投入现金；未知到账时conditional_cash_if_assumed_receipt_occurs为null。即便明确假设未来到账，也只另给“若该假设发生”的现金值，不回填期末现金。

比较项分别命名against_cash和against_equal_weight；另报risky_allocation_fraction、cash_equivalent_allocation。全现金风险资产投入为0，即使优于等权买持，也不能验证主动盈利能力；active_profitability_validated始终false。

三策略报告相同估值点最大回撤、最大敞口、平均资本占用与同条件终值差；现金利息固定0。门槛失败保留，不选费用参数或基金来美化结果。promotion始终retain_stable；条件账面优势不支持实际净收益/可执行alpha。后续仍需未来未见样本、成本风险与不确定性复核，以及独立授权。

## 已测与未测

合成fixture验证计算、原字节哈希、CLI完整运行、同分配与等权完全一致、费用不缺省、清算价值不计作现金、确认自然日、已知分红冲突及缺NAV拒绝。真实历史NAV和真实LLM分配由独立私有研究任务运行；本开发任务不生成方案、不读取用户持仓、不公开实际研究，不修改原预测或历史90情景。

## 经审阅的官方费用导入

`assumptions.costs[fund]`可用`official_rule`、`raw_document_path`、`identity`替代原固定费率字段。`official_fees.OfficialFees`复用现有`risk.FeeSchedule/FeeBand`逐批自然日赎回费工具，扩展含费金额档与每笔固定申购费。该结构已接入本页CLI及`evaluate`的每个方案，等权基线也按自己的实际申购金额选档。没有新增依赖或自动策略生成。

`official_rule`必需字段为：fund_code、share_class、currency、version、source_url（HTTPS）、published_on、reviewed_by、reviewed=true、pages、applicability_note、raw_sha256、nav_includes_recurring_fees=true、subscription_bands、redemption_bands。原件路径须在checkout外，文件0600、直接父目录0700，不接受符号或硬链接；运行时重新验证原字节SHA。审阅字段由调用方对原件负责，schema和哈希不证明来源真实。不能把下载日期填作规则发布日期或生效日。

`subscription_bands`逐档给min_amount（含）、max_amount（不含，末档null），并且恰选rate或fixed_fee之一；必须从0连续覆盖，拒绝交叉和缺档。比例申购使用含费金额/(1+rate)，固定费从含费金额直接扣除，零申购不收固定费。`redemption_bands`沿用FeeBand的min_days/max_days**两端含**及rate，未覆盖的自然日拒绝，不把“年”未经核实换成365日。A/C、币种和标的键必须匹配，不自动沿用其他类别的费率。

`effective_from/effective_until`未知时填null，默认拒绝历史适用；只有明确`document_version_scenario=true`才允许公告日之后的**该文档版本条件诊断**，输出仍不签认历史规则连续适用。已给生效区间之外必拒绝，不能用此开关绕过。公告日晚于交易日也拒绝。历史生效日期未知和渠道优惠未知分别保留，不阻塞已明确允许的官方标准版本情景。

`discount`省略/null表示只算官方标准，渠道折扣unknown；1表示有来源的无折扣，0表示有来源的全免比例申购费。显式优惠另须discount_evidence；不默认支付宝优惠，也不推定固定费能折扣。管理/托管/销售服务等NAV内费用不再扣。

`holding_basis`允许confirmation_to_confirmation_exclusive_end或confirmation_to_application_exclusive_end，并须holding_basis_evidence支持具体口径；未知用null。持有日按该口径的明确日期差计算，不用估值行数、工作日或平均批次年龄。`OfficialFees.redemption`接收已经明确选择的逐批份额，不猜FIFO卖出数量；返回每批持有日/费率/费用。当前固定初始分配估值只生成一个条件申购批次，不清算真实初始持仓。

申购确认或相应赎回日期/计日口径缺失时，保留已知申购费用、份额和NAV估值；赎回费、清算净额及依赖它的比较置null，风险费用闸门不通过。不会改成0或擅自增加有利确认日。实际确认/到账、分红、产品取整、暂停与历史适用性未齐时，输出继续是非可执行条件估值；本精确Decimal路径没有冒称产品逐笔两位取整。

合成使用和金额/日期边界见`tests/test_official_fees.py`：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_official_fees.py -v
```

输入和输出仍沿用上方CLI命令，真实文档、审阅记录、修订依据和纠错结果只存私有。费用事实纠错须另存修订及旧输入哈希，冻结原资产、窗口、分配和价格；不覆写旧结果，不计作策略alpha、结构晋级或投资验收。

### 赎回日期一致性

所有已给日期都须有效，不能因某日期不参与当前计日公式而忽略它。已知日期需满足申购确认日 ≤ 赎回申请日 ≤ 赎回确认日；已知到账日仍不得早于确认日。计日口径未知不掩盖已经明确的时序矛盾。逐批费用始终按产品已审阅的起止口径计算，不自动把确认日换成申请日。

缺失日期继续为unknown，不补造申请或到账日。所需计日依据不齐时，保留申购费和期末NAV估值，赎回费及依赖它的清算结果继续为null。合法日期也不证明开放日、未知价计价、历史费率适用性或实际成交已核实。
