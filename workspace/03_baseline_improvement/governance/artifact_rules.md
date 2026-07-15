# Artifact Rules

## 四类产物

| 类型 | 位置 | 允许上传 | 是否不可变 |
| --- | --- | --- | --- |
| 测试产物 | `outputs/tests/` | 否 | 否 |
| dry-run 产物 | `outputs/dry_runs/` | 否 | 否 |
| 实验产物 | `outputs/experiments/<experiment_id>/` | 否 | 否 |
| 候选产物 | `outputs/candidates/<pipeline_version>/` | 待晋升 | 晋升后冻结 |
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
