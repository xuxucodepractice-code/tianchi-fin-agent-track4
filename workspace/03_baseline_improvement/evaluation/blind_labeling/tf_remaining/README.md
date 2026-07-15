# S2 剩余 TF 预注册盲标包

本集合在查看新标定结果前冻结。它包含除 8 道历史标签和 S2a 两题以外的全部 10 道 TF，因此不存在“发现足够多 B 后提前停止”的选择偏差。

## 集合组成

| qid | 领域 | 状态 |
| --- | --- | --- |
| fc_a_018 | financial_contracts | 待盲标 |
| fin_a_003 | financial_reports | 待盲标 |
| fin_a_010 | financial_reports | 待盲标 |
| fin_a_018 | financial_reports | 待盲标 |
| reg_a_003 | regulatory | 待盲标 |
| reg_a_006 | regulatory | 待盲标 |
| reg_a_013 | regulatory | 待盲标 |
| res_a_006 | research | 待盲标 |
| res_a_010 | research | 待盲标 |
| res_a_018 | research | 待盲标 |

## 完成要求

- 同一标定人或互相隔离的标定人完成全部 10 题；
- 每题先拆分题干事实，再核对全部事实；
- 每题记录答案、置信度与 1–2 条决定性证据；
- 全部交回后一次性统计 `N_B`，不得中途揭晓 pipeline 答案；
- 与已有 8 题和 S2a 两题合并后，形成 20 道 TF 的完整本地真值覆盖。

预注册集合的机器可读版本为 `selection.json`。
