# Local Labels For Submission Experiments

本文件是提交线本地真值的唯一权威来源，仅用于离线评估和回归测试。禁止复制到
正式提交产物，也禁止在正式推理时把这里的答案注入模型。

基准：

- v0 线上分数：63.2607；
- v1s1 线上分数：61.8540；
- v0 冻结产物：`submissions/a_leaderboard_v0/2026-07-05_score_63_2607/`；
- S2a 盲标批次：`S2A_TF_GATE_2026-07-14`，2026-07-15 验收完成。

## Labeled Questions

| qid | format | label | confidence | source | v0 | v1s1 | v2s1 | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ins_a_007 | multi | BC | high | 学习线人工/模型复核；v1-0 审计同意 | AC | BC | — | v1s1 修复，但不属于 E001。 |
| ins_a_001 | mcq | B | high | v1-0 审计定位四个产品公式 | A | A | — | E002 硬验收题，不属于 E001。 |
| ins_a_002 | mcq | A | high | v1-0 审计定位三组公式 | A | A | — | v0/v1 答案正确但推理较弱。 |
| fc_a_013 | tf | A | high | v1-0 审计；两文档事实核对 | A | A | A | E001 回归题。 |
| fin_a_006 | tf | A | high | v1-0 审计；11.7% 与 10% 边界、单位核对 | A | A | A | E001 回归题。 |
| res_a_003 | tf | A | medium-high | v1-0 审计；50%/37% 比较方向核对 | A | A | A | rationale/verdict 一致性回归题。 |
| reg_a_018 | tf | A | medium | v1-0 审计；相关处罚条文核对 | A | A | A | E001 回归题。 |
| fin_a_013 | tf | A | high | v1-0 审计 | A | A | A | 旧 rationale/tag 矛盾回归题。 |
| fc_a_003 | tf | A | high | 本地 chunk 核对 text01/text03 | A | A | A | 非 low-confidence 标定样本。 |
| fc_a_006 | tf | A | medium-high | 本地 chunk 核对 text01/text04 | A | A | A | 非 low-confidence 标定样本。 |
| fc_a_010 | tf | A | high | 本地 chunk 核对 text02/text06 | A | A | A | 非 low-confidence 标定样本。 |
| reg_a_010 | tf | B | high | 独立 S2a 盲标；第 30 条要求“可疑交易报告”而非“大额交易报告” | A | A | B | E001：旧错新对。 |
| res_a_013 | tf | B | high | 独立 S2a 盲标；2786 亿元/30.2% 为美国 2024 数据，中国 2025 为约 395 亿元 | A | A | B | E001：旧错新对。 |

## E001 Calibration Conclusion

- 已标定 TF：10 题，其中 A=8、B=2；
- v0：8/10；
- v2s1：10/10；
- 旧错新对 `N=2`；
- 旧对新错 `M=0`；
- 本地净收益 `N-M=+2`；
- v2s1 相对 v0 的 100 题答案 diff 仅为 `reg_a_010 A→B`、`res_a_013 A→B`。

该结论只授权 E001 晋升为候选并占用一次线上提交机会；最终是否 `KEEP_SCORE` 必须
等待线上分数。

## Provenance

- `blind_labeling/S2a/selection.json`：盲标前冻结的两题集合；
- `blind_labeling/S2a/reg_a_010_blind.md`；
- `blind_labeling/S2a/res_a_013_blind.md`；
- `blind_labeling/S2a/results.json`：`complete=true`、2/2、0 errors。
