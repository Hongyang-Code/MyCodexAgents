# 冻结 LLM 卡的小型离线闭环

此CLI接收外部真实LLM生成的卡，先冻结，再读取NAV评分；自身不调用LLM、不联网、不生成伪LLM预测。合成fixture明确使用synthetic模式。可执行工程闭环不等于LLM能力、盈利或生产编排验证。私人输入输出不能进Git。

## 两步运行

在仓库根目录执行，所有输入/输出路径在仓库外，输出目录必须不存在：

```bash
PYTHONPATH=FundPilot python -m fundpilot.llm_loop freeze --cards /private/cards.json --sources /private/sources.json --calendar /private/calendar.json --output /private/frozen
PYTHONPATH=FundPilot python -m fundpilot.llm_loop score --frozen /private/frozen --nav /private/nav.csv --nav-manifest /private/nav-manifest.json --as-of <带时区真实评分时间> --output /private/scored
```

freeze不读NAV；复制三份原字节并生成receipt.json，记录真实冻结时刻及SHA-256。score验证其哈希后读取真值。receipt须由调用方另存私有不可变记录；本地哈希不防管理员同时篡改receipt及文件，不证明LLM此前从未看标签。真实LLM生成及卡写入在读评分标签之前完成；更大项目已见历史、模型参数记忆可能污染仍必须披露。不得覆盖既有前瞻9卡。

## 输入 schema

cards.json对象：

- mode：retrospective、prospective或synthetic。历史诊断用retrospective，不能伪报prospective。
- producer：真实卡actual_llm，synthetic模式必须synthetic_fixture；这只是须外部核查的声明。
- model_ref、prompt_version：真实可知版本；不可知细节明确unknown，不捏造。
- cutoff：原资料截点，带时区，日界使用其原始本地日期；中国基金应写+08:00。
- generated_at：实际LLM生成时刻，带时区，不得倒填历史。历史模式通常晚于截点。
- cards：1到9张。每张id、fund（完整代码/份额标识，与日历/NAV完全一致）、origin、horizon（1/5/20整数）、direction（up/flat/down/abstain）、source_ids列表、reasoning、counterevidence、invalidation、gaps、scenarios；弃权另含abstention_reason。

最多3只基金、同一origin，每基金/期限最多一张。origin为截点本地日期之后的首个核实估值日D0；目标为D0之后第h个估值日。方向比较D0至目标单位净值，正/零/负固定为up/flat/down，无容差调参。条件scenarios原样冻结，但没有单独冻结触发观测的本CLI不评分情景，也不从情景挑命中。缺少任何期限的卡不能编造补足，total报告实际卡数。

sources.json为最多12条来源对象的数组。每条含id、url（公开https）、raw_sha256、reviewed=true、published_at、retrieved_at、known_available_at；可增加原文/事实/版本等字段，全部原字节冻结。known_available_at不得早于retrieved_at；published_at必须是对应版本真实发布时点。历史模式另含assumed_available_at，不能早于published_at，引用卡的假设可得时间不得晚于cutoff。其他模式用真实known_available_at资格判断。未知发布时点不能伪填；该来源无法作为本CLI合格方向证据，应删除引用或先补核验，不能用当前修订内容冒历史版本。

calendar.json：`{"reviewed":true,"evidence_ref":"私有日历证据引用","dates":{"完整基金标识":["YYYY-MM-DD"]}}`。日期严格递增无重复，须覆盖初始化、D0及所需目标；来源证明的是估值日历，本CLI无申赎执行。没有目标日期时保留pending/target_calendar_missing，不猜工作日。

nav.csv精确列名：`fund,date,nav,retrieved_at,known_available_at,assumed_available_at`。nav为正有限十进制或空值；空值评分为missing。日期YYYY-MM-DD，时间均带时区；历史模式用单独假设时间筛基线，其他模式用known_available_at。真实检索/已知时间不可改写。CSV可以包含D0前初始化与评分目标，但基线只见截止时点合格行。重复基金/日期直接拒绝。

nav-manifest.json：`{"sha256":"nav.csv原字节SHA256","reviewed":true,"reviewed_by":"真实审阅标识","evidence_refs":["原净值公开来源及核验记录私有引用"]}`。输入reviewed声明和引用的真实性需调用方独立核查，程序不联网证明。

## 输出与解释

results.json保留全部卡的pending、missing、abstained或scored状态、缺失原因、实际方向、零值规则、LLM命中和固定基线。弃权永不算命中；报告成熟数、评分数、覆盖率及命中率。persistence恒flat；trend20使用截止前最后可用估值日及其之前20个连续核实估值日，缺行/缺资格为unsupported，不压缩缺日寻找替代窗口。三者共同可评分、LLM未弃权的paired_ids为严格同样本比较；同时保留全卡信息及每卡基金/期限身份，避免只展示有利样本。无概率校准、无独立样本置信区间；同一origin的基金/期限高度依赖。

历史模式固定标记retrospective、LLM memory contamination possible、returns seen by broader project、independent_oos=false。方向及变化仅是原始NAV路径，不是总回报，不证明投资有效。prospective也不由本CLI自动授予独立OOS身份。

错误归因保持unknown/candidate_only，仅列来源/时点/推理/未观测冲击/噪声待核查类别，附实际偏差与原卡反证。出现错误时至多输出一条固定的“冻结前增加反证检查”提案及支持/反例ID；这是确定性审查提示，不冒充LLM推理或已证原因，不自动注册、评估或晋级候选。父任务可另行由真实LLM复核原卡和结果，保留不同解释。

