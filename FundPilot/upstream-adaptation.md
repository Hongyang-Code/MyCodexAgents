# 固定上游的基金研究适配

本入口实际调用 TradingAgents 原生研究节点，并通过 LangGraph 执行和恢复。它是历史诊断的局部适配，不是完整基金投资系统，也不证明研究有效。

## 保留 替换 简化

| 处理 | 实现与边界 |
| --- | --- |
| 保留 | 固定 TradingAgents e8f5503e9b86d5c2710b0c76b1f686703968c9df；直接导入 create_bull_researcher、create_bear_researcher、create_research_manager、AgentState、ConditionalLogic；使用原生 StateGraph、interrupt、Command 和 SqliteSaver。没有重写多空节点的状态更新和路由逻辑。 |
| 替换 | 股票行情、财报和新闻工具不装入图；调用方提供基金公开证据包。模型边界替换股票提示，保留原节点插入的证据与辩论历史，加入未知价、类别、渠道、费用、确认到账及历史污染限制。股票工具代码仍随依赖安装，但本图不暴露工具执行入口。 |
| 简化 | 一轮多空、一个研究经理，共三份响应；不运行 Trader、风险投票、Portfolio Manager、股票策略、自动记忆反思或交易接口。资金模拟独立复用已有 conditional_value。 |

这是对原生节点的有限图组合，不声称运行了完整 TradingAgentsGraph 或完成全部股票工具替换。经理沿用上游只接收辩论历史的设计；尚未验证证据压缩是否遗漏重要资料。

## 实际当前 LLM 桥接

无API密钥时，图在真实节点的llm.invoke边界产生interrupt，保存提示及SHA256。当前会话LLM读取提示，实际生成响应并记录真实时间、模型标识和提示哈希，再由新进程resume。它不调用上游原生LLM API，不伪造SDK调用或usage。模型精确快照未知时明确unknown。

每个响应只接受actual_current_llm或synthetic_fixture；这些身份声明需要外部记录核验，程序不能证明文字究竟由谁产生。合成测试记录synthetic_fixture，不当真实模型。每图最多三份响应，失败保留，不自动修复重试；该限制不能替代调用方跨运行私有预算。没有完整旧候选历史时，禁止用新目录重置七天结构候选额度。

命令在仓库根目录执行，真实输入、输出、检查点及响应全部放在checkout之外：

```bash
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge start \
  --evidence /private/evidence.json --output /private/new-graph \
  --upstream /private/pinned-tradingagents
PYTHONPATH=FundPilot /private/venv/bin/python -m fundpilot.upstream_bridge resume \
  --root /private/new-graph --response /private/actual-response.json \
  --upstream /private/pinned-tradingagents
```

start的证据包含fund、information_cutoff、market_report、fundamentals_report字符串，可含context和news_report；本轮只允许一基金。响应含producer、model_ref、generated_at、prompt_sha256、content。generated_at是实际带时区生成时间，不倒填到历史。生成完毕后保存result.json、输入原字节及receipt。所有请求、响应和SQLite检查点均属私有研究材料。检查点恢复已测同云主机不同进程，尚未验收跨机器或定时恢复。

调用前检查上游git SHA、已跟踪文件洁净状态与导入路径。设置LANGCHAIN_TRACING_V2和LANGSMITH_TRACING为false，不创建模型客户端、不读取认证文件、不启动服务器。目录和文件使用0700/0600；这些权限和哈希不等于远程不可篡改存储或完整安全沙箱。传入的私有父目录与存储权限须由调用方核实。

## 安装 许可证 与对照

TradingAgents和FinRobot指定版本均为Apache 2.0。此次使用独立checkout及venv实际安装，依赖快照在integrations中；两项目不混装，避免模型SDK版本冲突。上游安装脚本与广泛依赖不构成安全审计通过。本适配通过导入链接原项目，不复制上游源码；没有使用其名称或标识作为本项目品牌。若将来分发上游源码或制品，须保留其LICENSE、NOTICE和适用修改声明，并遵守商标政策。

FinRobot V2固定2717499b8e30f242640af08c4ad9afd1113c2d45。已安装finrobot_desktop并执行离线数值边界测试；其桌面壳、自动代码执行、股票估值工具和真实模型均未启动。这是有限工程对照，未运行FinRobot基金研究或复现其收益。

TradingAgents原生chatgpt_auth和README描述SIWC；OpenAI官方https://developers.openai.com/siwc亦说明合格开源应用可使用ChatGPT套餐。本轮没有登录、读取现有凭据或调用原生认证。若后续改用原生SIWC，需另由用户本人在官方流程授权；不得从Windows或其他工具复制令牌，也不以当前桥接等同完成认证。

## 真实历史诊断与固定验收

