# v2 执行计划（详细版）

> 历史说明（2026-07-16）：本文件中的早期 `--qid/--all --use-qwen --resume`
> 命令早于 Agent Trace Gate，只能作为历史设计背景，不能再生成可晋升候选。E002 起请以
> `governance/agent_trace_gate.md` 和 `experiments/E002_mcq_global_comparison/experiment.md`
> 的 selection-backed fresh-run 命令为准。

制定日期：2026-07-08
前置文档：`v1_architecture_review.md`（瓶颈分析）、`v1_s1_diagnosis_and_v2_plan.md`（v1_s1 提分失败诊断）、`submissions/a_leaderboard_v0/v1_error_analysis/task_v1_0_manual_labeling_audit.md`（人工标定审计）
基准：v0 线上 63.2607（冻结于 `2026-07-05_score_63_2607/`）；当前 `submission/` 为 v1_s1 产物（pipeline_version=v1s1）

---

## 0. 全局不变量（每个任务逐字遵守，其余实现方式留给执行者）

**合规红线（不可触碰）**
- 正式推理只用 Qwen 系列 API；禁止 embedding 检索/rerank/推理。
- 代码侧算术复核属于确定性计算校验，合规；但不得用非 Qwen 模型生成语义内容进入答题链路。
- API key 只从环境变量读，不落盘、不进日志。

**工程不变量**
- `validate_answer_format` 与 `validate_submission.py` 的校验逻辑不放松，只能加严。
- 每个实验改动后必须全量 `python -m pytest tests/ -q` 通过（当前 64+ passed 是底线）。
- 缓存复用机制不破坏：未受影响的题走 `reasoning_samples/` 缓存，只重跑受影响题（用 `--rerun-qids`）。
- 每个实验升一次 `PIPELINE_VERSION`（v2s1、v2s2、…），保证 manifest 可追溯。
- 冻结规则延续：每次线上提交后，把 `answer.csv`/`evidence.json`/`run_manifest.json` + SHA256 + 分数快照进 `submissions/a_leaderboard_v0/<日期>_<版本>_score_<分数>/`。

**提交纪律（每天 3 次机会）**
- 一次提交只验证一个变量。禁止把两个实验混进同一次提交。
- 提交前必须：`python -m agent.validate_submission submission/answer.csv` → VALID。
- 提交后 10 分钟内在 `submissions/a_leaderboard_v0/notes.md` 追加记录，模板：

```markdown
## <日期> 提交记录：<pipeline_version>
- 变量：<本次唯一改动的一句话描述>
- 线上分数：<分> | 与 63.2607 差：<±分> | 与上一次提交差：<±分>
- 答案 diff：<N> 题变化（相对上一次提交），清单：<qid: 旧→新>
- token：total=<N>（系数 <x>）
- low_confidence：<N> 题
- 结论：<该变量的收益判定，一句话>
- 下一步：<继续/回滚/调整>
```

**每个任务的输出要求**
- 任务完成后在 notes.md 记录：目标、改动文件、命令、验收结果、当前限制。
- 新增一节「执行中观察到的越界问题」：发现相邻层的缺陷只记录、不顺手修（防止变量污染）。

---

## Task v2-0：标定与记录补齐（P0，半天，零 token）

### 目标

在动任何代码之前，建立本地真值集和干净的对照记录。没有这一步，后面所有实验的收益都无法归因。

### 0a. 补记 v1_s1

- 若 v1_s1 已提交：把分数按上面模板补记进 notes.md，并冻结 v1_s1 产物目录。
- 若尚未提交：**直接提交当前 `submission/`**（它是实验三的对照读数，已通过 validate），拿到分数后记录+冻结。

### 0b. 建立本地真值集 `evaluation/local_labels.md`（2026-07-15 已从旧位置迁移）

现成可写入（来源：学习线 + 审计报告）：

