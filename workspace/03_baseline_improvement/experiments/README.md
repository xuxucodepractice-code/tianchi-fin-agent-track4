# Experiments

本目录只保存单变量实验的设计、评估和决策记录。大型运行产物放到项目根目录 `outputs/experiments/`。

队友查看当前整体进度，请先读上级目录的 `ablation_progress.md`，再按实验 ID 进入本目录。

## 命名规范

```text
E000_submission_isolation/
E001_tf_direct_judgment/
E002_mcq_global_comparison/
E003_mcq_calculation_check/
E004_multi_atomic_support/
```

## 每个实验目录

```text
<experiment_id>/
├── experiment.md
├── rerun_qids.txt           # 需要时创建
├── answer_diff.csv          # 运行后创建
├── local_evaluation.md      # 运行后创建
├── online_result.md         # 真正提交后创建
└── decision.md              # 实验结束时创建
```

所有实验必须登记到 `registry.md`。
