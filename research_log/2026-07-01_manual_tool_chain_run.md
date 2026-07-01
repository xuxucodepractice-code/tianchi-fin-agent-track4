# 2026-07-01 Manual Tool Chain Run

## Date

2026-07-01

## Track

学习理解线

## Context

目前已经建立三个最小学习工具：

```text
inspect_question.py  # 读取题目
map_doc_id.py        # 映射 doc_id 到 raw 文件路径
search_keyword.py    # 在 PDF 中搜索一个关键词
```

本次目标不是写新工具，而是手动把三个工具串起来跑一遍，理解工具之间如何接力。

## Goal

验证最小工具链：

```text
题目 -> 文档路径 -> 证据线索
```

也就是：

```text
inspect_question.py
-> map_doc_id.py
-> search_keyword.py
```

## Actions

### 1. 读取题目

命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/inspect_question.py ins_a_007
```

关键输出：

```text
domain: insurance
answer_format: multi
doc_ids:
- 1
- 2
- 16
```

含义：

```text
题目属于 insurance 领域，需要查 1、2、16 三个原始文档。
```

### 2. 映射 doc_id 到文件路径

命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 1
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 2
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/map_doc_id.py insurance 16
```

输出：

```text
public_dataset_upload/raw/insurance/1.pdf
public_dataset_upload/raw/insurance/2.pdf
public_dataset_upload/raw/insurance/16.pdf
```

含义：

```text
题目里的抽象编号已经变成可以打开的本地 PDF 路径。
```

### 3. 搜索关键词

命令：

```bash
python3 workspace/01_agent_learning/sessions/2026-06-26_ins_a_007/scripts/search_keyword.py public_dataset_upload/raw/insurance/16.pdf 保单贷款
```

关键输出：

```text
page: 2
6.2 保单贷款

page: 9
经被保险人书面同意，您可申请保单贷款功能。
在本合同有效期内，经我们审核同意后您可办理保单贷款。
贷款金额不得超过本合同当时现金价值的 80%...
```

含义：

```text
page 2 是目录命中。
page 9 是正文证据线索命中。
```

## Difficulties

运行 `search_keyword.py` 时遇到：

```text
ModuleNotFoundError: No module named 'pypdf'
```

原因：

```text
前两个工具只依赖 Python 标准库。
第三个工具需要读取 PDF 文本，因此依赖 pypdf。
```

解决：

```text
在当前 Python 环境安装 pypdf 后重新运行，工具成功输出命中页码和上下文。
```

## Research Notes

这次手动跑通说明工具之间的接力关系已经清楚：

```text
上一个工具的输出，变成下一个工具的输入。
```

具体是：

```text
ins_a_007
-> inspect_question.py 输出 domain 和 doc_ids
-> map_doc_id.py 把 domain + doc_id 转成 PDF 路径
-> search_keyword.py 在 PDF 中找关键词上下文
-> 人或模型再判断证据是否支持选项
```

这对应未来 Agent workflow 的前三步：

```text
load_question
-> map_doc_ids
-> search_evidence
```

当前仍然没有进入模型推理。模型或人只在最后一步判断证据含义。

## Next Step

下一步可以继续保持手动 workflow，不急着自动合并：

```text
1. 用 search_keyword.py 分别搜索 1.pdf、2.pdf、16.pdf 的关键线索。
2. 对比工具输出和人工解题记录。
3. 决定是否需要把三工具合成一个小 workflow 脚本。
```

暂时不进入多关键词检索、模型 API 或 baseline。
