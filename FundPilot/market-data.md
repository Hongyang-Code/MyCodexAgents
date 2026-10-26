# 市场数据与可获取时间契约

版本：2026-10-23 / market-schema-v1。当前实现为**明确审阅的 JSON / CSV 导入**；不表示已部署无人值守官方抓取，也不保证全部基金覆盖。

## 已完成的公开来源验证

2026-10-23 13:06 UTC，对[华夏基金官方历史净值页](https://www.chinaamc.com.cn/product/fundLishijingzhi.do?fundcode=000001)执行只读 HTTPS 请求，读取公开分页 `pageIndex=1..7`，每次至少间隔一秒，单请求20秒超时、2MB上限，无登录、无凭据、无 JavaScript 执行。获取000001共140条日期，范围2026-03-27—2026-10-23，覆盖超过六个月。用于验证公开采集可行性，不代表用户持仓。

原始 HTML、逐页 SHA-256 和真实获取时间仅存在本次私有工作区 `/workspace/shared/fundpilot-market-evidence/`；不提交 Git。此工作区不等同经过验证的长期备份。页面可能修订、缺行或暂时不可用；当前未完成交易日历逐日完整性、份额类别和分红事件核对。

**历史页面没有每条数据原始发布时间/历史可获取凭据。** 今日获取的数据不得倒填为历史当日已知，也不得称为已通过无泄漏半年预测回放。可以用于标明局限的事后价格描述研究；正式 walk-forward 需要独立时点档案和完整分红、费率、可交易日证据。搜索引擎缓存可能落后于直接请求，不能把缓存时间当官方发布时间。

## 程序接口

`fundpilot.market.NavRecord.from_dict(row)` 与直接构造均执行相同校验。

必需字段：`fund_code`（6位字符串，保留前导零）、`share_class`（必须由证据确认，禁止按名称猜A/C）、`nav_date`（YYYY-MM-DD）、`unit_nav`（有限正数）、`source_url`（HTTPS）、`source_version`（非空版本）、`raw_sha256`（原始证据SHA-256）、`retrieved_at`、`available_at`、`reviewed_by`、`reviewed_at`。时间须ISO-8601且带时区，内部归一UTC。

可选：`published_at`（未知填null，禁止用净值日期代替）、`cumulative_nav`、`distribution_per_unit`、`distribution_status`（unknown / verified_none / verified_cash）、`currency`（默认CNY，非人民币须明确填写）。累计净值不能直接当成分红再投资总回报指数。未核对分红时 `distribution_status=unknown` 且分红值null；确认无分红才允许显式0；分红公告和除息日应与原始证据一同归档。

- `import_reviewed(path, reviewer=..., reviewed_at=...)`：只支持JSON数组/CSV，UTF-8，最大8MB；明确审阅后导入，不会抓网页或执行公式/脚本。字段错误、未知字段、重复版本行均拒绝。
- `verify_raw_evidence(record, raw_bytes)`：显式核对原始字节哈希。导入器只验证格式，**不会自行证明来源真实性、哈希内容或份额类别**；调用者必须审阅后批准。
- `available_as_of(records, cutoff)`：严格同时检查可用、获取、审阅时间。v1强制 `available_at >= retrieved_at`，不支持回填古老 vintage；即使提供历史公开日期，也不能绕过。
- `latest_known(records, cutoff)`：按基金代码和份额类别返回最新已知净值，保留实际净值日期；不补齐周末、节假日、不插值、不把陈旧值标成今日。相同时点版本冲突拒绝。
- `record.to_dict()`：可序列化对象，Decimal以字符串保存，避免无声浮点精度变化。

## 每日21:30 Asia/Shanghai

21:30为研究触发时间，不能保证当日净值已出齐。每只基金报告 `nav_date/retrieved_at/available_at`，未更新就保留陈旧标记，不以估算净值结算预测。周末、跨市场节假日、QDII延迟、暂停估值分别处理。[华夏QDII招募说明书示例](https://accountquery.chinaamc.com/upload/resources/file/2025/05/29/015299_%E5%8D%8E%E5%A4%8F%E7%BA%B3%E6%96%AF%E8%BE%BE%E5%85%8B100%E4%BA%A4%E6%98%93%E5%9E%8B%E5%BC%80%E6%94%BE%E5%BC%8F%E6%8C%87%E6%95%B0%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91%E5%8F%91%E8%B5%B7%E5%BC%8F%E8%81%94%E6%8E%A5%E5%9F%BA%E9%87%91%EF%BC%88QDII%EF%BC%89%E6%8B%9B%E5%8B%9F%E8%AF%B4%E6%98%8E%E4%B9%A6%E6%9B%B4%E6%96%B0%EF%BC%882025%E5%B9%B45%E6%9C%8830%E6%97%A5%E5%85%AC%E5%91%8A%EF%BC%89.pdf)明确存在T+2内公告安排；示例不能代替用户具体产品的现行合同。

自动抓取适配器为后续工作：须核对官网路径白名单、合法使用条件、交易日历、失败退避、响应体限制、禁止跨域重定向和SSRF，连续保存原始快照，不能以隐含API稳定性作承诺。当前程序没有网络抓取入口；公开可行性验证与生产自动采集分开验收。
