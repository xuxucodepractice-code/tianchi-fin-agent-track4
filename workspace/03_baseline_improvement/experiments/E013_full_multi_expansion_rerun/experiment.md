# E013：65 道 Multi 全量扩展技术重跑

## 当前状态

`FULL_MULTI_PASS / BUILDER_TECHNICAL_NO_GO / CANDIDATE_NOT_CREATED / DO_NOT_SUBMIT`

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

正式 full Multi run PASS：65 questions、260 logical calls、260 physical attempts、65 derivations、
0 retries、847,222 tokens；唯一 actual served model 为 `qwen-plus`，Trace/Parser/schema errors=[]。
observations SHA256=`195ad405daf16f35e614a7bf39e37c64d8128a94ff4f3d9ab97a157ed864cbff`；
receipt SHA256=`60696bd9a3d81f173ba32987c9f08b324f1c1f81d094288615d96a23788cd38f`。

冻结 builder 在生成 rerun bundle/candidate 前技术失败：只读 v2s1 父 manifest 的 E001 rerun 相对路径
被按隔离工作树解析，因该目录只存在于主工作区而报 unavailable。父三件套精确哈希、100 题和
1,168,763 tokens 均匹配；主工作区原生 E001 audit 为 12/12 PASS，SHA256=
`8f7455a76c7c945db0fa7dd42d39859bb8f58e44b3cac1698de4b8fb61f1b684`。E013 builder
身份不重跑；E013 full run/claim/Trace 永久只读。E014 只能以零 API 新 builder/candidate 槽复用
immutable E013 PASS，并严格绑定父三件套与原生 audit 哈希。
