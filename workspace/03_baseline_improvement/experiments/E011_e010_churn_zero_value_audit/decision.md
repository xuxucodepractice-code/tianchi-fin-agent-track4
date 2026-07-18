# E011 Decision

状态：`AUDIT_RUN_FROZEN / LABELS_SEALED / DO_NOT_SUBMIT`

- E010 pair/churn 全部只读；
- E011 不调用模型，不修改 E010 receipt 或 churn；
- 唯一变量是正确保留整数零值的 retry policy 读取；
- 新 audit 失败立即 NO-GO；PASS 才允许盲标；
- candidate、submission、upload、push、merge 均未授权。
- dry replay bundle errors=0、全部 checks PASS、C=0；下一步冻结 evaluator 与正式 audit 槽。
- evaluator commit 与 audit run-freeze 已冻结；下一合法动作是一次性零 API 正式 audit。
