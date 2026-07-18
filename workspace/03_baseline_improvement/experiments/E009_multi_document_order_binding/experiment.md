# E009：Multi document-order binding

## 当前状态

`PREREGISTERED / DEVELOPMENT_NOT_RUN / DO_NOT_SUBMIT`。

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
