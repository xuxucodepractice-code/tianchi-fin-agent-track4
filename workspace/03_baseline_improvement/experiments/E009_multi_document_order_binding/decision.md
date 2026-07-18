# E009 Decision

状态：`DEVELOPMENT_GATE_PASS / PROSPECTIVE_PRIMARY_NO_GO / DO_NOT_SUBMIT`

- E008 及以前产物只读保留；
- E009 只测试题面 doc_ids 顺序映射；
- code/run freeze 已完成；fresh control 52/52、零 retry、178,969 tokens、Trace PASS；
- treatment 已获一次性授权，prospective 与 candidate 尚未授权。
- treatment 已完成 52/52、零 retry、181,361 tokens；accuracy 8/13→10/13；
- 父正确题回退为 0，所有 Trace/schema/temporal/retrieval gate PASS；
- 全新的 15 题 prospective selection 已按冻结 SHA256 排序与 `4/4/1/3/3` 最小配额放宽冻结；
- code-freeze commit 与 run-freeze 已完成；下一合法动作是运行一次性 primary，再在其严格 PASS 后运行 repeat；candidate/submission 仍未授权。
- 资格池审计发现 insurance 仅 1 道未使用未标注 Multi，无法满足五领域各 3 道；
- labels/output 均未创建，183 tests PASS，尚无 prospective API 调用；
- 不得删除或覆盖未来任一失败槽，不得复用 E006 holdout 或已知标签题。
- primary 实际完成 60/60、零 retry、192,238 tokens、served model=`qwen-plus`；
- 冻结 Trace validator 因读取错误 evidence 字段产生 60 个 message mismatch，receipt=FAIL；
- E009 primary/claim/run-freeze/output 永久只读，禁止修补、删除、覆盖或重跑；
- repeat、churn、盲标和全量 65 Multi 均不授权。
