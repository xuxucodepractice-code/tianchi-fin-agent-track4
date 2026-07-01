# 2026-07-01 Map Doc ID Tool

## Date

2026-07-01

## Track

学习理解线

## Context

`ins_a_007` 的阶段 00 人工解题闭环已经完成，并且已经建立第一个学习工具：

```text
inspect_question.py
```

它负责：

```text
qid -> question / options / answer_format / doc_ids
```

下一步进入“工具辅助 1 题”，需要把题目里的 `doc_ids` 映射到本地 raw 文件路径。

## Goal

建立第二个最小学习工具：

```text
map_doc_id.py
```

功能：

```text
domain + doc_id -> public_dataset_upload/raw/<domain>/<doc_id>.pdf
```

## Actions

新增脚本：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py
```

新增测试：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/tests/test_map_doc_id.py
```

运行示例：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 1
```

输出：

```text
public_dataset_upload/raw/insurance/1.pdf
```

## Verification

先写失败测试，再写最小实现。

最终验证：

```bash
python3 -m pytest workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/tests -q
```

结果：

```text
3 passed
```

## Research Notes

这个工具对应未来 Agent workflow 中的：

```text
map_doc_ids
```

现在的小流程变成：

```text
inspect_question.py
-> 得到 domain 和 doc_ids
-> map_doc_id.py
-> 得到 raw PDF 路径
```

这一步仍然不涉及模型推理。它体现的是一个原则：

```text
确定性、机械、可验证的动作优先交给代码。
语义理解和证据判断再交给人或模型。
```

## Next Step

继续“工具辅助 1 题”：

```text
关键词搜索工具
```

目标是让程序辅助搜索文档中的关键词，但仍然由人来判断证据含义。
