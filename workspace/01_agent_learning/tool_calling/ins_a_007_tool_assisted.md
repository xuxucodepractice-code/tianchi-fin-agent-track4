# ins_a_007 Tool Assisted Solving

## Basic Info

- date: 2026-07-01
- track: 学习理解线
- stage: 工具辅助解 1 题
- qid: ins_a_007
- domain: insurance
- answer_format: multi
- docs:
  - `public_dataset_upload/raw/insurance/1.pdf`
  - `public_dataset_upload/raw/insurance/2.pdf`
  - `public_dataset_upload/raw/insurance/16.pdf`

## Purpose

这份记录不是为了直接追求自动化，而是记录一次最小的工具辅助解题过程。

核心目标是看清楚：

```text
题目 -> 文档编号 -> PDF 文件路径 -> 关键词搜索 -> 证据观察 -> 人工判断
```

这对应未来 Agent workflow 的雏形：

```text
load_question -> map_doc_ids -> search_evidence -> judge_options
```

## Question

关于“保单贷款”，以下哪些说法正确？

## Options

A. 平安智盈金生允许保单贷款，最高为现金价值的80%

B. 国寿增益宝允许保单贷款，最高为现金价值扣除欠款后的80%

C. 平安富鸿金生若按个人养老金制度投保，则不允许保单贷款

D. 平安富鸿金生无论何种投保方式，均不允许保单贷款

## Tool Chain

本次使用三个小工具，不使用大模型 API：

```text
inspect_question.py  # 根据 qid 读取题目
map_doc_id.py        # 根据 domain + doc_id 找到 PDF 路径
search_keyword.py    # 在 PDF 中搜索关键词
```

## Step 1: Load Question

命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/inspect_question.py ins_a_007
```

关键输出：

```text
qid: ins_a_007
domain: insurance
answer_format: multi
doc_ids:
- 1
- 2
- 16
```

含义：

```text
这道题是 insurance 领域的多选题，需要查 1、2、16 三份原始 PDF。
```

## Step 2: Map Doc IDs

命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 1
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 2
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 16
```

输出：

```text
public_dataset_upload/raw/insurance/1.pdf
public_dataset_upload/raw/insurance/2.pdf
public_dataset_upload/raw/insurance/16.pdf
```

含义：

```text
题目里的抽象 doc_id 已经变成电脑上可以读取的 PDF 文件路径。
```

## Step 3: Search Evidence By Option

### A / doc_id 1 / PDF-1

选项：

```text
平安智盈金生允许保单贷款，最高为现金价值的80%
```

要验证的判断点：

```text
1. 平安智盈金生是否允许保单贷款。
2. 如果允许，贷款上限是否为现金价值的 80%。
```

搜索关键词和结果：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/1.pdf 保单贷款
```

结果：

```text
No matches found for keyword: 保单贷款
```

继续放宽关键词：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/1.pdf 贷款
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/1.pdf 借款
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/1.pdf 80%
```

结果：

```text
贷款：未命中
借款：未命中
80%：未命中
```

最后搜索基础词：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/1.pdf 现金价值
```

命中观察：

```text
page: 13
7.1 现金价值 ...

page: 20
... 退还本合同的现金价值 ...
```

人工判断：

```text
PDF-1 中确实出现“现金价值”，但上下文是现金价值计算或退还，不是保单贷款规则。
目前没有找到支持 A 的正向证据。
```

阶段判断：

```text
A：暂不支持 / 初步判断错误。
```

### B / doc_id 2 / PDF-2

选项：

```text
国寿增益宝允许保单贷款，最高为现金价值扣除欠款后的80%
```

要验证的判断点：

```text
1. 国寿增益宝是否允许借款或保单贷款。
2. 借款上限是否为现金价值扣除借款及利息后余额的 80%。
```

搜索命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/2.pdf 借款
```

关键证据：

```text
page: 7
第二十二条借款
在本合同保险期间内，如果本合同已经具有现金价值，您可以书面形式向我们申请借款，
但最高借款金额不得超过本合同当时的现金价值扣除借款及借款利息后余额的 80%，
且每次借款期限不得超过6个月。
```

