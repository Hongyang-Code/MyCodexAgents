# TextReadable 契约

在内容审核之后读取 ../TextReadable/AGENTS.md、workflow.md、checklist.md、interface.md、requirements.md，由主任务执行文字审核，不为语言审核额外启动子智能体；前面的审稿与修订按multi-agent.md。默认max_rounds=3、output_mode=agent，整个PaperReviewer任务最多2批，不随N轮重置。每轮已有本地可读性检查，完整TextReadable通常只在最后运行一次。

original_text是内容修订结束后冻结的稿件，不能用最初有问题的原文要求语义完全不变；首次原文保留用于审计“原稿→内容修订稿”的有据变更。TextReadable检查“内容修订稿→语言终稿”双向语义不变。

必须传入展开的output_requirements：

- content：逐段或逐节列必需主张、研究范围、条件、作者归属、结论强度、已解决问题对应的修改、未决限制、数字、公式、引用及不可删除的图表内容。为全部输入范围建立要求，不能只检查摘要。
- format：按用户要求和实际源文建立，段落可以仅提供content，不为套模板强造标题；全文Markdown提供实际document_headings及适用sections，只有每个同级章节都列全时才设unit_level。LaTeX/DOCX等由相应源格式检查，不强套Markdown脚本。
- protected_spans：关键数字、公式、引用、用户明确不可改部分。严谨的限定不可被润色删除。

原文缺事实或解释不能由TextReadable补造，交回PaperReviewer内容阶段记录终审修复，重新冻结时仍计入任务级批次上限。若用户未授权核心研究方向改变，保留待决事项。

允许保存且有Markdown format要求时运行：
`python ../TextReadable/scripts/check_format.py --text <候选稿> --requirements <展开要求JSON>`

同时运行：
`python scripts/check_run.py <run.json> --final <最终正文> --original <原稿> --changes <changes.json> --change-report <changes.md>`

保存requirement_results、脚本结果、人工审查依据、各稿SHA256、TextReadable返回和实际语言修改轮数。没有format时格式脚本可为not_applicable；禁止落盘时记录mechanical_check=not_run，仍人工逐项检查，不声称脚本已过。源格式验证、内容审查与语言审核分别报告。

final_text来自最后通过语义检查的稿件。未通过时明确具体状态，不再缩写正文或新增未经审核的解释。问题回应默认在独立review.md，不能混入论文正文。

正文、回应、存在时的拟议方案和修改清单均纳入同一任务的审核范围与批次预算，不为每个文件重置2批。对changes.md的修改前后引文及精确定位作为protected_spans，解释必须匹配事实；生成式润色不得改动原文引述。变更解释的润色回写changes.json，再重生成changes.md并复查。

output_requirements增加各稿件覆盖、方案未验证身份、累计修改说明全部字段、每项原因与含义影响的实质要求。终审期间只要正文改动，就重建差异及修改说明；一批可含多稿件，但revision_rounds记本批实际迭代上限，不通过拆文件绕过预算。
