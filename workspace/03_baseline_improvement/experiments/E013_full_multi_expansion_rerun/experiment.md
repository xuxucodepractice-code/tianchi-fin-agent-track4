# E013：65 道 Multi 全量扩展技术重跑

## 当前状态

`RUN_FROZEN / AUTHORIZED_TO_RUN_ONCE / API_NOT_STARTED / DO_NOT_SUBMIT`

E013 继承 E012 的 E011 scored PASS 授权与全部模型行为。E012 在 claim 和任何 API 前因
output-root mkdir 不在精确写白名单内而技术 NO-GO，消耗 0 calls、0 attempts、0 tokens。
E012 run identity、nonce、claim/output/candidate 槽永久关闭且不得覆盖。

E013 使用全新的 experiment/run identity、nonce、claim、output、result、bundle 与 candidate
槽。唯一技术修正是在进入 fail-closed guard 前创建 E013 自己的空 output root；guard 内不再
尝试创建父目录，只能创建精确授权的 claim 文件与 full_multi_01 目录。检索、top-k、evidence、
Prompt、Parser、Trace binding、答案派生、qwen-plus、temperature=0、max_retries=0、官方 65 Multi
顺序和 260-call 拓扑全部不变。

代码、输入、输出槽、builder 和 run-freeze 必须先通过完整测试并提交冻结。正式运行任一硬门
失败即停止并永久保留，不得同身份重跑。PASS 后才允许冻结候选三件套；不上传、不 push、
不 merge main。

E013 使用独立 runner/builder 文件与独立契约测试。新增的 precreated-root test 在同一
fail-closed guard 下实际写入一次临时 claim，证明只允许精确 claim 文件且不会重现 E012
父目录 mkdir 失败；完整测试 `196 passed`。下一步先提交代码快照，再创建 E013 run-freeze。

source code commit=`c0f126c3071e5fdda4a3c11c07f7689b1992926f`；E013 run-freeze
SHA256=`f33e2129a2a7660eae0baec034306d8f585afa764d002bd4efdcddeba97d77d4`，
自校验 `AUTHORIZED_TO_RUN_ONCE`。新 output root/claim/output/result/bundle/candidate 槽全部为空。
下一合法动作是 Keychain 临时注入与冻结 CA 下的唯一一次 full Multi run。
