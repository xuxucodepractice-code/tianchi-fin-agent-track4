# tianchi-fin-agent-track4

AFAC2026 挑战组赛题四：金融长文本 Agent 的动态记忆压缩与高效问答挑战。

This repository is our shared workspace for the Tianchi Financial Long-Text Agent Challenge. The goal is to build a Qwen-based long-document QA agent that can retrieve evidence, compress context, reason over financial documents, and control token cost.

## Project Goal

比赛任务要求针对保险条款、监管法规、金融合同、财务报表、行业研报等长文本材料，构建金融问答 Agent：

- 根据题目定位相关文档和证据。
- 在不使用 embedding 模型的前提下完成检索。
- 使用 Qwen 系列模型完成正式推理问答。
- 输出合法的单选、多选、判断题答案。
- 统计每道题和全局 Token 消耗。
- 生成符合天池要求的 `answer.csv`。

## Repository Map

```text
docs/
  competition_foundation/       # 赛制、规则、评分、数据盘点和路线图

public_dataset_upload/
  questions/group_a/            # A 榜公开题目 JSON
  raw/                          # 官方公开原始材料

workspace/
  01_agent_learning/            # Agent 基础学习和最小实验记录
  02_baseline_understanding/    # baseline 流程拆解、数据流和失败模式
  03_baseline_improvement/      # 检索、prompt、解析、token 优化实验
```

## Dataset Snapshot

当前仓库已包含 A 榜公开数据：

| Item | Count |
| --- | ---: |
| A 榜题目 | 100 |
| 题目 JSON | 5 |
| PDF 文件 | 190 |
| HTML 文件 | 377 |
| TXT 文件 | 6 |
| 数据总量 | 约 343 MB |

领域分布：

| Domain | Raw Files |
| --- | ---: |
| `insurance` | 16 PDF |
| `financial_contracts` | 14 PDF |
| `financial_reports` | 10 PDF |
| `research` | 20 PDF |
| `regulatory` | 377 HTML + 130 attachment PDF + 6 TXT |

## Important Docs

- `docs/competition_foundation/README.md`
- `docs/competition_foundation/task_and_data.md`
- `docs/competition_foundation/local_dataset_inventory.md`
- `docs/competition_foundation/public_dataset_scan.md`
- `docs/competition_foundation/submission_scoring_compliance.md`
- `docs/competition_foundation/agent_learning_to_baseline_roadmap.md`

## Competition Constraints

- 正式推理问答阶段必须使用 Qwen 系列模型 API。
- 禁止使用 embedding 模型进行检索、rerank 或推理。
- 可以在预处理阶段使用 OCR、PDF 转文本、版面分析和表格恢复工具。
- 不能把非 Qwen 模型生成的语义摘要、FAQ、结论提炼结果用于正式答题。
- 提交文件需要包含答案和 Token 统计。

## Suggested Work Plan

1. 建立确定性的 `doc_id -> raw file path` 映射。
2. 分领域解析 PDF、HTML、TXT，保留页码、章节、条款编号和表格信息。
3. 构建不用 embedding 的关键词、BM25、规则字段检索。
4. 按选项逐项判断，输出支持、反驳或证据不足。
5. 加入答案格式校验和 Token 统计。
6. 从单题复现扩展到 5 题、20 题、100 题评估。
7. 记录每次实验的准确率、Token 变化和失败类型。

## Collaboration Workflow

建议队友先拉取仓库：

```bash
git clone git@github.com:xuxucodepractice-code/tianchi-fin-agent-track4.git
cd tianchi-fin-agent-track4
```

开始工作前同步最新内容：

```bash
git pull --rebase
```

建议每个较大的实验开独立分支：

```bash
git checkout -b feat/doc-id-map
```

提交前检查状态：

```bash
git status
```

## Git Notes

仓库当前追踪官方公开数据集，体积较大。以下本地生成内容默认不提交：

- `processed_data/`
- `logs/`
- `submission/`
- `.venv/`
- `.playwright-cli/`
- `.DS_Store`

如果后续生成了可复现的中间文件，应先确认文件大小和用途，再决定是否纳入版本管理。
