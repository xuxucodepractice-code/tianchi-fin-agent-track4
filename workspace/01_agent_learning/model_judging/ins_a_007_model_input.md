# ins_a_007 Model Input

## How To Use

把下面从 `MODEL MESSAGE START` 到 `MODEL MESSAGE END` 之间的全部内容复制到模型 chatbox。

这份输入由两部分组成：

```text
judgment prompt  # 告诉模型怎么判断
evidence pack    # 给模型看的题目、选项和证据
```

---

## MODEL MESSAGE START

你是一个金融长文本问答任务中的证据判断助手。

你会收到一份 evidence pack，其中包含：

- qid
- question
- options
- answer_format
- 每个选项对应的证据片段
- 每个选项对应的搜索观察
- 要求你判断的问题

你的任务是：
只基于 evidence pack 中提供的证据，逐项判断 A/B/C/D 是否成立。

请严格遵守以下规则：

1. 只能使用 evidence pack 中提供的证据。
2. 不要使用外部知识。
3. 不要根据常识猜测。
4. 如果证据明确支持某个选项，判断为“支持”。
5. 如果证据明确反驳某个选项，判断为“反驳”。
6. 如果证据不足以确认某个选项正确或错误，判断为“证据不足”。
7. 注意区分“没有找到支持证据”和“找到明确反驳证据”。
8. 注意选项中的范围词和条件词，例如“若”“无论何种”“均”等。
9. 对多选题，最终答案只包含被判断为“支持”的选项字母。
10. 最终答案按 A/B/C/D 顺序排列，不加逗号、空格或其他分隔符。

请按以下格式输出：

```text
A: 支持/反驳/证据不足
理由：引用或概括 evidence pack 中与 A 相关的证据，说明为什么这样判断。

B: 支持/反驳/证据不足
理由：引用或概括 evidence pack 中与 B 相关的证据，说明为什么这样判断。

C: 支持/反驳/证据不足
理由：引用或概括 evidence pack 中与 C 相关的证据，说明为什么这样判断。

D: 支持/反驳/证据不足
理由：引用或概括 evidence pack 中与 D 相关的证据，说明为什么这样判断。

最终答案：仅输出符合 answer_format 的选项字母。
```

以下是 evidence pack：

# ins_a_007 Evidence Pack

## Purpose

这份文件是给模型阅读的证据包。

目标不是让模型自己搜索资料，而是让模型只基于这里提供的题目、选项和证据片段，判断每个选项是否成立。

## Basic Info

- qid: ins_a_007
- domain: insurance
- answer_format: multi
- task_type: 推理判断
- doc_ids:
  - 1
  - 2
  - 16

## Question

关于“保单贷款”，以下哪些说法正确？

## Options

A. 平安智盈金生允许保单贷款，最高为现金价值的80%

B. 国寿增益宝允许保单贷款，最高为现金价值扣除欠款后的80%

C. 平安富鸿金生若按个人养老金制度投保，则不允许保单贷款

D. 平安富鸿金生无论何种投保方式，均不允许保单贷款

## Judgment Rules For Model

请只基于本文件提供的证据判断，不要使用外部知识，不要猜测。

对每个选项，请判断为以下三类之一：

```text
支持：证据明确支持该选项。
反驳：证据明确反驳该选项。
证据不足：现有证据无法确认该选项正确或错误。
```

因为 `answer_format` 是 `multi`，最终答案应输出所有被判断为“支持”的选项字母，并按 A/B/C/D 顺序排列，不加分隔符。

## Evidence For Option A

### Option

```text
平安智盈金生允许保单贷款，最高为现金价值的80%
```

### Source

```text
public_dataset_upload/raw/insurance/1.pdf
```

### Evidence Snippets

未找到能直接支持 A 的原文证据。

搜索“现金价值”有命中，但上下文是现金价值计算或退还，不是保单贷款规则。例如：

```text
page: 13
7.1 现金价值 ...
```

```text
page: 20
... 退还本合同的现金价值 ...
```

### Search Observations

```text
保单贷款：未命中
贷款：未命中
借款：未命中
80%：未命中
现金价值：命中，但上下文不是保单贷款规则
```

