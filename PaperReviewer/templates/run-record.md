# run.json 字段约定 v2

UTF-8 JSON对象；只记录可核查摘要，不记录冗长内部推理。SHA256按实际文件字节计算（含换行），不能随意编造。完整合成构造见tests/test_run.py。

| 字段 | 内容 |
| --- | --- |
| schema_version | 当前记录固定为2；旧v1只保留历史，不冒充多智能体验收 |
| requested_rounds | 用户N或默认3，正整数 |
| round_mode | max / exact |
| original_sha256 | 第一版原文字节哈希 |
| rounds | 按number=1开始连续记录；每项含input_sha256、output_sha256、no_progress布尔、recheck说明及issues列表、submissions列表 |
| completion_status | checked / partial / needs_input |
| stop_reason | resolved / max_rounds / stagnation / awaiting_evidence / needs_input / user_stopped / role_failed |
| unresolved_ids | 所有轮次最新状态仍未解决的问题ID，排序去重；不能因后轮没重提就消失 |
| text_readable_batches | 最多2个，每项revision_rounds=0至3，status为passed/not_passed/needs_clarification |
| checks | content、coverage、readability、semantic_audit、format各项pass/fail/unknown；format含实际适用的人工或源格式检查，不等于Markdown脚本 |
| final_sha256 | 交付正文实际字节哈希 |

issues每项包含id、priority（critical/major/minor）、location、question、basis、impact、verdict、state、action、response、recheck；未解决还须有next_step。verdict映射：supported=成立、partly_supported=部分成立、unsupported=不成立、insufficient_evidence=证据不足。state为resolved/open/awaiting_evidence。部分成立须在basis与action分开处理两部分。

同一问题跨轮沿用ID，每轮内不重复；状态与证据更新有复查依据。输入输出哈希链连接每轮；最终语言审校可改变正文，因此final_sha256另记，并通过TextReadable记录绑定其冻结输入与最终稿。

脚本报告pass仅表示记录形式及已声明状态一致。事实、语义、来源真实性、轮次是否真实执行、适用检查是否遗漏由内容审核负责。


## 独立角色提交

rounds[].submissions按reviewer_a、reviewer_b、editor顺序记录。每项含role、实际agent_id、status=completed、input_sha256（该轮冻结稿）、report_path（run.json所在目录内的相对路径）、report_sha256。两位审稿人及修订者本轮ID不能相同；审稿人跨轮必须新建上下文。编辑者可在同任务后续轮复用，但必须收到新裁决和版本。

提交文件可保存完整原始回复；如只保存结构化摘要须注明由主任务从实际回复转录/归纳，不能声称逐字原件，不能增添角色未提出的结论。角色执行失败记录在attempts并以role_failed终止，不计为已完成轮次。CLI核查提交文件存在、在目录内、哈希一致；这不能单凭记录证明模型执行真实性，验收还须保留工具调用依据。

artifact_checks分别记录manuscript、responses、changes、proposal的pass/fail/unknown。无proposal可not_applicable，其他三项不能豁免。checks仍记录全文科研判断与语义审核；报告partial可以通过记录一致性检查，但不代表研究可靠性全部通过。

## 累计清单与命令

changes.json使用独立schema_version=1，含original_sha256、final_sha256、entries和no_changes_reason。entries每项为id、location、hunks、operation、reason、meaning_impact、issue_ids。hunks中保存确定性的差异ID、原/新行半开区间、before、after精确文本。operation使用add/delete/replace/split/merge/reorder/limit_claim/format；移动把源和目标差异合并解释。机械改动可合并多个hunk，实质改动仍逐项解释。issue_ids引用本任务问题ID，纯语言调整可以为空但原因不得为空。

从PaperReviewer目录运行：

1. `python scripts/change_manifest.py draft <原稿> <终稿> <changes.json>`，生成待解释骨架。
2. 主任务依据实际修改填写位置、原因、含义影响及问题ID；不是运行脚本自动认定修改正确。
3. `python scripts/change_manifest.py render <原稿> <终稿> <changes.json> <changes.md>`。
4. `python scripts/check_run.py <run.json> --final <终稿> --original <原稿> --changes <changes.json> --change-report <changes.md>`。

所有路径使用真实文件。最后一条同时核对正文哈希、实际角色报告、轮次、问题状态、清单覆盖及可读报告。对二进制论文，用明确绑定源文件版本的文本投影进行文字差异核对，版式和非文本对象另行检查。
