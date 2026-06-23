# Agent Competition Workspace

AFAC2026 挑战组赛题四：金融长文本 Agent 的动态记忆压缩与高效问答挑战。

## Directory Map

```text
docs/                  # 赛制、规则、评分、数据盘点和路线图
public_dataset_upload/ # 官方 A 榜公开数据和题目
workspace/             # Agent 学习、baseline 理解和改进实验记录
```

## Current Dataset Snapshot

- A 榜题目：5 个 JSON 文件，每个领域 20 道，共 100 道。
- 原始材料：PDF 190 个、HTML 377 个、TXT 6 个。
- 数据领域：保险条款、监管法规、金融合同、财务报表、行业研报。
- 数据总量：约 343 MB。

## Important Docs

- `docs/competition_foundation/README.md`
- `docs/competition_foundation/local_dataset_inventory.md`
- `docs/competition_foundation/public_dataset_scan.md`
- `docs/competition_foundation/submission_scoring_compliance.md`
- `docs/competition_foundation/agent_learning_to_baseline_roadmap.md`

## Suggested Next Work

1. 建立 `doc_id -> raw file path` 映射。
2. 解析 PDF/HTML/TXT，保留页码、章节、条款编号和表格信息。
3. 做不用 embedding 的规则/BM25 检索。
4. 构建单题到全量 A 榜的评估与提交生成流程。
