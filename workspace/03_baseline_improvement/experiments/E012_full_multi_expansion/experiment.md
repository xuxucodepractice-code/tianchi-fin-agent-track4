# E012：65 道 Multi 全量扩展

## 当前状态

`RUN_FROZEN / AUTHORIZED_TO_RUN_ONCE / API_NOT_STARTED / DO_NOT_SUBMIT`

E012 是 E011 prospective scored PASS 后的部署扩展，不引入新的模型行为变量。它把已经在
E009 development、E010 primary/repeat 和 E011 独立审计/盲标中通过的 treatment，按官方
group_a 顺序运行全部 65 道 Multi。

冻结不变：E006 treatment 检索路由、top-k=5、evidence 内容/顺序/字符预算、E009 文档顺序
绑定 Prompt、Trace `call.model_evidence` provenance、reference-free parser、v0 判断规则、
normalize_answer/fallback、qwen-plus、temperature=0、max_retries=0、每题 A/B/C/D 各一次调用。
TF 与 MCQ 不重跑，候选合成时逐记录继承线上最佳 v2s1（65.0912）三件套。

授权依据是冻结的 E011 scored result：`N=2、M=0、C=0`，投影分数 69.36777264，状态
`ALLOW_FULL_65_MULTI_EXPANSION`。全量运行必须使用一次性 claim、固定 output slot、完整
Agent Trace/raw response/messages/evidence/attempts/receipt，并严格要求 65 derivations、260 logical
calls、260 physical attempts、零 retry、零 parser/schema/Trace error、唯一 actual served model
精确为 `qwen-plus`。

全量硬门失败时立即停止并永久保留失败产物，不生成候选。全量 PASS 后，只允许由冻结 builder
把 65 道 Multi 与只读 v2s1 父版本的 35 道 TF/MCQ 合成；候选必须再通过通用 validator、
父/重跑分区、Token、lineage、Trace 与哈希审计，且 Token 惩罚后的 prospective 投影仍严格高于
65.0912，才可冻结候选三件套。未经主理人确认，不上传、不 push、不 merge main。

E012 runner、严格 Trace validator 与确定性 candidate builder 已实现；新增契约测试后全套
`192 passed`。代码与预注册文件将先提交形成 source commit，再创建绑定整个 `agent/*.py`
快照、三个关键代码文件哈希、输入哈希、nonce、一次性槽位和失败保留策略的 run-freeze。

source code commit=`f88bb5749040b39853d2e80ef82b2aa5234ba781`；run-freeze SHA256=
`40cb570eabfc6a4aceaaf4f9e1138f4c24a2644dd458ea31e33753d190d8be06`。自校验
`AUTHORIZED_TO_RUN_ONCE`，所有 claim/output/result/bundle/candidate 槽在冻结时为空。
下一合法动作是从 macOS Keychain 临时注入 `DASHSCOPE_API_KEY` 与冻结 CA bundle，执行唯一一次
full Multi run；key 不得打印或写盘。
