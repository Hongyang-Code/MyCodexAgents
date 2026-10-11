# 内部状态（由Agent维护）

用户不用填写此规范。每任务单独目录，start生成时间+随机ID；不共享科学模块、数据、要求、坐标。brief记录原话/模式/展示宽度；assets记录来源、真实哈希、角色和数据变换；state记录当前阶段、优化轮次和快照；revisions不可变。

## semantic_graph.json

nodes每项id、label、type、evidence必需，type为process/data/tensor/decision/state/storage/annotation/image；可选role（语义配色）、parent（组ID）、asset_id。edges每项id/source/target/kind/evidence，kind为data/control/supervision/spatial/grouping，可选label、feedback、source_port/target_port。feedback必须有科学依据，不为通过DAG检查随意指定。

groups每项id/label，当前自动布局支持一级语义分组；手工原生编辑可保留更多层级。page_id默认main；unresolved列真正未决科学事实。来源位置写如“用户原话第2句”“PDF第4页图2/§3.1”，不能只写“论文”。布局或颜色判断不伪装成科学证据。

可选alignment_groups为{axis:x或y,ids:[节点ID],tolerance:编辑器单位}列表，约束中心线；由宿主根据布局要求填写，不能无依据强迫所有节点排一行。几何报告记录实际印刷字号与近似空白比例，后者只辅助视觉判断。

## layout_plan.json 与 style_guide.json

nodes为id到{x,y,w,h}的绝对坐标映射；构建时自动换成组内相对坐标。edges为id到source_port/target_port/points/label_offset/route_reason的映射。候选算法支持LR/TB与显式反馈；用户草图或更复杂布局由宿主给定坐标后运行plan(graph,boxes=...)避障。不能用节点坐标推断科学边。

style_guide包含display_width_mm、font_pt、font、background/text/edge、group_fill/group_stroke，以及roles下每个语义角色的fill/stroke/text。缺省为中性外观，样例配色不绑定核心。物理字号换算后仍按实际导出边界复查。

assets每项id、path或source、sha256、role。image组件必须用path、受支持栅格格式和真实哈希；role说明user_image/derived/conceptual等。派生素材另存transform及parameters/data_source，不伪称真实输出。

## requirements.json

每项id、text、source、objects、status(active/superseded)、supersedes。可增加checks：kind=label时{id,value}；kind=edge时{id,source,target}。自动约束只覆盖可直接检查部分；全部有效要求必须在host-review中逐项语义核对。

## host-review.json

- figure_sha256：当前.drawio哈希；baseline_hashes复制本次qa_report基准哈希。
- scientific、visual_full、visual_print、history各为{status:pass/fail/not_run,evidence:具体依据}。visual项写构图、主次、配色、字体、阅读路径、贡献和缺陷修正，不能只写好看。
- requirements：每个active要求的{id,status,evidence}，完整且不重复。
- native_render：实际render收据（PNG预览），包含源/输出哈希、工具、状态。PDF/SVG收据另存。
- edit：{status,evidence}，not_run如实解释环境障碍；patch单测与UI实测分开。
- unresolved：未解决事项列表。优化轮次只从state.json取值。

deliver检查基准和图都未变化、必要项目通过；交互编辑not_run可交付但必须展示限制。原生渲染失败、科学/结构错误等只能使用--problem交付明确的问题版本。qa_report包含检查范围，不把内部一致性称为科研正确性证明。
