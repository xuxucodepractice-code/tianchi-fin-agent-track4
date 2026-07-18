# E012 Decision

状态：`RUN_FROZEN / AUTHORIZED_TO_RUN_ONCE / API_NOT_STARTED / DO_NOT_SUBMIT`

- E011 已授权全量 65 道 Multi 扩展；
- E012 不改变检索、Prompt、Parser、推理、模型或调用拓扑，只扩大到全部 Multi；
- 全量输出槽、claim、runner、builder、输入哈希与 run-freeze 必须在 API 前冻结；
- 任一 Trace/schema/parser/model/retry 硬门失败即 NO-GO，失败目录不可删除或覆盖；
- 全量 PASS 前不得生成 candidate/answer.csv；
- 最终只冻结候选三件套和外部审计记录，不自动上传、push 或 merge。
- runner/builder 已实现，完整测试 192 passed；下一合法动作是提交代码并创建 run-freeze。
- source commit 与 run-freeze 已冻结且自校验 PASS；下一合法动作是 Keychain 临时注入后的一次性全量运行。
