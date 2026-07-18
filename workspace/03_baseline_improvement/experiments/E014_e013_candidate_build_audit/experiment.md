# E014：E013 candidate build locality audit

## 当前状态

`CANDIDATE_FROZEN / READY_FOR_USER_SUBMISSION / DO_NOT_AUTO_UPLOAD`

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

source code commit=`713840ba561f608befcf5c7d2681a19d5ea2a860`；build-freeze SHA256=
`60b7b1a0ef381c77d44af0426d612b085d5d84a9764cefa06ad74efc45d4b597`，自校验
`AUTHORIZED_TO_BUILD_ONCE`；所有 E014 bundle/candidate/audit/result/freeze 槽为空。

一次性 build PASS。候选恰好包含三件套，通用 validator `VALID / 100 questions / 1,171,501
tokens`；E014 专属审计 11/11 PASS、errors=[]。65 Multi 逐记录来自 immutable E013 full run，
35 TF/MCQ 逐记录继承 exact v2s1 parent；actual served model=`qwen-plus`、260 logical/physical
attempts、0 retries。相对 v2s1 答案 diff=12，prospective gate 保持 `N=2、M=0、C=0`。

候选实际 Token factor=`0.92970994`；沿用冻结 prospective projected correct=78.6667，Token
惩罚后预计分数=`73.13718194666667`，严格高于 65.0912。该值是提交前投影，不冒充平台实分。

冻结三件套 SHA256：

- `answer.csv`：`464d8376b662cbee513167d2d833fcaf2875b0968b7db761dfdcb89e2e322465`
- `evidence.json`：`c03542a100e400c80ea69ad95035d79b05e8dfc11e438423ef4d269903c988f9`
- `run_manifest.json`：`d6fe87243e77eeaca8af58e7f957409302c2100f896dd1bd50c92c74f0add5a2`

candidate audit SHA256=`ab8c88a93989bbebc8b02d80dd1ebed5885ea0e50cdd9e2fd6643b435457c0db`；
candidate freeze SHA256=`5db40d1018d52fbb6f2c11e44a5d662c794fa8367d7d637aef82c35105f57e41`。
生成后全套测试再次 `198 passed`。没有修改根 `submission/`、线上最佳候选、main、远端或平台。
