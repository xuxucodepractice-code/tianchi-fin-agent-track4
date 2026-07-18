# Experiment Registry

| ID | 实验 | 父版本 | 唯一变量 | 本地净收益 | Token 变化 | 线上分差 | 状态/决策 |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| E000 | 提交与测试产物隔离 | current workspace | 输出目录、lineage、合并与缓存护栏 | 不改变答案 | 0 | 不提交 | KEEP_INFRA（当前全套 132 tests） |
| O000 | Gold Oracle 错误分层 | v0 / v2s1 只读产物 | O1/O2/O3 统一记录与确定性分类 | 已完成 3 题：1 道推理/Prompt、2 道 no_failure | 88,619（3 题 O2+O3） | 不提交 | IN PROGRESS / 3 complete, 12 pending labels |
| B001 | 无 doc_ids 文档卡片召回 | A 榜 100 题隐藏 doc_ids | 68 文档卡片 + card BM25，K=12 | Complete Recall 96%；Micro Recall 98.27% | 0 | 不提交 | KEEP_INFRA / B dry-run 100/100 |
| E001 | TF 题干级判断链路包 | v0 产物级合成 | 20 道 TF 改用题干级 true/false/uncertain（含已有重问链路） | N=2，M=0，净 +2；10 个已标 TF 8/10→10/10 | +7,170 | 待测 | PILOT / VALIDATED / PROMOTED / READY_TO_UPLOAD |
| E002 | MCQ 四选一统一比较 | 最佳已保留版本 | MCQ 推理方式 | 待测 | 待测 | 待测 | PLANNED |
| E003 | MCQ 确定性计算校验 | E002 KEEP 版本 | 仅增加算术复核 | 待测 | 待测 | 待测 | PLANNED |
| E004 | Multi 逐要素 support 试点 | 最佳已保留版本 | support 判准 | 待测 | 待测 | 待测 | PLANNED |
| E005 | Multi 整题一致性复核 | E004 KEEP 版本 | 仅增加整题复核 | 待测 | 待测 | 待测 | PLANNED |
| E006 | Multi 选项到文档的保守路由 | 线上 v2s1 的 v0 Multi 检索 | 仅改变高置信唯一标题命中时的 top-5 chunk 选择 | canonical recall 30/41→34/41；development fresh pair 6/13→9/13，N=3、M=0 | development +356 tokens | 不提交 | DEVELOPMENT_GATE_PASS / PROSPECTIVE_UNLOCKED |

状态建议使用：

```text
PLANNED / IN PROGRESS / PILOT / KEEP_INFRA / KEEP_SCORE / KEEP_CODE_ONLY / ROLLBACK / BLOCKED
```
