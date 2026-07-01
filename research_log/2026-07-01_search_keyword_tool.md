# 2026-07-01 Search Keyword Tool

## Date

2026-07-01

## Track

学习理解线

## Context

学习线已经有两个最小工具：

```text
inspect_question.py  # qid -> question / options / answer_format / doc_ids
map_doc_id.py        # domain + doc_id -> raw PDF 路径
```

下一步需要从“知道文档在哪里”推进到“知道证据可能在哪里”。

## Goal

建立第三个最小学习工具：

```text
search_keyword.py
```

功能：

```text
PDF 文件 + 一个关键词
-> 命中页码 + 附近原文片段
```

当前只支持一个关键词，不做多关键词排序、去重、BM25、向量检索或答案判断。

## Actions

新增脚本：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py
```

新增测试：

```text
workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/tests/test_search_keyword.py
```

运行示例：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/16.pdf 保单贷款
```

示例结果：

```text
page: 2  # 目录命中
page: 9  # 正文证据命中
```

## Verification

先写失败测试，再写最小实现。

最终验证：

```bash
python3 -m pytest workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/tests -q
```

结果：

```text
5 passed
```

## Research Notes

这个工具对应未来 Agent workflow 中的：

```text
search_evidence
```

当前工具链变成：

```text
inspect_question.py
-> map_doc_id.py
-> search_keyword.py
```

它体现的原则是：

```text
先用确定性工具把长文档缩小成证据候选片段。
再由人或模型判断片段是否真的支持选项。
```

## Next Step

下一步仍在“工具辅助 1 题”范围内：

```text
把三个工具串成一次手动 workflow：
1. inspect_question.py 读取题目
2. map_doc_id.py 找文档路径
3. search_keyword.py 搜关键词
4. 人工判断证据
```

暂时不进入多关键词检索、模型 API 或 baseline。
