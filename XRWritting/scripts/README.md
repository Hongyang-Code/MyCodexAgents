# 辅助检查接口

使用Python标准库，无模型调用。运行：

```powershell
python E:\MyCodexAgents\XRWritting\scripts\check_result.py <original.json> <result.json>
```

真实文件放本目录outputs/下，不加入Git。原稿单独保存，不能由最终改稿反向生成。schema_version=1。

original.json包括max_rounds（默认3）、units列表。每个单位含id、text、可选protected_spans。单位可取完整章节或段落；revised内可以拆句分段。检查器不支持跨单位重排，需重组时把完整重组范围选为一个单位，且保存之前的逐段去向核对。原稿确定后不能为避开保护检查改基准。

result.json字段：

- status：passed / needs_clarification / not_passed / checked_only。style judgment为原稿判断，不假装通过结果本身等于教授认可。
- judgment：基本符合 / 部分符合 / 明显偏离 / 材料不足无法判断。
- units：按原顺序列全部id与revised（完整正文）。
- original_sha256、final_sha256：各单位正文按两个换行连接后UTF-8哈希。
- style_revision_rounds：实际修改轮数。0轮但有改动会被拒绝；没有最终改动仍可能记录多轮往返。
- issues：unit_id、kind（style/language/content）、observation；style含rule_id（XR01～XR10），内容问题未决时state=unresolved。
- changes：每个最终有变动的单位一项，含unit_id、before、after、reason。before/after为该单位完整文本；详细句子对照另在报告展示。未变化单位不得伪造改动。
- text_readable_batches：最多两项，各含status、revision_rounds（0～3）、final_sha256；passed必须绑定最后受检正文。
- review：semantic_fidelity、style、readability、requirements、claim_strength，各含status与具体evidence。
- unresolved：未决项列表；overall passed时必须为空。

数字检查比较每单位的数值字面集合；保护项必须在原稿和终稿逐字出现。术语重复可在保真前提下合并，因此不要求出现次数相同。引语、重复术语及引用的全部所属主张仍需人工逐项核查。数字的“含义、归属、百分点、比较方向”和英文数字词均无法由此证明。公式、术语、引语及引用请列入protected_spans。若数字确需改动，返回用户或有据处理源问题，不能删除保护项绕过。

脚本只校验记录完整性，不会运行TextReadable或判定内容/风格。即使把may改成proves，字面检查也可能通过，必须由实际语义审校拦截。不能把填好的pass字段当实际运行证据。

测试：

```powershell
python -m unittest discover -s E:\MyCodexAgents\XRWritting\tests -p "test_*.py"
```

合成试读输出仅证明本次这些案例表现，非真实作者风格的统计验证。验收报告分开记录脚本结果与人工检查。