manifest.json记录冻结receipt、卡片/来源/日历、NAV及manifest、结果哈希。输出目录0700，JSON0600；不自动上传或通知。调用方须按controlled-iteration.md检查完整私有预算历史，不能利用每次CLI进程重置计数；本CLI只复用单批形状上限，尚不接跨运行持久预算。不得据CLI成功宣称预算硬闸、真正盲测或效果改善。

## 合成验证

`PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_llm_loop.py -v`运行真实freeze/score子进程和合成数据，覆盖缺失、未成熟、重复、未来证据、弃权、零变化、冻结篡改、基线时点限制及私有权限。fixture不是LLM，真实卡和实际市场评分另行私有执行。

## 显式有限日期诊断适配

实际接入发现部分公开证据只有日期精度，且保留的是工具抽取或结构化摘要。此时不得伪填精确发布时间或把摘要哈希称HTTP原件。原retrospective/prospective/synthetic门槛不变；另选`mode=retrospective_diagnostic`（producer仍actual_llm），仅用于有限历史诊断。

该模式每条来源仍需id、url、reviewed=true、真实retrieved_at/known_available_at；替代原published_at/raw_sha256/assumed_available_at的字段为：

- published_precision：day；published_date：原资料标示YYYY-MM-DD；timezone：unknown。
- snapshot_kind：structured_summary或tool_extracted_text。
- snapshot_content：实际捕获文本字符串，不改写补料；若已有JSON摘要，可保存其原序列化文本字符串。
- snapshot_sha256：snapshot_content解码后字符串的UTF-8原字节SHA-256，仅代表所捕获摘要/抽取文本。不得同时填写raw_sha256冒充HTTP。
- revision_status：unknown，明确不能证明捕获内容与历史原版一致；本最小适配不支持自行声明已核实无修订。

未知时区按UTC-12的最晚日界，即该日期次日12:00 UTC，要求严格早于截点且不晚于真实known时间；同日、临界时点或未知发布日期拒绝。日期通过仅是有限资格，不能证明原版历史可得。此分支不伪造published_at或available_at，不将计算日界写作已知发布时间。NAV CSV仍保留真实retrieved/known与独立assumed_available_at，历史基线规则不变。

receipt、结果及每张tape、改进提案、输出manifest均标source_time_qualification=limited、non_blind=true、non_oos=true、current_vintage=true、historical_revision_status=unknown及snapshot_hash_basis=captured_content_utf8_not_raw_http。原来源快照原样保存，不加伪造标签改变原字节；模式和限制由生成的审计输出承载。诊断成功不表示strict gate通过。

保留首次真实拒绝日志及原LLM卡；适配仅建立新的输入封装/证据schema版本，不更改原判断、理由、期限或方向。新封装另行freeze，不覆盖首次记录或原前瞻9卡。同卡复测只验schema修复，不能称新模型改进或重新调参。

## 新批次的独立数值研究预测

交易弃权、无校准优势、方向弃权，不自动等于缺研究预测。后续新冻结批次可提供可反驳的主观概率和分位数供成熟后校准；证据不足仍可明确缺预测。此项仅改善测量，不提高买入权限，不证明盈利，不重置结构候选/调优预算，也不自动采用候选。

启用时在cards.json顶层增加numeric_schema=research_numeric_v1与new_batch_no_backfill=true。每卡增加以下numeric_forecast对象，horizon须等于原卡期限（1/5/20估值日），模型版本未知仍写unknown：

```json
{
  "unit": "raw_nav_return_fraction",
  "event": "return_gt_zero",
  "horizon": 5,
  "calibration_status": "subjective_uncalibrated",
  "p_up": "0.55",
  "q10": "-0.03",
  "q50": "0.005",
  "q90": "0.04"
}
```

上例仅示意字段，不是行情预测。p_up是目标NAV相对D0严格上涨的主观概率，零收益标签为0；0.01代表1%原始NAV变化，不是价格或百分数1。q10/q50/q90为同一D0到目标的NAV变化分位数，必须有序且不小于-1；标称中央区间覆盖率80%不等于实际覆盖率已校准。不得把角色投票或任意置信分直接冒称校准概率。

p_up可为null；分位数只能三项都有或全部null。任一组缺失须写missing_reason。direction=abstain仍可独立提供数值预测，保留原方向弃权理由；无交易不需要把概率或分位数清空。所有字段先冻结，禁止给旧方向卡事后补概率；new_batch_no_backfill是调用方声明，CLI不跨批次识别历史ID，调用方必须保留原卡及独立新批次记录。冻结后改数值同样触发哈希拒绝。

原freeze/score命令不变。成熟且有实际NAV的标签才产生numeric_scores：Brier复用research.evaluate；分位数给各自pinball损失、闭区间覆盖及宽度。未成熟、缺实际值或缺预测对应损失为null，绝不当0损失或命中。数值评分不依赖方向是否弃权，更不生成交易动作。

新增numeric_metrics及逐卡基金/期限指标，分开probability_n、quantile_n、成熟标签数、缺失数与覆盖率。Brier基线预先固定p_up=0.5；分位数基线另为q10=q50=q90=0的水平不变退化分布。两者是不同比较基线，均不拟合、不读未来特征、不按结果选择；每项基线仅与该项LLM可评分样本配对。旧方向基线不改。区间覆盖与宽度、pinball同时看；不能用扩大区间或少量命中宣称有效。

主观预测是否校准须积累未来未见、合理非重叠样本并审查不确定性；本接口不做校准拟合、不提供小样本独立CI。输出calibration_proven、profitability_improved及trading_authorized均为false。已见历史仍非OOS；测量能力改进不等于策略或净收益改善。
