# Agent Trace Gate

## 状态与范围

- schema：`agent-trace/v1`、`candidate-freeze/v1`、`label-reveal/v1`；
- 治理归属：E000 的强制基础设施扩展；
- 答案变化：0；
- API 调用：本步骤 0；
- 适用范围：从 E002 起，任何包含新 API 推理、且可能晋升为线上提交的候选；
- 历史边界：v0、v1s1、v2s1 均早于本 Gate，统一标记为 `LEGACY_PRE_TRACE_GATE`。
- E002 实现状态：M1 4+1 与 v2s2 identity 已完成本地无 API 测试，E002 本身仍为
  `NOT_RUN`；无新答案、rerun、candidate、Token 实测或 N/M。

本 Gate 不改变检索、Prompt、模型判断或答案合成。它只回答一个问题：候选答案是否由
事先冻结的代码和输入，经一次可审计的 Agent 运行产生，并且候选是否先于盲标揭晓冻结。

## 必须保存的证据

每次候选级 API 运行必须保存并校验：

1. 运行前和运行后的 `agent/*.py` 文件哈希与代码树哈希；
2. 公开题目树、chunks、doc_meta（可选 doc_cards）、pipeline、experiment、selection、
   top-k、模型别名、超时、重试配置与哈希；
3. 模型实际收到的完整 `messages`、完整 evidence、请求 payload 与各自 SHA256；
4. 原始模型响应、实际服务模型、provider/local request ID、finish reason；
5. prompt/completion/total Token、每次尝试、重试错误与工具调用；
6. 每道题的 verdict/option judgments/global comparison 如何经确定性 normalizer 派生为最终答案；
7. 运行产物、trace 文件、候选三件套及父版本三件套的 SHA256；
8. trace/call/attempt/derivation 的带时区时间窗、`candidate_frozen_at`、首次
   `label_revealed_at` 以及严格先后关系。

标准 trace 目录包含：

```text
agent_traces/run-<uuid>/
├── calls.jsonl
├── derivations.jsonl
└── trace_manifest.json
```

候选冻结后还必须包含：

```text
<candidate_dir>/
├── answer.csv
├── evidence.json
├── run_manifest.json
├── candidate_freeze.json
├── agent_trace/
│   ├── calls.jsonl
│   ├── derivations.jsonl
│   └── trace_manifest.json
└── label_reveal.json          # 揭标后才产生；不可预写或覆盖
```

## 五道强制门

### Gate 1：无答案选择集先冻结

候选运行只能读取显式 `--selection-file`。该 JSON 必须：

- `frozen_before_labeling=true`；
- 只含允许的选择元数据和 qid，不含答案、置信度、证据或历史 pipeline 输出；
- 将 qid 完整且互斥地分成 `prospective_qids` 与
  `known_before_freeze_qids`；
- 在 trace 中保存文件 SHA256。

E002 使用 `experiments/E002_mcq_global_comparison/selection_gate.json`。它包含 15 道
fresh traced MCQ，但只有 13 道属于 prospective blind gate；`ins_a_001`、
`ins_a_002` 的标签已在 E002 候选冻结前暴露，只能作为已知标签回归题。当前 selection
SHA256 为 `662cb1694c8e2b87ce98f96f04604da0f141b2c76a213eeb0b4812d3438e80f5`；
若文件变化，必须视为新 selection 并重新审查，不得沿用该冻结声明。
其中 `frozen_before_labeling=true` 由 2026-07-14 的原始 15 题 source selection 支撑；
wrapper 明确承认两道标签后来已暴露，不把它们计入 prospective。

### Gate 2：新鲜、隔离的候选推理

- 输出目录必须是 `outputs/experiments/` 下的新建空目录；reasoning cache 必须使用该
  output 内的默认 `reasoning_samples/`，候选运行禁止 `--resume`；
- 生成进程只允许读取公开题目、冻结 chunks/doc metadata、生成代码、指定 selection、
  本次 output 及固定的解释器/系统运行时只读根；记录的 allowlist 必须与 runner 推导值完全一致；
