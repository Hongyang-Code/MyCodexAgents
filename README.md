# MyCodexAgents

个人 Codex 智能体配置库。默认以简体中文工作，强调来源可查、结论有边界和可读性。

| 智能体 | 用途 | 使用说明 |
| --- | --- | --- |
| PaperFigureAgent | 从自然材料构建和局部编辑原生 draw.io 科研图，含布局、路由与分层验收 | [使用说明](PaperFigureAgent/README.md) |
| XRWritting | 基于参考语料的学术行文风格检查、保真改写与修改说明 | [使用说明](XRWritting/README.md) |
| PPTMaker | 模板改制、材料重组与主题调研，制作可编辑PPT并逐页审核 | [使用说明](PPTMaker/README.md) |
| PaperReviewer | 多智能体审稿、质疑裁决、论文修订及累计修改说明 | [使用说明](PaperReviewer/README.md) |
| ResearchFieldSurvey | 至少20篇主干论文，方法路线、发展脉络与阅读路径 | [使用说明](ResearchFieldSurvey/README.md) |
| ResearchHotspotFollow | 研究领域近一周新论文四线追踪，每篇一条，轻量评估和文字审校 | [ResearchHotspotFollow/README.md](ResearchHotspotFollow/README.md) |
| NewsChaser | 指定时期的重要新闻简报，地区与领域双索引，事实核查及文字审校 | [NewsChaser/README.md](NewsChaser/README.md) |
| FundPilot | 场外基金研究基础模块、可审计账本、验证与条件通知；未正式部署 | [使用说明](FundPilot/README.md) |
| TextReadable | 保持原意的可读性与用语严谨性审校，支持其他智能体复用 | [TextReadable/README.md](TextReadable/README.md) |
| PaperReader | 论文概括、阅读价值判断、证据评估、详细报告和结构导图 | [PaperReader/README.md](PaperReader/README.md) |

这是可复用的目录指令和工具，不是独立模型服务。将智能体目录作为 Codex 工作目录，或在根目录明确要求读取对应 AGENTS.md。

GitHub 保存配置和工具；论文材料与产物、TextReadable 的真实输入与改稿、NewsChaser 的新闻产物与来源记录、ResearchHotspotFollow 的论文追踪产物与来源记录只保存在本地，被 .gitignore 排除。没有定时同步或 Zotero 集成。

目录指令机制参考：[OpenAI 官方 AGENTS.md 文档](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

共享 CCF 参考目录、版本限制和查询方法见 [目录说明](shared/references/ccf/README.md)。ResearchFieldSurvey 的真实材料与产物同样仅保存在本地。
