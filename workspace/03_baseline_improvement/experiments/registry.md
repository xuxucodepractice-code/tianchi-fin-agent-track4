# Experiment Registry

| ID | 实验 | 父版本 | 唯一变量 | 本地净收益 | Token 变化 | 线上分差 | 状态/决策 |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| E000 | 提交隔离 + Agent Trace Gate | current workspace | 输出、lineage、合并、缓存、API trace、候选冻结与揭标时序护栏 | 不改变答案 | 0 | 不提交 | KEEP_INFRA / Trace Gate ready |
| O000 | Gold Oracle 错误分层 | v0 / v2s1 只读产物 | O1/O2/O3 统一记录与确定性分类 | 已完成 3 题：1 道推理/Prompt、2 道 no_failure | 88,619（3 题 O2+O3） | 不提交 | IN PROGRESS / 3 complete, 12 pending labels |
| B001 | 无 doc_ids 文档卡片召回 | A 榜 100 题隐藏 doc_ids | 68 文档卡片 + card BM25，K=12 | Complete Recall 96%；Micro Recall 98.27% | 0 | 不提交 | KEEP_INFRA / B dry-run 100/100 |
| E001 | TF 题干级判断链路包 | v0 产物级合成 | 20 道 TF 改用题干级 true/false/uncertain（含已有重问链路） | N=2，M=0，净 +2；正确题数 68→70 | +7,170 | +1.8305（65.0912） | KEEP_SCORE / FROZEN / LEGACY_PRE_TRACE_GATE |
| E002 | MCQ 四选一统一比较 | v2s1 / E001 KEEP_SCORE | 15 道 MCQ 使用 4 次独立参考判断 + 1 次统一比较，最终答案只由第 5 次调用决定；其余 85 道继承 | 未运行、无 N/M；13 prospective + 2 known regression 分开报告 | 未实测 | 未提交 | PREPARED / HUMAN_ATTESTATION_RECORDED / CODE_FREEZE_PENDING / NOT_RUN |
| E003 | MCQ 确定性计算校验 | E002 KEEP 版本 | 仅增加算术复核 | 待测 | 待测 | 待测 | PLANNED |
| E004 | Multi 逐要素 support 试点 | 最佳已保留版本 | support 判准 | 待测 | 待测 | 待测 | PLANNED |
| E005 | Multi 整题一致性复核 | E004 KEEP 版本 | 仅增加整题复核 | 待测 | 待测 | 待测 | PLANNED |

状态建议使用：

```text
PLANNED / IN PROGRESS / PILOT / KEEP_INFRA / KEEP_SCORE / KEEP_CODE_ONLY / ROLLBACK / BLOCKED
```

## Trace Gate 口径

- E000 的 Trace Gate 扩展是基础设施，答案变化与本步骤 API 调用均为 0，不产生计分版本；
- E001 只能标记为 `LEGACY_PRE_TRACE_GATE`，不能事后补写 trace，但其 `KEEP_SCORE` 不受影响；
- E002 selection 已冻结且不含答案。15 题都要求 fresh trace，其中 13 题可作 prospective
  时序评估，`ins_a_001`、`ins_a_002` 仅作已知标签回归；
- E002 的 M1 与 v2s2 identity 已完成本地无 API 测试；当前仍未运行 API、未生成答案或
  候选，也没有 N/M。Gate 通过本身不构成 `KEEP_SCORE`；确定性计算复核只在 E003 单独进行。