- 禁止读取 `evaluation/`、历史提交、候选、旧 reasoning cache、测试与 Git 元数据；
- 只允许写入本次输出目录；禁止子进程、fork/exec 和运行中的文件系统拓扑修改；
- 每次 API 调用必须附着在同一个活动 guard 和 Trace Recorder 上；
- 候选只接受官方 DashScope HTTPS endpoint、Qwen 模型名及非空 provider request ID；
- 直接写入 `submission/` 被禁止。

任何访问违规都会粘性记录；即使调用者捕获异常，最终 trace 仍必须失败。

### Gate 3：Trace 验证后才能合成和冻结

`agent.validate_trace_gate` 会 fail closed 检查 calls、derivations、代码、配置、模型、
输入语料哈希、Token、重试、时间窗、evidence、normalizer 回放和输出关联。非空 rerun 只能通过
`agent.merge_submission` 与冻结父版本合成；合并器要求 experiment、pipeline、selection、
rerun qids 与 trace 精确一致，并证明所有非 rerun 题的答案行和 evidence 与父版本逐字段相同；
然后自动写入不可覆盖的 `candidate_freeze.json` 并复制 trace。

原始 rerun 三件套必须保留到上传完成，因为候选 validator 会再次核对 candidate、parent、
rerun、trace 四方哈希与 lineage；只保留候选三件套不够。

揭标前允许的状态是：

```text
candidate = VALID
temporal_gate = PENDING_LABEL_REVEAL
```

`PENDING` 不是失败，它表示候选已先冻结、标签仍未向生成方揭晓。

### Gate 4：候选冻结后才登记揭标

标签结果文件必须 `complete=true`、`errors=[]`，并按 selection 原顺序覆盖全部 qid。
揭标时只运行：

```bash
python -m agent.register_label_reveal \
  --candidate-dir <candidate_dir> \
  --labels <completed_results.json>
```

程序自动记录当前时间，不接受人工传入或回填 `label_revealed_at`，并要求：

```text
candidate_frozen_at < label_revealed_at
```

`candidate_freeze.json` 不会被改写；首次揭标单独写入不可覆盖的
`label_reveal.json`。13 道 prospective 题与 2 道 known-before-freeze 题必须分开统计，
不得把 15/15 描述成前瞻盲测。

### Gate 5：上传前再验证

```bash
python -m agent.validate_trace_gate \
  --candidate-dir <candidate_dir> \
  --require-label-reveal
```

只有 candidate、trace、selection、label result 哈希仍一致且 temporal gate 为 `PASS`，
才可执行答案 diff、N/M 审计与上传决策。通过 Gate 只证明过程可追溯，不自动等于
`KEEP_SCORE`；仍须满足 `N-M>C`、正期望与单变量规则。

## 诊断 Trace 不等于候选 Trace

Gold Oracle 等已知标签诊断运行也可以保存 trace，但必须标记为 diagnostic，并用
`python -m agent.validate_trace_gate --diagnostic ...` 验证。它允许分析错误层，却不具备
candidate eligibility，不能拿来合成或冻结计分候选，也不能替代 E002 的 fresh run。

## E002 标准顺序

E002 的 M1 代码已经实现，pipeline identity 已明确升级为 `v2s2`，并通过本地无 API
测试。其 4+1 拓扑要求每道 MCQ 记录 A/B/C/D 四次独立参考判断和第五次统一比较；
第五次调用只读取题目、选项与原始检索证据，不读取前四次判断，并独占最终答案决定权。
Trace validator 必须关联全部五次调用与最终派生。确定性计算校验不属于 E002，只能在
后续 E003 单独执行。

API 前的 primary/repeat 角色、空目录要求、人类标签密封确认、两层外部锚定方式与
receipt 字段已经预注册在
`../experiments/E002_mcq_global_comparison/execution_preregistration.md`；实际 receipt
必须由 `anchor_receipt_template.json` 在候选冻结后填充，模板本身不构成外部锚定。

截至当前，以下真实运行顺序尚未开始：没有 API、新答案、rerun、candidate 或 N/M。
只有其余 Gate 前置条件也满足后，才按以下顺序执行：

