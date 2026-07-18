# E010：Multi Trace evidence-pack binding

## 当前状态

`TECHNICAL_REPLAY_PASS / RUN_FROZEN / PRIMARY_NOT_RUN / DO_NOT_SUBMIT`。

E009 prospective primary 已完整执行 15 题、60 calls、零 retry，模型、parser 与实际 messages
均正常，但冻结 validator 从不存在的 `context.evidence` 重建 prompt；Agent Trace 的完整证据
按 schema 位于 `model_evidence`，导致 receipt FAIL。E009 pair、claim、run-freeze 和输出永久
只读，不修补、不删除、不重跑。

## 唯一技术变量

E010 只把 Trace prompt replay 的 evidence 来源从 `context.evidence` 改为
`call.model_evidence`。模型请求、E009 treatment prompt/parser、E006 treatment retrieval、
top-k=5、evidence 内容/顺序/预算、doc_ids 顺序映射、normalize/fallback、qwen-plus、
temperature=0、max_retries=0、CA bundle、TF、MCQ 与 65.0912 锚点全部不变。

先用 E009 immutable Trace 做离线回放测试，要求旧 validator 0/60、新 validator 60/60，且
不写回任何 E009 文件。通过后才可冻结全新 E010 code/pair/claims/run-freeze/output slots。

## Fresh prospective selection

排除 E006 development/prospective、Gold/已知标签、E009 selection 后，剩余合格池为合同4、
财报4、保险0、监管6、研究6。为了保持 15 题全部 fresh，冻结配额 `4/4/0/4/3`；保险缺口
显式记录，不复用 E009 的保险题。领域内按冻结 seed 的 `SHA256(seed:qid)` 升序选择。

primary 是唯一计分臂，repeat 只测稳定性。两轮 PASS 后先冻结无标签 churn，再独立盲标。
只有 Trace/temporal/schema 全 PASS、`N-M>C` 且 Token 惩罚后预计分数严格高于 65.0912，
才允许全量 65 Multi。否则立即 NO-GO，不生成候选。

## Technical replay gate

E009 immutable 60-call Trace 的离线回放结果：旧 `context.evidence` 路径 0/60，新
`call.model_evidence` 路径 60/60；Trace 顶层 messages 60/60、严格 parser 60/60；全部
E009 输入哈希前后相同。全量 187 tests PASS。已生成技术授权，但尚未创建 run-freeze、
未读取 Key、未调用 E010 API。

code-freeze commit 为 `2ed5c6b51c4815c8996a7a4db8d348f0a83cde31`；run-freeze SHA256
为 `f1c7472775724a00f080c27364f355075a3e3b055577ccbd4713417088aea5a5`，自校验 PASS。
