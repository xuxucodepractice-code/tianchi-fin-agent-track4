# E009 Prospective Protocol

固定 pair `e009-prospective-pair-01`，selection 为 `prospective_selection.json`。primary 与
repeat 使用相同代码、输入、qwen-plus、temperature=0、max_retries=0、固定 CA bundle，
每轮 15 题、每题 A/B/C/D 各一次，共 60 logical/physical calls。两轮必须只有一个且完全
相同的 actual served model。

primary 是唯一计分臂；repeat 只测 answer/option churn。每轮在输出目录外使用一次性 claim，
repeat 必须绑定 primary observations、receipt、Trace manifest 与 primary claim 的 SHA256。
任一 API、parser、schema、Trace、temporal 或 receipt 错误立即永久 NO-GO，不重试、不删除、
不替换失败目录。

完整 Trace 必须保留 messages、raw response、rendered evidence、physical attempts、usage 和
provider/served-model 标识。E009 treatment 固定为 E006 treatment retrieval + top-k=5，
reference-free standalone JSON 和题面 doc_ids 顺序映射；禁止 qid/doc/chunk 特判。

两轮 PASS 后，在 prospective labels 不存在的条件下先冻结 churn。之后才能独立创建
`prospective_labels.json`，并计算 N、M、C。只有 `N-M>C` 且按
`0.7 + 0.3 × max(0,(5,000,000-total_tokens)/5,000,000)` 计算的预计分数严格高于
65.0912，才允许运行全部 65 道 Multi。即使全量通过，也只冻结三件套，未经主理人确认
不得上传、推送或合并。
