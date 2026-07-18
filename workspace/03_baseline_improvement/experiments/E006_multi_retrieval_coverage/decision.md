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

## Prospective primary 结果

`PROSPECTIVE_PRIMARY_SCHEMA_NO_GO / REPEAT_NOT_RUN / LABELS_STILL_SEALED`。

primary one-shot 于 2026-07-18 完成 15 题、60 个逻辑调用，runner receipt 与基础 Trace
均为 PASS；总 Token 为 196,512，实际 served model 唯一为 `qwen-plus`，没有发生 HTTP
重试。但随后按冻结 evaluator 做 raw judgment 复核时发现一处阻断：

```text
ins_a_008:A
rendered evidence count = 5
model evidence_refs      = [2, 23]
```

模型很可能把条款中的“第二十三条”混成了“证据23”，而实际只提供了证据 1–5。
这是 provenance/schema failure；不能人工删除越界编号，也不能用 repeat 充当 primary 的
补考。因此 repeat claim、repeat 目录、churn report 和 prospective labels 均保持不存在。
完整哈希与失败回执见 `prospective_primary_result.json`。如需继续，必须另开一个明确改变
schema/provenance 约束的新实验，不能覆盖或重跑本 E006 primary。
