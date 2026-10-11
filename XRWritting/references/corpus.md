# 语料、版本与证据

核查日期：2026-10-07。风格规则是智能体对下列原文的分析归纳。用户提供的xr-writing-style规则用于提出线索，未直接作为事实依据。没有复制其完整规则和HTML演示进配置库。

## 作者身份与覆盖限制

- [个人主页](https://li-xirong.github.io/)明确姓名为李锡荣（LI, Xirong），并链接以下论文及其[Google Scholar主页](https://scholar.google.com/citations?hl=en&oi=ao&user=6m-ZQ1EAAAAJ)。
- 用户给的[学者搜索页](https://scholar.google.com/citations?view_op=search_authors&mauthors=xirong+li&hl=zh-CN&oi=ao)与Scholar主页均未成功获取。通过个人主页、作者栏和CVF/arXiv原文交叉确认，没有读取其完整Scholar文献清单。
- 本次读取八篇公开PDF，以及EI指定v1的HTML。覆盖选定的摘要、引言、方法/构建、实验和结论段落；未逐篇精读所有公式、表格与补充材料，也未评估其科研结论正确性。
- SEA与MM-MIL中李锡荣列第一作者，其余样本为合著且原文标有通讯作者。作者次序无法证明每句话的执笔归属。语料偏向多媒体、视觉与医学影像研究，不能声称跨语言或跨领域全面刻画。
- PDF下载、提取文本和哈希保存在被Git排除的outputs/setup-2026-10-07/。配置仅保存书目信息、位置与简短中文归纳，不保存论文全文。

## 核查论文

页码均指PDF页序，从1开始；发表信息与所读版本分别记录。SEA的2021采用个人主页列示年份，所读预印本为2020年版本；不把在线发表时间、卷期年份和预印本时间混为同一日期。

| ID | 作者—正式发表年份—题目—渠道 | 所读版本与链接 | 本次核对位置和用途 |
| --- | --- | --- | --- |
| SEA | Xirong Li等—2021—SEA: Sentence Encoder Assembly for Video Retrieval by Textual Queries—IEEE TMM | [arXiv:2011.12091v1](https://arxiv.org/abs/2011.12091v1)，预印本2020 | 摘要与§I（p1–2）从检索任务转向编码器缺口并分解差异；§II（p2–3）围绕查询表示组织前作；§III交代表示与损失；§V（p10）回到结构与训练的具体发现 |
| MM-MIL | Xirong Li等—2021—Multi-Modal Multi-Instance Learning for Retinal Disease Recognition—ACM MM | [arXiv:2109.12307v1](https://arxiv.org/abs/2109.12307v1) | 摘要、§1（p1–3）用临床输入与标注成本约束方案；§3（p3–5）任务及模块；§4.3（p7）先报告消融再解释；§5（p8）总结选择性与可解释性的发现 |
| LAFF | Fan Hu、Aozhu Chen等，Xirong Li—2022—Lightweight Attentional Feature Fusion: A New Baseline for Text-to-Video Retrieval—ECCV | [作者公开PDF](https://li-xirong.github.io/pub/eccv2022-LAFF.pdf) | 摘要及§1（p1–3）明确假设、比较替代方案；§2（p4–5）区分视频端与文本端；§4.3（p13–14）说明比较特征设置；§5（p14）总结发现并保留展望语气 |
| GeoFormer | Jiazhen Liu、Xirong Li—2023—Geometrized Transformer for Self-Supervised Homography Estimation—ICCV | [作者公开PDF](https://li-xirong.github.io/pub/iccv2023-GeoFormer.pdf) | 摘要及§1（p1–2）将问题与几何机制对应；§2（p2–3）按方法类型归组；§3（p3–5）先概括已有流程再交代变化；§5（p8）按数据条件区分改善幅度 |
| TeachCLIP | Kaibin Tian、Ruixiang Zhao、Zijie Xin、Bangxiang Lan、Xirong Li—2024—Holistic Features are almost Sufficient for Text-to-Video Retrieval—CVPR | [CVF正式页面](https://openaccess.thecvf.com/content/CVPR2024/html/Tian_Holistic_Features_are_almost_Sufficient_for_Text-to-Video_Retrieval_CVPR_2024_paper.html)；[PDF](https://openaccess.thecvf.com/content/CVPR2024/papers/Tian_Holistic_Features_are_almost_Sufficient_for_Text-to-Video_Retrieval_CVPR_2024_paper.pdf) | 摘要、§1（p1–2）问题式开头并区分科学与实际价值；§2（p2–3）以检索及蒸馏定位贡献；§3.2（p3）从流程过渡公式；§4（p5–8）按评估问题组织结果；§5（p8）回到粒度与效率。与2023预印本TeachCLIP有关，本语料采用正式版标题及作者，未把两个版本当两个独立样本 |
| PhD | Jiazhen Liu等，Xirong Li—2025—PhD: A ChatGPT-Prompted Visual Hallucination Evaluation Dataset—CVPR | [CVF正式页面](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_PhD_A_ChatGPT-Prompted_Visual_Hallucination_Evaluation_Dataset_CVPR_2025_paper.html)；[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/Liu_PhD_A_ChatGPT-Prompted_Visual_Hallucination_Evaluation_Dataset_CVPR_2025_paper.pdf) | 摘要、§1–2（p1–3）按任务与模式定位评测；§3（p3–5）将构建步骤对应小节；§4.1（p6）说明评测范围与资源约束；§5（p8）归纳不同条件的发现。本次使用PhD-sec正式版，不混用早期PhD-iac命名 |
| MGSV | Zijie Xin等，Xirong Li—2025—Music Grounding by Short Video—ICCV | [CVF正式页面](https://openaccess.thecvf.com/content/ICCV2025/html/Xin_Music_Grounding_by_Short_Video_ICCV_2025_paper.html)；[PDF](https://openaccess.thecvf.com/content/ICCV2025/papers/Xin_Music_Grounding_by_Short_Video_ICCV_2025_paper.pdf) | 摘要与§1（p1–2）由实际时长问题定义新任务；§2（p2–3）说明借鉴领域；§4（p4–5）先介绍输入输出，再说明模块及设计动机；§6（p8）具体发现与单列局限 |
| FunBench | Qijie Wei、Kaiheng Qian、Xirong Li—2025—FunBench: Benchmarking Fundus Reading Skills of MLLMs—MICCAI | [作者公开PDF](https://li-xirong.github.io/pub/miccai2025-FunBench.pdf) | 摘要、§1（p1–3）从评测不足引出分层任务与模块评测，贡献按类别列项；§2（p3–6）分层构建；§3.2（p6–8）按对象讨论结果；§4（p8–9）逐项总结已有发现 |
| EI | Qijie Wei、Hailan Lin、Xirong Li—2026—EI: Early Intervention for Multimodal Imaging based Disease Recognition—个人主页列CVPR Findings 2026 | [arXiv:2603.17514v1 HTML](https://arxiv.org/html/2603.17514v1)，2026-03-18 | 摘要、§1两项挑战对应两项设计；§2按技术维度分类；§3先定义输入符号再分模块；§4.2说明baseline及增强版本；§5总结具体发现并注明局限。下载v1 PDF失败，实际读取HTML；当前arXiv版本题目已变，此处固定v1，不混用新版 |

## 证据等级与更新方法

style-guide.md中多个来源重复支持的结构特征可作为主要检查依据；只在少数论文出现的问句、类比、引语、短语归为可选。即使来源重复，也不推断其在全部作品中的频率。

新增规则必须记录：规则ID、原论文、版本、章节或页序、中文观察、适用类型及反例。查不到原文只记“待核实”，不能升级成默认门槛。更新时保留旧版本记录，不改写过去审校所用的档案版本。不得凭记忆造引文或把搜索摘要当正文。
