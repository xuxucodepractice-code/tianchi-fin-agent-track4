# 提交线消融实验进度看板

更新时间：2026-07-16

这份文件给队友快速了解：我们已经做了什么、当前能提交什么、后面按什么顺序继续。
详细规则仍以 `step_by_step_experiment_playbook.md` 为准。

## 一句话状态

基础设施与可靠基准已经建立；第一个单变量计分实验 E001（TF 题干级判断链路包）已
取得线上 65.0912，并以 `KEEP_SCORE` 结案。正确题数由 68 增至 70，v2s1 现为当前
受治理消融线的父版本。Agent Trace Gate 已作为 E000 基础设施落地，本步骤 0 API、
0 答案变化。M1 的 4+1 MCQ 链路与 v2s2 identity 已实现并通过本地无 API 测试，但
E002 尚未运行：没有新答案、候选或 N/M。下一步是在其余门槛满足后执行 fresh traced
primary/repeat；MCQ、计算复核、Multi 不得混成同一次实验。

## 当前进度

| 阶段/实验 | 当前状态 | 已经证明什么 | 还缺什么 |
| --- | --- | --- | --- |
| E000 提交隔离与 Trace Gate | **完成 / KEEP_INFRA** | 产物隔离、lineage、API trace、候选冻结、揭标时序与 fail-closed validator | E002 揭标前需做外部 freeze 哈希锚定 |
| S1 冻结基准 | **完成** | v0 三件套不可变且可产物级复用；线上 63.2607，1,161,593 Token | 无 |
| S2a TF 双题盲标 | **完成** | `reg_a_010=B`、`res_a_013=B`，均 high；2/2、0 errors | 无 |
| S2 Tier-1 全集 | **进行中** | 15 MCQ、剩余 10 TF、15 Multi 题卡已冻结 | MCQ 中 13 道仍可 prospective；`ins_a_001/002` 已知，只作回归 |
| O000 Gold Oracle | **进行中：3/15** | `ins_a_001` 为推理/Prompt 主错误；另两题 no_failure | 其余 12 题需标签和 Tier-2 事实卡 |
| B001 无 doc_ids 召回 | **完成 / KEEP_INFRA** | K=12：Complete Recall 96%、Micro Recall 98.27%；B dry-run 100/100 | 07-20 冻结 B 管线 |
| E001 TF-only | **线上完成 / KEEP_SCORE / FROZEN / LEGACY_PRE_TRACE_GATE** | 65.0912；68→70；净 +2；只改变两题答案 | 无；作为 E002 父版本，不事后回填 trace |
| E002 MCQ 全题比较 | **已实现 / 本地测试通过 / PREPARED / 未运行** | v2s2 identity 与 4+1 链路；primary/repeat 已预注册为空；GitHub+独立队友锚定协议已固定；15 fresh traced 仍为 13 prospective + 2 known | 标签持有人书面密封确认、独立 worktree 代码快照、API/trace/freeze/anchor/reveal；当前 0 API、无候选与 N/M |
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
- 结案全量测试：127 passed；
- 通用 validator：VALID；
- E001 专属审计：12/12 PASS；
- 预期线上分数：65.0912；
- 实际线上分数：65.0912（2026-07-16 13:10:51）；
- 相对 v0：线上 +1.8305，正确题数 68→70；
- 冻结快照：`submissions/a_leaderboard_v0/2026-07-16_v2s1_score_65_0912/`；
- 最终决策：`KEEP_SCORE`。

E001 已上传三件套（仅供复核，不得重复提交）：

```text
/Users/xuzijian/Desktop/Agent Competition/submission/answer.csv
/Users/xuzijian/Desktop/Agent Competition/submission/evidence.json
/Users/xuzijian/Desktop/Agent Competition/submission/run_manifest.json
```

## E001 保留的可追溯性限制

1. 20 道 TF 中仍有 7 道在二次判断后为 uncertain，并显式 fallback A；这是后续可研究风险，不能把本轮分差仅归因为最终判断 Prompt。
2. 旧缓存未保存调用时完整 retrieval；当前 evidence 使用冻结 chunks 与当前检索代码重建，相关 SHA256 已登记，不能声称原始 Prompt 可字节级复现。
3. E001 早于 Agent Trace Gate，标记为 `LEGACY_PRE_TRACE_GATE`；没有完整原始
   messages/response 或机器生成的 freeze/reveal 时间记录，不能事后补写。这不影响
   65.0912、68→70 与 `KEEP_SCORE`。

## 本轮 Agent Trace Gate 做了什么

本轮只新增 E000 基础设施，不改变任何答案，也没有调用 API：

- API 调用自动记录完整 messages、模型实际 evidence、原始 response、request ID、Token、重试与工具调用；
- 保存代码、配置、模型、selection、trace 与候选产物 SHA256；
- 记录 verdict/option judgments 到最终答案的确定性派生；
- 候选运行强制空输出、空 cache 和读写 allowlist，禁止 resume、旧 cache 与子进程；
- 只有 trace 验证通过才能合成并写入 `candidate_freeze.json`；
- 揭标另写 `label_reveal.json`，并验证 `candidate_frozen_at < label_revealed_at`；
- E002 冻结为 15 道 fresh trace，其中 13 道 prospective、2 道 known-before-freeze。

