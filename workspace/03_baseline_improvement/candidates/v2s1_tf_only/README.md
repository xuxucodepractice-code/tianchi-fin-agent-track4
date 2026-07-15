# Candidate v2s1_tf_only

状态：`VALIDATED / PROMOTED_TO_SUBMISSION / NOT YET UPLOADED`

本候选以冻结 v0（线上 63.2607）为直接父版本，只替换预注册的 20 道 TF 记录。
100 道答案中只有 `reg_a_010` 与 `res_a_013` 从 A 变为 B；两题均已被独立盲标为
B/high，因此本地净收益为 +2，值得占用一次线上提交机会。

实际三件套位于：

```text
outputs/candidates/v2s1_tf_only/answer.csv
outputs/candidates/v2s1_tf_only/evidence.json
outputs/candidates/v2s1_tf_only/run_manifest.json
```

不要上传本目录中的 Markdown 元数据；上传出口只使用项目根目录 `submission/` 中的
三件套。晋升时三份文件必须与上述候选逐字节相同。

2026-07-15T17:44:20+08:00，候选三件套已晋升至项目根目录 `submission/`；三文件
逐字节比较一致，晋升后 validator 再次返回 VALID。

## 当前验收

- 全量测试：132 passed；
- 通用 validator：VALID / 100 questions / 1,168,763 tokens；
- E001 专属审计：12/12 passed；
- 答案 diff：2；其余答案不变：98；
- rerun：20 TF；非 rerun：80；
- API 调用：0（使用已完成的真实 Qwen v2s1 缓存）；
- 预计线上分数：约 65.0912，实际结果待提交。

可追溯性限制：缓存未保存调用时的完整 retrieval；候选 evidence 使用当前冻结 chunks
与检索代码重建，相关哈希已写入 rerun manifest。不得声称原始 Prompt 可字节级复现。
