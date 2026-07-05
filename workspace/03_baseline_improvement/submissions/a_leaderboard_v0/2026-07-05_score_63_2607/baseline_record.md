# A Leaderboard v0 Baseline Record

## Snapshot

- Baseline name: `a_leaderboard_v0_score_63_2607`
- Frozen at: 2026-07-05
- Online submission time: 2026-07-05 15:47:32
- Online score: 63.2607
- Leaderboard split: A 榜
- Submission file: `answer.csv`
- Purpose: 作为后续 v1 检索、prompt、答案后处理和 token 优化的对照基准。

## Local Validation

```text
[VALID] questions=100 total_tokens=1161593
```

## Run Manifest Summary

```text
run_started_at: 2026-07-05T15:31:14+08:00
run_finished_at: 2026-07-05T15:36:20+08:00
mode: qwen
requested_scope: all
success_count: 100
failure_count: 0
low_confidence_count: 17
resume: True
reused_from_cache_count: 77
total_prompt_tokens: 1141466
total_completion_tokens: 20127
total_tokens: 1161593
average_total_tokens: 11615.93
```

## Frozen Artifacts

- `answer.csv`: official upload file.
- `evidence.json`: per-question retrieval, judgments, warnings, token records.
- `run_manifest.json`: run metadata and summary.

## SHA256

```text
c1a70a5697fbb55b0248d2a6b9aa34ca7279975ed3689d5cadc5f9a7b22421ff  answer.csv
ba5ee86f9155672cace1fe7a2428bb30ec8e01f62bb96bef9dbdf8133029de49  evidence.json
b22230895d9f421a578ecf49e70e58e46f93bde5a8434acf1040fb77f1d8e451  run_manifest.json
```

## Low Confidence Qids

```text
fc_a_008
fc_a_013
fc_a_018
fin_a_006
fin_a_013
fin_a_015
fin_a_018
ins_a_001
ins_a_002
ins_a_003
ins_a_006
ins_a_020
reg_a_003
reg_a_008
reg_a_018
res_a_003
res_a_013
```

## Comparison Rule

后续所有 v1 改动都应至少记录：

- 改动点。
- 新 answer.csv 的线上分数。
- total_tokens 变化。
- low_confidence_count 变化。
- 与本基准相比提升或下降。

除非明确决定替换基准，否则不要覆盖本目录内三份冻结产物。
