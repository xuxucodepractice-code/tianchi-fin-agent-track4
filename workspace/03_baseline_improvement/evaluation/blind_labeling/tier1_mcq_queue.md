# S2 Tier-1：15 道 MCQ 标定队列

本表只登记标定任务，不记录任何 pipeline 答案。正式标定前应为每题生成独立题卡，并核对全部四个选项；不能只为看似正确的选项寻找支持证据。

| 顺序 | qid | 领域 | doc_ids | 状态 | 标定人 |
| ---: | --- | --- | --- | --- | --- |
| 1 | ins_a_001 | insurance | 1; 2; 15; 16 | 已有高置信历史标签，待迁移复核 |  |
| 2 | ins_a_002 | insurance | 1; 2; 16 | 已有高置信历史标签，待迁移复核 |  |
| 3 | ins_a_003 | insurance | 3; 5; 6 | 待标 |  |
| 4 | ins_a_004 | insurance | 4; 5; 6; 12 | 待标 |  |
| 5 | ins_a_006 | insurance | 5; 6 | 待标 |  |
| 6 | ins_a_013 | insurance | 1; 15; 16 | 待标 |  |
| 7 | ins_a_020 | insurance | 5; 6; 12 | 待标 |  |
| 8 | fc_a_008 | financial_contracts | text02; text03 | 待标 |  |
| 9 | fc_a_015 | financial_contracts | text03; text14 | 待标 |  |
| 10 | fin_a_008 | financial_reports | annual_byd_2024_report; annual_catl_2024_report | 待标 |  |
| 11 | fin_a_015 | financial_reports | annual_catl_2024_report; annual_chinamobile_2025_report | 待标 |  |
| 12 | reg_a_008 | regulatory | strict_v3_009; strict_v3_016 | 待标 |  |
| 13 | reg_a_015 | regulatory | csrc_0009_att1; csrc_0023_att1 | 待标 |  |
| 14 | res_a_008 | research | pack2_text02; pack2_text11 | 待标 |  |
| 15 | res_a_015 | research | pack2_text03; pack2_text14 | 待标 |  |

## 每题 Tier-1 完成条件

- [ ] 正确答案；
- [ ] 置信度；
- [ ] 至少 1–2 条关键证据指针（`doc_id` + 页码或 `chunk_id`）；
- [ ] 四个选项均逐项核对；
- [ ] 标定完成后才揭晓并登记 v0/v1/v2 答案；
- [ ] 若进入 S3 Gold Oracle，再升级为 Tier-2 完整证据卡。