| qid | format | 真值 | 置信度 | 来源 | v0 答案 | v1_s1 答案 |
| --- | --- | --- | --- | --- | --- | --- |
| ins_a_007 | multi | BC | 高 | 学习线人工+模型复核（research_log 2026-07-02） | AC ✗ | BC ✓ |
| ins_a_001 | mcq | B | 高 | 审计报告四公式全定位 | A ✗ | A ✗ |
| ins_a_002 | mcq | A | 高 | 审计报告三公式全定位 | A ✓(撞对) | A ✓ |
| fc_a_013 | tf | A | 高 | 审计初判，按核对点确认 | A ✓ | A ✓ |
| fin_a_006 | tf | A | 高 | 审计初判（复核 11.7% vs 10% 边界与千元单位） | A ✓ | A ✓ |
| res_a_003 | tf | A | 中高 | 审计初判（确认 50%/37% 两数字） | A ✓ | A ✓ |
| reg_a_018 | tf | A | 中 | 审计初判（翻原 PDF 确认董事会审议条文） | A ✓ | A ✓ |
| fin_a_013 | tf | A | 高 | 审计初判 | A ✓ | A ✓ |

规则：每行必须注明来源和置信度；文件头注明「仅限本地分析与回归测试，不进提交产物」。

### 0c. 补充标定 3 道非低置信 tf 题（关键决策输入）

人工核 fc_a_003、fc_a_006、fc_a_010 的真值（v0 均判 A 且非 lc）。目的：审计的 5 题 tf 样本全来自 lc 清单，有选择偏差；只有核过非 lc 的题，才能回答「tf 全 A 到底丢几题」，从而决定 Task v2-1 的预期收益是 +2 还是 +8。

### 0d. （可选，30 分钟）标定 v1_s1 遗留的 7 题 multi

ins_a_005/009/010/014/015/016/019 的新旧答案哪个对。核几题算几题，结果进 local_labels.md，供 Task v2-3 使用。

### 验收标准

- notes.md 有 v1_s1 记录（含分数）。
- local_labels.md ≥ 11 题（8 现成 + 3 补标），每题有来源。
- 得出结论：「11 道已标定 tf 中真值为 B 的有 N 道」→ 写入 Task v2-1 的预期收益。

---

## Task v2-1：tf 判定框架重做（实验一，最高优先级）

### 目标

废除「逐选项判断 tf + 恒 A fallback」，改为对题干陈述做一次 true/false/uncertain 直接判定。验收指标用结果定义：**tf 答案分布不得再 20/20 单边；local_labels 中已标定的 tf 题全部答对；res_a_003 / fin_a_013 的判断内部自洽**。

### 背景（为什么现在的 tf 是坏的）

- 选项文本是「正确/错误」元标签，进检索被当停用词，A/B 拿到相同证据、问两个对称问题 → 模型语义混乱（v0 中 res_a_003 的 rationale 论证「命题为真」标签却打 refute）。
- `normalize_answer.py:87-97`：双 support / 双 insufficient / 双 refute 全部 fallback A → 20/20 全 A。
- 每题 2 次调用问同一件事，token 翻倍。

### 改动文件与实现规格

**`agent/prompts.py`** — 新增 `build_tf_judgment_messages(question, evidence)`：

- 输入：题干 + 题干级证据（不再按 A/B 选项分路）。
- prompt 要点（草案，可调整措辞但要点不可少）：
  - 「判断下面这条陈述是否被证据支持：整体为真输出 true；任何一个事实点被证据明确否定输出 false；证据缺失或不完整输出 uncertain。」
  - **复合陈述必须拆点**：「若陈述包含多个事实点（如涉及两份文档、两个数字），先逐点列出并逐点判定，全部为真才是 true。」（审计发现 4/5 的 tf 是双文档双事实点，v0 单查询只覆盖一半）
  - 严格 JSON：`{"verdict": "true|false|uncertain", "fact_checks": [{"claim": "...", "verdict": "...", "evidence_refs": [...]}], "rationale": "..."}`
- 复用现有 `format_evidence_block` 和 `SYSTEM_PROMPT` 基调（只准用给定证据）。

