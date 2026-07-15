# Tier-2 Case: ins_a_002

## Gold label

- answer：A
- confidence：high
- source：历史人工审计；三项退保规则均已定位

## Required facts

| fact_id | 必要事实 | doc_id | page | chunk_id | 计算 |
| --- | --- | --- | ---: | --- | --- |
| F1 | 智盈金生第 6–10 保单年度现金价值为累计保费 + 累计收益的 75% | 1 | 13 | `insurance:1:13:0` | 10+2×75%=11.5 万 |
| F2 | 增益宝现金价值为个人账户价值扣除退保费用；第六年及以后退保费用 0% | 2 | 9 | `insurance:2:9:0` | 12×(1−0%)=12 万 |
| F3 | 富鸿金生犹豫期后解除合同退还现金价值 | 16 | 10 | `insurance:16:10:0` | 题设现金价值 9 万 |

最终排序：12 > 11.5 > 9，对应 A。

## O1 Gold Chunk

- [x] 三项原始规则均存在于 PDF。
- [x] 三项规则均存在于 `chunks.jsonl`。
- 结论：无解析缺失。

## O3 Current Evidence 预审

- 当前检索的原始/合并 chunk ID 覆盖三个必要 chunk。
- 当前生产 evidence 文本保留智盈金生 75% 与增益宝 0% 规则。
- 当前生产 evidence 文本未完整保留富鸿金生“解除合同退还现金价值”的决定性语句。
- 初步层级：`evidence_organization`，仍需 O2 和受控当前推理确认。

## O2/O3 结果

- Gold Evidence：A（正确）；10,811 tokens。
- Current Evidence：A（正确）；17,531 tokens。
- 模型：qwen-plus；pipeline：v2s1。
- 主分类：`no_failure`。
- 风险标记：`evidence_organization`。

当前答案正确，因此不计入错误题；缺失的富鸿金生退保语句作为回归风险保留。
