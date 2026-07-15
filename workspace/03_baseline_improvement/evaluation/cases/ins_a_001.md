# Tier-2 Case: ins_a_001

## Gold label

- answer：B
- confidence：high
- source：历史人工审计；四个产品公式均已定位

## Required facts

| fact_id | 必要事实 | doc_id | page | chunk_id | 计算 |
| --- | --- | --- | ---: | --- | --- |
| F1 | 智盈金生领取日前身故，按身故时保单账户价值给付 | 1 | 4 | `insurance:1:4:0` | 90 万 |
| F2 | 增益宝 40 岁身故给付比例 160%，身故金额取比例×基本保额与个人账户价值较大者 | 2 | 3 | `insurance:2:3:0` | max(90×160%, 85)=144 万 |
| F3 | 鑫享添盈身故金额取“已交保费−累计养老年金”与现金价值较大者 | 15 | 3 | `insurance:15:3:0` | max(100−20, 80)=80 万 |
| F4 | 富鸿金生身故金额取“累计已交保费−累计已给付养老年金”与现金价值较大者 | 16 | 5 | `insurance:16:5:0` | max(100−15, 80)=85 万 |

最终排序：144 > 90 > 85 > 80，对应 B。

## O1 Gold Chunk

- [x] 四项原始公式均存在于 PDF。
- [x] 四项公式均存在于 `chunks.jsonl`。
- 结论：无解析缺失。

## O3 Current Evidence 预审

- 当前检索的 `merged_chunk_ids` 覆盖四个必要 chunk。
- 当前生产 evidence 文本能看到 doc 2 与 doc 16 的关键公式。
- 当前生产 evidence 文本未完整保留 doc 1 与 doc 15 的决定性公式。
- 初步层级：`evidence_organization`，仍需 O2 和受控当前推理确认。

## O2/O3 结果

- Gold Evidence：A（错误）；16,185 tokens。
- Current Evidence：A（错误）；19,060 tokens。
- 模型：qwen-plus；pipeline：v2s1。
- 主错误层：`reasoning_or_prompt`。
- 风险标记：`evidence_organization`。

完整 Gold Evidence 仍无法完成四产品的统一计算和排序，因此证据截断不是唯一根因；S5/M1 的全题比较是被本题直接解锁的下一实验。
