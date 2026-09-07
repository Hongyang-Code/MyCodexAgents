# NewsChaser

按指定时期整理重要事件，输出事实陈述为主的中文新闻简报。不设事件数量配额，支持地区与领域双索引。

## 使用

> 请先读取 E:\MyCodexAgents\NewsChaser\AGENTS.md，整理最近一周的重要新闻，完成来源核查和TextReadable审校。

> 请按NewsChaser流程整理2026年9月1日至9月7日的新闻，关注欧洲和东南亚，领域为经济与金融、科技与科研。

未指定时间默认检索开始前7×24小时，北京时间。未指定筛选则广泛覆盖；不按历史兴趣自动个性化。只在发起任务后检索，不持续后台运行。

这是目录指令流程，由当前任务执行，不是独立模型/API服务。跨目录复用TextReadable采用显式读取，符合仓库已有方式；[官方目录指令说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

## 文件和输出

入口AGENTS.md；流程workflow.md；分类taxonomy.md；门槛quality-check.md；templates/供填充；tests/acceptance.md是合成验收挑战，VALIDATION.md记录真实验收范围。

每期保存在 outputs/YYYY-MM-DD_HH-mm-ss/：report.md、sources.md、events.md、.cache/quality-review.md。outputs/event-index.md用于跨期事件ID与状态；旧报告保留，更正可追溯。真实材料、索引、产物和缓存被Git排除。

## 陈述边界

不写智能体立场、赞贬、建议或自行预测。引述明确说话者，起因和影响必须有来源。重要争议按证据呈现，不机械对半分配观点。来源多样和透明筛选降低偏差，但不保证绝对中立或全球无遗漏。

事实核查后才进入TextReadable，默认3轮、最多2批；词句审校通过不等于新闻事实核查或覆盖通过。窗口内材料不足时如实部分交付。

不自动提交推送、定时通知或启动子智能体。

## 内容与格式检查

TextReadable 同时接收完整正文和本目录 text-readable-requirements.md 展开的要求。逐项实质覆盖与结构脚本分别检查，最终交付保留已审版本。缺少原始信息会返回本智能体核查，不能靠文字润色补全。
