# Evaluation

本目录保存跨版本共享的本地评估资产：真值、证据要求、单题卡片和错误地图。

## 当前迁移状态

S2a 首批新盲标完成后，历史真值已于 2026-07-15 完整迁移。本目录中的
`local_labels.md` 是唯一权威真值表；旧位置只保留迁移指针，禁止继续写入。

## 目标结构

```text
evaluation/
├── README.md
├── local_labels.md          # 唯一权威真值总表
├── error_map.md
├── evidence_requirements.md
├── blind_labeling/          # 不包含任何 pipeline 答案的独立标定包
└── cases/
    └── <qid>.md
```

当前 S2a 双题盲标入口：`blind_labeling/S2a/README.md`。标定人在提交答案前不得查看
v0、v1 或 v2 的答案、推理缓存、审查报告和实验结论。

其余执行入口：

- 15 道 MCQ：`blind_labeling/tier1_mcq/README.md`；
- 剩余全部 10 道 TF：`blind_labeling/tf_remaining/README.md`；
- 15 道 Multi：`blind_labeling/multi_tier1/README.md`；
- 总体状态：`labeling_status.md`；
- S3 Gold Oracle：`../experiments/O_gold_oracle/README.md`。