```text
冻结 selection_gate.json（已完成，无答案）
→ 15 道 MCQ 以空输出/空缓存 fresh traced primary run
→ 同配置、另一空目录 fresh traced repeat，先计算无标签 churn
→ 两个 trace 均验证；预注册 primary 不得按结果挑选
→ primary 与冻结 v2s1 合成
→ 自动冻结候选与 trace
→ 对 candidate_freeze.json 做外部锚定
→ 首次揭晓完整标签结果并登记 label_reveal.json
→ 分开计算 13 道 prospective 与 2 道 known regression
→ 通过上传前 Gate
→ 再决定 KEEP_SCORE / PILOT / ROLLBACK
```

命令模板（`CURRENT_PIPELINE_VERSION=v2s2` 与 M1 已完成；仍须在其余前置门槛满足后使用）：

```bash
python -m agent.run_submission \
  --selection-file workspace/03_baseline_improvement/experiments/E002_mcq_global_comparison/selection_gate.json \
  --use-qwen \
  --top-k 5 \
  --experiment-id E002 \
  --output-dir outputs/experiments/E002_mcq_global_comparison/rerun_bundle

python -m agent.run_submission \
  --selection-file workspace/03_baseline_improvement/experiments/E002_mcq_global_comparison/selection_gate.json \
  --use-qwen \
  --top-k 5 \
  --experiment-id E002 \
  --output-dir outputs/experiments/E002_mcq_global_comparison/churn_repeat

python -m agent.validate_trace_gate \
  --trace-dir <rerun_bundle/agent_traces/run-uuid> \
  --artifact-dir outputs/experiments/E002_mcq_global_comparison/rerun_bundle

python -m agent.validate_trace_gate \
  --trace-dir <churn_repeat/agent_traces/run-uuid> \
  --artifact-dir outputs/experiments/E002_mcq_global_comparison/churn_repeat

python -m agent.merge_submission \
  --parent-dir workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-16_v2s1_score_65_0912 \
  --rerun-dir outputs/experiments/E002_mcq_global_comparison/rerun_bundle \
  --output-dir outputs/candidates/v2s2_mcq_global_comparison \
  --rerun-qids workspace/03_baseline_improvement/experiments/E002_mcq_global_comparison/selection_gate.json \
  --selection-file workspace/03_baseline_improvement/experiments/E002_mcq_global_comparison/selection_gate.json \
  --parent-version v2s1 \
  --experiment-id E002 \
  --experiment-pipeline-version v2s2

python -m agent.validate_trace_gate \
  --candidate-dir outputs/candidates/v2s2_mcq_global_comparison
```

## 证明边界

当前 Gate 是本机、单进程、Python audit hook 和文件哈希构成的**自证审计层**，不是
OS 级沙箱、远程见证或不可篡改账本，因此必须如实保留以下边界：

1. 本机拥有者仍可事后改代码、文件和时间；只保存本地哈希不能独立证明历史未被改写。
2. 路径 allowlist 会阻止普通 symlink/hardlink 旁路，但 Python 路径检查不能证明 inode
   来源，也不能撤销 guard 启动前已打开的文件描述符；强隔离仍需 OS sandbox/container。
3. 模块在 guard 激活前已发生的解释器导入，不属于当前运行期 guard 的证明范围。
4. 官方 endpoint、模型名和 provider request ID 只能形成一致性证据；本地记录仍不能替代
   供应商签名回执或 usage log，因此不构成密码学意义上的 API 身份证明。
5. v2s1 没有原始完整 messages/response 与机器生成的 freeze/reveal 记录，不能事后补写成合规 trace。
6. M1 的 `eliminated` 理由仍是自由文本。Gate 能证明模型看到的原始 evidence、原始输出和
   最终派生未被链路内替换，但不会把理由中的 `A-1` 等引用作语义正确性认证，也不能保证
   自由文本理由与答案在语义上完全一致；这仍需后续标定与人工审计。

因此，强时序证明还必须在揭标前把 `candidate_freeze.json` 的 SHA256 锚定到本机之外，
例如推送到队友可见的 Git 远端、由独立标定人签收，或写入带可信时间戳的外部系统。
外部锚定记录应保存锚定位置、提交/消息 ID、时间与 SHA256。未做外部锚定时，结论只能写
“通过本机 Trace Gate”，不能写“第三方不可篡改证明”。
