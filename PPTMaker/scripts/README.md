# 检查接口

使用标准库Python；结构检查不调用外部模型或自动修改文件。路径由调用方提供，真实要求与记录留在该任务输出目录。先读取AGENTS.md完整流程，检查器不能独立完成制作或审核。

## 文件检查

`python scripts/check_deck.py <最终PPTX> --requirements <requirements.json>`

要求格式schema_version=1，slide_count等于完整slides列表长度。slides按最终播放顺序列出，id用S01等稳定标识。visible_contains检查原生页面文字，notes_contains检查对应页备注，二者不能互相替代。原生成品图片内部文字不要求OCR匹配。表格文字可通过visible_contains保护，图表缓存数值用chart_values保护。

```json
{
  "schema_version": 1,
  "slide_count": 1,
  "size_emu": [12192000, 6858000],
  "slides": [{
    "id": "S01",
    "visible_contains": ["合成结果", "未做显著性检验"],
    "notes_contains": ["合成材料"],
    "forbidden_text": ["旧项目标题"],
    "native_min": {"text_shapes": 2, "tables": 1, "charts": 1},
    "object_names": ["title"],
    "chart_values": [[0.8, 0.82]],
    "chart_y_ranges": [[0, 1]],
    "embedded_chart_data": true
  }]
}
```

native_min支持text_shapes、tables、charts、connectors、pictures、equations；只为实际需要的对象设置数量。成品图片不需要表格/图表豁免，不声明不存在的原生对象即可。方法图可声明对象名称与连接线数量，连接方向仍须人工及视觉核查。复杂分组变换、重叠和字体依赖技能检查器与实际预览，不能用数量证明美观。

输出status、errors、warnings与文件/要求哈希。超出页面边界和缺少保护文字会失败；文字密度只提示，不以字数阈值自动删信息。必须记录提示的处理依据。

## 交付门槛

`python scripts/check_delivery.py <review.json>`

review.json schema_version=1。所有文件引用均为`{"path":"批次内相对路径","sha256":"真实哈希"}`，不允许指向批次外。实际例子见本地验收批次记录，合成契约测试见tests/test_checks.py。

必填字段：mode(template/materials/topic)、interaction(collaborative/direct)、approval(state及用户原话evidence)、pptx、finalizer（技能检查收据）、requirements、copy_sha256、visual_revision_rounds、text_batches、checks、slides_reviewed、unresolved。template另需changes文件与checks.template；topic另需sources文件。finalizer须绑定同一最终PPT且结构、布局及重新导入检查通过。

- approval.state：协作模式为confirmed，直接模式为direct_authorized；记录授权依据，检查器不替用户确认。
- text_batches：1～2项，每项含revision_rounds(0～3)、original、final、requirements、result四个文件引用。TextReadable结果依其接口保存，另记录original_sha256；requirement_results必须逐项覆盖content并有evidence，不能仅留状态。最后一批final哈希必须等于copy_sha256。
- 最后一批的sections须按顺序覆盖全部最终S编号，代表页的一批不能代替整套审核。
- checks：facts、coverage、narrative、copy_to_deck、editability、visual逐项含status与具体evidence，所有必要项pass。template模式另有template。语言通过不能替代这些判断。
- slides_reviewed：按播放顺序列全部页面，每项含id、image文件引用、pptx_sha256、status、evidence。只绑定实际查看的最终PNG，不伪造查看记录。
- warning_dispositions：有结构密度提示时记录处理。unresolved有内容则整体失败；此时可交有明确限制的草稿，不能标最终合格。

checks还必须包含design，记录具体参考/模板对照和设计判断依据。几何及visual检查不代替此项；格式检查器只能拦截缺记录，不能客观证明美观。

### 固定风格美观度记录

所有新交付须有design_review；旧记录不自动获得通过状态。字段如下：

- status=pass、pptx_sha256绑定最终PPT。
- references为非空列表。每项kind为reference或template，source为链接或文件路径，pages为实际查看页码的文字说明，viewed=true；adopt写借鉴关系，avoid写不适用之处或不需偏离模板的理由。新设计按visual-reference-review.md选择参考，模板模式必须实际对照模板。
- slides按最终顺序覆盖所有页面。每项id、status=pass、image（与slides_reviewed同页完全一致的文件引用）；dimensions包含composition、hierarchy、color、typography、visual_expression、alignment，各有status=pass和具体evidence。
- whole_deck含consistency、rhythm、reference_fit三项，各有status=pass和具体evidence。
- issues显式列表，无则[]。每项id唯一，scope为页面ID或whole_deck，finding、impact、action、recheck说明问题、影响、处置及实际复查。status仅resolved或rejected可通过；后者须在action与recheck说明驳回依据。
- user_style_feedback含state和evidence。state为pending、accepted或rejected；pending注明用户尚未审阅或未明确认可，直接模式允许通过。accepted须有用户明确反馈，rejected阻止交付。内部判断不能代填用户认可。

逐页图片引用已由slides_reviewed验证实际文件哈希，设计记录须与其匹配。缺页、缺维度、未查看参考、未决缺陷和旧版本均阻止交付；脚本不能证明记录真实或美观程度。文字/视觉修订上限仍沿用原预算。

检查器重新读取PPTX和文字契约并核对哈希，不仅相信旧pass。记录完整性不证明来源和视觉判断真实，需要当前任务实际检查并诚实记录。技能finalizer记录、目标应用实际运行状态另存并在验收中说明。

## 严格听众审查记录（所有新交付必需）

review.json增加必填audience_review。旧记录缺少该项时不能通过新门槛，不自动补写pass。其字段：

- status必须为pass；target_audience、reviewer_profile、basis分别记录目标听众、严格审查角色及推定依据。
- pptx_sha256、copy_sha256绑定本次最终PPT与审校文案；revision_rounds为0～3的整数。
- dimensions包含evidence、reasoning、comparisons、communication、purpose五项，各有status=pass及具体evidence。范围见audience-review.md。
- slides按最终页面顺序列全部id，每项包含status=pass、question和evidence，记录最重要的追问及核查。无问题也记录审查依据。
- issues显式列全部已发现问题，无则空列表。每项含稳定id、scope（实际S编号或whole_deck）、question、evidence、impact、severity、decision、action、recheck和status。只有resolved（已修正复查）或rejected（有据驳回）可以通过，未决状态阻止交付。删除历史问题或只改状态不能代替实际修正。

脚本验证记录、覆盖、问题处置和版本绑定，不验证专业判断真假。审查失败只报告阻塞；用户明确要求时才交付标注失败的草稿。代表页可保留待用户确认状态，但不得伪造整套审查通过。

## 渲染辅助工具

`node scripts/render_deck.mjs <最终PPTX> <新的预览目录>`，先用配套运行时路径设置RUNTIME_NODE_MODULES。工具重新导入指定文件，生成每页PNG、整套overview.webp及绑定PPT/图片哈希的render-manifest.json；拒绝覆盖已有预览目录。导出成功只证明渲染完成，仍须实际查看每页和整套预览。

## 测试

`python -m unittest discover -s PPTMaker/tests -p "test_*.py" -v`（仓库根目录）

tests/make_examples.mjs仅供合成/公开验收材料制作，使用load_workspace_dependencies给出的SKILL_DIR、RUNTIME_NODE_MODULES、RUNTIME_PYTHON，以及绝对PPTMAKER_RUN输出目录。先运行当前Presentations技能要求的制作登记，再运行source、template、materials、topic阶段。每次使用新输出目录，禁止覆写旧最终文件。模板阶段须先实际查看source预览；topic实际资料核验与审校不能由这个脚本代做。
