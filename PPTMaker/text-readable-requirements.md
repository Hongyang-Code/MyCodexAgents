# TextReadable契约

完整读取../TextReadable/AGENTS.md及其要求文件。在当前任务执行output_mode=agent、max_rounds=3；整个PPT任务最多2批，样页计入。优先样页一批、完整稿一批；直接模式通常完整稿一批即可。检查预算不随页面数、角色或模式重置。

采用稳定三级标题 `### [S01] 页面标题`，每页包括独立行前缀：`**页面文字：**`、`**图表文字与数据：**`、`**讲解备注：**`、`**来源：**`。字段第一行有非空实际内容，允许下续列表；不适用写明原因。标题、原生图内标签/单元格/数值、成品图片说明和备注均需涵盖。实际显示以这些明确范围为准，不把内部字段名放上幻灯片。

output_requirements必须展开为真实内容：

- content：全局目标、全部S编号与顺序；逐页标题含义、必保留事实/限定、数字单位、图表数据、来源归属、哪些文字必须屏幕可见、哪些只在备注。每项有唯一id、scope、requirement，不能只写“完整”。
- format：unit_level=3，sections列全部实际三级标题与四个required_markers；document_headings按实际稿件列出。不仅传模板路径。
- protected_spans：逐字保护引用、公式、标识、数字、单位与来源URL。可读性优化不得增强结论、删除条件或将备注里的假设写成实测事实。

冻结copy-original.md与text-requirements.json，每轮双向核对。缺事实或有实质错误时返回PPTMaker核查，建立有依据的新基准并计入总批次。审校元信息放在正文外；requirement_results逐项记录原文位置、最终位置、检查依据与状态。语言passed不表示外部事实核实。

执行 `python ../TextReadable/scripts/check_format.py --text <copy-final.md> --requirements <text-requirements.json>`，保存结果与SHA256。漏页、缺字段、删必要条件或引用、改变结论强度均不能通过；后两者需要实质内容审查，不能用脚本或关键词自动保证。

终稿制作成PPT后核对屏幕与备注的位置、文字、数据及来源。排版导致删字、缩写、图注改动后须复查受影响要求；实质文字修订计入剩余审核预算。只改变位置大小且文字不变无需再启动文字批次。