人工判断：

```text
原文支持“可以申请借款”，也支持“最高借款金额不超过现金价值扣除借款及借款利息后余额的 80%”。
选项中的“欠款”可以对应原文中的借款及借款利息。
```

阶段判断：

```text
B：正确。
```

### C / doc_id 16 / PDF-16

选项：

```text
平安富鸿金生若按个人养老金制度投保，则不允许保单贷款
```

要验证的判断点：

```text
1. 是否存在“个人养老金制度投保”这个条件。
2. 在该条件下是否不接受保单贷款申请。
```

搜索命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/16.pdf 个人养老金制度
```

关键证据：

```text
page: 9
若您按照个人养老金制度（10.14）投保并订立本合同的，我们不接受保单贷款申请。
```

人工判断：

```text
原文条件和选项条件一致，原文结论和选项结论一致。
```

阶段判断：

```text
C：正确。
```

### D / doc_id 16 / PDF-16

选项：

```text
平安富鸿金生无论何种投保方式，均不允许保单贷款
```

要验证的判断点：

```text
1. 原文是否说所有投保方式都不允许保单贷款。
2. 还是只在个人养老金制度投保条件下不接受保单贷款申请。
```

搜索命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/16.pdf 保单贷款
```

关键证据：

```text
page: 9
经被保险人书面同意，您可申请保单贷款功能。
在本合同有效期内，经我们审核同意后您可办理保单贷款。
贷款金额不得超过本合同当时现金价值的 80%。
```

结合 C 的条件证据：

```text
若您按照个人养老金制度（10.14）投保并订立本合同的，我们不接受保单贷款申请。
```

人工判断：

```text
原文更像是“一般情况下可以申请保单贷款；特殊情况下，按个人养老金制度投保则不接受保单贷款申请”。
D 把特定条件下的不允许扩大成“无论何种投保方式均不允许”，属于过度概括。
```

阶段判断：

```text
D：错误。
```

## Current Judgment

| Option | Tool Observation | Human Judgment | Result |
| --- | --- | --- | --- |
| A | PDF-1 未命中“保单贷款”“贷款”“借款”“80%”；“现金价值”命中但上下文不是贷款规则 | 没有正向证据支持 A | 错误 / 暂不支持 |
| B | PDF-2 第 7 页命中“第二十二条借款”及 80% 上限 | 原文支持可以申请借款和扣除借款利息后余额的 80% | 正确 |
| C | PDF-16 第 9 页命中个人养老金制度条件下不接受保单贷款申请 | 条件和结论都与选项一致 | 正确 |
| D | PDF-16 第 9 页同时说明一般可申请保单贷款，个人养老金制度例外 | D 的“无论何种投保方式”过度概括 | 错误 |

当前答案候选：

```text
BC
```

## What The Tools Did

工具完成的是偏机械、可重复的部分：

```text
读取题目字段
定位 PDF 文件路径
搜索关键词
返回命中页码和上下文
```

## What Human Or Model Still Did

人或模型完成的是语义判断：

```text
判断“借款”和“保单贷款”是否可以对应
判断“欠款”是否可以对应借款及借款利息
判断 C 是条件判断，而不是普遍判断
判断 D 是否把条件扩大成绝对说法
判断没有命中的关键词是否足以支持反向判断
```

## Learning Notes

这一步体现了工具之间的接力：

```text
inspect_question.py 的输出 doc_ids
-> 成为 map_doc_id.py 的输入
-> map_doc_id.py 的输出 PDF 路径
-> 成为 search_keyword.py 的输入
-> search_keyword.py 的输出证据上下文
-> 成为人工或模型判断的输入
```

这就是 Agent loop 的底层结构：

```text
任务 -> 工具 -> 观察 -> 再决定下一步 -> 证据判断
```

目前仍然是“人主导、工具辅助”。

下一阶段才考虑把这些手动步骤合并成一个更自动的小 workflow。
