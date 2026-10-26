# 十二个月历史验收

本入口只计算已登记样本的验收结果，不执行交易、不抓取真实资料、不运行模型，也不授权现实指导。真实开源LLM适配仍须独立实跑。原有短期Brier/方向评分保持不变。

## 固定标准与解释

固定12个月扣费不亏目标0.95、严格跑赢同期全国CPI目标0.90、单位化最大回撤上限0.05。分别使用单侧95% Clopper-Pearson精确二项下限；每项下限达到目标才满足该项数值门槛。两项置信区间分别解释，没有声称同时覆盖率为95%。未见样本假设、未来市场稳定性和风险上限均不能由公式保证。

全部成功时下限为0.05**(1/n)：达到0.95至少需要59个独立成功样本，达到0.90至少需要29个。它们只是理想独立模型下的最低全胜数量；多只基金同一窗口、重叠月份及调参后样本不能用来凑数。独立性、代表性、历史可得性及模型记忆边界须外部证据审查，不能凭布尔自签证明。

## 最小输入

schema_version=1；test_only必须显式布尔；data_role可为synthetic、reused_development、retrospective_diagnostic、untouched_historical_validation。

每个episodes条目携唯一id、start/end、net_liquidation_return、unitized_max_drawdown、source_refs和cpi_monthly。收益与回撤为小数比例；收益须由已核实基金模拟器提供，含适用退出费用与分红，外部出入金先单位化。本入口不重新模拟资金或自行验证收益真实性。

v1只支持月末至次年同月末的12个月窗口，避免猜测每日CPI。cpi_monthly提供之后连续12个月的month(YYYY-MM)、basis=month_on_month_fraction、change，以连乘计算同期涨幅。不能将单月同比或全年平均同比直接替代。净值归属、可得日期及月末估值覆盖由上游审核；v1不会把缺失价格前向填补。

缺收益、CPI、回撤或来源保留条目和独立分母；不静默丢弃。不同基金同时段也判重叠，不能增加独立样本数。相邻窗口不重叠仍不自动证明独立，仍需审查。

reviews逐项携status=verified及非空evidence_ref：frozen_protocol、all_registered_episodes、independent_sampling、untouched_validation、model_memory_boundary、point_in_time_inputs、fund_and_channel_rules、costs_and_distributions、unitized_external_flows、cpi_precision。引用内容、完整登记表和审查者真实性必须实际核对；本模块只校验声明格式。

## 输出和边界

- synthetic_only：合成测试，即使数值达标也不是真实通过。
- pending_evidence：开发/回顾性数据、缺资料、重叠或资格不足；下限仅作条件描述。
- pending_sample_size：合格样本点估计达标，但下限不足。
- not_met：合格观察中收益频率或回撤不满足要求。
- historical_gate_passed：外部资格声明与数值均满足历史门槛；仍不证明未来、部署或项目完成。

所有状态都固定project_complete=false、real_guidance_authorized=false。用户最新要求是历史研发通过前不进入现实指导；本入口没有绕过该边界。遇到LLM历史记忆风险不能核实时，model_memory_boundary必须保持未核实。

公开环比的舍入误差可能使连乘值与官方同月同比有差异。靠近通胀边界且误差未排除时，cpi_precision不得签verified，应使用更高精度的官方同基期指数核验，保持pending；本入口不把舍入值当无误差真值。

公式出处：[NIST精确二项区间](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm)。CPI连接关系：[国家统计局编制方法](https://www.stats.gov.cn/zs/tjws/zytjzbqs/jmxxggzs/202411/t20241127_1957589.html)。

## 运行

Python接口：from fundpilot.acceptance import assess。现有263项测试无需安装额外库即可运行；新增测试只使用合成记录。

私有CLI：

```bash
PYTHONPATH=FundPilot python -m fundpilot.acceptance --input /private/fundpilot/qualified-episodes.json --output /private/fundpilot/new-acceptance-run
```

输入须在checkout外，父目录0700、文件0600且不得有符号链接。输出必须是新目录，结果文件0600；不能覆盖旧评价。CLI只输出状态与路径，不打印真实内容。输入JSON为上述schema，示例结构及边界见tests/test_acceptance.py，不能把合成示例改名当真实证据。

此程序是验收工具，不是金融预测Agent；真正模型接入、完整基金费用规则、历史数据验证及独立审查仍是必要条件。
