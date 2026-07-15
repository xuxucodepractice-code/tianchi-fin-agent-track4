# Experiment E001: TF 题干级判断链路

## 基本信息

- 日期：2026-07-15；
- parent_version：v0（冻结线上 63.2607 产物）；
- pipeline_version：v2s1；
- 唯一实验包：TF 从逐选项合成改为题干级 `true/false/uncertain` 判断；
- 已知捆绑项：题干级检索与 `uncertain` 最多一次重问均包含在已有 v2s1 实现中，因此线上分差只能归因于“TF 专项链路包”，不能进一步拆归因；
- 影响题型：20 道 TF；
- rerun_qids：`submissions/a_leaderboard_v0/v2_s1/tf_rerun_qids.json` 中冻结的 20 题；
- cached_qids：其余 80 题从 v0 产物级继承。

## 实验前预测与 Go/No-Go

v2s1 在 20 道 TF 中仅把 `reg_a_010`、`res_a_013` 从 A 翻为 B。查看 v2s1
答案前，S2a 已冻结这两题并交由独立标定。

```text
两题均为 B → N=2, M=0，允许进入候选并占用一次提交机会
一 B 一 A → 净收益 0，不提交
两题均为 A → 净 -2，回滚
```

S2a 于 2026-07-15 返回 `B+B / high`，并由本地 validator 复验为
`complete=true / 2 of 2 / 0 errors`，因此门槛通过。

## 实现与产物范围

- 正式推理缓存：`processed_data/reasoning_samples/<qid>.json`，20/20 均通过 `mode=qwen`、`model=qwen-plus`、`pipeline_version=v2s1` 和正 Token 检查；
- cache-only 重打包：`outputs/experiments/E001_tf_v2s1/rerun_bundle/`；
- 候选三件套：`outputs/candidates/v2s1_tf_only/`；
- 正式父版本：`submissions/a_leaderboard_v0/2026-07-05_score_63_2607/`；
- 合成方式：20 道 rerun 记录来自 v2s1，其他 80 道答案、Token 行和 evidence 逐字段继承 v0；
- 本轮构建 API 调用：0。

## 离线结果

| 指标 | v0 | v2s1 候选 | 变化 |
| --- | ---: | ---: | ---: |
| 已标定 TF 正确数 | 8/10 | 10/10 | +2 |
| 旧错新对 N | — | 2 | +2 |
| 旧对新错 M | — | 0 | 0 |
| 答案变化题数 | — | 2/100 | — |
| low confidence | 17/100 | 15/100 | -2 |
| total_tokens | 1,161,593 | 1,168,763 | +7,170 |

答案 diff：

```text
reg_a_010: A -> B（gold B）
res_a_013: A -> B（gold B）
```

其余 98 道答案不变；其中 80 道非 rerun 的完整答案/Token 行与 evidence 和 v0
逐字段相同。20 道 v2s1 bundle Token 为 prompt 125,889、completion 3,769、
total 129,658。

## 验证

- 全量回归：`132 passed`；
- 20 题 rerun bundle validator：`VALID / 20 / 129,658 tokens`；
- 100 题候选 validator：`VALID / 100 / 1,168,763 tokens`；
- E001 专属审计：`PASS / 12 of 12 checks`；
- mode/model/pipeline：`qwen / qwen-plus / v2s1`；
- 预注册 rerun 集：精确 20 道 TF；
- 缓存重打包 manifest：`cache_only=true`、`api_calls=0`、`network_calls=0`。

## 可追溯性限制

v2s1 缓存在生成时没有保存完整 retrieval，因此本次 evidence 是用当前
`chunks.jsonl` 与检索代码重新构建的，manifest 已保存 chunks、retrieve.py 和
query_terms.py 的 SHA256。它能证明当前候选证据与答案一致，但不能声称完全复原
当时 API Prompt 的每个字节。该限制不改变两题独立盲标门槛，但必须保留在实验解释中。

## 当前结论

- 本地决策：`PILOT / GO_TO_CANDIDATE / READY_TO_UPLOAD`；
- 预期线上分数：约 65.0912（仅为两题净提升的推算）；
- 线上结果：待提交；
- 最终决策：待线上结果后填写 `KEEP_SCORE` 或 `ROLLBACK`。
