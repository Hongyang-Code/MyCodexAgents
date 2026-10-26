# 内容与格式契约 v1

读取 ../TextReadable/AGENTS.md 及其 workflow.md、checklist.md、interface.md、requirements.md。事实核查后冻结 original_text 和展开后的 output_requirements，在当前任务执行，output_mode=agent、max_rounds=3；每份报告最多2批。

content 按全文建立范围、完整论文集合、合格篇数、方法主体、发展脉络、路线对比、阅读路径、来源及覆盖限制要求。每篇按P编号为scope，为基本信息和八个字段各建实质要求；列该篇不得丢失的主张、数字、条件、归属和关系强度。骨干综述单列入选依据，不能用普通摘要替代领域位置。

format.document_headings 为模板六个二级标题；unit_level=3，sections 逐篇列实际标题。required_markers 为 **基本信息：** 和 - **速览：**、- **问题：**、- **方法：**、- **创新点：**、- **结果与可靠性：**、- **阅读建议：**、- **领域位置：**、- **前后关系：**。每篇独立块，字段分别成段并空行，禁止多个字段挤在同一行。不得传未展开模板，不得漏掉后面的论文。

每轮检查可读性、严谨性、相对冻结原文的双向语义保真、实质覆盖及格式。不得增删事实、关系、范围、条件、引用、等级核验状态和判断强度。缺失事实返回本调研流程，不靠润色凑20篇或补关系。记录 requirement_results 的原文/终稿位置、依据及状态。

最终运行：

- `python ../TextReadable/scripts/check_format.py --text <报告> --requirements <要求JSON>`
- `python scripts/check_survey.py <报告> --papers <papers.json>`

脚本结果、人工复查结论和最终SHA256分别保存。结构通过不证明方法理解、语义保真、主干地位或关系正确；逐项审阅这些内容。任一必需项fail/unknown或数量不足时标明未完成/未通过，不降低要求，不增加批次。最终全文来自审校版，分批只按完整块切分，不再缩写。
