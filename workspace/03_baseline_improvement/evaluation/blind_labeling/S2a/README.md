# S2a 双题独立盲标包

## 目的

独立确定 `reg_a_010` 与 `res_a_013` 的真值。两题会直接决定 TF 改造实验是否值得占用一次线上提交槽位。

## 隔离要求

标定人必须满足：

- 尚未看过这两题的 v0、v1、v2 答案或推理结果；
- 标定过程中只打开本目录两份题卡及题卡列出的原始文档；
- 不打开 `reasoning_samples`、历史提交、审查报告或实验结论；
- 两题都完成后一次性交回，不因先找到某类答案而提前停止。

## 操作步骤

1. 分别打开 `reg_a_010_blind.md` 和 `res_a_013_blind.md`。
2. 逐个核对题干中的事实点，不凭常识猜测。
3. 填写答案、置信度、证据定位和简短理由。
4. 在下面签名并记录完成时间。
5. 将两份已填写题卡交回实验负责人，再由负责人揭晓 pipeline 输出并登记真值。

交回后使用以下命令验收完整性；未完成时退出码为 2：

```bash
python -m agent.validate_completed_labels \
  --cards-dir workspace/03_baseline_improvement/evaluation/blind_labeling/S2a \
  --selection-file workspace/03_baseline_improvement/evaluation/blind_labeling/S2a/selection.json \
  --output workspace/03_baseline_improvement/evaluation/blind_labeling/S2a/results.json
```

## 交付检查

- [ ] 两题均已填写答案。
- [ ] 每题至少一条能够直接支持或反驳题干的证据。
- [ ] 证据包含 `doc_id` 和页码或 `chunk_id`。
- [ ] 标定期间未查看任何 pipeline 答案。

标定人：____________________

完成时间：__________________

隔离声明：我在提交答案前未查看这两题的任何 pipeline 答案或推理结果。签名：____________________

## 完成状态（2026-07-15）

- 独立标定人：Claude Fable（independent blind label）；
- `reg_a_010=B/high`；
- `res_a_013=B/high`；
- 独立复验：`complete=true`、validated 2/2、errors=0；
- 当前检查：`readiness_check.json`；标定前检查快照：`prelabel_readiness_check.json`；
- 权威登记：`../../local_labels.md`。

冻结 provenance SHA256：

```text
selection.json         669fa425f833674b17c9bcb43c9184b729f4b710bc4ec2ef1e0c72a34eb4c0fc
reg_a_010_blind.md     6218e065e63644a9c14fdc73d9769e492c5ef5c55477d8f4cc50954a6205429e
res_a_013_blind.md     62c2736ee0ce583f2926cd293cfc86077559c843f607c29508c9f7e043aadb05
results.json           47308d5079c1f7bd409cce1dcfc5e22883529caaa89ffc77cb9ead89d3321743
```
