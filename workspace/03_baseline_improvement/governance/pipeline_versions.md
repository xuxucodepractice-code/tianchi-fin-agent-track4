# Pipeline Version Registry

| Pipeline | Parent | 状态 | 主要变量 | 线上分数 | 决策 |
| --- | --- | --- | --- | ---: | --- |
| v0 | — | frozen | 基础提交线 | 63.2607 | KEEP / baseline |
| v1s1 | v0 | submitted | 多项检索和证据组织改动混合 | 61.8540 | ROLLBACK as best |
| v2s1 | v0（提交直接父版本；代码沿革来自 v1s1） | submitted and frozen / `LEGACY_PRE_TRACE_GATE` | E001 TF 题干级判断链路包 | 65.0912 | KEEP_SCORE / current governed parent |
| v2s2 | v2s1 | implemented / local-tested / `NOT_RUN` | E002 MCQ 4+1：保留四次逐选项参考判断，新增一次四选项统一比较决定最终答案；首个要求使用 `agent-trace/v1` 的计分实验 | — | M1 与 identity 已完成；0 API、无候选、无 N/M |

## 父版本可复用验收

2026-07-14，v0 通过空 rerun 产物级合并回归：三文件 SHA256 与冻结目录完全一致，validator 报告 `VALID / 100 questions / 1,161,593 tokens`。v0 现在既是不可变文件基准，也是已验证可复用父版本。

2026-07-16，v2s1 以 E001 单变量候选取得线上 65.0912，按 1,168,763 Token 精确反推 70/100，较 v0 净增加 2 题。已冻结于 `submissions/a_leaderboard_v0/2026-07-16_v2s1_score_65_0912/`；空 rerun 回归三件套与冻结快照逐字节一致，validator 为 `VALID / 100 / 1,168,763`，因此成为当前受治理消融线的可复用父版本。v0 继续保留为不可变原始对照与回滚基准。

## Trace Gate 边界

- v0、v1s1、v2s1 生成于 `agent-trace/v1` 之前，均为 `LEGACY_PRE_TRACE_GATE`；
- 该标记不改变既有分数、正确题数、冻结 SHA256 或 E001 的 `KEEP_SCORE`；
- 历史版本不得凭当前重建 evidence 或补写时间戳，宣称拥有当时不存在的完整 trace；
- v2s2 identity 已在代码中显式启用，M1 已完成本地无 API 测试；这只证明实现就绪，**不代表 E002 已运行或形成计分版本**；
- M1 对每道 MCQ 使用 4+1 调用拓扑：A/B/C/D 四次旧式独立判断继续作为诊断参考，第五次统一比较只读取四个选项与原始检索证据，不读取前四次判断，并独占最终答案决定权；
- v2s2 当前未调用 E002 API，尚无新答案、rerun、候选、答案 diff、Token 实测或 N/M；确定性计算复核仍属于后续 E003；
- v2s2 若产生候选，必须以冻结 v2s1 为父版本，15 道 MCQ fresh traced，其余 85 道逐字段继承。

新增 pipeline 时必须补充：

- 直接父版本；
- 对应实验 ID；
- 唯一变量；
- 缓存兼容范围；
- 是否形成候选版本；
- 是否真实上传；
- 最终决策。
