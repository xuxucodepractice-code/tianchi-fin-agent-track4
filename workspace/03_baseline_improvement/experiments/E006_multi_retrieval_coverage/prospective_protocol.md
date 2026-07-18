# E006 prospective primary/repeat 协议

状态：`AUTHORIZED_TO_RUN_PRIMARY_REPEAT / LABELS_SEALED / DO_NOT_SUBMIT`。

## 固定样本

沿用 E004 在任何 E006 标签生成前冻结的 15 道 holdout，五个领域各 3 道，顺序保持
不变。原始 source selection 的 SHA256 为
`bc0cecefb1298f193da33efc293e96d2340aa223cd1a97599ba3305d39e5e5df`。

## 运行协议

1. 新建 prospective 专用 runner，不修改已完成的 development 产物；代码、测试与本协议
   先单独提交，再生成 `AUTHORIZED_TO_RUN_PRIMARY_REPEAT` run-freeze，避免冻结文件自引用；
2. run-freeze 固定 agent tree、runner/evaluator 哈希、15 个 qid、全部输入、模型参数、调用
   拓扑和唯一输出槽；primary 与 repeat 使用同一代码、模型、Prompt、temperature、输入和
   路由规则；
3. 两轮各 15 题、60 个 logical calls、15 条派生，均从注册的空目录启动；客户端沿用
   development 的 `max_retries=2`，因此物理 HTTP attempts 可为 60–180，必须逐次留痕并
   在无标签 churn 报告中单独列出，不能把重试隐去；
4. primary、repeat 各自在 arm 目录之外原子消费一次性 claim；删除 arm 目录不能恢复
   运行资格。repeat 还必须绑定 primary 的 claim、run ID 与
   observations/manifest/receipt 哈希；
5. 两轮冻结后先计算无标签 churn，不得查看标签来选择某一轮；
6. primary 为预注册计分臂，repeat 只估计稳定性，不能替换 primary；primary/repeat 必须
   各自只有一个精确 served-model 值，且两轮完全相同；
7. 之后才允许创建独立盲标题，并计算：

```text
N = 冻结 v2s1 父答案错误、primary 正确
M = 冻结 v2s1 父答案正确、primary 错误
C = primary 与 repeat 的整题答案 churn 数
```

只有 `N-M>C`、Trace/temporal gate 全部通过、Token 惩罚后仍有正收益时，才允许讨论
扩展到全部 65 道 Multi。prospective PASS 也不直接授权候选或平台提交。

## 密封边界

运行代码只可读取不含答案的 selection、题面、chunks、doc_meta、control reference、
offline gate 与 prospective authorization。不得读取 development labels、历史 Gold、
盲标题、旧答案或候选目录。任何 schema/API/Trace failure 都永久记入对应 attempt，禁止
用 repeat 替换 primary。无标签 churn 只能原子写入固定的
`outputs/experiments/E006_multi_retrieval_coverage/prospective_churn.json`；在该文件冻结前
不得创建 prospective labels 或 scored result。后续盲标只能把 primary 的 observations
哈希和 trace run ID 作为计分输入，repeat 永久为 non-scoring。
