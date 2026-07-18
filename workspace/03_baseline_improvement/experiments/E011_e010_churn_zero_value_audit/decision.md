# E011 Decision

状态：`AUDIT_PASS / CHURN_FROZEN / READY_FOR_BLIND_LABELING / DO_NOT_SUBMIT`

- E010 pair/churn 全部只读；
- E011 不调用模型，不修改 E010 receipt 或 churn；
- 唯一变量是正确保留整数零值的 retry policy 读取；
- 新 audit 失败立即 NO-GO；PASS 才允许盲标；
- candidate、submission、upload、push、merge 均未授权。
- dry replay bundle errors=0、全部 checks PASS、C=0；下一步冻结 evaluator 与正式 audit 槽。
- evaluator commit 与 audit run-freeze 已冻结；下一合法动作是一次性零 API 正式 audit。
- 正式 audit bundle errors=0、全部 checks PASS、C=0；audit report 在 labels 缺席时冻结；
- 已允许独立盲标，尚未允许全量扩展或 candidate。
- scorer 已在 label reveal 前实现，189 tests PASS；下一步冻结 scorer/input/gate 后接收盲标。
- score run-freeze 已绑定 scorer 与所有输入哈希；labels/scored 槽为空，允许接收盲标。
