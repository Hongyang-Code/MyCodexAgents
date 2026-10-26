# PaperReader 内容与格式要求 v1

## 内容责任：根据本次论文展开

为以下每项创建独立 content 项，写明 id、scope、requirement。材料不足只能由 PaperReader 据已读范围写明缺失及影响，不能要求 TextReadable 补齐论文事实。

- 论文摘要：领域与任务、核心问题、核心方法、创新与贡献、性能与代价、阅读建议、潜在问题、后续方向、相关工作共 9 项，每项独立检查。建议含理由与推荐章节；问题区分限制与疑点，方向区分作者与分析并给出最小验证思路。
- 可靠性评估：开源、复现条件、公平比较、结论支撑、外部一致性、泄漏与混杂逐项说明发现、证据位置、对结论的影响和待验证事项。不得用综合评分替代证据强度评估。
- Quick Info 与 Links：身份、版本、年份、venue、稳定标识、已核查资料链接与覆盖范围。
- Abstract、Introduction、Related Work：中文摘要解读、研究问题及动机、可核查相关工作及关系，不把完整翻译或凑数作为默认要求。
- Methods：直觉、输入输出与流程、必要公式及符号、关键条件和适用边界。保护原题、公式、数字、来源及论断强度；不能通过删除限定简化解释。
- Experiments：数据和划分、指标方向、baseline、关键数值、比较条件、证据位置、消融和统计证据及泛化局限。未知不能补全。
- Conclusion 与 Thoughts：证据支持的结论和边界、优点与局限、可开展工作与最小验证、未决问题。区分作者报告、外部核实、智能体分析和未知。
- 导图：正文保留图片引用和导图章节，图按论文结构组织。TextReadable 仅检查文字及引用保留；PNG 实际存在、内容一致和可读性由 PaperReader 单独检查。

理论、综述、数据集等论文由 PaperReader 起草前将实验或方法的细项映射为证明、检索方法或数据构建评估，并在要求记录适用理由。保留报告一级栏目；不适用的细项可以事先豁免，不能在审校时为了通过擅自删掉要求。

## 格式约束：生成本次 format

- document_headings 包含模板全部二级标题：论文摘要、可靠性评估、基本信息（Quick Info）、资料链接（Links）、摘要解读（Abstract）、研究动机与目标（Introduction）、相关工作（Related Work）、方法（Methods）、实验与证据（Experiments）、结论与边界（Conclusion）、评价与研究启发（Thoughts）、论文结构导图。JSON 中写出每项完整的“## 标题”行。
- sections 至少包含 heading=## 论文摘要，其 required_markers 使用模板表格的九个行前缀：| 领域与任务 |、| 核心问题 |、| 核心方法 |、| 创新与贡献 |、| 性能与代价 |、| 阅读建议 |、| 潜在问题 |、| 后续方向 |、| 相关工作 |。
- sections 另含 heading=## 论文结构导图、required_markers=["![论文结构导图]"]；图片路径单独由 PaperReader 检查。
- 不设置 unit_level，方法和 Thoughts 可使用三级小标题。正文保持规范 Markdown、简体中文、必要 LaTeX 和就近引用。表格空单元格即使结构脚本放行，实质覆盖检查仍须判失败。

## 调用与交付门槛

1. 起草前读取本文件，按本次实际材料和用户要求展开具体约束。将每项内容责任转换为 content 中的 id、scope、requirement；不能只传原文或模板路径。
2. 事实核查完成后，将完整 original_text 与 output_requirements 一起冻结。调用时显式读取 ../TextReadable/AGENTS.md、workflow.md、checklist.md、interface.md、requirements.md，在当前任务中执行，output_mode=agent、max_rounds=3。每份报告最多 2 批。
3. 在本次产物 .cache/ 保存 original-text.md、output-requirements.json 和候选稿；这些属于已授权的本地产物。要求版本记录在 quality-review.md，不混入脚本输入对象。
4. 初稿缺少实质内容时由调用方回到来源核查。补充事实或缺口说明后明确新基准；不能要求 TextReadable 编造内容、预测或未知状态来凑齐字段。已有内容可无损调整格式，计入修改轮数。
5. 取回逐项 requirement_results，核对每个条目的原文与终稿位置、依据和状态；少一项也不能通过。所有适用内容与格式检查必须 pass，未查不能等同于不适用。
6. 对最终 report.md 运行 TextReadable/scripts/check_format.py，传入本次 output-requirements.json。记录命令结果与 sha256，失败则在预算内修改复查，不能宣布通过。脚本成功仍需内容覆盖审查。
7. 对话正文使用已审校版本；不得在返回时另写一个删栏摘要替代完整正文。确实超过容量时按完整章节或事件分批展示，说明剩余内容及完整文件位置。完整文件和逐批正文都必须保留适用要求。改动正文后原通过状态失效，按受影响范围复查，不增加预算。
8. 保持最终事实、专业或图片检查职责；无法通过时交付明确状态与缺口，不能为了合格删除要求。用户明确调整结构时由调用方记录新要求，再审校。
