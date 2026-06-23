# Local Dataset Inventory

整理日期：2026-06-23  
工作区根目录：`/Users/xuzijian/Desktop/Agent Competition`

## 顶层数据目录

当前 A 榜公开数据位于：

```text
public_dataset_upload/
├── questions/group_a/
└── raw/
```

## A 榜问题文件

| 文件 | 题数 | 字段 |
| --- | ---: | --- |
| `public_dataset_upload/questions/group_a/financial_contracts_questions.json` | 20 | `qid, domain, split, question, options, answer_format, type, doc_ids` |
| `public_dataset_upload/questions/group_a/financial_reports_questions.json` | 20 | `qid, domain, split, question, options, answer_format, type, doc_ids` |
| `public_dataset_upload/questions/group_a/insurance_questions.json` | 20 | `qid, domain, split, question, options, answer_format, type, doc_ids` |
| `public_dataset_upload/questions/group_a/regulatory_questions.json` | 20 | `qid, domain, split, question, options, answer_format, type, doc_ids` |
| `public_dataset_upload/questions/group_a/research_questions.json` | 20 | `qid, domain, split, question, options, answer_format, type, doc_ids` |

合计：A 榜 100 道题。

## Raw 数据盘点

| 领域 | 本地 raw 形态 | 当前可见数量 | 备注 |
| --- | --- | ---: | --- |
| `insurance` | PDF | 16 | 与官方文档数量一致 |
| `financial_contracts` | PDF | 14 | 与官方文档数量一致 |
| `financial_reports` | PDF | 10 | 与官方文档数量一致 |
| `research` | PDF | 20 | 与官方文档数量一致 |
| `regulatory` | HTML/TXT/附件 PDF | HTML 377、TXT 6、附件 130 | 官方说明为 26 份文档；本地以法规网页、严格文本和附件多形态出现，需要按 `doc_ids` 映射 |

## A 榜题目涉及的唯一 doc_id 数

| 领域 | A 榜涉及唯一 `doc_ids` 数 | 说明 |
| --- | ---: | --- |
| `insurance` | 16 | 覆盖 1 至 16 |
| `financial_contracts` | 13 | 覆盖 text01 至 text14 中的 13 个 |
| `financial_reports` | 9 | 覆盖 9 份年报 |
| `research` | 15 | 覆盖 15 份研报 |
| `regulatory` | 15 | 混合 `csrc_*`、`csrc_*_att*` 与 `strict_v3_*` |

## 数据处理注意事项

- A 榜所有题目都带 `doc_ids`，可以先建立确定性 doc_id 到文件路径映射。
- `regulatory` 领域不能只按文件名数量理解，必须区分 HTML 正文、附件 PDF、严格文本 TXT 三种来源。
- 监管 TXT 文件名存在编码异常，但题目 `doc_ids` 中包含可读中文名；后续需要建立标准化映射表。
- PDF 解析需要保留页码、标题层级、表格、条款编号和原始文件路径。
- 生成证据时建议统一输出 `doc_id`、文件路径、页码或章节、引用文本、支持或反驳的选项。

## 建议后续产物目录

```text
processed_data/
├── documents.jsonl
├── chunks.jsonl
├── doc_id_map.json
└── parse_reports/

agent/
├── retrieve.py
├── reason.py
├── answer.py
└── token_meter.py

submission/
├── answer.csv
├── evidence.json
└── run_manifest.json
```

