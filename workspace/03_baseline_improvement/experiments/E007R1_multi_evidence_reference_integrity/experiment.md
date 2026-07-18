# E007R1：Multi evidence reference integrity（TLS 修复后重注册）

## 当前状态

`DEVELOPMENT_CONTROL_PASS / TREATMENT_AUTHORIZED / DO_NOT_SUBMIT`。

E007 原 pair `e007-development-pair-01` 已在首个 control 请求的 TLS 握手阶段永久
失败，失败目录与哈希保持不变。E007R1 是全新的治理运行身份，不删除、不覆盖、不复用
原 pair 的输出、claim 或计分资格。

## 环境修复边界

Python 3.12 的默认 OpenSSL CA 文件不存在；无 key 探针证明 `/etc/ssl/cert.pem` 可完成
DashScope TLS 握手并获得 HTTP 400。E007R1 仅增加冻结的运行时传输配置：

```text
SSL_CERT_FILE=/etc/ssl/cert.pem
SHA256=9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994
```

该配置只影响 TLS 信任链，不改变请求、Prompt、Parser、检索、模型或答案推理。

## 唯一实验变量

- control：evidence 标记 `[证据1]`～`[证据5]`，输出整数 `evidence_refs`；
- treatment：evidence 标记 `[EV1]`～`[EV5]`，输出字符串 `evidence_refs`。

treatment parser 严格要求 standalone JSON、当前 option、实际渲染且唯一的 EV ID；禁止
静默修正、删除、去重或截断，禁止 qid/doc_id/chunk_id 特判。

## 冻结项与硬门

完全沿用 E007 的 E006 treatment retrieval、top-k=5、evidence 内容/顺序/字符预算、v0
判断规则、qwen-plus、temperature=0、每题四次调用、normalize_answer/fallback、TF、
MCQ 和 65.0912 锚点。`max_retries=0`。development 仍为原 13 道 retrospective 题。

硬门：treatment 未知/越界/重复 ref=0；treatment schema/API/Trace/temporal errors=0；
treatment 正确率不低于 fresh control；冻结父版本正确 6 题零回退；两臂各 52 logical 与
52 physical attempts；retrieval/evidence 逐字节一致。任一失败立即 NO-GO 并停止后续 API。

development PASS 后才可选择全新的五领域各 3 道 prospective holdout。后续 primary、
repeat、churn、盲标、N/M/C、Token 惩罚与全量扩展门完全沿用原计划。未经主理人确认，
不上传、不推送、不合并 main。

## Development control

fresh control 已于 2026-07-18 完成：13/13 题、52 logical calls、52 physical attempts、
零 retry、180,692 tokens，唯一 actual served model 为 `qwen-plus`；receipt 与 Trace 均
PASS。一次性 treatment authorization 已生成，treatment 尚未启动。
