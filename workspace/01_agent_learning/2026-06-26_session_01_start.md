# 2026-06-26 Session 01: Start

## 今日定位

今天重新开始 Agent Competition 的学习，不直接进入 baseline，而是先恢复项目记忆，并从阶段 00 开始。

## 我们之前定下的三阶段路线

1. Agent 基础学习与逐步摸索
2. 理解比赛 baseline
3. 具备完整优化或修改 baseline 的能力

## 今日学习目标

- 重新理解这个比赛在做什么。
- 理解为什么不能一开始就读 baseline。
- 明确 Agent 在这个比赛里的最小含义。
- 准备进入“人肉解 1 题”。

## 当前项目事实

- 比赛：AFAC2026挑战组-赛题四：金融长文本Agent 的动态记忆压缩与高效问答挑战。
- 数据：当前已有 A 榜公开数据 `public_dataset_upload/`。
- A 榜题目：100 道，5 个领域，每个领域 20 道。
- 原始材料：PDF、HTML、TXT 混合。
- 关键限制：正式检索和推理阶段禁止使用 embedding 模型，必须使用 Qwen 系列模型完成推理问答。

## 今天的第一步

从一道人能看懂、能手动追证据的 A 榜题开始。

目标不是马上自动化，而是先回答：

```text
一个人解这道题时，到底做了哪些动作？
```

这些动作之后才会逐步变成：

```text
工具 -> workflow -> agent loop -> baseline -> 优化系统
```

## 本次新增的工作区分层

今天明确区分三类内容：

```text
01_agent_learning/          # 学习阶段：从人肉解题到最小 Agent 循环
02_baseline_understanding/  # baseline 理解阶段：读懂模块和数据流
03_baseline_improvement/    # baseline 改进阶段：做实验、跑评估、记录结果
```

这次建立了更细的子目录：

```text
workspace/01_agent_learning/manual_solving/  # 人工解题记录
workspace/01_agent_learning/minimal_loop/    # 零框架 Think-Act-Observe 小实验
workspace/01_agent_learning/tool_calling/    # 工具调用练习
workspace/01_agent_learning/state_graph/     # 后续状态图或显式 workflow 练习
workspace/01_agent_learning/notes/           # 学习笔记
workspace/01_agent_learning/sessions/        # 每天或每个小闭环的学习现场

workspace/02_baseline_understanding/single_question_runs/
workspace/02_baseline_understanding/module_notes/
workspace/02_baseline_understanding/data_flow/
workspace/02_baseline_understanding/doc_id_mapping/
workspace/02_baseline_understanding/failure_modes/

workspace/03_baseline_improvement/experiments/
workspace/03_baseline_improvement/error_analysis/
workspace/03_baseline_improvement/retrieval/
workspace/03_baseline_improvement/prompts/
workspace/03_baseline_improvement/token_budget/
workspace/03_baseline_improvement/submissions/
```

## 今天已经明确的判断

- 今天不是修改官方 baseline，也不是准备正式提交。
- 今天是在通往 baseline 的阶段性学习。
- 官方数据放在 `public_dataset_upload/`，不要修改。
- 学习记录放在 `workspace/01_agent_learning/`。
- 未来真正面向效果的实验，放在 `workspace/03_baseline_improvement/experiments/`。
- 今天推荐题目是 `ins_a_007`。
- 今天要先理解一道人类如何解题，再把机械步骤逐步变成工具。

## 学习阶段代码放置规则

为了避免把每天的学习代码混成大杂汇，今天采用两层规则：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/
```

放今天这个小闭环的现场材料：

```text
scripts/  # 今天为 ins_a_007 写的小脚本或草稿代码
outputs/  # 脚本输出、临时观察结果
notes/    # 临时说明或理解笔记
```

只有当某个脚本被证明可以跨题、跨日期复用时，再提升到项目根目录：

```text
scripts/
```

也就是说：

```text
当天学习代码 -> workspace/01_agent_learning/sessions/YYYY-MM-DD_topic/scripts/
稳定通用工具 -> scripts/
```

今天的 `inspect_question.py` 可以先写在 session 的 `scripts/` 里。等我们确认它对 group_a 所有题都有用，再决定是否提升为根目录通用脚本。

## 待办

- [x] 选 1 道 A 榜题：`ins_a_007`。
- [x] 读取题目字段：`qid`、`domain`、`question`、`options`、`answer_format`、`doc_ids`。
- [x] 创建学习脚本：`workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/inspect_question.py`。
- [x] 验证脚本可以打印 `ins_a_007` 的题目观察卡。
- [x] 建立人工解题记录第一版：`workspace/01_agent_learning/manual_solving/ins_a_007.md`。
- [x] 找到 `doc_ids` 对应的原始材料：`public_dataset_upload/raw/insurance/1.pdf`、`2.pdf`、`16.pdf`。
- [x] 人工寻找证据，并记录 A/B/C/D 的搜索过程。
- [x] 判断选项：A 初步不成立，B 成立，C 成立，D 不成立。
- [x] 补充证据摘录和最终选项判断到 `workspace/01_agent_learning/manual_solving/ins_a_007.md`。

## 当前人工判断结果

基于目前证据，`ins_a_007` 的答案候选为：

```text
BC
```

判断依据简述：

- A: 未找到支持“允许保单贷款，最高为现金价值的80%”的正向证据；人工搜索和工具文本扫描均未命中“保单贷款”“贷款”“借款”“80%”等关键组合。
- B: PDF-2 第二十二条支持可以申请借款，最高借款金额不超过现金价值扣除借款及借款利息后余额的 80%。
- C: PDF-16 第六章 6.2 明确写明，按照个人养老金制度投保并订立合同时，不接受保单贷款申请。
- D: PDF-16 第六章 6.2 存在一般情况下可申请/办理保单贷款的表述，因此 D 的“无论何种投保方式”属于过度概括。

## 已创建的第一个学习工具

脚本路径：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/inspect_question.py
```

运行方式：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/inspect_question.py ins_a_007
```

这个脚本不调用大模型 API，只做确定性文件读取：

```text
读取 group_a 的 JSON 题目文件
-> 按 qid 查找题目
-> 打印 question、options、answer_format、doc_ids
```

验证方式：

```bash
python3 -m pytest workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/tests/test_inspect_question.py -q
```

验证结果：

```text
1 passed
```
