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
| E006 | Multi 选项到文档的保守路由 | 线上 v2s1 的 v0 Multi 检索 | 仅改变高置信唯一标题命中时的 top-5 chunk 选择 | canonical recall 30/41→34/41；development 6/13→9/13；prospective primary 因 1 个越界 evidence ref NO-GO | development +356；primary 196,512 tokens | 不提交 | DEVELOPMENT_GATE_PASS / PROSPECTIVE_PRIMARY_SCHEMA_NO_GO / REPEAT_NOT_RUN |
| E007 | Multi evidence reference integrity | E006 treatment 检索 | `[证据N]`+整数引用改为 `[EVN]`+严格字符串引用 | 未形成可评分 paired 结果；control 首调用 TLS 失败 | 1 physical attempt / 0 tokens | 不提交 | DEVELOPMENT_NO_GO / CONTROL_TRANSPORT_FAILURE / TREATMENT_NOT_RUN |
| E007R1 | Multi evidence reference integrity TLS-fixed rerun | E007 设计、全新治理身份 | 仅 `[证据N]`+整数引用改为 `[EVN]`+严格字符串引用；CA bundle 是冻结传输环境 | refs 违规归零，但 accuracy 9/13→8/13；父正确题回退 1 | +275 | 不提交 | DEVELOPMENT_NO_GO / TREATMENT_ACCURACY_REGRESSION |
| E008 | Multi trace-bound provenance | E006 treatment retrieval | treatment 取消模型自报 evidence_refs，以完整 Trace evidence pack 作为 provenance | refs 通道安全且 accuracy 8/13 持平，但父正确题回退 1 | -1,643 | 不提交 | DEVELOPMENT_NO_GO / FROZEN_PARENT_REGRESSION |
| E009 | Multi document-order binding | E008 reference-free technical base | 显式绑定题面第一/第二份文档与 doc_ids 顺序 | development 8/13→10/13；primary 60/60 后冻结 validator 误读 evidence 字段，receipt FAIL | primary 192,238 | 不提交 | DEVELOPMENT_GATE_PASS / PROSPECTIVE_PRIMARY_NO_GO / TRACE_VALIDATOR_IMPLEMENTATION_ERROR |
| E010 | Multi Trace evidence-pack binding | E009 model behavior 与 immutable failure Trace | validator replay 从 `context.evidence` 改为 `call.model_evidence`，模型行为不变 | primary/repeat 均 PASS、C=0；frozen churn evaluator 将 retry=0 误读为 -1 | 184,925 + 184,890 | 不提交 | PRIMARY_REPEAT_PASS / FROZEN_CHURN_NO_GO / LABELS_SEALED |
| E011 | E010 churn zero-value audit | immutable E010 primary/repeat/churn | 仅把 retry policy 的 0 与 missing 分开读取；零 API | 独立盲标 N=2、M=0、C=0；投影分数 69.3678 > 65.0912 | 0 API tokens（复用 E010 primary 184,925） | 不提交 | PROSPECTIVE_SCORED_PASS / ALLOW_FULL_65_MULTI_EXPANSION |
| E012 | 65 道 Multi 全量扩展 | E011 scored PASS / v2s1 | 不改变 E009/E010 treatment，仅扩展至官方全部 65 道 Multi | claim/API 前 output-root mkdir 被写护栏拦截 | 0 calls / 0 attempts / 0 tokens | 不提交 | TECHNICAL_NO_GO / PRE_API_WRITE_GUARD_FAILURE |
| E013 | 65 道 Multi 全量扩展技术重跑 | E012 zero-API technical failure | 仅在 guard 前创建新的空 output root；模型行为不变 | guard/claim 回归 + 全套 196 tests PASS | 预注册 260 calls / 0 retries | 不提交 | PREREGISTERED / CODE_TESTED / RUN_FREEZE_PENDING |

状态建议使用：

```text
PLANNED / IN PROGRESS / PILOT / KEEP_INFRA / KEEP_SCORE / KEEP_CODE_ONLY / ROLLBACK / BLOCKED
```
