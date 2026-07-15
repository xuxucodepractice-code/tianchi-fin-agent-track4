# Tier-1 MCQ 独立标定包

本目录的 15 份题卡由公开 group A 题目文件确定性生成，不包含历史标签、pipeline 答案或推理缓存。

## 标定要求

1. 标定前不要查看历史提交、`reasoning_samples`、既有 `local_labels.md` 或审查报告。
2. 每题必须核对 A/B/C/D 全部选项，不能只为候选答案找支持材料。
3. 数值题必须保留公式、单位、时点和中间结果。
4. 每题填写答案、置信度、1–2 条决定性证据及标定人信息。
5. 全部 15 题交回后，实验负责人再揭晓 v0/v1/v2 答案并迁入权威真值表。

任务队列与进度登记见相邻文件 `../tier1_mcq_queue.md`。

## 重新生成

```bash
python -m agent.generate_labeling_packets
```

生成器只读取：

```text
public_dataset_upload/questions/group_a/*.json
```

默认情况下，生成器发现已有题卡会立即失败，以保护可能已经填写的结果。只有确认尚未开始标定、确实要整体重建时，才可使用 `--force`。若重建后出现非预期差异，应先检查公开题目文件是否发生变化。
