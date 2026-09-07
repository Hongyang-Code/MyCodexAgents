# 内容与格式交付约束 v2

起草前展开 output_requirements，不能只传模板路径。content 为全文领域、窗口、四线覆盖、完整论文集合分别建项；每篇以 P 编号为 scope，为基本信息及六个字段分别建立实质要求，写明该篇关键数字、条件、来源归属和不确定性。约180～300字为软目标，不能删限定来凑字数。

format.document_headings 为模板五个完整二级标题。unit_level=3；sections 逐篇列实际三级标题（含ID、题目和链接）。required_markers 固定为 **基本信息：** 以及 - **速览：**、- **问题：**、- **方法：**、- **创新点：**、- **结果与可靠性：**、- **阅读建议：**。所有入选论文都须展开，空组没有论文 section，但需说明已查范围与未检出。

每篇独立标题，基本信息独立成段；六个列表项各自成段并空行。禁止“一篇一段”旧格式。元数据包含作者、发表简称、等级及目录版次/状态、日期版本、已读范围。目录限制需保留。

事实核查后冻结 original_text 和要求。读取 ../TextReadable/AGENTS.md、workflow.md、checklist.md、interface.md、requirements.md，在当前任务执行 output_mode=agent、max_rounds=3，每期最多2批。原文缺事实交回追踪流程核查；不得靠润色补造。每轮与冻结原文双向核对，保留题目、数字、日期、引用、归属、条件和判断强度。

在本期 .cache/ 保存原文、展开要求、候选、requirement_results 和审校结果。逐项记录原文位置、终稿位置、依据与状态。最终运行：

- `python ../TextReadable/scripts/check_format.py --text <报告> --requirements <要求JSON>`
- `python scripts/check_brief.py <报告>`

脚本只检查结构。漏论文、漏字段、挤成一段、重复编号均阻止通过。仍需人工核查论文身份去重、实质内容、来源及语义。任一适用检查 fail/unknown 不得宣称全部通过；不增加轮数或批次掩盖失败。

保存最终文件 SHA256 和检查结果。完整 final_text 原样交付，不再次缩写；过长按完整论文块分批。无法通过时说明具体缺口和状态。
