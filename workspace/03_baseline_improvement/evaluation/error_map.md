# Error Map

本文件用于汇总本地标定题的主错误层。完成 Gold Chunk、Gold Evidence 和 Current Evidence 审计后更新。

| 错误层 | 题数 | qids | 主要失败模式 | 下一实验 |
| --- | ---: | --- | --- | --- |
| 数据/题目 | 0 |  |  |  |
| 解析 | 0 |  |  |  |
| 检索 | 0 |  |  |  |
| 证据组织 | 0 |  |  |  |
| 推理/Prompt | 1 | ins_a_001 | MCQ 逐选项判断无法完成四产品公式的全题排序；完整 Gold Evidence 仍输出 A 而真值为 B | S5 / M1 四选一统一比较 |
| 答案合成 | 0 |  |  |  |
| 提交流程 | 0 |  |  |  |

## 已关闭的基础设施问题

| 问题 | 修复实验 | 验证证据 | 状态 |
| --- | --- | --- | --- |
| 三份提交产物可能来自不同运行，旧 validator 未拦截 | E000 | 官方 qid 全集、mode/model、Token、parent SHA256、逐题 lineage 校验；空 rerun 与冻结 v0 三文件哈希完全一致 | RESOLVED / KEEP_INFRA |

## 更新规则

1. 每道题只指定一个 `primary_failure`。
2. 可以补充 `secondary_failure`，但不重复计入主错误数。
3. 只有人工证据审计完成后才改变统计。
4. 后续实验优先级由本表决定。
5. `incomplete` 的 Gold Oracle 案例不得写入本表计数。

## 已完成 Gold Oracle 的对照题

| qid | gold | Gold Evidence | Current Evidence | 主分类 | 风险标记 |
| --- | --- | --- | --- | --- | --- |
| ins_a_001 | B | A | A | 推理/Prompt | 证据组织 |
| ins_a_002 | A | A | A | no_failure | 证据组织 |
| ins_a_007 | BC | BC | BC | no_failure | — |

本表只按实际错题统计主错误层；答案已正确但证据不完整的情况只记风险，不重复计为失分。
