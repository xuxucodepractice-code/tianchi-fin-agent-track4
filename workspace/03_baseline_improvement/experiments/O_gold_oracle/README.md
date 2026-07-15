# S3 Gold Oracle 定位实验

本目录承载 O1 Gold Chunk、O2 Gold Evidence 与 O3 Current Evidence 的统一审计记录。它只做本地诊断，不改变正式答案，也不允许将 `gold_answer` 注入生产推理。

## 预注册样本

共 15 题，其中 11 道 Multi，以匹配当前最可能的误差主体：

- MCQ：`ins_a_001`、`ins_a_002`；
- TF：`reg_a_010`、`res_a_013`；
- Multi：`fc_a_016`、`fin_a_005`、`ins_a_005`、`ins_a_007`、`ins_a_009`、`ins_a_010`、`ins_a_014`、`ins_a_015`、`ins_a_016`、`ins_a_019`、`res_a_014`。

在 S2 标签完成前只允许填写证据位置，不得猜测 `gold_answer`。

## 三步审计

1. O1：确认必要事实是否存在于原始文档以及 `chunks.jsonl`。
2. O2：用人工选定的 gold chunks 运行当前推理。`build_gold_retrieval` 会构造生产推理入口可直接消费的结构，并由生产函数 `format_evidence_block` 渲染；它不读取或注入答案。
3. O3：审计当前检索是否召回全部必要事实、渲染时是否截断或错配，以及模型判断与最终答案是否一致。

## 自动分类

完成 `cases.json` 后运行：

```bash
python -m agent.gold_oracle \
  --input workspace/03_baseline_improvement/experiments/O_gold_oracle/cases.json \
  --output workspace/03_baseline_improvement/experiments/O_gold_oracle/results.json
```

只要有任一字段未完成，命令会以退出码 2 结束，且不会把该题强行归入某个错误层。

## O2/O3 受控模型运行

O1 完成并登记 `required_chunk_ids` 后，使用独立输出目录运行。该命令不会读取或向模型传递 `gold_answer`：

```bash
python -m agent.run_gold_oracle \
  --cases workspace/03_baseline_improvement/experiments/O_gold_oracle/cases.json \
  --qids ins_a_001,ins_a_002,ins_a_007 \
  --output outputs/experiments/S3_gold_oracle/observations.json
```

运行器对每题执行两次受控观察：Gold Evidence 与 Current Evidence。结果先写独立 observations，不会自动覆盖 `cases.json` 或正式提交。

观察结果生成后，使用合并器验证 `mode=qwen`、正 Token 和 qid 一致性，再写入新的 case 副本并分类：

```bash
python -m agent.merge_oracle_observations \
  --cases workspace/03_baseline_improvement/experiments/O_gold_oracle/cases.json \
  --observations outputs/experiments/S3_gold_oracle/observations.json \
  --output-cases outputs/experiments/S3_gold_oracle/cases_observed.json \
  --output-results outputs/experiments/S3_gold_oracle/results.json
```

合并器不原地改写预注册 `cases.json`；确认结果后再由实验负责人回填权威记录。

## 当前进度（2026-07-14）

- 已完成：`ins_a_001`、`ins_a_002`、`ins_a_007` 的 O1/O2/O3；
- 实际消耗：Gold Evidence 34,377 Token，Current Evidence 54,242 Token，合计 88,619 Token；
- `ins_a_001`：Gold Evidence 与 Current Evidence 均答 A，真值为 B，主分类为推理/Prompt；
- `ins_a_002`：两组证据均答 A，与真值一致，分类为 `no_failure`，保留证据组织风险；
- `ins_a_007`：两组证据均答 BC，与真值一致，分类为 `no_failure`；
- 剩余 12 题仍为 `incomplete`，不得据此扩大错误地图计数。

原始观察保存在 `outputs/experiments/S3_gold_oracle/observations.json`，确定性分类保存在
`outputs/experiments/S3_gold_oracle/readiness_check.json`。

## 分类顺序

```text
原始文档缺事实 → 数据/题目
原始文档有、Chunk 无 → 解析
Chunk 有、当前检索未召回 → 检索
召回了但生产渲染丢失关键事实 → 证据组织
Gold Evidence 仍答错或当前判断答错 → 推理/Prompt
模型判断正确但最终答案错误 → 答案合成
全部正确 → no_failure
```
