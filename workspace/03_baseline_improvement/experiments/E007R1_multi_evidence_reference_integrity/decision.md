# E007R1 Decision

状态：`DEVELOPMENT_NO_GO / TREATMENT_ACCURACY_REGRESSION / DO_NOT_SUBMIT`

- E007 原失败目录只读保留；
- 无 key TLS 探针通过，CA bundle 待纳入 code/run freeze；
- fresh control 已 PASS：13 derivations、52/52 calls/attempts、0 retry、180,692 tokens、
  actual served model=`qwen-plus`；
- treatment 也完成 52/52、零 retry、180,967 tokens，Trace/schema/temporal PASS；
- opaque EV 引用完整性达到目标：未知/越界/重复 ref 均为 0；
- 但 fresh accuracy 9/13→8/13，且 `fc_a_001` 父版本正确题回退，两个硬门失败；
- E007R1 永久 NO-GO，不运行 prospective，不允许复用或重跑该 pair；
- prospective、candidate、answer.csv、上传、push 和 main merge 均未授权。
