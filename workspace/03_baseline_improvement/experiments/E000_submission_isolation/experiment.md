# Experiment E000: 提交与测试产物隔离

## 基本信息

- 状态：KEEP_INFRA
- parent_version：current workspace
- pipeline_version：不改变推理版本
- 唯一变量：运行产物目录和提交一致性护栏
- 影响题型：无
- 线上提交：不需要

## 实验假设

当前测试和 dry-run 可以覆盖正式 `submission/`，且 validator 没有严格检查三份产物的 qid 集合和运行身份。先消除实验污染，后续消融结果才可信。

## 本实验允许修改

- 输出路径配置；
- pytest 临时输出路径；
- dry-run 默认输出路径；
- submission validator；
- 产物元数据和 SHA256 护栏；
- 相关测试。

## 本实验禁止修改

- 检索算法；
- Prompt；
- Qwen 判断；
- TF/MCQ/Multi 答案逻辑；
- 文档解析；
- 任何题目答案。

## 验收清单

- [x] pytest 不修改根目录 `submission/`。
- [x] dry-run 不修改根目录 `submission/`。
- [x] mock 不修改根目录 `submission/`。
- [x] 实验默认写入 `outputs/experiments/<experiment_id>/`；dry-run 写入 `outputs/dry_runs/`。
- [x] answer/evidence/manifest 缺少任意 qid 时 validator 失败。
- [x] 官方提交与官方 group_a qid 全集逐一核对。
- [x] 三份产物 mode/model 与声明不一致时 validator 失败。
- [x] 混合版本通过 parent SHA256、rerun_qids 和逐题 lineage 校验。
- [x] 正式产物包含 dry-run、mock 或占位 rationale 时 validator 失败。
- [x] Token 汇总不一致时 validator 失败。
- [x] 版本化正式缓存写入 `processed_data/reasoning_samples/by_pipeline/<version>/`。
- [x] 3 个污染平铺缓存移入 quarantine 并生成清单。
- [x] 产物级合并工具存在并有空集、非空 lineage 测试。
- [x] 全量 pytest 通过（当前全套 132 passed）。
- [x] 运行 dry-run 和全量测试前后，根 `submission/` 与冻结 v0 的 SHA256 均不变。

## Go 条件

全部验收项已通过，标记 `KEEP_INFRA`。本实验不改变答案、未调用 Qwen、无需线上提交。

## 验证证据（2026-07-14）

- `python -m pytest tests/ -q`：E000 完成后持续回归，当前全套 `132 passed`。
- 默认 dry-run 输出：`outputs/dry_runs/latest/`，未触碰根 `submission/`。
- v0 空 rerun 合并输出：`outputs/candidates/v0_empty_regression/`。
- 空 rerun 三文件 SHA256 与冻结 v0 完全一致：
  - answer.csv：`c1a70a5697fbb55b0248d2a6b9aa34ca7279975ed3689d5cadc5f9a7b22421ff`
  - evidence.json：`ba5ee86f9155672cace1fe7a2428bb30ec8e01f62bb96bef9dbdf8133029de49`
  - run_manifest.json：`b22230895d9f421a578ecf49e70e58e46f93bde5a8434acf1040fb77f1d8e451`
- 空集候选通过 validator：`[VALID] questions=100 total_tokens=1161593`。
- quarantine 清单：`processed_data/reasoning_samples/quarantine/legacy_flat_invalid/quarantine_manifest.json`。
