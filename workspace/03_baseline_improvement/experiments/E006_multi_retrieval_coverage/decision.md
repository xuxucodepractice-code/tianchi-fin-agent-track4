# E006 development 决策

## 结论

`DEVELOPMENT_GATE_PASS / PROSPECTIVE_UNLOCKED / DO_NOT_SUBMIT`。

本轮 fresh paired control 与 treatment 均完成 13 题、52 次 API 调用和 13 条答案派生，
Trace、receipt、control anchor、一次性 claim 与唯一变量检查全部通过。严格评估结果为：

- control：6/13；
- treatment：9/13；
- control → treatment：N=3、M=0、净 +3；
- treatment → 冻结 v2s1 父答案：N=3、M=0、净 +3；
- 6 道父版本正确题零回退；
- Token：180,329 → 180,685，仅增加 356。

三处答案变化全部命中真值：

```text
ins_a_007: AC   -> BC
ins_a_009: BC   -> C
ins_a_019: ABC  -> ABCD
```

路由共触发 27 个选项，其中 15 个 evidence pack 实际改变，12 个为 no-op；所有改变均由
冻结路由规则解释，fallback evidence 保持逐字节一致，`unique_variable_errors=[]`。

## 允许与禁止

本结论只解锁一套新冻结代码下的 15 道密封 prospective `primary + repeat`。在两轮结果
冻结、无标签 churn 通过、随后完成独立盲标并得到正向 N−M 之前：

- 不生成全量候选；
- 不修改 `answer.csv`；
- 不上传比赛平台；
- 不查看或使用 prospective 标签调参；
- 不把 development 的 +3 直接外推成线上 +3。
