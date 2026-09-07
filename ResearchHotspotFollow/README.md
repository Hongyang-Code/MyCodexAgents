# ResearchHotspotFollow

按研究领域追踪近7天论文，帮助决定接下来读什么。默认四线扫描：CCF及其他重要期刊会议、arXiv、Hugging Face、其他相关论文。每篇独立成块、要点分行，包含速览、问题、方法、创新点、结果与可靠性、阅读建议。默认分层阅读，不调用PaperReader。

## 使用

> 请读取 E:\MyCodexAgents\ResearchHotspotFollow\AGENTS.md，追踪最近一周“图像配准”的新论文。重点关注大形变与无监督方法。

也可以只说“按ResearchHotspotFollow追踪最近一周研究论文”。它会优先采用当前任务中明确的领域，或标明根据上下文的推定；依据不足才询问。不会访问不到历史却声称记得你的领域，不保存未经确认的长期偏好。

可指定时间范围、子方向、排除主题、venue或论文类型。未指定时不限制条数；没有适合论文时如实报告。新预印本与正式发表、旧稿实质更新分开标记，跨平台同一篇只保留一条。

## 质量与开销

先看摘要与结论，短名单再查方法总览、关键实验与局限。每条都写已读范围，摘要级材料不能得出全面可靠性结论。CCF级别只作导航；精读建议依据实质贡献、领域作用或方法借鉴价值。

使用TextReadable的可选内容与格式接口，必须传入具体要求。默认最多3轮、每期最多2批。共享格式检查和本目录条目检查提供结构检查；语义与事实仍由当前智能体核查。

完整报告、来源、论文索引及审校记录留在outputs/，配置可版本管理。不默认运行论文实验、绘制导图、配置定时追踪或提交推送。需要精读某篇时再明确交给PaperReader。

## 验证

从仓库根目录运行：
python -m unittest discover -s ResearchHotspotFollow/tests -p "test_*.py" -v

人工内容与日期挑战见tests/acceptance.md。已完成“图像配准、最近一周”的有限覆盖联网试运行，确认收录1篇，记录旧文排除与访问缺口。详细状态见VALIDATION.md；结构测试不证明科研判断可靠。

## 发表信息与共享目录

读取 ../shared/references/ccf/README.md，使用其中的目录和查询脚本。每篇基本信息必须有作者、发表渠道简称、等级（含目录年份或不适用/待核实说明）、日期及版本状态、已读范围。按正式 venue 全名匹配，保留原始来源与等级查询记录；预印本不套用拟投会议等级。当前副本与官方勘误的一致性限制必须披露。papers.json 保存 venue_full_name、venue_abbreviation、ccf_grade、ccf_edition、ccf_lookup_status。