### What The Model Should Judge

```text
1. 证据是否支持“平安智盈金生允许保单贷款”？
2. 证据是否支持“最高为现金价值的80%”？
3. 如果关键证据没有找到，应判断为支持、反驳，还是证据不足？
```

## Evidence For Option B

### Option

```text
国寿增益宝允许保单贷款，最高为现金价值扣除欠款后的80%
```

### Source

```text
public_dataset_upload/raw/insurance/2.pdf
```

### Evidence Snippets

```text
page: 7
第二十二条借款
在本合同保险期间内，如果本合同已经具有现金价值，您可以书面形式向我们申请借款，
但最高借款金额不得超过本合同当时的现金价值扣除借款及借款利息后余额的 80%，
且每次借款期限不得超过6个月。
```

### Search Observations

```text
关键词“借款”命中 page 7。
该页出现“您可以书面形式向我们申请借款”。
该页出现“现金价值扣除借款及借款利息后余额的 80%”。
选项中的“欠款”需要和原文中的“借款及借款利息”进行语义对应判断。
```

### What The Model Should Judge

```text
1. 证据是否支持“可以申请借款/保单贷款”？
2. 证据是否支持“最高为现金价值扣除欠款后的80%”？
3. “借款”“保单贷款”“欠款”这些表述是否可以根据证据对应？
```

## Evidence For Option C

### Option

```text
平安富鸿金生若按个人养老金制度投保，则不允许保单贷款
```

### Source

```text
public_dataset_upload/raw/insurance/16.pdf
```

### Evidence Snippets

```text
page: 9
若您按照个人养老金制度（10.14）投保并订立本合同的，我们不接受保单贷款申请。
```

### Search Observations

```text
关键词“个人养老金制度”命中 page 9。
该页明确出现“按照个人养老金制度投保并订立本合同”的条件。
该页明确出现“我们不接受保单贷款申请”的限制。
该选项是条件判断，需要判断该条件和结论是否与原文一致。
```

### What The Model Should Judge

```text
1. 证据是否出现“个人养老金制度投保”这个条件？
2. 在该条件下，证据是否说明不接受保单贷款申请？
3. 该选项是否是条件判断，而不是普遍判断？
```

## Evidence For Option D

### Option

```text
平安富鸿金生无论何种投保方式，均不允许保单贷款
```

### Source

```text
public_dataset_upload/raw/insurance/16.pdf
```

### Evidence Snippets

一般情况下可以申请保单贷款的证据：

```text
page: 9
经被保险人书面同意，您可申请保单贷款功能。
在本合同有效期内，经我们审核同意后您可办理保单贷款。
贷款金额不得超过本合同当时现金价值的 80%。
```

特殊情况下不接受保单贷款申请的证据：

```text
page: 9
若您按照个人养老金制度（10.14）投保并订立本合同的，我们不接受保单贷款申请。
```

### Search Observations

```text
关键词“保单贷款”命中 page 9。
该页先说明一般情况下可以申请或办理保单贷款。
同一页又说明，如果按照个人养老金制度投保并订立本合同，则不接受保单贷款申请。
因此需要判断 D 中“无论何种投保方式，均不允许保单贷款”是否过度概括。
```

### What The Model Should Judge

```text
1. 证据是否支持“无论何种投保方式均不允许”？
2. 证据是否说明一般情况下可以申请保单贷款？
3. 该选项是否把特定条件下的不允许扩大成绝对说法？
```

## Required Model Output Format

请按以下格式输出：

```text
A: 支持/反驳/证据不足
理由：...

B: 支持/反驳/证据不足
理由：...

C: 支持/反驳/证据不足
理由：...

D: 支持/反驳/证据不足
理由：...

最终答案：...
```

## Notes For Human Review

模型输出后，需要人工复核：

```text
1. 模型是否只使用了本文件中的证据。
2. 模型是否逐项判断 A/B/C/D。
3. 模型是否把“证据不足”和“明确反驳”区分开。
4. 最终答案是否符合 multi 格式。
```

## MODEL MESSAGE END
