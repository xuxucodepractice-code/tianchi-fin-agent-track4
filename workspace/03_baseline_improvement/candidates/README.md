# Candidates

本目录只登记已通过本地 Go/No-Go、等待生成或上传正式提交件的候选版本。

候选版本目录建议：

```text
candidates/<pipeline_version>/
├── README.md
├── parent_version.txt
├── experiment_ids.txt
├── answer_diff.csv
├── validation_report.md
└── sha256.txt
```

大型 `answer.csv`、`evidence.json` 和 `run_manifest.json` 运行产物放在项目根目录：

```text
outputs/candidates/<pipeline_version>/
```

只有验证通过并准备上传时，才复制到根目录 `submission/`。取得线上分数后，再冻结到 `submissions/`。
