# 冻结趋势的评分与经验接线

本增量解决“统一趋势已经保存，但尚未接入逐项核验和经验记录”的工程缺口。复用 `llm_loop.freeze/score` 和 `research.Experience`，不重新编写评分公式，不生成新预测，不运行新研究实验。

## 数据流

**原始桥接输出 → 明确审阅的身份／日期／引用映射 → 冻结评分卡 → 既有评分器 → 正确、错误及未知状态记录 → 零权重经验候选。**

`fundpilot.trend_feedback.freeze_bridge_cards` 接收已完成的 stable 桥接目录、独立 binding、来源与估值日历。binding 必须绑定原输入与经理响应的哈希、精确基金标识、原信息截点、明确起点以及各期限的引用。估值日不按自然日或工作日猜测，由原有校验器检查；缺映射时停止，不生成虚假目标日期。

原 1／5／20 方向、理由、反证、失效条件和缺口逐项保留；完整原始 claim 同时保存。原生成时间不改成导出时间，也不把旧响应当作新推理。合成材料只能映射为 synthetic；实际既有响应只允许 retrospective 或带受限时间证明的 retrospective_diagnostic，不据此获得新的评分预算或研究权限。

概率原值仍在原始 claim 中。原桥接没有完整数值事件／单位／分位数契约时，数值评分保持待核查；不补造分位数，不给旧卡回填 numeric_schema，不把主观概率写成已校准概率。条件情景未记录时明确标记，不能把情景命中混入无条件方向成绩。

## 结果到经验

调用原有 `llm_loop.score` 后，`feedback_from_scores` 读取已经保存的结果及清单，不再次评分。结果必须绑定同一冻结卡和原始判断，全部卡均保留：

- 正确：保存对应结果、原理由、反证和失效条件。
- 错误：保存相同字段，不自行编造错误原因。
- 弃权：单列，不计为正确或错误。
- 未成熟／日历不足：保留 pending。
- 缺净值或标签：保留 missing，不当作预测失败。

正确和错误两类都会生成 `Experience(state="candidate", weight=0)`，只形成单案例审查材料。原因默认为 unknown；成功不证明因果，错误也不自动证明方法失效。现有候选经验的验证／失效／停用政策继续适用，不自动晋级、改变仓位或回灌较早历史时点。重复评分与修订需要保留旧输出，不能覆盖或删除反例；调用方在长期经验索引中按 forecast ID 去重。

冻结包保留原桥接输入、经理响应、映射原件及来源／日历的字节哈希。反馈另存新私有目录，包含案例、经验候选及来源绑定清单。哈希不是独立签名，也不防同一文件所有者同时重写全部记录。

## CLI 使用步骤

CLI 只连接已经存在的真实研究与离线评分，不负责获取来源、调用模型、分配研究预算或选择历史窗口。调用方必须先在外部协调并原子预留适用预算，完成真实 stable 研究，保存原始 `input.json`、三份请求／响应、`result.json`、`receipt.json` 和检查点；合成 fixture 只能用于工程测试。

输入 schema 由现有实现和回归共同约束：

- `research-root`：`frozen_topdown.load_frozen_research` 可读取的已完成 stable 桥接目录。
- `binding.json`：精确绑定原输入和 manager 响应 SHA-256、cutoff、fund、D0 origin、mode、review_ref，以及 1／5／20 每项 source IDs。
- `sources.json`、`calendar.json`：遵循 `llm_loop.validate`；估值日必须为审阅后的有序唯一序列，不能按工作日猜测。`retrospective_diagnostic` 仅接受捕获文本摘要及其 UTF-8 哈希，不能把摘要哈希称为原始 HTTP 字节哈希。
- `nav.csv`、`nav-manifest.json`：遵循 `llm_loop.score`；manifest 绑定精确 CSV，NAV 行分别记录 valuation date、retrieved、known available 和 assumed available 时间。

以下命令均从仓库根目录运行；输入和输出位于 checkout 外的私有目录，每个输出目录必须尚不存在：

```bash
PYTHONPATH=FundPilot python -m fundpilot.trend_feedback freeze \
  --research-root /private/research/stable \
  --binding /private/evaluation/binding.json \
  --sources /private/evaluation/sources.json \
  --calendar /private/evaluation/calendar.json \
  --output /private/evaluation/frozen

PYTHONPATH=FundPilot python -m fundpilot.trend_feedback score \
  --frozen /private/evaluation/frozen \
  --nav /private/evaluation/nav.csv \
  --nav-manifest /private/evaluation/nav-manifest.json \
  --as-of 2026-01-01T00:00:00Z \
  --output /private/evaluation/scored

PYTHONPATH=FundPilot python -m fundpilot.trend_feedback feedback \
  --frozen-root /private/evaluation/frozen \
  --scored-root /private/evaluation/scored \
  --output /private/evaluation/feedback
```

`freeze` 生成冻结卡、来源、日历、receipt、原桥接副本及导出 manifest；`score` 生成 `results.json` 和评分 manifest；`feedback` 生成 `feedback.json` 和反馈 manifest。命令会把结果 JSON 写到标准输出，真实运行应同时保留命令日志，但不得提交真实材料。

弃权在目标成熟后保留 `actual_direction`，状态仍为 abstained，既不计正确也不计错误，不生成经验候选。persistence 是同窗 flat 基线；trend20 只有在截点前存在 21 个连续且时间资格合格的估值观察时才计算，否则明确记录 missing reason。NAV 方向不是分红调整、扣费后的投资收益。

## 验证

在 Linux / Python 3.12 仓库根目录：

```bash
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -p test_trend_feedback.py -v
PYTHONPATH=FundPilot python -m unittest discover -s FundPilot/tests -q
```

测试使用明确合成的桥接资料、日历和净值，包含一项正确、一项错误、一项弃权，以及缺失、未成熟、未来来源、错误映射、漏卡和篡改等反例。子进程回归实际依次运行 freeze、score、feedback，并核对三个阶段的 JSON 和最终 manifest；`--help` 只检查参数展示，不替代该入口回归。真实执行结果以对应的私有运行回执为准。

## 尚未完成的研究验收

该入口已经承载过真实 historical diagnostic，包括失败案例与弃权案例，但这仍只是研究诊断版本。工程闭环和少量回顾性结果没有证明动态投资或盈利能力。后续研究必须另有固定资料、比较协议和适用预算；耗尽批次不能重用。

本反馈只评价原始 NAV 方向，不代表包含分红与交易费用的投资收益，也不构成12个月保本／抗通胀验收。项目保持未完成，现实指导禁用。
