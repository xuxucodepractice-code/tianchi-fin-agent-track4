# Experiment E002: MCQ 四选一统一比较

## 基本信息

- 状态：`IMPLEMENTED / LOCAL_TESTED / PREPARED / HUMAN_ATTESTATION_RECORDED / CODE_FREEZE_PENDING / NOT_RUN`；
- parent_version：冻结 v2s1 / 65.0912 / 70 of 100；
- pipeline_version：v2s2（代码 identity 已显式升级；尚未执行 E002 API）；
- experiment_id：E002；
- 唯一变量：MCQ 最终答案从“逐选项判断后规则合成”改为“四个选项与证据在一次调用中统一比较”；
- rerun：`selection_gate.json` 中全部 15 道 MCQ；
- inherited：其余 85 道从冻结 v2s1 逐字段继承；
- 本步骤 API 调用：0；
- 本步骤答案变化：0。
- 本步骤 rerun / candidate / N/M：均未产生。

## 为什么是 15 fresh traced，但只有 13 prospective

`selection_gate.json` 不含答案，并与原始 Tier-1 MCQ selection 的 15 个 qid 一致。15 题都
必须由 v2s2 在空输出、空缓存下重新推理并留下 `agent-trace/v1`。但
`ins_a_001`、`ins_a_002` 的标签在 E002 冻结前已经出现在本地标签和 Gold Oracle 记录中，
所以：

| 分组 | 数量 | 用途 |
| --- | ---: | --- |
| prospective_qids | 13 | 候选先冻结、标签后揭晓的主要 N/M 证据 |
| known_before_freeze_qids | 2 | 已知标签回归与验收，不计作前瞻盲测 |
| fresh traced qids | 15 | 技术 Trace 覆盖与候选 rerun 范围 |

不得把结果表述为“15/15 前瞻盲测”。

## 冻结选择集

- 文件：`selection_gate.json`；
- selection SHA256：`662cb1694c8e2b87ce98f96f04604da0f141b2c76a213eeb0b4812d3438e80f5`；
- source：`evaluation/blind_labeling/tier1_mcq/selection.json`；
- source SHA256：`c63850fbd9139d318f82022074f9ec7ed9071e44e7d342b5870b8b4f0302f504`；
- 答案字段：无；
- qid 顺序：与 source 完全一致。

`frozen_before_labeling=true` 继承的是 2026-07-14 原始 15 题 selection 的预注册事实；
本 wrapper 不声称自己早于 `ins_a_001/002` 的标签暴露。它没有增删 qid，只是把这两题
显式降级为 known-before-freeze，并把余下 13 题定义为 E002 的 prospective 集合。

## 实现规格

保持不变：

- 题目、文档、chunks、检索与 top-k；
- 每个选项现有独立判断仍执行并写入 evidence，降级为参考信号；
- TF、Multi、解析、检索参数和父版本其余 85 题；
- 确定性计算校验不在本实验内，留给 E003。

M1 已实现为明确的 **4+1 调用拓扑**：先对 A/B/C/D 各做一次旧式独立判断，共四次；
再做第五次统一比较。第五次调用只看到题目、四个选项及各自的原始检索证据，**不会读取
前四次判断结果**，从而避免被参考信号锚定。前四次只保留作诊断；唯一替换是最终答案
由第五次统一比较的结构化输出直接决定，不能再以 0-support fallback A 或 evidence_refs
数量决定答案。

本轮没有加入公式、数值、单位或排序的 Python 计算复核；该变量只能在 E002 获得
`KEEP_SCORE` 后，作为 E003 单独实验。

为防止多变量运行冒充 E002，首次 API 前与事后 Trace validator 都会锁死实验签名：
`experiment_id=E002`、`pipeline_version=v2s2`、`model=qwen-plus`、`top_k=5`、
`hide_doc_ids=false`，以及本页登记的 `selection_gate.json` SHA256。任一项漂移即失败。

## 执行前硬门槛

- [x] 冻结无答案的 15 题选择集，并声明 13+2 分区；
- [x] Agent Trace Gate 基础设施归入 E000；
- [x] M1 4+1 代码完成，且 pipeline identity 从 v2s1 显式升级为 v2s2；
- [x] 相关本地无 API 单元测试与全量回归通过；
- [x] workspace user 已书面确认 13 道 prospective 标签仍未向生成方揭晓；身份验证局限见 attestation；
- [x] 在 `outputs/experiments/` 下创建全新的空 rerun 输出目录，并只使用其内部默认空 cache；
- [x] 预注册 `rerun_bundle` 为 primary，另建空 `churn_repeat`；禁止事后挑选较好的一次；
- [x] 约定候选冻结哈希的外部锚定方式与接收人角色。

任一项不满足，不得调用 API。

本地验证记录（2026-07-16）：`python -m pytest -q` 为 `171 passed`；检查时不存在
E002 输出、v2s2 reasoning cache 或真实 API 结果。

运行角色、目录、密封确认文本、两层 GitHub/队友锚定协议与 receipt 模板见
`execution_preregistration.md` 和 `anchor_receipt_template.json`。当前生成进程隔离已通过，
workspace user 的书面密封确认已登记为 `human_label_seal_attestation.json`；由于任务界面
不提供消息 ID 且代理无法独立验证身份，该回执只作为具名来源受限的人类确认，不冒充第三方证明。

## 受治理执行顺序

```text
M1 + v2s2 完成并冻结代码
→ 用 selection_gate.json fresh trace 全部 15 题（预注册 primary）
→ 同配置 fresh traced repeat，未看标签先算 churn_mcq
→ 两个 trace validator 均 PASS
→ primary 与冻结 v2s1 合成，只替换 15 道 MCQ
→ submission validator PASS
→ candidate_freeze.json + trace 自动冻结
→ 外部锚定 freeze SHA256
→ 揭晓并登记完整 15 题结果
→ 13 道 prospective 与 2 道 known regression 分开统计
→ 答案 diff + N/M + churn + Token 审计
→ 决定是否上传
```

完整命令与证据规范见 `../../governance/agent_trace_gate.md`。

## 验收与 Go/No-Go

- `ins_a_001` 自动得到 B、`ins_a_002` 自动得到 A，且均不是 fallback；这两题只算已知回归；
- 13 道 prospective 题单独计算 `N_prospective` 与 `M_prospective`；
- 全部 15 题另报总体回归，但不能替代 prospective 统计；
- 同配置重复运行得到 `churn_mcq=C`；
- 只有 `N_prospective-M_prospective>C`，且全部 15 题总体无不可接受回归、期望线上分差为正，
  才允许进入上传评估；
- Gate 通过但净收益不足时，结论仍应为 `PILOT` 或 `ROLLBACK`，不能因“Trace 完整”而晋升。

## 当前结论

E002 已完成 M1 4+1 实现、v2s2 identity 升级和本地无 API 测试，但实验本身仍为
`NOT_RUN`。目前没有调用 API、没有生成任何新答案，也没有 rerun、candidate、答案 diff、
Token 实测、N/M 或提交文件。13 道 prospective 与 2 道 known regression 的分区保持不变；
primary/repeat 已预注册为空目录，锚定协议与人类密封确认均已登记。下一步是在独立
worktree 推送无标签的代码快照；该快照完成前仍不得启动 fresh traced primary run。
