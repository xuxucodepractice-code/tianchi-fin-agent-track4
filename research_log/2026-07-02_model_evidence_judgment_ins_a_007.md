# 2026-07-02 Model Evidence Judgment: ins_a_007

## Date

2026-07-02

## Track

学习理解线

## Position In Roadmap

本次工作对应学习路线中的第三步：

```text
模型基于证据判断 1 题
```

此前已完成：

```text
1. 人肉解 1 题
2. 工具辅助解 1 题
```

本次目标是在已经找到证据的前提下，测试模型是否能只基于证据逐项判断 A/B/C/D。

## Context

围绕 `ins_a_007`，前期已经完成：

```text
inspect_question.py 读取题目
map_doc_id.py 映射 doc_id 到 PDF
search_keyword.py 搜索关键词证据
人工判断 A/B/C/D
工具辅助解题记录
```

本次不继续搜索 PDF，也不启动 baseline，而是把已经找到的证据整理成模型可读输入。

## Goal

建立一个最小的 evidence-grounded judgment 闭环：

```text
工具找到证据
-> 人整理 evidence pack
-> prompt 约束模型
-> 模型基于证据判断
-> 人工复核模型输出
```

核心问题是：

```text
模型能否在不给外部知识、不给自由搜索的情况下，只根据证据判断选项？
```

## Actions

### 1. 建立 model_judging 工作区

新增目录：

```text
workspace/01_agent_learning/model_judging/
```

该目录用于保存：

```text
模型需要阅读的证据包
模型判断 prompt
可复制到 chatbox 的完整输入
模型输出和人工复核记录
```

### 2. 整理 evidence pack

新增文件：

```text
workspace/01_agent_learning/model_judging/ins_a_007_evidence_pack.md
```

内容包括：

```text
题目
选项
answer_format
判断规则
A/B/C/D 对应证据
搜索观察
模型应判断的问题
```

关键设计：

```text
证据包不直接告诉模型答案，而是给模型可判断的材料。
```

### 3. 编写 judgment prompt

新增文件：

```text
workspace/01_agent_learning/model_judging/ins_a_007_judgment_prompt.md
```

prompt 明确要求模型：

```text
只使用 evidence pack 中的证据
不要使用外部知识
不要猜测
逐项判断 A/B/C/D
区分“支持”“反驳”“证据不足”
最终答案按 multi 格式输出
```

### 4. 生成 model input

新增文件：

```text
workspace/01_agent_learning/model_judging/ins_a_007_model_input.md
```

该文件将：

```text
judgment prompt
+ evidence pack
```

合并成一份可以直接复制到模型 chatbox 的完整输入。

### 5. 保存模型输出与人工复核

新增文件：

```text
workspace/01_agent_learning/model_judging/ins_a_007_model_output.md
```

模型输出：

```text
A: 证据不足
B: 支持
C: 支持
D: 反驳
最终答案：BC
```

人工复核认为该输出可以接受。

## Key Findings

### A

模型判断为：

```text
证据不足
```

复核结论：

```text
合理。
```

原因是当前 evidence pack 中没有找到直接支持 A 的正向证据，但也没有给出明确反驳 A 的原文证据。模型正确区分了：

```text
没有找到支持证据
```

和：

```text
找到明确反驳证据
```

### B

模型判断为：

```text
支持
```

复核结论：

```text
合理。
```

模型正确处理了：

```text
借款 -> 保单贷款
借款及借款利息 -> 欠款
```

这些近义或概括表达之间的对应关系。

### C

模型判断为：

```text
支持
```

复核结论：

```text
合理。
```

模型正确识别 C 是条件判断：

```text
若按个人养老金制度投保 -> 不接受保单贷款申请
```

### D

模型判断为：

```text
反驳
```

复核结论：

```text
合理。
```

模型正确识别 D 的问题是把特定条件下的不允许扩大成：

```text
无论何种投保方式，均不允许
```

属于过度概括。

## Difficulties

本次主要困难不是模型调用，而是证据表达：

```text
1. A 的证据状态是“证据不足”，不是“明确反驳”。
2. B 需要处理“借款”和“保单贷款”的语义对应。
3. D 需要处理“条件限制”和“绝对范围”的区别。
```

这些都说明比赛中的模型判断不能只看关键词命中，还要理解证据与选项之间的语义关系。

## Research Notes

这一步把 Agent loop 中的职责边界拆得更清楚：

```text
工具：负责找证据。
人：负责整理证据和复核输出。
Prompt：负责限制模型行为。
模型：负责基于证据做语义判断。
```

当前仍然不是自动 Agent，而是：

```text
人主导的模型判断实验。
```

这一步为后续“自动跑 1 题”打基础，因为未来程序要做的就是把今天手动整理的流程自动化：

```text
自动拼接 prompt
自动组织 evidence pack
自动调用模型
自动保存输出
自动校验答案格式
```

## Artifacts

```text
workspace/01_agent_learning/model_judging/ins_a_007_evidence_pack.md
workspace/01_agent_learning/model_judging/ins_a_007_judgment_prompt.md
workspace/01_agent_learning/model_judging/ins_a_007_model_input.md
workspace/01_agent_learning/model_judging/ins_a_007_model_output.md
```

## Current Status

学习路线进度：

```text
1. 人肉解 1 题              已完成
2. 工具辅助解 1 题          已完成
3. 模型基于证据判断 1 题    已完成
4. 自动跑 1 题              下一步
```

## Next Step

下一步建议进入：

```text
自动跑 1 题
```

但仍保持小步推进，不直接进入完整 baseline。

建议先做一个最小脚本或流程，把已经手动完成的动作连接起来：

```text
读取 evidence pack
读取 judgment prompt
拼接 model input
保存模型输出
检查最终答案格式
```

暂时不引入 LangChain、LangGraph、向量数据库或复杂框架。
