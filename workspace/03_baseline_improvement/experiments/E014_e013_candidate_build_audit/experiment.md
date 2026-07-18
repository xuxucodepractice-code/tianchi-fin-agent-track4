# E014：E013 candidate build locality audit

## 当前状态

`PREREGISTERED / CODE_TESTED / BUILD_FREEZE_PENDING / ZERO_API / DO_NOT_SUBMIT`

E014 不重跑模型，只读复用 immutable E013 full Multi PASS：65 derivations、260/260 calls/attempts、
0 retries、847,222 tokens、唯一 served model `qwen-plus`、Trace/schema PASS。E013 原 claim、output、
run-freeze、Trace、receipt 和 builder failure 全部只读。

E013 builder 唯一失败是父 v2s1 manifest 的 E001 rerun 相对路径按隔离工作树解析。E014 的唯一
修正是：先要求父三件套精确 SHA256 匹配，再要求主工作区原生 E001 candidate audit 精确哈希、
`ok=true`、12/12 checks、100 questions、1,168,763 tokens 和三件套哈希全部匹配；随后只允许
隔离 validator 出现且仅出现已知的 external-parent lineage locality error。不得过滤任何其他错误。

E014 使用新的 builder identity、rerun bundle、candidate、audit/result/freeze 槽。builder 与所有
immutable source/parent/audit 哈希须先提交并冻结。候选必须通过通用 100 题 validator、65 Multi
逐记录等于 E013 rerun、35 TF/MCQ 逐记录等于 v2s1 parent、Trace/lineage/token/hash 全部硬门，
且 Token 惩罚后的 prospective 投影严格高于 65.0912。PASS 后只冻结三件套；不上传、不 push、
不 merge main。

E014 builder 的只读 preflight 已用真实 frozen artifacts PASS：父 exact hash/native audit gate PASS，
E013 260-call Trace 复审 PASS；新增两项回归后完整测试 `198 passed`。下一步提交 builder/code
快照与授权文件，再创建绑定 source/parent/audit/outputs 的一次性 build-freeze。
