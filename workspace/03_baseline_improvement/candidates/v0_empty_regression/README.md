# v0 Empty-Rerun Regression

- 日期：2026-07-14
- 目的：验证冻结 v0 可作为产物级合并父版本。
- rerun_qids：空集。
- 运行产物：`outputs/candidates/v0_empty_regression/`。
- Validator：`VALID / questions=100 / total_tokens=1,161,593`。

## SHA256

| 文件 | SHA256 | 与冻结 v0 |
| --- | --- | --- |
| answer.csv | `c1a70a5697fbb55b0248d2a6b9aa34ca7279975ed3689d5cadc5f9a7b22421ff` | 完全一致 |
| evidence.json | `ba5ee86f9155672cace1fe7a2428bb30ec8e01f62bb96bef9dbdf8133029de49` | 完全一致 |
| run_manifest.json | `b22230895d9f421a578ecf49e70e58e46f93bde5a8434acf1040fb77f1d8e451` | 完全一致 |

结论：S1 父版本可复用门槛通过。