**`agent/retrieve.py`（小改）** — tf 题证据获取：

- 现有 `retrieve_for_question` 是逐选项检索；tf 题改为对题干做检索，且**对题干中的每个 doc_id 保证至少 2 条证据配额**（复用 v1_s1 已有的 coverage/quota 机制，把它对 tf 按 doc 分桶启用）。这直接治 fc_a_013 型「text03 声明页没进 top-5」的失败。
- 实现自由度：可以在 retrieve 层加 tf 分支，也可以在 reason 层把 A/B 两路证据并集去重后使用——二选一，以测试可写、改动面小者为准。

**`agent/reason_qwen.py`** — 新增 `reason_tf_question_with_qwen(question, retrieval, client)`：

- 单次调用；verdict=true→A、false→B。
- **uncertain 处理（替代恒 A fallback）**：uncertain 时允许一次重问（可附带 fact_checks 中缺证据的点作为补充检索词，追加一轮检索后重判；限一轮，硬编码上限）。重问后仍 uncertain 才 fallback，fallback 方向由 Task v2-0 的标定结果决定（若已标定样本中 uncertain 题真值多为 A，就保持 A，但必须是数据决定，不是格式规定），并标 low_confidence。
- token 逐次累加进题级统计（含重问轮）。
- `_assemble_result` 兼容：tf 题的 `option_judgments` 字段写入 `{"A": {...verdict 映射...}, "B": {...}}` 或新增 `tf_judgment` 字段——保证 `output_writer` 和 `validate_submission` 不需要放松校验。

**`agent/normalize_answer.py`** — tf 分支重写：

- 输入改为 verdict（或从新结构读取）；**删除第 96 行「无法确定→A」的无条件规则**。
- `validate_answer_format` 不动。

**`agent/run_submission.py`**：

- `solve_question` 按 `answer_format` 分派：tf 走新链路，mcq/multi 走原链路。
- `PIPELINE_VERSION` 升为 `v2s1`。

### 测试要求

- 新增 `tests/test_reason_tf.py`（fake client，不调真实 API）：
  - true→A、false→B、uncertain→重问→仍 uncertain→fallback+low_confidence。
  - **回归用例（固化审计发现）**：构造 res_a_003 / fin_a_013 场景——rationale 与 verdict 必须自洽（fake client 返回矛盾结构时应记 error 而非静默采纳）。
  - JSON 解析容错（markdown 包裹、多余文字）复用 `extract_json_from_text` 的既有测试模式。
- `tests/test_normalize_answer.py` 中 tf 相关用例同步更新。
- 全量 `pytest tests/ -q` 通过。

