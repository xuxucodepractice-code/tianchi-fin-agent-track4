# Pipeline Version Registry

| Pipeline | Parent | 状态 | 主要变量 | 线上分数 | 决策 |
| --- | --- | --- | --- | ---: | --- |
| v0 | — | frozen | 基础提交线 | 63.2607 | KEEP / baseline |
| v1s1 | v0 | submitted | 多项检索和证据组织改动混合 | 61.8540 | ROLLBACK as best |
| v2s1 | v0（提交直接父版本；代码沿革来自 v1s1） | validated and promoted to `submission/`, not uploaded | E001 TF 题干级判断链路包 | — | PILOT / READY_TO_UPLOAD |

## 父版本可复用验收

2026-07-14，v0 通过空 rerun 产物级合并回归：三文件 SHA256 与冻结目录完全一致，validator 报告 `VALID / 100 questions / 1,161,593 tokens`。v0 现在既是不可变文件基准，也是已验证可复用父版本。

新增 pipeline 时必须补充：

- 直接父版本；
- 对应实验 ID；
- 唯一变量；
- 缓存兼容范围；
- 是否形成候选版本；
- 是否真实上传；
- 最终决策。
