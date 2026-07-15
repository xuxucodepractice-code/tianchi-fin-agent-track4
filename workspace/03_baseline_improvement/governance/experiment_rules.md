# Experiment Rules

## 核心纪律

1. 一次实验只修改一个变量。
2. 每个实验必须声明直接父版本。
3. 没有本地净收益，不得晋升为候选版本。
4. 所有答案变化必须逐题审计。
5. 评分实验必须以 `KEEP_SCORE`、`KEEP_CODE_ONLY`、`ROLLBACK` 或 `PILOT` 结束；不改变答案的强制基础设施可使用 `KEEP_INFRA`。
6. 一次线上提交只验证一个实验变量。

## 标准晋升路径

```text
experiments/
→ 本地真值回归通过
→ candidates/
→ 正式产物一致性校验通过
→ 上传并取得线上分数
→ submissions/ 冻结
```

## Go / No-Go

定义：

```text
N = 旧错新对
M = 旧对新错
```

- `N - M > C`：允许进入候选版本评估；`C` 是对应题型同配置重复运行的答案翻转题数。
- `0 < N - M <= C`：保持 `PILOT`，扩大标定或停止。
- `N = M`：若只有工程价值则 `KEEP_CODE_ONLY`，否则 `ROLLBACK`。
- `N < M`：`ROLLBACK`。

`KEEP_CODE_ONLY` 默认关闭，不得成为最佳提交父版本，也不进入最终集成。线上提交后还需要结合 Token 系数反推正确题数，不能只看裸分变化。
