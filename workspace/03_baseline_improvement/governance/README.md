# Experiment Governance

本目录保存提交线实验的长期规则，不保存某一次实验的运行结果。

- `experiment_rules.md`：单变量实验和晋升规则。
- `artifact_rules.md`：测试、实验、候选版本和正式提交的产物边界。
- `pipeline_versions.md`：pipeline 版本登记表。
- `agent_trace_gate.md`：从 E002 起的 API 调用追踪、候选冻结与盲标揭晓时序门。

详细执行路线见上级目录中的 `step_by_step_experiment_playbook.md`。

## 当前强制边界

v0、v1s1、v2s1 均属于 `LEGACY_PRE_TRACE_GATE`；它们保留既有线上事实和实验决策，
但不得事后补写为 `agent-trace/v1`。从 E002 起，只要候选包含新 API 推理，就必须通过
Trace Gate 后才能合成、揭标和上传。纯粹逐字节复制冻结父版本的空 rerun 回归不需要
伪造 trace。