### 运行与重跑范围

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m pytest tests/ -q
# 先单题冒烟（挑一道已标定 tf）
python -m agent.run_submission --qid fc_a_013 --use-qwen
# 全量：只重跑 20 道 tf，其余 80 题走缓存
python -m agent.build_rerun_list ...  # 或手写 rerun_qids.json（20 道 tf 的 qid 清单）
python -m agent.run_submission --all --use-qwen --resume --rerun-qids <path>
python -m agent.validate_submission submission/answer.csv
```

### 验收标准（全部满足才提交）

1. pytest 全量通过。
2. tf 答案分布不再 20/20 全 A（若真是全 A，必须逐题人工抽查 3 道确认判定链路自洽，而非 fallback 堆出来的）。
3. local_labels 中已标定的 tf 题（≥8 道）全部答对。
4. res_a_003、fin_a_013 的新判断 rationale 与结论自洽。
5. 其余 80 题答案与 v1_s1 完全一致（缓存复用验证：diff 只出现在 tf 20 题内）。
6. validate → VALID。

### token 预算与提交

- 预计 +8~15 万（20 题 × 1~2 次调用，比 v0 的 2 次/题省）。
- 单变量提交，记录分差 → **这个分差就是 tf 的真实收益读数**。

### 风险与回滚

- 风险低：影响面锁死在 20 题。
- 回滚：`reasoning_samples` 有 archive 机制 + v1_s1 已冻结，`--rerun-qids` 换回旧缓存即可。建议开分支 `feat/v2s1-tf`。

---

## Task v2-2：mcq 全题比较判定 + 确定性计算校验（历史合并规格）

> 2026-07-16 范围勘误：当前权威 E002 只实现 M1 四选一统一比较，保留 4 次参考判断并
> 新增 1 次 global comparison；本节下方的 `verify_calc`、算术重问和相应测试已拆到 E003，
> 本轮不得实现。E002 的状态与命令以 `experiments/E002_mcq_global_comparison/experiment.md`
> 和 `governance/agent_trace_gate.md` 为准。

### 目标

废除「逐选项独立判断 + evidence_refs 决胜 + 0-support fallback A」，改为四选项一次比较判定；计算题由代码复核算术。**硬验收：ins_a_001 管线自动得出 B**（公式页码已全部定位、检索实体分桶已就位，此题现在只差推理层，是完美验收样本）。

### 改动文件与实现规格

**`agent/prompts.py`** — 新增 `build_mcq_comparison_messages(question, options, evidence_by_option)`：

- 四个选项 + 各自证据一次性给出（证据块按选项分节，沿用 source_header 来源行）。
- prompt 要点：
  - 「比较四个选项，选出唯一最可能正确的一项，并给出排除其余三项的理由。」
  - **题面级自洽检查**：「若某选项内部数字自相矛盾（如声称 90 > 144），直接排除并说明。」（ins_a_001 的干扰项 A 就是这种，逐选项模式感知不到）
  - **计算题要求列算式**：「若判断依赖计算，在 calculations 字段列出每一步算式（如 `max(90*1.6, 85) = 144`），不要心算跳步。」
  - 严格 JSON：`{"answer": "A|B|C|D", "eliminated": {"B": "理由", ...}, "calculations": ["...", ...], "confidence": "high|low", "rationale": "..."}`

**新增 `agent/verify_calc.py`（小模块）** — 确定性算术复核：

- 输入 calculations 字符串列表，用 `ast` 安全解析四则运算 + max/min（**禁 eval 裸执行**），复核等式两边。
- 复核不改答案：不一致时写 warning + 标 low_confidence + **触发一次重问**（把不一致的算式指给模型：「第 N 步算术不成立，请重新计算并复核答案」）。限一轮。
- 定位：确定性校验，合规；它不生成语义内容。

**`agent/reason_qwen.py`** — 新增 `reason_mcq_question_with_qwen`：

- 流程：逐选项判断照跑（**降级为参考信号**，结果仍写入 evidence.json 的 option_judgments）→ 比较调用给出 answer → verify_calc 复核 → 不一致重问一轮 → 最终答案。
- 逐选项判断可复用 v1_s1 缓存里的 judgment（若检索结果 jaccard 高），省一半 token——实现自由度：也可以直接全部重跑，以简单为准。

**`agent/normalize_answer.py`** — mcq 分支重写：

- **删除**：多 support 按 evidence_refs 数决胜（75-81 行）、0-support fallback letters[0]（82-85 行）。
- 新逻辑：比较调用的 answer 为准；比较调用失败/JSON 不合法时才 fallback（此时保留 low_confidence + warning）。
- multi 分支和 `validate_answer_format` 不动。

**`agent/run_submission.py`**：mcq 分派新链路；`PIPELINE_VERSION` 升 `v2s2`。

### 测试要求

- `tests/test_reason_mcq.py`（fake client）：比较判定正常路径、JSON 解析失败 fallback、算式复核不一致触发重问、重问后采纳修正答案。
- `tests/test_verify_calc.py`：四则/max/min/百分比、恶意输入不执行（安全测试）、浮点容差。
- 全量回归通过。

### 运行与重跑范围

```bash
python -m agent.run_submission --qid ins_a_001 --use-qwen   # 硬验收题先行
python -m agent.run_submission --all --use-qwen --resume --rerun-qids <mcq 15 题清单>
python -m agent.validate_submission submission/answer.csv
```

### 验收标准

1. **ins_a_001 自动得出 B**（不满足则不提交，回头查证据分桶是否把 doc 2 送进去了）。
2. ins_a_002 仍为 A（防止改造把撞对的题改错）。
3. mcq 答案分布不再 A=11/15。
4. 其余 85 题与上一版完全一致；validate VALID；pytest 全过。

### token 预算与提交

- 预计 +20~25 万（15 题 × [逐选项参考 + 1 次比较 + 少量重问]；复用缓存可减半）。
- 单变量提交，记录分差。

---

## Task v2-3：multi support 收紧（实验四，条件触发，试点先行）

### 触发条件（不满足就不做）

Task v2-1 + v2-2 提交后，若累计分差距离预期明显不足，且错误分析显示 multi 仍是大头，才启动。**这是风险最高的实验（可能把判对的改错），必须试点。**

### 试点（离线，先不提交）

- 试点集 16 题：全选 6 题（fc_a_016、fin_a_005、ins_a_005、ins_a_010、ins_a_017、res_a_014）+ 3-support 题抽 10 题。
- 改动（试点分支上）：judgment prompt 增加逐要素核对清单——「support 前必须逐项确认：主体一致 / 数值一致 / 时间一致 / 条件一致，任一要素证据缺失即不得 support」；可选加一次整题一致性复核调用。
- 人工比对新旧判断（结合 Task v2-0d 标定的 7 题 multi），产出对照表：改对 N 题 / 改错 M 题。
- **Go/No-Go：N > M 才全量**；否则记录结论、关闭实验。

### 全量（仅当 Go）

- 重跑 65 道 multi，token ~80 万；单变量提交。
- 顺带决策：v1_s1 遗留 7 题 multi 变化，按标定结果保留或回滚。

---

## Task v2-4：B 榜迁移准备（7-14 前后启动，A 榜管线稳定为前提）

- 给 68 个文档建「文档卡片」（标题、主体实体、年份、类型关键词）——`doc_meta.py` 已有雏形，扩展即可。
- B 榜无 doc_ids 时：卡片级 BM25 先选档（top 3-5 文档），再进正常管线；`filter_chunks_for_question` 已留插槽。
- 验收方式：拿 A 榜题**隐藏 doc_ids** 模拟：选档命中率（真 doc_ids ⊆ 选出集合）≥ 90%。
- 本任务零线上提交，纯离线。

---

## 时间表与预期

| 日期 | 任务 | 提交 | token 增量 | 预期分数收益 |
| --- | --- | --- | ---: | --- |
| D1（今天） | v2-0 标定+补记 | v1_s1（若未交） | 0 | 拿到实验三对照读数 |
| D2 | v2-1 tf 重做 | 是（v2s1） | +8~15 万 | +2 ~ +8 题（v2-0c 标定后收窄） |
| D3 | v2-2 mcq 比较 | 是（v2s2） | +20~25 万 | +3 ~ +5 题 |
| D4+ | v2-3 试点（条件触发） | 试点不提交 | +20 万 | 试点定夺 |
| 7-14 后 | v2-4 B 榜卡片 | 否 | 0 | B 榜生存能力 |

- v2-1 + v2-2 后总 token ≈ 1.65M，系数 0.901：**累计多对 3 题即回本**，预期 +5~13 题（对应约 66~75 分区间）。
- 每步都有独立分差读数，任何一步不涨都能明确归因并回滚，不再出现 v1_s1 式的「改了但不知道为什么没涨」。

## 附：本计划刻意不做的事（防跑偏清单）

- BM25 参数/权重微调（无本地标签，不可归因）
- 解析层重构 / 表格重建 / 换 PDF 解析器
- multi 检索继续加料（v1_s1 已证明穿不透判断层）
- agent 自主多轮循环（破坏可复现与缓存）
- 任何省 token 的优化（预算用了 26%，负优先级）
- B 榜检索在 7-14 前动工