当前 Gate 是本机自证审计层，不是 OS 级防篡改。E002 揭标前还要把 freeze SHA256
锚定到本机之外，才能形成更强的时序证据。

基础设施回归：`python -m pytest -q` 为 `145 passed`；本轮没有调用真实 API，也没有
改动 `submission/` 的答案。

## 本轮 M1 / v2s2 开发做了什么

这一步只完成代码与本地测试，不是 E002 的推理实验，也不是新提交版本：

- pipeline identity 已从 v2s1 显式升级为 v2s2；
- 每道 MCQ 保留 A/B/C/D 四次独立判断作诊断参考，再增加第五次统一比较；
- 第五次调用只读取题目、四个选项和原始检索证据，不读取前四次判断；
- 最终答案只由第五次统一比较的结构化结果决定，前四次不再参与答案合成；
- TF、Multi、检索、解析均未改变；确定性计算复核明确留给 E003；
- 本地结构、路由、派生与 Trace Gate 回归已经覆盖；真实 API 调用为 0。
- 当前全量回归：`python -m pytest -q` 为 `171 passed`，且未留下 v2s2 reasoning cache。
- E002 签名已在 API 前与 validator 双重锁定：qwen-plus、top-k=5、原 selection 哈希、非 hide-doc-ids；参数漂移不能冒充本实验。

因此，当前不能汇报任何“新答案”“分数提升”或“N/M”：尚无 E002 rerun、candidate、
answer diff、Token 实测或线上提交，13 prospective + 2 known regression 的治理口径也未改变。

## 队友现在可以并行做什么

1. **实验负责人**：M1 和 v2s2 identity 已完成；确认其余门槛后，以冻结 v2s1 为父版本，按 Trace Gate fresh run 15 道 MCQ。
2. **标定负责人**：继续隔离完成 13 道尚未暴露标签的 MCQ；`ins_a_001/002` 明确标为 known regression，不得混报为 prospective。
3. **提交负责人**：保管 E001 平台截图与冻结快照；不得重复提交或覆盖三件套。
4. **B 线负责人**：在 B001 已通过的 K=12 文档卡片召回上继续做冻结准备，不与 A 线题型实验混合。

## 下一步顺序

```text
E001 KEEP_SCORE 并冻结
→ E000 Agent Trace Gate（0 API、0 答案变化）
→ 完成 M1 4+1 + v2s2 identity + 本地无 API 测试（已完成）
→ E002 fresh trace 15 MCQ，并先冻结候选
→ 外部锚定 freeze SHA256，再揭晓 13 道 prospective 标签
→ E002 只测试 MCQ 四选一统一比较
→ 若 E002 KEEP，再做 E003 计算校验
→ 完成 Multi 标定
→ E004 小范围试点，再决定是否扩大
→ 最后只集成线上证明有效的组件
```

## 禁止事项

- 不要把 MCQ、Multi、检索调参混进 E001；
- 不要直接手工修改零散答案形成新候选；
- 不要重复提交已经得到 65.0912 的 E001；
- 不要重复提交 v0 或已知下降的 v1s1；
- 不要在标签未完成时运行剩余 Gold Oracle 并强行归因；
- 不要修改 E001 冻结快照或把盲标答案作为后续 pipeline 输入。
- 不要把 `ins_a_001/002` 计入 E002 的 prospective 13 题；
- 不要把 M1 本地测试写成 E002 已运行，也不要在其余 Trace Gate 门槛未满足时运行 E002 API；
- 不要在 E002 中加入确定性计算复核；该变量只能留给 E003；
- 不要在 candidate freeze 和外部哈希锚定前揭晓 13 道 prospective 标签；
- 不要把本机 Trace Gate 描述为 OS 级或第三方不可篡改证明。

## 关键入口

- 总手册：`step_by_step_experiment_playbook.md`；
- 实验注册表：`experiments/registry.md`；
- E001 记录：`experiments/E001_tf_direct_judgment/experiment.md`；
- E001 决策：`experiments/E001_tf_direct_judgment/decision.md`；
- 权威真值：`evaluation/local_labels.md`；
- 标定状态：`evaluation/labeling_status.md`；
- 候选说明：`candidates/v2s1_tf_only/README.md`。
- 线上冻结：`submissions/a_leaderboard_v0/2026-07-16_v2s1_score_65_0912/`。
- Trace Gate：`governance/agent_trace_gate.md`；
- Pipeline 版本登记：`governance/pipeline_versions.md`；
- E002 预注册：`experiments/E002_mcq_global_comparison/experiment.md`；
- E002 无答案选择集：`experiments/E002_mcq_global_comparison/selection_gate.json`。
