# E009：Multi document-order binding

## 当前状态

`DEVELOPMENT_GATE_PASS / PROSPECTIVE_PRIMARY_NO_GO / DO_NOT_SUBMIT`。

E008 的 control/treatment 13/13 答案完全一致，reference-free provenance 可稳定工作，但
`fc_a_001` 把 evidence 呈现顺序误当成题面“第一份/第二份文档”的顺序。题面 `doc_ids`
实际为 `[text01,text02]`，而按相关度排序的 evidence 先出现 text02，导致 5 亿元/10 亿元
比较方向反转。

## 唯一变量

两臂都使用 E008 的 reference-free strict JSON 与完整 Trace evidence-pack provenance。

- control：不向模型显式说明题面 doc_id 顺序；
- treatment：在题目后增加确定性映射，例如
  `文档顺序：第一份文档 doc_id=text01；第二份文档 doc_id=text02`。

映射严格来自当前问题的 `doc_ids` 数组，适用于所有题，禁止 qid/doc_id/chunk_id 特判。
该行只解析题面中的“第一份/第二份”等指代，不作为支持/refute 的证据。

## 冻结与门槛

E006 treatment retrieval、top-k=5、evidence 内容/顺序/预算、判断规则、reference-free
schema、qwen-plus、temperature=0、max_retries=0、四调用、normalize/fallback、TF、MCQ、
CA bundle 与 65.0912 锚点全部不变。

13 题 fresh paired 各 52 logical/physical attempts。treatment schema/Trace/temporal errors=0；
准确率不低于 control；冻结父正确 6 题零回退；retrieval/evidence 逐字节一致。失败立即
NO-GO；PASS 后才进入全新 prospective primary/repeat/churn 与盲标。

fresh control：13/13、52 logical/physical attempts、零 retry、178,969 tokens、唯一 served
model=`qwen-plus`，receipt/Trace PASS。一次性 treatment authorization 已生成。

treatment 同样完成 52/52、零 retry、181,361 tokens。准确率 8/13→10/13，净 +2；
`fc_a_016:ABCD→ABC` 与 `fc_a_001:AD→ABD` 均改对，冻结父正确 6 题零回退。
Trace/schema/temporal、reference-free provenance 与 retrieval equality 全部 PASS，允许进入
全新 prospective selection 的预注册，但仍不授权 candidate 或 submission。

## Prospective selection 可行性

只读枚举 65 道 Multi，并排除 E006 development、E006 prospective、Multi Tier-1 已知标签
及既有 E004/E006 holdout 后，合格余量为：financial_contracts=8、financial_reports=8、
insurance=1、regulatory=9、research=9。insurance 仅剩 `ins_a_012`，所以“全新且五领域
各 3 道”在当前数据集上数学不可行。

主理人随后要求 persistent goal 自主推进至下一份可提交候选。为保持 15 题全部全新、
未标注且不复用旧 holdout，采用最小必要配额放宽 `4/4/1/3/3`；保险使用唯一合格题，
其余领域尽量均衡。领域内以冻结 seed 对 `seed:qid` 的 SHA256 升序选择，未访问答案。
selection、配额授权和可行性审计已分别冻结并互相绑定。

prospective runner、churn evaluator 与 scored evaluator 已完成：primary/repeat 固定各 15 题、
60 logical/physical calls、max_retries=0、同一 exact served model；primary 是唯一计分臂，
repeat 只计算稳定性；labels 在 churn 冻结前必须不存在。评分门同时要求 `N-M>C` 且按
5,000,000 Token 预算公式惩罚后的预计分数严格高于 65.0912。全量 183 tests PASS；
run-freeze 已绑定 code-freeze commit `9f8d76c0e49223f121b5883e5ffc8e34c283d73e`，SHA256
为 `04af55a5b552f933d061261bc769d99623c8dd09439b7563bb3fe2bfea548b72`。当前尚未读取
API key、未调用 prospective API。

## Prospective primary 结果

primary 已 one-shot 完成 15 题、60 logical/physical calls、零 retry、192,238 tokens，唯一
served model 为 `qwen-plus`；60/60 raw responses 均通过 reference-free 严格 parser，且实际
request messages 与 Trace 顶层 messages、以 `model_evidence` 重建的冻结 builder 完全一致。

但冻结 validator 错从 `context.evidence` 重建消息；Trace 按设计把完整 evidence pack 存在
`model_evidence`，context 不含 evidence，因而 60/60 被误报 message mismatch，receipt=FAIL。
严格 one-shot 治理不允许追溯修正 receipt、删除或重跑该槽。E009 primary 永久 NO-GO；
repeat/churn/labels/全量扩展均不运行，失败产物完整保留。
