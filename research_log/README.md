# Research Log

这个目录用于记录 AFAC2026 赛题四学习、实验和研究过程中的关键脉络。

它不是代码目录，也不是每日流水账，而是跨日期的研究日志。每次重要学习闭环、工具建设、baseline 理解、实验设计、失败复盘或策略变化，都应该在这里留下记录。

## 记录目标

每条 research log 需要回答：

- 日期是什么。
- 今天做了什么。
- 为什么要做这件事。
- 它在整个学习或比赛体系中属于什么位置。
- 输入材料是什么。
- 产出了哪些文件或结论。
- 遇到了什么困难。
- 如何解决或暂时绕过。
- 对后续 workflow、agent loop 或 baseline 优化有什么启发。
- 下一步是什么。

## 和 workspace 的区别

```text
workspace/
```

记录具体学习材料、脚本、单题解题过程、baseline 拆解和实验细节。

```text
research_log/
```

记录研究脉络、关键判断、困难、解决方案和阶段性结论。

可以理解为：

```text
workspace 是工作现场。
research_log 是研究日志。
```

## 建议文件命名

```text
YYYY-MM-DD_topic.md
```

示例：

```text
2026-06-26_ins_a_007_stage00.md
2026-06-28_research_log_system_setup.md
```

## 推荐模板

```markdown
# YYYY-MM-DD Topic

## Date

## Context

## Position In Roadmap

## Goal

## Actions

## Artifacts

## Difficulties

## Resolutions

## Research Notes

## Next Step
```

## 长期规则

以后无论在哪一天做什么，只要它影响学习路线、工具体系、baseline 理解、实验设计或比赛策略，都要同步写入这里。

每条重要记录都要标注它属于哪条推进线：

```text
学习理解线      # 慢慢理解任务、工具、Agent loop 和 baseline 模块
提交反馈线      # 尽快跑通提交，拿到线上反馈，记录失败类型
两线交融点      # 学习线产物进入提交线，或提交反馈反过来指导学习重点
```

尤其需要记录：

- 为什么做这个动作，而不是另一个动作。
- 这个动作如何服务于最终比赛目标。
- 哪些步骤适合代码完成。
- 哪些步骤需要模型判断。
- 哪些失败暴露了系统短板。
- 哪些经验可以复用到后续题目或 baseline。
