# Artifact Rules

## 四类产物

| 类型 | 位置 | 允许上传 | 是否不可变 |
| --- | --- | --- | --- |
| 测试产物 | `outputs/tests/` | 否 | 否 |
| dry-run 产物 | `outputs/dry_runs/` | 否 | 否 |
| 实验产物 | `outputs/experiments/<experiment_id>/` | 否 | 否 |
| 候选产物 | `outputs/candidates/<pipeline_version>/` | 待晋升 | 写入 `candidate_freeze.json` 后冻结 |
| 正式上传出口 | `submission/` | 是 | 上传前禁止再修改 |
| 已提交快照 | `workspace/03_baseline_improvement/submissions/` | 已上传 | 是 |

## 正式提交规则

`submission/` 只能由显式正式命令写入。以下流程不得写入：

- pytest；
- dry-run；
- mock；
- 单题冒烟；
- 尚未通过 Go/No-Go 的实验。

正式上传前必须确认：

1. `answer.csv`、`evidence.json`、`run_manifest.json` 都包含相同的 100 个 qid。
2. pipeline version、mode、model 一致。
3. Token 汇总一致。
4. 不含 dry-run、mock 或占位判断。
5. 先复制到不可变候选目录并计算 SHA256。
6. 上传后立即复制到 `submissions/` 并记录线上分数。

## 含新 API 推理的候选

从 E002 起，非空 rerun 还必须满足：

1. 使用无答案、`frozen_before_labeling=true` 的 selection 文件；
2. 在 `outputs/experiments/` 下创建空输出；cache 只能位于该 output 内，fresh run
   禁止 `--resume` 和旧 cache 复用；
3. 实验产物携带 `agent-trace/v1` 的 calls、derivations 与 manifest；
4. trace 同时冻结公开题目、chunks、doc metadata、代码、模型、Prompt 和响应哈希；
5. 合并器验证 trace、selection、rerun qids、experiment 与 pipeline 完全一致，并验证
   所有 inherited qid 与冻结父版本逐字段相同；
6. 合并后自动生成不可覆盖的 `candidate_freeze.json`，并将 trace 复制进候选目录；
7. 原始 rerun、冻结 parent 与候选均保留到上传后，供 validator 复核 lineage 和 SHA256；
8. 揭标前 candidate validator 必须为 `VALID / PENDING_LABEL_REVEAL`；
9. 揭标后单独生成 `label_reveal.json`，上传前必须为 `VALID / PASS`；
10. 盲标答案、历史 pipeline 答案和 Gold Oracle 结论不得进入生成输入。

Trace、freeze 或 reveal 任一哈希不一致，候选立即失去上传资格。详细字段和命令见
`agent_trace_gate.md`。

### 允许的无 Trace 特例

只有 `rerun_qids` 为空、候选三件套与冻结父版本三件套逐字节相同的
`byte_identical_parent_copy` 可以不带 trace。它只用于父版本回归，不构成新 Agent 实验。

### 不可变的实际含义

候选冻结后，不得修改三件套、冻结 selection、复制的 trace 或 `candidate_freeze.json`。
若需重跑，必须使用新目录和新运行 ID。首次揭标时间只能由
`agent.register_label_reveal` 自动写入另一个文件，不能回填到冻结记录。
