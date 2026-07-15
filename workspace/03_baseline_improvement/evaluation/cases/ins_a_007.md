# Tier-2 Case: ins_a_007

## Gold label

- answer：BC
- confidence：high
- source：学习线人工检索 + 独立模型证据包复核

## Required facts

| fact_id | 必要事实 | doc_id | page | chunk_id | 对应选项 |
| --- | --- | --- | ---: | --- | --- |
| F1 | 增益宝允许借款，上限为现金价值扣除借款及利息后余额的 80% | 2 | 7 | `insurance:2:7:0` | B |
| F2 | 富鸿金生一般情况下允许保单贷款，金额不超过现金价值 80% | 16 | 9 | `insurance:16:9:0` | 反驳 D |
| F3 | 富鸿金生按个人养老金制度投保时不接受保单贷款申请 | 16 | 9 | `insurance:16:9:0` | C |
| F4 | 智盈金生全文未出现保单贷款/贷款/借款/80%条款 | 1 | 全文 | full-document negative audit | A 不成立 |

## O1 Gold Chunk

- [x] B/C/D 所需正向与反向原文均存在于 PDF 和 Chunk。
- [x] doc 1 已做全文关键词负向审计，不是只因 top-k 未命中而判 A。
- 结论：无解析缺失。

## O3 Current Evidence 预审

- 当前生产 evidence 保留“最高借款金额”“一般允许”“个人养老金制度时不接受”三项关键语句。
- 当前检索足以支持 BC 并排除 D；A 仍依赖完整文档负向审计纪律。

## O2/O3 结果

- Gold Evidence：BC（正确）；7,381 tokens。
- Current Evidence：BC（正确）；17,651 tokens。
- 模型：qwen-plus；pipeline：v2s1。
- 主分类：`no_failure`。
- 风险标记：无。
