# 2026-06-28 Research Log System Setup

## Date

2026-06-28

## Context

经过 `ins_a_007` 的阶段 00 学习闭环后，项目中已经出现多类材料：

- 官方数据。
- 学习现场脚本。
- 人工解题记录。
- 原始思考草稿。
- session checklist。

这些材料能记录具体过程，但缺少一个跨日期、跨阶段的研究脉络记录。

## Position In Roadmap

这个动作不属于某一道题本身，而是建立比赛学习和研究的元记录系统。

它服务于后续所有阶段：

```text
阶段 00：人肉解题
阶段 01：工具辅助和最简记忆
阶段 02：可观测状态图
阶段 03：评估与可靠性
阶段 04：比赛版 Agentic RAG
baseline 理解
baseline 优化
```

## Goal

建立根目录级别的 research log：

```text
research_log/
```

用于长期记录：

- 为什么做某个动作。
- 它在体系中的位置。
- 日期和背景。
- 遇到的困难。
- 如何解决。
- 产出的文件。
- 对后续 Agent workflow 或 baseline 优化的启发。

## Actions

创建目录：

```text
research_log/
```

创建说明文件：

```text
research_log/README.md
```

补记第一条核心研究日志：

```text
research_log/2026-06-26_ins_a_007_stage00.md
```

记录本次日志系统建立：

```text
research_log/2026-06-28_research_log_system_setup.md
```

## Artifacts

```text
research_log/README.md
research_log/2026-06-26_ins_a_007_stage00.md
research_log/2026-06-28_research_log_system_setup.md
```

## Difficulties

需要区分三类记录：

```text
workspace：工作现场和具体材料。
Agent思考.md：原始思维草稿。
research_log：跨日期研究脉络。
```

如果不区分，后续会出现：

- 学习代码和正式工具混在一起。
- 临时笔记和研究结论混在一起。
- 实验结果缺少前因后果。
- baseline 优化时无法追踪决策来源。

## Resolutions

建立规则：

```text
workspace/ 记录具体工作现场。
research_log/ 记录研究脉络。
```

以后每次重要动作都补一条 research log。

## Research Notes

这个目录的价值在于支持比赛的科研属性。

比赛不只是提交答案，也需要长期追踪：

- 为什么这个检索策略值得尝试。
- 为什么这个 evidence compression 会帮助或伤害判断。
- 为什么某类题错。
- 哪些失败来自文档解析。
- 哪些失败来自证据检索。
- 哪些失败来自模型推理。
- 哪些失败来自答案格式。

这些内容如果不记录，后续优化会变成凭感觉乱试。

## Next Step

后续每次推进时，同步更新：

```text
research_log/YYYY-MM-DD_topic.md
```

下一条可能记录：

```text
工具辅助解 1 题：map_doc_id.py 和关键词搜索工具
```
