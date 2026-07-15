# Experiment B001: 无 doc_ids 文档卡片召回

## 基本信息

- 日期：2026-07-14
- 状态：KEEP_INFRA
- parent_version：当前 A 线解析产物，只读
- 唯一变量：题目无 `doc_ids` 时，先进行文档卡片召回
- 线上提交：不需要
- 模型调用：无

## 实现范围

- 为全部 68 份文档建立标题、主体、年份、类型词和文档特异关键词卡片；
- 在领域内做卡片级召回，再进入既有 chunk 检索；
- A 题存在 `doc_ids` 时保持原路径不变；
- `--hide-doc-ids` 只用于离线模拟，禁止与 `--official-output` 同用；
- 当前 B 模式 `K=12`。

## 离线评估

使用 A 榜全部 100 题，检索前隐藏真实 `doc_ids`，检索后才用于计算指标。

| K | Complete Recall | Micro Recall |
| ---: | ---: | ---: |
| 1 | 0.00% | 32.47% |
| 3 | 42.00% | 70.13% |
| 5 | 69.00% | 85.28% |
| 8 | 88.00% | 94.81% |
| 10 | 90.00% | 95.67% |
| 11 | 93.00% | 96.97% |
| 12 | **96.00%** | **98.27%** |
| 13 | 98.00% | 99.13% |
| 14 | 100.00% | 100.00% |

K=10 虽达到总体门槛，但 research=75%、insurance=85%。K=12 是五个领域 Complete Recall 均达到 90% 的最小值：

| 领域 | Complete Recall@12 | Micro Recall@12 |
| --- | ---: | ---: |
| financial_contracts | 95.00% | 97.50% |
| financial_reports | 100.00% | 100.00% |
| insurance | 90.00% | 97.18% |
| regulatory | 100.00% | 100.00% |
| research | 95.00% | 97.50% |

## 端到端 dry-run

```text
requested_scope=all hide_doc_ids
document_selection_mode=card_retrieval_k12
success=100
failure=0
mode=dry_run_mock
tokens=0
```

该运行只验证 loader → 文档卡片 → chunk 检索 → 推理接口 → 三份隔离产物完整连通；占位答案不用于评价正确率。

## 产物与哈希

- `processed_data/doc_cards.json`：`d5308cb190236c2740ec4606cf2d2bb303ab5a88eec6f4c61071e9d4dc720e10`
- `processed_data/doc_recall_report.json`：`4d95951353c4f91672b0f9d27b82e7cedea7269527e5b098b1c7654c2db32c53`
- `outputs/dry_runs/b_mode_full/run_manifest.json`：`5b2e6dcf124d8ac700ebcd9a4de41ab44603e6d46df3b8af1f83aa8018b92a42`

## 决策

标记 `KEEP_INFRA`。当前卡片召回达到离线门槛并完成全链路 dry-run；在真实 B 数据到来前不继续调权重，也不宣称答案质量已验证。07-20 冻结前只接受回归修复和真实数据接口适配。
