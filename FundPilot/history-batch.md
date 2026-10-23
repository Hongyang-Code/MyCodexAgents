# 离线历史研究批处理

入口只读取本地材料，不联网、不登录、不通知、不下单。生产 `market` 和 `research` 接口未放宽。该批处理支持显式假设的当前版本数据研究，不能证明历史发布时刻或真实可执行收益。

## 运行

在仓库根目录运行；输出目录必须不存在、位于仓库外，路径各级不得是符号链接：

```bash
PYTHONPATH=FundPilot python -m fundpilot.history_batch \
  --input /private/dataset/input.json \
  --protocol /private/protocol-v2.json \
  --protocol-sha256 VERIFIED_PROTOCOL_SHA256 \
  --supplement /private/protocol-v2-calendar-supplement.json \
  --supplement-sha256 VERIFIED_SUPPLEMENT_SHA256 \
  --output /private/new-history-run
```

SHA占位符必须替换为此前已冻结的文件哈希，不得在看过收益后改写协议。真实数据批次必须提供与协议哈希关联的日历补充协议。`--predictions-only` 只计算原始净值水平/回报诊断，跳过全部策略；它允许分红状态未知，但不允许没有核实日历。不得将此模式报告为完成策略比较。

## 输入结构

`input.json` 使用 UTF-8 JSON，版本为1。`synthetic` 必须显式为布尔值；真实材料使用 false。文件字节最大20 MB，路径相对于 input.json 目录，禁止绝对路径、`..` 和符号链接。每个路径都需存在并匹配SHA；同一证据可以被多个字段引用。

```json
{
  "schema_version": 1,
  "synthetic": true,
  "calendar_mode": "verified_open_sessions",
  "files": {
    "nav-a": {
      "path": "nav-a.csv",
      "sha256": "REPLACE_WITH_ACTUAL_SHA256",
      "source_url": "https://example.org/synthetic/nav",
      "retrieved_at": "2026-10-24T12:00:00+08:00",
      "known_available_at": "2026-10-24T12:00:00+08:00",
      "license_note": "合成示例；真实批次填写来源许可及未知边界。"
    }
  },
  "instruments": [
    {
      "instrument": "SYNTH-A",
      "share_class": "A",
      "nav_file": "nav-a",
      "calendar_file": "valuation-calendar-a",
      "dealing_calendar_file": "dealing-calendar-a",
      "calendar_evidence": "valuation-evidence",
      "dealing_calendar_evidence": "dealing-evidence",
      "identity_evidence": "identity-evidence",
      "channel_evidence": "ant-sale-evidence",
      "rules_evidence": "rules-evidence",
      "calendar_reviewed": true,
      "dealing_calendar_reviewed": true,
      "public_ant_sale_and_product_open": true,
      "channel_limitations": "合成示例；账户额度、渠道费率、历史限制须分别记录。",
      "distribution_status": "verified_none",
      "distribution_evidence": "distribution-evidence",
      "distribution_start": "2025-10-23",
      "distribution_end": "2026-10-23",
      "no_split_reviewed": true
    }
  ]
}
```

这是字段说明示例，不是完整可执行输入。必须在 `files` 中逐一提供所有引用，并为冻结协议中的每只基金提供一个 instrument。代码不从基金名称推断A/C。各 reviewed 字段是资料审阅者的声明；程序只检验声明和证据字节存在，不替代官方内容核查。

NAV CSV表头必须恰为 `date,nav`，日期为ISO格式，净值为有限正数，日期不重复。不能用累计净值替换单位净值。每只基金的估值日历和申赎日历分别为只有 `date` 表头的CSV，日期升序且唯一。估值日历必须包含NAV日期，申赎日历必须是估值日历子集。将存在NAV但暂停申赎的日期从申赎日历排除，保留在估值日历。不能默认星期一至五就是开放日。

预测目标需要估值日历延伸至窗口结束后20日及信息延迟所需范围，否则保留 `target_calendar_unavailable`；不能猜未来日历填满。策略还要求共同申赎日历覆盖窗口结束后至少4个开放日，以表达未完成订单；这些未来日期不提供未来价格，不进入窗口内评分。

`retrieved_at` 是实际获取时间；`known_available_at` 必须相同，不能回填为网页所写净值日期。晚于冻结取证截止的抓取保留并标注，只能支持当前版本的事后评分，不成为截止已知数据。官方原始HTML/PDF、日历、分红和规则文件均通过 `files` 保存源URL、获取时间、SHA及许可边界；标准化CSV也应引用其公开来源并记录实际生成/取得时间与转换说明。

