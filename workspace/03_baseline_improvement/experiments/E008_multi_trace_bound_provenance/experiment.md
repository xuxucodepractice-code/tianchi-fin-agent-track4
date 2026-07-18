# E008：Multi trace-bound provenance

## 当前状态

`DEVELOPMENT_NO_GO / FROZEN_PARENT_REGRESSION / DO_NOT_SUBMIT`。

E007R1 证明 opaque EV ID 能把未知/越界引用降为 0，但 fresh accuracy 9/13→8/13，不能
晋升。E008 保留原 `[证据N]` evidence 展示与判断语义，取消模型生成的编号引用字段；每次
调用的完整 messages、五条 evidence、raw response 及其 SHA256 已由 Agent Trace 一一绑定，
因此 provenance 改为 call-level full-pack，而不是依赖容易与正文条款号混淆的自报整数。

## 唯一变量

- control：原 v0 输出包含整数 `evidence_refs`；
- treatment：输出严格 standalone JSON，仅含 `option`、`judgment`、`rationale`，禁止出现
  `evidence_refs` 或任何额外字段。

两臂 evidence 标记都保持 `[证据1]`～`[证据5]`。treatment parser 严格要求 exact keys、
当前 option、合法 judgment、字符串 rationale；不扫描 markdown、不提取子 JSON、不修正。

## 冻结项

- E006 treatment retrieval、top-k=5、evidence 内容/顺序/字符预算；
- v0 support/refute/insufficient 规则与 system prompt；
- qwen-plus、temperature=0、max_retries=0；
- 每题 A/B/C/D 各一次、normalize_answer 与 fallback；
- TF、MCQ、v2s1 65.0912 锚点；
- `SSL_CERT_FILE=/etc/ssl/cert.pem` 及 CA SHA256。

## Development 硬门

沿用 13 道 retrospective development，fresh paired 两臂各 52 logical/physical attempts。
treatment unexpected `evidence_refs`/extra keys=0；schema/API/Trace/temporal errors=0；准确率
不低于 fresh control；冻结父版本正确 6 题零回退；retrieval/evidence 逐字节相同。

任一失败立即 NO-GO。PASS 后才可从从未用于 E006/E007/E008 development、E006
prospective、Gold 或已知标签的 Multi 中按五领域各 3 题冻结全新 prospective holdout。
后续 primary/repeat/churn、盲标、N-M>C、Token 惩罚和 65 Multi 扩展门沿用总计划。

## Development control

fresh control 已完成 13/13、52 logical/physical attempts、零 retry、180,727 tokens；
receipt/Trace PASS，actual served model 唯一为 `qwen-plus`。treatment authorization 已生成。

treatment 也完成 52/52、零 retry、179,084 tokens。两臂答案 13/13 完全一致，准确率均
为 8/13；treatment 没有任何 unexpected evidence_refs/extra field，Trace/temporal/schema
与 retrieval equality 全部 PASS。但 `fc_a_001` 两臂均把冻结父版本正确答案 `ABD` 改成
`AD`，触发父正确题零回退门。E008 development NO-GO，不运行 prospective。
