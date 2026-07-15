# Evidence Requirements

每道标定题需要定义“回答正确所必需的最小证据集合”。

## 通用字段

```yaml
qid:
gold_answer:
confidence:
required_facts:
  - fact_id:
    description:
    doc_id:
    page:
    chunk_id:
    required_for_options:
calculation:
primary_failure:
secondary_failure:
```

## 题型要求

### TF

- 题干中的每个并列事实点；
- 多文档陈述的每份必要文档；
- 能直接支持或反驳题干的原文。

### MCQ

- 区分四个选项所需的全部事实；
- 排序、比例或金额题所需的全部公式与数值；
- 单位和时间口径。

### Multi

每个选项分别核对：

- 主体；
- 时间；
- 数值与单位；
- 比较方向；
- 范围与条件；
- 否定词。
