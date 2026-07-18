# E011：E010 churn zero-value audit

## 当前状态

`AUDIT_PASS / CHURN_FROZEN / READY_FOR_BLIND_LABELING / DO_NOT_SUBMIT`。

E010 primary/repeat 的独立 receipts 均 PASS，答案 churn C=0；冻结 churn evaluator 仅因
`int(value or -1)` 把合法 `max_retries_per_logical_call=0` 误读为 -1 而 FAIL。E010 的
churn、输出、claims 与 run-freeze 永久只读，禁止修补、替换或重跑。

E011 是零 API 的独立审计实验：只把 retry policy 读取改为
`int(value if value is not None else -1)`，并在新 identity、audit claim、run-freeze 和输出槽
下重新验证 immutable E010 pair。不得过滤其他错误；任何其他 Trace/schema/temporal/parser/
retrieval/model 错误仍立即 NO-GO。

E011 audit PASS 后才允许创建全新的 E011 blind labels，并以 E010 primary 作为唯一计分臂、
E010 repeat 只计算稳定性。仍必须满足 `N-M>C` 和 Token 惩罚后预计分数高于 65.0912，
才允许全量扩展。

新 evaluator 对 immutable E010 pair 的只读 dry replay 已得到 bundle errors=0、全部 checks
PASS、C=0；没有写入 E011 audit claim/report，也没有访问 labels 或调用 API。正式审计必须
等待 code commit 与 audit run-freeze。

audit code commit=`cc93266c0739d29845fbcb611888c0248d6e79f8`；run-freeze SHA256=
`d8b62d84daad54f7efba9b8d9c77d786ca7c4906c938570df7cf54acd41af0b7`，输入/代码/槽自校验 PASS。

正式 audit PASS：bundle errors=0、全部 10 项 checks PASS、answer churn C=0、option churn=2、
retrieval drift=0，且 primary/repeat exact served model 均为 `qwen-plus`。audit report 已在 labels
不存在时冻结，允许进入独立盲标；E010 原 FAIL churn 哈希保持不变。

scored evaluator 已在 labels 创建前实现并通过 189 tests；它固定读取 E010 primary、E011
audit 与未来 E011 blind labels，计算 N/M/C 和 65-Multi Token 投影。需先提交 scorer code
并创建独立 score run-freeze，之后才接收盲标答案。
