# E002 执行预注册与外部锚定协议

登记时间：2026-07-16T16:50:59+08:00
状态：`PREPARED / API_NOT_RUN / HUMAN_ATTESTATION_RECORDED / CODE_FREEZE_PENDING`

本文件不含任何答案。它在 E002 API 运行前固定 primary/repeat 角色、空目录、实验签名、
标签密封边界和候选冻结后的外部锚定方式，禁止根据运行结果事后改选较好的一次。

## 1. Selection 与标签密封审计

- selection：`selection_gate.json`；
- SHA256：`662cb1694c8e2b87ce98f96f04604da0f141b2c76a213eeb0b4812d3438e80f5`；
- source selection SHA256：`c63850fbd9139d318f82022074f9ec7ed9071e44e7d342b5870b8b4f0302f504`；
- 分区：15 fresh traced = 13 prospective + 2 known-before-freeze；两组互斥且并集完整；
- selection 只有 8 个允许的元数据字段，不含 answer、label、gold 或 result 字段；
- 本次准备审计没有打开 `local_labels.md`、`labeling_status.md`、盲标结果、题卡答案或
  Gold Oracle 结果，也没有读取任何 prospective 答案。

当前结论：`PROCESS_ISOLATION_PASS / HUMAN_LABEL_SEAL_REQUIRES_ATTESTATION`。

在首次 API 调用前，独立标签持有人必须书面确认：

> 截至确认时间，13 个 prospective qid 的答案尚未向 E002 生成方、当前生成会话或代码作者揭晓。

确认记录必须包含确认人/角色、平台时间、消息 ID 和上述 selection SHA256。没有该回执，
不得把本项标为 PASS，也不得运行 E002 API。本机文件权限和哈希不能替代这项人类层面的确认。

2026-07-16T16:56:57+08:00，当前 Codex 任务中的 workspace user 已原样提交上述确认，
记录于 `human_label_seal_attestation.json`。Codex 界面没有向代理暴露消息 ID，也无法独立
验证确认人身份，因此状态记为 `RECORDED_WITH_IDENTITY_LIMITATION`，不能表述为第三方证明。

## 2. Primary 与 repeat 预注册

固定角色如下，禁止交换：

| 角色 | 输出目录 | 选择规则 |
| --- | --- | --- |
| primary | `outputs/experiments/E002_mcq_global_comparison/rerun_bundle` | 唯一允许合成候选的 run |
| churn repeat | `outputs/experiments/E002_mcq_global_comparison/churn_repeat` | 只计算无标签 churn，不得替代 primary |

两个目录已于登记时间创建，均为普通目录且 0 项。不得提前放入 `.DS_Store`、`.gitkeep`、
README 或 `reasoning_samples/`；runner 会在空目录检查通过后自行创建内部 cache。

运行瞬间必须再次执行空目录预检。任何一次启动后若留下内容，无论成功或失败，都必须保留
现场并换用重新预注册的新目录，禁止清空后复用。

固定实验签名：

```text
experiment_id=E002
pipeline_version=v2s2
model=qwen-plus
top_k=5
hide_doc_ids=false
selection_sha256=662cb1694c8e2b87ce98f96f04604da0f141b2c76a213eeb0b4812d3438e80f5
```

代码会在首次 API 前和事后 Trace validator 中双重校验该签名。

## 3. 外部锚定方式与接收人

采用两层锚定，Git 远端固定为：
`git@github.com:xuxucodepractice-code/tianchi-fin-agent-track4.git`。

### A. API 前代码快照

- 在独立 worktree 使用专用分支 `codex/e002-v2s2-code-freeze`；
- 只按 allowlist 提交生成代码、Trace Gate、E002 selection/配置、治理文档和测试；
- 明确排除 `evaluation/local_labels.md`、`evaluation/labeling_status.md`、盲标答案、
  Gold Oracle 结果、submission 答案和任何其他标签文件；
- 推送 origin 后记录 code commit SHA。不得在当前 dirty worktree 直接整体 commit/push。

### B. 候选冻结后的 freeze receipt

只有 primary 合成、validator PASS 并生成 `candidate_freeze.json` 后，才能填充
`anchor_receipt_template.json`。在独立 worktree 使用
`codex/e002-freeze-anchor-<UTC>` 分支，提交 candidate freeze 的原样副本与 receipt，推送 origin。

接收人固定为：**未参与 E002 生成的独立标定负责人/队友（GitHub collaborator）**。
该队友必须在独立聊天中原样回执 candidate freeze SHA256 与 Git commit SHA；记录消息 ID
和平台时间。只有远端 commit 可达且队友回执完成后，才允许首次揭晓 prospective 标签。

GitHub 远端加队友回执属于“外部时序见证”，不得表述为密码学不可篡改证明。

## 4. 当前完成度

- [x] selection 哈希、无答案 schema 与 13+2 分区复核；
- [x] 生成进程隔离审计；
- [x] primary/repeat 角色预注册；
- [x] 两个叶子输出目录创建并验证为空；
- [x] 外部锚定方式、分支命名、receipt 内容和接收人角色固定；
- [x] workspace user 书面密封确认已登记（身份/消息 ID 局限已显式记录）；
- [ ] API 前代码快照在独立 worktree 推送 origin；
- [ ] primary/repeat API 运行；
- [ ] 候选 freeze receipt 推送并取得队友回执；
- [ ] prospective 标签揭晓。

在 API 前代码快照未完成前，E002 API 仍保持 `NOT_RUN`。