当前策略驱动只支持审阅后确认所用历史至观察窗末无分红、无拆分的区间。`distribution_status=verified_none` 必须有证据引用和覆盖起止日期。存在分红/拆分或证据未知时，完整策略运行失败关闭；不得借修改标签绕过。可选择明确的净值预测诊断模式，或先开发并独立验证有证据的分红事件处理。此限制是实现范围，不是宣称基金从未分红。

## 固定计算与边界

模型是弃权、水平不变、20估值间隔固定趋势；不训练参数、不搜索模型。训练期之前的历史用于初始化，滚动特征只能访问假设可得数据。信息延迟为1/3/5个核实估值间隔，不声称是实际披露时间或QDII的保守上界。假设可得视图时刻为北京时间21:30。

预测原点是决策日；目标从决策日加1/5/20估值间隔。趋势分别估计决策日未知价格和未来目标价，预测回报为两者之比减1。实际回报只在评分时使用目标日NAV/决策日NAV减1。预测和实际均保留 raw_nav 标记，不宣称分红调整后的总回报。水平不变预测回报为0；方向统计包含平、涨、跌三类，并另列非零方向调用数量及命中率。弃权不计为0收益预测。

验证期标签跨界标为 purged；观察窗口之后到期标为 pending，即使输入包含未来NAV也不评分。缺特征、缺评分净值、弃权均逐行保留原因。`frozen-predictions.json` 保存不含实际结果的预测字段，`predictions.json/csv` 保存事后状态和结果。

指标按基金、模型、期限、延迟、时间分区分别输出。`ex_post` 是当前版本事后评分；`cutoff_known` 还要求实际获取时间不晚于取证截止、假设目标可得日期严格早于截止日期，因当日实际发布时间不明而排除同日目标。该定义不能证明历史当时可得。非重叠样本从最早合格原点起，依核实估值日历至少间隔h步，不输出独立同分布置信区间。不提供模型未输出的概率或校准数值。

四种策略共72个固定情景：4策略×3信息延迟×2确认/到账延迟×3双边成本。买持等权；六期投入使用冻结日期后的首个共同申赎开放日；再平衡使用月内首个共同申赎日；趋势正向维持1/N目标，非正向转零收益现金，仅信号变化时调整。卖出所得未到账不能用于买入，当下现金不足按比例缩减买入，不假设新增资金、不在到账后自动补单。未完成订单/结算时跳过新指令并记原因。

决定交易时只用假设可见的旧净值分配金额；订单在下一个共同申赎开放日以当时尚未知的NAV计价。买入先冻结含费预算，净买入金额为预算/(1+费率)；卖出冻结份额，到账额为份额×未来NAV×(1-费率)。1/3个共同开放日后确认买入份额或释放卖出应收。双边0/20/100bp是压力假设，不是渠道报价；不重复扣NAV内费用。

每日资产按估值日并集记录，非估值日使用最近核实估值并显示其日期；遇应有估值但数据缺失即失败。没有强制期末卖出，终值包括冻结现金、待确认份额及应收，另报可支取现金，不计算可变现收益。验证/测试子区间继承同一资金池，不重新注入本金。产品实际取整、申购额度、历史渠道变更与真实确认规则未被该情景引擎证明。

## 输出与复验

输出目录0700、文件0600。完整输入与原始证据保存在私有输出，禁止加入Git。包括协议/补充、原输入与可重放输入、原始证据、代码副本及逐文件哈希、质量记录、无结果预测、完整结果、指标JSON/CSV、每个情景交易流水/每日资产、策略汇总、经验候选及中文报告。经验记录支持、反例、适用/失效条件与样本局限，固定为候选，不自动升级。失败留下 `run-status.json`，不生成成功审计包。

`audit.zip` 内含 `audit-manifest.json`，打包后逐文件回读核对。解包到私有目录后，可使用包内代码重放（输出指向新的仓库外私有目录）：

```bash
PYTHONPATH=source/FundPilot python -m fundpilot.history_batch \
  --input replay-input.json --protocol protocol.json \
  --protocol-sha256 VERIFIED_PROTOCOL_SHA256 \
  --supplement protocol-calendar-supplement.json \
  --supplement-sha256 VERIFIED_SUPPLEMENT_SHA256 \
  --output /private/new-replay
```

时间、Git环境和ZIP元数据可能不同；复验比较规范化预测、交易及统计，不要求ZIP整体字节相同。合成测试覆盖整条CLI和72情景，但不代表完成真实半年研究或证明预测有效。
