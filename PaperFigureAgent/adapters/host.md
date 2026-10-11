# 宿主适配

当前已实际使用：Codex对话模型读取自然输入并生成内部图谱，文件工具运行Python，view_image读取原生PNG，联网核实官方draw.io接口。无固定模型名称、供应商或密钥。没有独立常驻LLM服务；CLI不会把一句话自行解析成完整科学方法。

任何有文件、执行与看图能力的宿主可使用同一协议：读取agent.md → start原始文本/材料 → 由真实模型调用read/看图 → 自主填写内部状态 → plan/build/check/render → 看图与评审 → deliver。每一步是真实工具调用，不能返回伪造的模型JSON作为“模型已执行”证明。

能力探测分两层：capabilities检测本机Python/可选读取包/draw.io；宿主实际调用读取、视觉、浏览和交互工具并把结果放入任务的capabilities.json。截图重建缺视觉时只处理可读文字，必要图关系不能猜。

无本机draw.io时可用官方https://app.diagrams.net/打开并导出，记录该方式与哈希；真实私有素材不默认上传第三方。若不能原生渲染，仍可构建问题版本.drawio，原生渲染/视觉记not_run。自写SVG不替代此项目。

第三方宿主适配未实测，不声称全面兼容。替换宿主不用修改图谱/原生构建核心。可替换render适配器须保留status、figure_sha256、output_sha256与工具身份协议。
