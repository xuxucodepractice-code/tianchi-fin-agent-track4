# E007：Multi evidence reference integrity

## 当前状态

`PREREGISTERED / DEVELOPMENT_NOT_RUN / DO_NOT_SUBMIT`。

E006 development 已证明选项到唯一文档的保守路由有效，但其 prospective primary 在
`ins_a_008:A` 仅渲染 5 条 evidence 时返回了整数引用 `[2,23]`。E007 只消融证据标识，
检验 opaque ID 是否能避免把正文条款号误当作证据编号。

## 父版本与分区

- 平台分数锚点：线上 `v2s1`，65.0912；
- 代码与数据父提交：`5e0640bbe8f37f6e2b8be3e7be83f208c5bc05fe`；
- 检索父版本：E006 treatment，`v2s1-e006-option-doc-route`；
- development：E006 retrospective development 的固定 13 题，标签在代码冻结前已知；
- prospective：仅在 development PASS 后新选 15 道，且不得复用 E006 development、
  E006 prospective、Gold 或任何其他已知标签题。

## 唯一变量

两臂使用逐字节相同的题面、选项、E006 treatment retrieval、top-k=5、evidence 内容、
顺序和字符预算。唯一变化为证据标识及其对应输出 schema：

- control：`[证据1]`～`[证据5]`，`evidence_refs` 为整数数组，例如 `[1,2]`；
- treatment：`[EV1]`～`[EV5]`，`evidence_refs` 为字符串数组，例如
  `["EV1","EV2"]`。

treatment parser 必须把整段 response 直接作为 standalone JSON 解析，严格要求 option
等于当前选项、judgment 合法、rationale 为字符串、evidence_refs 为字符串数组且每个 ID
来自实际渲染的 `EV1..EVK`。重复、未知、越界、错误类型或多余外层文字均记为 schema
failure；不得删除、修正、去重或截断。禁止 qid/doc_id/chunk_id 特判。

## 冻结项

- E006 treatment 的检索路由与四个标题阈值；
- top-k=5、单 chunk、1200 字 earliest-match 截断；
- evidence 的内容、顺序、位置元数据和字符预算；
- v0 support/refute/insufficient 判断规则；
- qwen-plus、temperature=0、`max_retries=0`；
- 每题 A/B/C/D 各一次调用，无整题复核；
- `normalize_answer` 与答案 fallback；
- TF、MCQ 和候选/提交目录；
- 线上 v2s1 65.0912 分数锚点。

## Development 硬门

fresh paired control+treatment 均必须从注册的空目录启动，各 13 题、52 次 logical/physical
attempts、13 条 derivation。treatment 启动前必须由 control 原子生成并消费一次性 claim。
两臂均保存完整 calls、raw response、messages、evidence、attempts、derivations、receipt、
manifest 和 SHA256。

全部条件同时满足才 PASS：

1. treatment 未知/越界/重复 evidence ref 为 0；
2. treatment schema、API、Trace 和 temporal errors 为 0；
3. treatment 正确率不低于 fresh control；
4. E006 冻结父版本正确 6 题零回退；
5. 记录逐题答案 churn、两臂 Token、physical attempts 和 exact served model；
6. retrieval 与 evidence 在两臂间逐字节一致，所有非标识文本保持一致。

任一硬门失败立即 `DEVELOPMENT_NO_GO`，永久保留失败产物，不再调用 API。

## Prospective 与扩展门

development PASS 后才可从未使用、未标注的 Multi 中按五领域各 3 题冻结全新 15 题。
primary 是唯一计分臂，repeat 仅估计稳定性；两轮使用外部一次性 claims，并要求同代码、
输入、参数和 exact served model。先冻结无标签 churn，之后才允许独立盲标。

只有 `N-M>C`、Trace/temporal/schema 全部 PASS，且 Token 惩罚后的预计平台分数严格高于
65.0912，才允许扩展全部 65 道 Multi。否则不生成 `answer.csv`、不修改当前最佳候选、
不上传。即使全量通过，也只冻结三件套，未经主理人确认不上传、不推送、不合并 main。

## 内部审计边界

本实验使用本地一次性 claim、ISO-8601 时间、Git commit、文件 SHA256 和 Trace 交叉绑定；
不要求队友见证。`processed_data` 可能是未跟踪 symlink，禁止提交、删除或替换。E006 的
primary、claim、run-freeze 与全部输出均为只读历史证据，E007 不修改、不覆盖、不重跑。
