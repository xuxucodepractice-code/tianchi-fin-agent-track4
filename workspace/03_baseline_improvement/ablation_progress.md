# 提交线消融实验进度看板

更新时间：2026-07-15

这份文件给队友快速了解：我们已经做了什么、当前能提交什么、后面按什么顺序继续。
详细规则仍以 `step_by_step_experiment_playbook.md` 为准。

## 一句话状态

基础设施与可靠基准已经建立；第一个单变量计分实验 E001（TF 题干级判断链路包）已
完成本地验证并晋升到 `submission/`，现在只差上传取得线上分数。MCQ、Multi 和其余
Gold Oracle 尚未完成，禁止混入本次提交。

## 当前进度

| 阶段/实验 | 当前状态 | 已经证明什么 | 还缺什么 |
| --- | --- | --- | --- |
| E000 提交隔离 | **完成 / KEEP_INFRA** | 测试、dry-run、候选和正式出口隔离；完整 lineage 与 validator；132 tests | 无 |
| S1 冻结基准 | **完成** | v0 三件套不可变且可产物级复用；线上 63.2607，1,161,593 Token | 无 |
| S2a TF 双题盲标 | **完成** | `reg_a_010=B`、`res_a_013=B`，均 high；2/2、0 errors | 无 |
| S2 Tier-1 全集 | **进行中** | 15 MCQ、剩余 10 TF、15 Multi 题卡已冻结 | 新盲标目前仍为 0；不能启动计分实验 |
| O000 Gold Oracle | **进行中：3/15** | `ins_a_001` 为推理/Prompt 主错误；另两题 no_failure | 其余 12 题需标签和 Tier-2 事实卡 |
| B001 无 doc_ids 召回 | **完成 / KEEP_INFRA** | K=12：Complete Recall 96%、Micro Recall 98.27%；B dry-run 100/100 | 07-20 冻结 B 管线 |
| E001 TF-only | **本地完成 / READY_TO_UPLOAD** | 已标 TF 8/10→10/10；N=2、M=0；只改变两题 | 上传、回传分数、KEEP/ROLLBACK |
| E002 MCQ 全题比较 | **未启动 / 被标签门槛锁定** | 已通过 Oracle 确认 `ins_a_001` 推理层问题 | 完成 15 MCQ 盲标后开发/评估 M1 |
| E003 MCQ 计算校验 | **未启动** | — | 只有 E002 KEEP_SCORE 后才能开始 |
| E004 Multi 逐要素 | **未启动** | 已知 Multi 可能是最大失分主体 | 完成 Multi 标定后小样本试点 |
| E005 Multi 整题复核 | **未启动** | — | 只有 E004 KEEP_SCORE 后再决定 |

## 本轮 E001 做了什么

本轮不是手工挑两题改答案，而是把 20 道 TF 的推理链统一替换为 v2s1 题干级
`true/false/uncertain` 链路，再用冻结 v0 合成单变量候选。20 道 TF 中只有两道答案
发生变化：

```text
reg_a_010: A -> B（独立盲标 B）
res_a_013: A -> B（独立盲标 B）
```

离线结果：

- 10 道已标 TF：v0 为 8/10，v2s1 为 10/10；
- N=2、M=0、净收益 +2；
- 其余 98 道答案不变；
- 20 道 rerun，其余 80 道完整记录逐字段继承 v0；
- Token：1,168,763，相对 v0 +7,170；
- 全量测试：132 passed；
- 通用 validator：VALID；
- E001 专属审计：12/12 PASS；
- 预期线上分数：约 65.0912，但最终结论必须以平台分数为准。

当前可上传文件：

```text
/Users/xuzijian/Desktop/Agent Competition/submission/answer.csv
/Users/xuzijian/Desktop/Agent Competition/submission/evidence.json
/Users/xuzijian/Desktop/Agent Competition/submission/run_manifest.json
```

## E001 尚未解决的问题

1. 20 道 TF 中仍有 7 道在二次判断后为 uncertain，并显式 fallback A；这是后续可研究风险，不能把本轮分差仅归因为最终判断 Prompt。
2. 旧缓存未保存调用时完整 retrieval；当前 evidence 使用冻结 chunks 与当前检索代码重建，相关 SHA256 已登记，不能声称原始 Prompt 可字节级复现。
3. E001 当前只能标记 `PILOT / READY_TO_UPLOAD`，未取得线上分数前不能写 `KEEP_SCORE`，也不能作为 E002 的最佳父版本。

## 队友现在可以并行做什么

1. **提交负责人**：上传 E001 三件套，回传分数；不要重新运行或改写 `submission/`。
2. **标定负责人**：独立完成 15 道 MCQ Tier-1；不得查看现有 pipeline 答案或 Gold Oracle 结论。
3. **实验负责人**：收到线上分数后，冻结提交快照，计算正确题数变化，并把 E001 决策更新为 KEEP_SCORE 或 ROLLBACK。
4. **B 线负责人**：在 B001 已通过的 K=12 文档卡片召回上继续做冻结准备，不与 A 线题型实验混合。

## 下一步顺序

```text
上传 E001
→ 根据线上分数 KEEP 或 ROLLBACK
→ 完成 15 MCQ 盲标
→ E002 只测试 MCQ 四选一统一比较
→ 若 E002 KEEP，再做 E003 计算校验
→ 完成 Multi 标定
→ E004 小范围试点，再决定是否扩大
→ 最后只集成线上证明有效的组件
```

## 禁止事项

- 不要把 MCQ、Multi、检索调参混进 E001；
- 不要直接手工修改零散答案形成新候选；
- 不要重复提交 v0 或已知下降的 v1s1；
- 不要在标签未完成时运行剩余 Gold Oracle 并强行归因；
- 不要在取得线上分数前把 E001 写成 KEEP_SCORE。

## 关键入口

- 总手册：`step_by_step_experiment_playbook.md`；
- 实验注册表：`experiments/registry.md`；
- E001 记录：`experiments/E001_tf_direct_judgment/experiment.md`；
- E001 决策：`experiments/E001_tf_direct_judgment/decision.md`；
- 权威真值：`evaluation/local_labels.md`；
- 标定状态：`evaluation/labeling_status.md`；
- 候选说明：`candidates/v2s1_tf_only/README.md`。
