# 02 Baseline Understanding

目标：在已有 Agent 基础直觉后，逐模块理解比赛 baseline，不把它当黑盒。

## 应放内容

- baseline 数据流图
- 单题复现记录
- 模块拆解笔记
- `doc_id -> raw file path` 映射设计
- 文档解析策略说明
- 检索流程说明
- prompt 与答案校验说明
- Token 统计说明
- baseline 失败模式总结

## 推荐子目录

```text
single_question_runs/  # 1 道题、5 道题的小规模复现记录
module_notes/          # 各模块职责拆解
data_flow/             # 数据流图、流程图
doc_id_mapping/        # doc_id 映射表和设计说明
failure_modes/         # baseline 错误类型和原因
```

## 通关目标

能不用看代码，口头解释完整 baseline 流程：

```text
questions JSON
-> doc_id map
-> raw document
-> parsed text
-> chunks
-> retrieval
-> Qwen reasoning
-> answer normalization
-> token summary
-> answer.csv
```

