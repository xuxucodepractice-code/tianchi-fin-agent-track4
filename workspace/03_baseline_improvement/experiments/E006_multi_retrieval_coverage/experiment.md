# E006：Multi 选项到文档的保守路由试点

## 当前状态

`OFFLINE_PASS / PRE_API_FREEZE / DEVELOPMENT_ONLY`。尚未运行 development API，
prospective 仍由代码封锁，尚未生成候选，不授权提交。

## 为什么先修正 control

线上 `v2s1`（65.0912）的 65 道 Multi 全部从 v0 继承；E001 只重跑了 20 道 TF。
线上 Multi 的真实检索器来自 commit `82041d0`：严格 top-5、单 chunk、无文档配额、
无 neighbor、无 source header，单条窗口 1200 字。当前 `f31e4ed` 源码中的 quota、
neighbor、header 与动态窗口是后加能力，不能当成线上父版本 control。

已经用历史算法和冻结 chunks 重算 65 道 Multi、260 个 option pack，ordered evidence
dict 与冻结 v2s1 产物 `260/260` 完全一致。E006 必须从这个可复现 control 出发。

## 父版本与目标

- 线上分数锚点：v2s1，65.0912；
- 代码工作边界：`f31e4ed38c5ad14a8b49abceca4bb4baefc745db`；
- 检索 control：`online-v2s1-multi-retrieval-v0`；
- 目标：减少多文档 Multi 中“当前选项与其他文档证据混在一起”的错绑；
- 非目标：不修 Prompt、reasoner、窗口、neighbor、top-k、Token 预算或答案 fallback。

## 唯一变量

只对 Multi 做确定性的“选项 → 唯一文档”高置信路由。每个选项先在完整候选索引上
按 v0 BM25 打分；文档标题只用于决定是否路由，不重建子索引，因此 chunk score/IDF
不变。标题门槛固定为：

```text
top title score >= 12
最长标题匹配 >= 4 字
top score >= 3 * max(second score, 1)
top - second >= 8
```

全部满足时，从目标文档中取完整索引原排名的前 5 条；否则逐字节 fallback 到 v0
global top-5。目标文档不足 5 个有效 hit、metadata 缺失或题目不是 Multi 时也 fail-safe。

## 冻结项

- `chunks.jsonl`、题面 `doc_ids` 与 BM25 计分；
- 每选项恰好 5 条 evidence；
- 单 chunk、1200 字 earliest-match 截断；
- v0 Prompt（包括证据位置的括号格式）；
- 每题 A/B/C/D 各一次调用、qwen-plus、temperature=0；
- JSON parser、`normalize_answer` 与答案 fallback；
- TF、MCQ；
- 线上父答案与 65.0912 分数锚点。

## 开发分区和评估

1. 8 道 Gold-complete Multi 做渲染前 canonical chunk recall；
2. 13 道已知标签 development 做 fresh paired API：control 与 treatment 使用同一代码、
   Prompt、模型和参数，只允许 retrieval selection 不同；
3. 冻结 v2s1 的 6 道父版本正确题必须零回退；
4. 旧线上答案不直接充当因果 control，因为 51/65 Multi 使用了 pre-Trace cache。

## 运行治理

- 当前 runner 只接受治理目录中的 `development_selection.json`，同时核对文件路径、
  SHA256、恰好 13 个 qid 及固定顺序；`primary/repeat` 在开发 PASS 前不可调用；
- questions tree、chunks、doc_meta、control reference、selection 与 offline gate 六类输入
  都在创建 API client 前核对冻结 SHA，任一变化立即失败；
- control 与 treatment 必须分别从不存在的空目录启动，每臂恰好 13 个 derivation、
  52 次独立调用；provider、模型、temperature、finish reason、tool calls、guard allowlist、
  call ownership 与 Trace 哈希均需通过；
- paired evaluator 强制消费两份 receipt，并把 observations、Trace manifest、代码、模型、
  输入和 selection 哈希串起来；随后从冻结输入重新计算两臂 retrieval，fallback 必须
  逐字节相同，所有变化必须由 route 决策完整解释；
- development labels 仅在两臂运行完成后由 evaluator 读取；父版本正确集合由 truth 与
  冻结父答案重新计算，不信任手工填写的汇总字段。

## 开发门槛

- 65 道 control 的 canonical retrieval hash 必须与冻结参考完全一致；
- Gold canonical recall 必须上升，已命中的 required chunk 不得减少；
- paired API 的 `N_control_to_treatment - M_control_to_treatment >= 1`；
- treatment 相对冻结父答案的开发净收益至少 +1；
- 6 道冻结父版本正确题 `M_dev = 0`；
- 两臂均 52/52 调用、无 API/schema failure、Trace Gate PASS；
- Token 增量和 control-vs-frozen churn 必须记录，不得隐去。

任一硬门失败即 `ROLLBACK_DEVELOPMENT_NO_GO`，不运行 prospective。即使通过，也只
解锁密封的 15 题 primary+repeat；不直接解锁全量候选或上传。

## 已知边界

保守路由预期只解决唯一实体绑定问题；`fc_a_016:D` 的跨文档反证与
`fin_a_005:B` 的双公司比较仍保留为未解决 control。不得为追这两题放宽阈值或加入
同义词，因为那会成为另一个检索变量。若 chunk 已命中但决定句仍未显示，应关闭 E006，
另开 E007 evidence rendering/window 实验。
