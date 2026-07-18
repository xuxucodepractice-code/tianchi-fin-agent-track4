# E007 Decision

状态：`DEVELOPMENT_NO_GO / CONTROL_TRANSPORT_FAILURE / TREATMENT_NOT_RUN / DO_NOT_SUBMIT`

- control 在 `fc_a_016:A` 的第一次且唯一一次 physical attempt 遭遇本机 TLS CA
  校验失败；无 retry、无 raw provider response、无 served model、无 token；
- 失败 control 的 observations、calls、attempts、evidence、messages、manifest 与 receipt
  已原样永久保留；
- control 未通过，因而没有生成 treatment authorization/claim，treatment 未运行；
- development 硬门失败，prospective selection 未创建，后续 API 已停止；
- candidate、answer.csv、上传、push 和 main merge 均未授权；
- 本 E007 one-shot pair 不得删除、替换或重跑。若要修复 TLS 后继续，需主理人另行授权
  新实验 ID、全新输出槽与新 run-freeze。
