# TextReadable调用契约

读取 E:\MyCodexAgents\TextReadable\AGENTS.md、workflow.md、checklist.md、interface.md 和 requirements.md。在当前任务执行，不启动子智能体。

传入：

- original_text：用户最初完整原文，含全部段落、原有标题、公式和引用。
- candidate_text：XRWritting完成风格修订的完整正文。它是候选，不能替换最初语义基准。
- audience：原文预期读者；style：保留原文语言，以简洁、精确、论证明确为目标，不要求特定英文短语。
- context：用户提供的章节类型与上下文，仅作解释。
- protected_spans：逐字保护的术语、数字/单位、公式、引用、模型名称、用户保护项。
- max_rounds：3；output_mode：agent。整个任务最多2批，分块不重置。
- output_requirements：展开如下要求，真实格式约束为空时不加模板。

## 内容要求

针对每个真实单位P01等生成content条目，唯一ID形如P01-fidelity，scope=P01。明确列出该单位的事实/主张、方法关系、数字、比较、归属、条件和语气，并要求保留。不能仅写“内容完整”，不能把风格指南链接当展开的内容要求。

额外记录：原有标题与引用对应主张；用户明确要求的格式；必保留内容的位置。不强求补充原文中没有的实验、解释或相关工作。

格式要求只来自实际稿件和用户指令。原文只有一段正文时只传content；用户要求已有Markdown标题则将完整标题展开为format.document_headings，适用时列出sections及required_markers。使用TextReadable约定的键，不加入检查器不支持的自定义字段。

## 审校后

审校语义与风格复查分别记录。TextReadable发现须改原意的问题，返回XRWritting，不静默修改。仍能完成的安全改写可交付受限稿。

正文通过后再组成报告，问题清单与修改说明单独写，不能被混进用户论文。按templates/report.md人工或脚本检查报告格式。若有保存授权，运行TextReadable/scripts/check_format.py并绑定最终报告或正文版本；无授权时人工检查并明确mechanical_format_check=not_run。

最终改写再次对照最初原文，累计修改说明包含语言审校后的全部真实变化。风格复查如需改稿仍占用风格预算，并重新审校受影响内容；没有预算则如实记录未通过。
