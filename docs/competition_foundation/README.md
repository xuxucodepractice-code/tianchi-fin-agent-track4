# Competition Foundation

整理日期：2026-06-23  
比赛链接：https://tianchi.aliyun.com/competition/entrance/532486/information

本目录用于沉淀 AFAC2026 挑战组赛题四的行政、赛制、命题、提交与本地数据基础信息。后续代码、方案、报告和复现文档应优先引用这里的事实口径。

## 赛事基本信息

- 比赛 ID：532486
- 赛题名称：AFAC2026挑战组-赛题四：金融长文本Agent 的动态记忆压缩与高效问答挑战
- 所属专题赛：AFAC2026金融智能创新大赛
- 任务类型：金融长文本问答 Agent，重点考查检索、证据定位、动态记忆压缩、推理作答和 Token 成本控制。
- 官方推荐平台：阿里云百炼平台；推理问答阶段必须使用 Qwen 系列模型 API。

## 文件索引

- [administration.md](administration.md)：报名、认证、队伍、奖项、组织机构、答疑群等行政信息。
- [schedule_rules.md](schedule_rules.md)：赛程、A/B 榜、提交流程、入围和报告阶段规则。
- [task_and_data.md](task_and_data.md)：命题背景、任务目标、题型、数据领域、A/B 榜差异。
- [submission_scoring_compliance.md](submission_scoring_compliance.md)：提交格式、评分公式、模型使用边界、代码审核要求。
- [local_dataset_inventory.md](local_dataset_inventory.md)：当前工作区内 `public_dataset_upload` 的数据盘点。
- [public_dataset_scan.md](public_dataset_scan.md)：对官方 A 榜公开数据包的结构、题目、doc_id、文件形态和 PDF 粗略页数扫描。
- [agent_learning_to_baseline_roadmap.md](agent_learning_to_baseline_roadmap.md)：把原 AI Agent 学习计划衔接到比赛 baseline 理解与优化能力建设。

## 当前关键判断

- A 榜公开数据已在当前工作区中，路径为 `public_dataset_upload/`。
- A 榜题目每个领域 20 道，共 100 道；B 榜官方说明为 100 道，且不直接给出 `doc_ids`。
- 本赛题不是单纯“堆长上下文”竞赛，Token 统计会进入最终评分。
- 规则明确禁止在正式检索与推理阶段使用 embedding 模型。
- 预处理可以使用 OCR、版面分析、PDF 转结构化文本等工具，但预处理阶段的非 Qwen 语义能力不能延伸到正式答题。
