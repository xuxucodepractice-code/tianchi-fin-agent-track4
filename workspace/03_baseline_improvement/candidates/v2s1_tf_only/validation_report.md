# Validation Report

- 时间：2026-07-15T17:38:24+08:00
- 通用 validator：PASS（100 题，1,168,763 Token）
- 实验专属审计：PASS（12/12）
- pytest：132 passed
- parent SHA256：与冻结 v0 三件套一致
- rerun 集：精确等于预注册 20 道 TF
- 答案 diff：精确 2 道
- 其余答案：98/98 不变
- non-rerun 完整记录：80/80 与父版本逐字段相同
- rerun 完整记录：20/20 与 cache-only bundle 逐字段相同
- Token 算术、官方题面元数据、mode/model/pipeline、证据引用范围：全部通过
- 正式出口晋升：`submission/` 与候选三件套逐字节一致；晋升后 validator 再次 PASS

机器可读报告：`outputs/candidates/v2s1_tf_only/audit_report.json`。