本轮私有运行使用一个公开基金研究对象、官网原始HTTP、三份真实当前LLM响应、实际生成/冻结时间、一个预冻结窗口和一次条件估值。之后才完成目标值诊断与净成本比较；抓取页面本身已经包含后续历史，当前会话及更大项目可能已见结果，故全程retrospective、reused_development、non-OOS。模型参数历史记忆污染不能靠裁剪材料消除。真实来源、预测、协议、结果、错误及状态不提交Git或公开CI。

现金、买持、固定trend20和LLM条件分配使用同本金、窗口、基金机会及费用假设。trend20在该窗口的冻结规则对应买持相同分配，复用同一估值路径，不另做参数搜索。暴露差异单列；较低暴露不能直接解释为预测优势。费用未核实、分红拆分未知、类别与渠道及完整估值日历缺证据，严格资格pending。未知确认与到账不计作可用现金，NAV内部费用不重复扣除。不把条件NAV估值当实际可执行净收益，不以观察对象代替真实初始持仓。

一次有据改动限定为工程字节保留：原实现对输入重新序列化，却用原字节生成receipt哈希；非规范JSON可导致保存件与receipt不符。修改为保留原始输入字节，固定合成负例和不同进程恢复测试通过。真实历史结果未因这项修复重调；研究结构候选因旧七天记录未知保持阻塞，不将工程修复称策略改善。

历史验收固定12个月扣费不亏概率目标95%、严格超同期中国全国CPI目标90%、单侧95%置信下限和单位化最大回撤5%。独立全胜样本的精确下限为0.05**(1/n)，分别至少59和29个；相关、重叠及调参后数据不能套独立二项公式。验收模块与精确统计由主任务独立维护，本适配不定义晋级算法。短窗口、LLM自报概率或工程测试通过均不能验收。

本轮未取得合格12个月独立样本、同期全国CPI或全部交易机制证据，项目未完成。没有创建前瞻、正式投资、真实交易或自动续跑任务。普通Work Linux容器不能声称已绑定已发布Codex Cloud环境。

## 合成复验

```bash
PYTHONPATH=FundPilot FUND_PILOT_UPSTREAM=/private/pinned-tradingagents \
  /private/venv/bin/python -m unittest discover -s FundPilot/tests -p test_upstream_bridge.py -v
```

实际导入固定上游节点，分别以新子进程开始和恢复三次，核对多空顺序、计数、原始输入哈希、错误响应拒绝、完成后拒绝再响应及合成身份。未安装可选依赖或未指定checkout时，该集成项明确skip，不用mock代替安装。验收统计与污染/重叠拦截的测试由主任务单独负责。手动结果与GitHub CI状态分开报告。


## 私有路径与恢复证据加固

v2桥接拒绝checkout内的真实或合成输入、响应和输出；路径逐组件通过O_NOFOLLOW及目录描述符打开，不跟随父路径或文件符号链接，拒绝父目录跳转。直接数据父目录必须当前用户所有且无任何组/其他权限；文件必须同属当前用户、普通文件、无组/其他权限且硬链接数为1。系统上层目录可为共享遍历目录，不能把它直接用作私有数据父目录。SQLite、WAL及SHM等已存在图目录内容同样检查，新建SQLite及侧文件使用私有权限。检查失败不会悄悄chmod补过门槛。

resume先核对input.json原字节与receipt哈希，再与SQLite检查点的输入/receipt元数据锚点和原始证据字段核对。逐份已保存请求须匹配其指定历史检查点的实际中断；当前请求还须对应最新检查点。历史响应亦核对提示哈希、捕获/生成时间及检查点中的辩论内容。修改输入和receipt两者仍会因检查点锚点不符而拒绝。不创建缺失的恢复数据库，不把新空图冒充恢复。

请求第一次进入真实节点中断时捕获带时区captured_at，并持久保存。LangGraph重放从原请求复用该时间；响应生成时间须不早于该原始捕获时间且不晚于实际检查时间。时间检查在保存响应前执行，拒绝旧响应而不误拒绝晚于原捕获、早于重放的合法响应。旧v1记录缺少这些证据时失败关闭，不自动迁移或改写旧真实研究。

新增实质回归覆盖checkout、父/叶符号链接、非私有目录/文件、硬链接、FIFO、原始输入/receipt单独和协同篡改、请求时间/提示/检查点ID篡改、历史请求/响应篡改、检查点原证据改变、过早响应，以及跨进程重放复用捕获时间。均使用合成输入和真实安装的上游图，无新增真实LLM/来源请求、历史收益计算或结构候选。私有权限和本地相互核对仍不能防同一文件所有者同时改写所有证据，不宣称远程WORM或完整抵御同uid攻击。
