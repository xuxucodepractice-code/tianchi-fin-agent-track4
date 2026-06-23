# Public Dataset Scan

扫描日期：2026-06-23  
扫描对象：`public_dataset_upload/`

## 总览

| 指标 | 数值 |
| --- | ---: |
| 总大小 | 343 MB |
| 总文件数 | 580 |
| JSON 题目文件 | 5 |
| PDF 文件 | 190 |
| HTML 文件 | 377 |
| TXT 文件 | 6 |
| `.DS_Store` | 2 |

目录结构：

```text
public_dataset_upload/
├── questions/group_a/
└── raw/
    ├── financial_contracts/
    ├── financial_reports/
    ├── insurance/
    ├── regulatory/
    │   ├── attachments/
    │   ├── html/
    │   └── txt/
    └── research/
```

## 大小分布

| 路径 | 大小 |
| --- | ---: |
| `public_dataset_upload/raw/financial_contracts` | 106 MB |
| `public_dataset_upload/raw/financial_reports` | 105 MB |
| `public_dataset_upload/raw/regulatory` | 72 MB |
| `public_dataset_upload/raw/research` | 53 MB |
| `public_dataset_upload/raw/insurance` | 7.1 MB |
| `public_dataset_upload/questions/group_a` | 84 KB |

## A 榜题目文件

| 文件 | 题数 | 领域 | split | answer_format 分布 |
| --- | ---: | --- | --- | --- |
| `financial_contracts_questions.json` | 20 | `financial_contracts` | `A` | `multi`: 13, `tf`: 5, `mcq`: 2 |
| `financial_reports_questions.json` | 20 | `financial_reports` | `A` | `multi`: 13, `tf`: 5, `mcq`: 2 |
| `insurance_questions.json` | 20 | `insurance` | `A` | `multi`: 13, `mcq`: 7 |
| `regulatory_questions.json` | 20 | `regulatory` | `A` | `multi`: 13, `tf`: 5, `mcq`: 2 |
| `research_questions.json` | 20 | `research` | `A` | `multi`: 13, `tf`: 5, `mcq`: 2 |

全局分布：

| 项目 | 数值 |
| --- | ---: |
| 总题数 | 100 |
| 多选题 `multi` | 65 |
| 判断题 `tf` | 20 |
| 单选题 `mcq` | 15 |
| 4 选项题 | 80 |
| A/B 判断题 | 20 |
| 每题 `doc_ids` 数量 | 最少 2，最多 4，平均 2.31 |

题目字段统一为：

```text
qid, domain, split, question, options, answer_format, type, doc_ids
```

注意：题目文件没有标准答案字段。后续需要生成 `answer.csv`，不能从本地 JSON 直接读取答案。

## doc_id 一致性

本次扫描中，A 榜所有题目 `doc_ids` 都能映射到本地 raw 材料，未发现缺失。

| 领域 | 题目数 | A 榜唯一 doc_id 数 | 缺失 doc_id |
| --- | ---: | ---: | --- |
| `financial_contracts` | 20 | 13 | 无 |
| `financial_reports` | 20 | 9 | 无 |
| `insurance` | 20 | 16 | 无 |
| `regulatory` | 20 | 15 | 无 |
| `research` | 20 | 15 | 无 |

## Raw 数据形态

| 领域 | 文件形态 | 数量 |
| --- | --- | ---: |
| `financial_contracts` | PDF | 14 |
| `financial_reports` | PDF | 10 |
| `insurance` | PDF | 16 |
| `research` | PDF | 20 |
| `regulatory` | HTML | 377 |
| `regulatory` | 附件 PDF | 130 |
| `regulatory` | TXT | 6 |

## PDF 页数粗扫

本机没有 `pdfinfo/pdftotext`，本次使用 macOS `file` 命令做页数粗扫。部分 PDF 因编码或结构原因未返回页数。

| 领域 | PDF 数 | 可读页数文件 | 已知总页数 | 已知平均页数 | 最大页数文件 |
| --- | ---: | ---: | ---: | ---: | --- |
| `research` | 20 | 20 | 775 | 38.8 | `pack2_text04.pdf`，106 页 |
| `regulatory/attachments` | 130 | 121 | 2366 | 19.6 | `csrc_0008_att1.pdf`，394 页 |
| `financial_contracts` | 14 | 10 | 3121 | 312.1 | `text10.pdf`，516 页 |
| `financial_reports` | 10 | 6 | 1590 | 265.0 | `annual_midea_2024_report.PDF`，295 页 |
| `insurance` | 16 | 13 | 213 | 16.4 | `6.pdf`，42 页 |

最长文件前几名：

| 页数 | 文件 |
| ---: | --- |
| 516 | `public_dataset_upload/raw/financial_contracts/text10.pdf` |
| 495 | `public_dataset_upload/raw/financial_contracts/text04.pdf` |
| 468 | `public_dataset_upload/raw/financial_contracts/text08.pdf` |
| 394 | `public_dataset_upload/raw/regulatory/attachments/csrc_0008_att1.pdf` |
| 295 | `public_dataset_upload/raw/financial_reports/annual_midea_2024_report.PDF` |
| 290 | `public_dataset_upload/raw/financial_reports/annual_byd_2024_report.PDF` |

## Regulatory 特殊情况

`regulatory` 领域是最特殊的：

- 题目涉及 `csrc_*` HTML 正文。
- 题目涉及 `csrc_*_att*` PDF 附件。
- 题目涉及 `strict_v3_*` TXT 法规文本。
- TXT 文件名显示为 mojibake，但内容是 UTF-8 with BOM，可正常读出中文正文。

`strict_v3_*` 的映射应按数字前缀处理，例如：

| 题目 doc_id | 本地文件匹配策略 |
| --- | --- |
| `strict_v3_008_中国人民银行令〔2025〕第12号（金融机构客户受益所有人识别管理办法）` | 匹配 `strict_v3_008_*.txt` |
| `strict_v3_009_中国人民银行_国家金融监督管理总局_中国证券监督管理委员会令〔2025〕第11号...` | 匹配 `strict_v3_009_*.txt` |
| `strict_v3_015_中国人民银行令〔2025〕第3号...` | 匹配 `strict_v3_015_*.txt` |
| `strict_v3_016_中国人民银行_国家金融监督管理总局令〔2025〕第2号...` | 匹配 `strict_v3_016_*.txt` |
| `strict_v3_017_中华人民共和国反洗钱法` | 匹配 `strict_v3_017_*.txt` |
| `strict_v3_018_中国人民银行令〔2024〕第4号...` | 匹配 `strict_v3_018_*.txt` |

## 对 baseline 工程的直接启发

1. 先建立确定性的 `doc_id -> raw file path` 映射，不要在运行时临时猜路径。
2. PDF 解析优先级应按领域区分：金融合同和财报最长，必须做章节、页码、表格级解析；保险条款短，可以更直接做条款级切分。
3. `regulatory` 需要三套解析器：HTML 正文解析、附件 PDF 解析、TXT 法规解析。
4. 判断题只有 A/B 选项，答案标准化逻辑不能强行要求 A/B/C/D 四项齐全。
5. `type` 字段风格不统一，有中文、英文和枚举混用，不能把它当强 schema 使用。
6. `.DS_Store` 可以在后续打包、遍历和 checksum 时排除。
7. 本数据集没有标准答案，评测只能通过线上提交反馈或自建人工/弱标注验证集来估计。

