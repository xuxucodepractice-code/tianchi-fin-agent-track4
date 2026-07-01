# 2026-07-01 Tool Assisted Solving: ins_a_007

## Date

2026-07-01

## Track

学习理解线

## Context

此前已经完成了 `ins_a_007` 的人工解题记录，并建立了三个最小工具：

```text
inspect_question.py
map_doc_id.py
search_keyword.py
```

今天这一步的目标不是写新代码，而是把三个工具真正用于一题的辅助解题过程。

## Why This Matters

人工解题能训练“怎么读题、怎么找证据、怎么判断选项”。

工具辅助解题要进一步训练：

```text
人如何把自己的解题动作拆成工具可以执行的小步骤。
```

这一步是从“人肉解 1 题”过渡到“工具辅助解 1 题”的关键位置。

## Actions

完成了一次手动工具接力：

```text
inspect_question.py
-> map_doc_id.py
-> search_keyword.py
-> 人工判断 A/B/C/D
```

并将详细过程整理到：

```text
workspace/01_agent_learning/tool_calling/ins_a_007_tool_assisted.md
```

## Key Findings

- A：在 `1.pdf` 中未找到“保单贷款”“贷款”“借款”“80%”等关键证据；“现金价值”命中但上下文不是贷款规则，因此暂不支持。
- B：在 `2.pdf` 中找到“第二十二条借款”，支持可以申请借款以及扣除借款及借款利息后余额的 80%。
- C：在 `16.pdf` 中找到个人养老金制度投保条件下不接受保单贷款申请的明确证据。
- D：在 `16.pdf` 中同时找到一般情况下可以申请保单贷款的证据，因此“无论何种投保方式均不允许”过度概括。

当前答案候选：

```text
BC
```

## Difficulty

本次主要困难不是工具运行，而是理解工具输出的含义：

```text
没有命中关键词，不等于一定错误。
命中关键词，也不等于一定正确。
必须回到上下文判断证据是否真的支持选项。
```

这正好说明未来 Agent 不能只有搜索工具，还需要 evidence judgment。

## Next Step

下一步建议继续保持小步推进：

```text
1. 复盘这份工具辅助记录。
2. 总结一个通用的“选项拆解 -> 多关键词搜索 -> 证据判断”模板。
3. 再考虑是否写一个最小 workflow，把三个工具串起来自动跑一题。
```

暂时不进入 LangChain、LangGraph、向量数据库或 baseline 修改。
