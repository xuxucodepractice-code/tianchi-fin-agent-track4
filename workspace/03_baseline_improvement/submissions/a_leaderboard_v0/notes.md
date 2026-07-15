# A 榜提交线 v0 过程记录

## 2026-07-05 Task 1：搭建提交线工程骨架

### 本任务目标

创建最小可运行的提交线工程，打通「题目 JSON -> 按 qid 定位 -> answer.csv / evidence.json / run_manifest.json」数据流。本轮使用 mock 占位答案，不接 Qwen，不做检索和文档解析。

### 创建/修改的文件

- `agent/__init__.py`：包说明与版本。
- `agent/paths.py`：集中路径管理（repo root、questions dir、submission dir、notes dir），`ensure_output_dirs()` 幂等建目录。
- `agent/load_questions.py`：加载 `public_dataset_upload/questions/group_a/*.json`（共 100 题），按 qid 查找；doc_ids 缺失时空列表兜底（B 榜预留）。
- `agent/output_writer.py`：写 answer.csv（summary 行 + 每题行，列为 qid,answer,prompt_tokens,completion_tokens,total_tokens）、evidence.json、run_manifest.json。
- `agent/run_submission.py`：CLI 入口与数据流编排，`solve_question_mock()` 明确标注为 mock/dry-run 占位。

### 运行命令

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m agent.run_submission --qid ins_a_007
```

### 输出文件位置

- `submission/answer.csv`
- `submission/evidence.json`
- `submission/run_manifest.json`

以上均为本地运行产物，默认不进 Git。

### 验证结果

- 正常路径：`--qid ins_a_007` 退出码 0，answer.csv 含 header + summary 行 + ins_a_007 行；evidence.json 含完整题目上下文（domain=insurance, answer_format=multi, doc_ids=["1","2","16"]）、空 evidence 列表、mode=mock_dry_run；run_manifest.json 含起止时间、requested_scope、repo 相对输出路径、success=1/failure=0、Token 合计 0。
- 错误路径：`--qid no_such_qid` 退出码 1，stderr 提示未找到并给出示例 qid，manifest 记 failure=1。加载题目总数 100，与预期一致。

### 当前限制

- mode=mock_dry_run：答案是占位 "A"，不是任何推理结果，禁止用于正式提交。
- Token 全为 0（未调用任何模型 API）。
- evidence 为空列表：尚无 doc_id 映射、文档解析和检索。
- 每次运行覆盖 submission/ 下同名文件，暂无 run 归档。

### 下一步 Task 2：A 榜 doc_id 映射

建立确定性 `doc_id -> raw 文件路径` 映射（建议产物 `processed_data/doc_id_map.json`）：五个领域分别处理；regulatory 需覆盖 `csrc_*` HTML、`csrc_*_att*` 附件 PDF、`strict_v3_*` TXT（按数字前缀匹配 mojibake 文件名）；验收标准为 A 榜 100 题全部 doc_ids 可解析到存在的本地文件，零缺失。

## 2026-07-05 Task 2：A 榜 doc_id 到本地文件的完整映射

### 本任务目标

实现 A 榜 100 题所有 doc_ids 到 `public_dataset_upload/raw` 真实文件的确定性映射（按领域命名规则，不逐题硬编码），提供 CLI 验证和 pytest 测试。

### 创建/修改的文件

- `agent/doc_id_map.py`：`resolve_doc_path` / `resolve_question_doc_paths` / `build_group_doc_map`，DocMapError 报错含 domain、doc_id、尝试路径或匹配模式。
- `agent/check_doc_map.py`：CLI，扫描全部 group_a 题目并生成 `processed_data/doc_id_map.json`。
- `tests/test_doc_id_map.py`：10 项测试（五领域规则、大小写扩展名、regulatory 三形态、错误信息、全量 100 题覆盖）。

### 运行命令

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m agent.check_doc_map
python -m pytest tests/test_doc_id_map.py -q
```

### 映射覆盖结果

- questions=100，全部扫描成功。
- unique_doc_count=68：insurance 16、financial_contracts 13、regulatory 15、research 15、financial_reports 9。
- source_type 分布：pdf 59、html 3、txt 6。
- missing=[]，errors=[]。
- `processed_data/doc_id_map.json` 已生成，含 generated_at、group、question_count、unique_doc_count、mappings、missing、errors；mappings 每条含 domain、doc_id、source_type、path（repo 相对路径）。

### 测试结果

pytest 10 passed。过程中测试抓到一个真实缺陷：在大小写不敏感文件系统上，用 `is_file()` 逐个探测 `.PDF`/`.pdf` 会命中但返回错误大小写的路径；已改为列目录按真实文件名匹配（stem 精确、后缀不区分大小写），保证 doc_id_map.json 中记录的是磁盘上的真实文件名。

### 当前限制

- 只做路径映射，未解析文件内容。
- strict_v3 依赖 `strict_v3_NNN` 前缀唯一性（当前 6 个文件均唯一；命中 0 或多个会显式报错）。
- doc_id_map.json 每次运行覆盖生成，无历史版本。
- 映射仅覆盖 A 榜出现过的 doc_ids（68 个），不是 raw 全量文件清单；B 榜需要另建全量文档索引。

### 下一步 Task 3：文档解析和 chunks

按 source_type 分三条解析管线（PDF/HTML/TXT），产出 `processed_data/documents.jsonl` 与 `chunks.jsonl`：PDF 保留页码（合同/财报最长 516 页，需关注解析耗时与表格）；HTML 去噪保正文；strict_v3 TXT 为 UTF-8 with BOM，按章/节/条切分；chunk 需带 doc_id、路径、页码或章节定位信息，为后续无 embedding 检索做准备。

## 2026-07-05 Task 3：文档解析和 chunks 生成

### 重要说明：代码已由并行工作提前完成，本轮职责转为审查与验证

开始 Task 3 时发现 `agent/chunk_schema.py`、`agent/parse_documents.py`、`tests/test_parse_documents.py` 及产物 `processed_data/chunks.jsonl`、`parse_report.json`、`parse_cache/` 均已存在（文件时间戳晚于 Task 2 完成时间数分钟，应为队友并行会话产出）。为遵守"不删除已有工作"原则，本轮未重写覆盖，改为逐项审查代码是否符合 Task 3 规格，并独立运行验证。

### 代码审查结论

- `agent/chunk_schema.py`：`make_chunk` / `validate_chunk` 齐全；校验覆盖空文本、pdf 必须有页码、html/txt page 必须为 null、char_count 一致性、source_path 相对路径。符合规格。
- `agent/parse_documents.py`：CLI `--group group_a`；缺 doc_id_map.json 时明确提示先跑 check_doc_map；PDF 用 pypdf 逐页抽取、单页失败记 failure 不中断；滑窗 1800/200；HTML 用 bs4 去 script/style/noscript/nav 等噪声、h1/h2/h3/title 作 section、div 布局页有整页兜底；TXT 依次 utf-8-sig/utf-8/gb18030、按章/条切分；<20 字非标题片段过滤；全部失败时退出非 0。额外实现了 `parse_cache/` 逐文档缓存（断点续跑，支持 `--refresh`），超出规格但合理。
- 审查中重点排查了 HTML 管线 li/td 与 p 嵌套可能导致的重复计文：用 30 字符 shingle 重复检测实测 csrc_0262，无重复。

### 运行命令与验证结果

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m agent.parse_documents --group group_a   # exit 0
python -m pytest tests/test_parse_documents.py tests/test_doc_id_map.py -q  # 20 passed
```

- 解析覆盖：documents=68，parsed=68，failed=0，failures=[]。
- chunk 总数：8545。source_type 分布：pdf 59 docs / 8107 chunks，html 3 / 31，txt 6 / 407。
- domain 分布：financial_contracts 4205、financial_reports 2689、regulatory 679、research 664、insurance 308。
- 可复现性：对 insurance doc 1 强制 `refresh=True` 重新解析，与缓存结果逐字段一致。
- chunk 质量抽样：char_count min 2（"附则"类标题豁免）/ median 905 / max 1800（滑窗上限被遵守）；PDF chunk 页码齐全。

### 当前限制

- pypdf 纯文本抽取：无 OCR，扫描版或复杂表格页的文本质量未逐页人工核验；表格结构信息（行列关系）未保留，财报数值题可能受影响。
- HTML 去噪不完全：csrc 页面为 div 布局，触发整页兜底路径，导航文字（"首页/机构概况"等）仍混入 chunk 头部，Task 4 检索需容忍或后续清洗。
- section 字段在 PDF 管线为空字符串，条款号定位靠 text 内容本身。
- chunks 仅覆盖 A 榜 68 个文档，B 榜需全量扩展。

### 下一步 Task 4：无 embedding 检索

基于 chunks.jsonl 构建检索：中文分词（jieba 或字符 n-gram）+ BM25 纯 Python 实现；按题目 doc_ids 限定候选范围（A 榜）；对题干+选项分别生成查询；输出 top-k chunk 及 chunk_id/page/section 证据定位；为 Task 5 Qwen 判断提供 evidence pack。需验证：ins_a_007 等已人工解过的题，正确证据 chunk 是否能进 top-k。

## 2026-07-05 Task 4：无 embedding 证据检索

### 本任务目标

基于 group_a 题目和 chunks.jsonl，实现纯规则检索（无 embedding、不调用模型）：A 榜按 doc_ids 限定候选，逐选项返回 top-k evidence，供 Task 5 Qwen 逐项判断直接消费。

### 创建/修改的文件（全部为本轮新建，未改动 Task 3 任何代码与产物）

- `agent/query_terms.py`：normalize/term 抽取（数字+单位、百分比、年份、金额、条款号、英文 token、中文 2-6 字短语与 2-4 字 n-gram）、领域提示词表、`build_term_weights`（选项词 2.0 > 题干词 1.0 > 领域提示 0.3；数字类 ×3；题干∩选项共现 ×1.5；长词按长度加权）。停用词表过滤题面套话。
- `agent/retrieve.py`：`Bm25LiteIndex`（子串匹配 tf/df + BM25 饱和 + 长度归一 + idf；section 命中 ×1.1）；`filter_chunks_for_question` doc_ids 严格限定（B 榜无 doc_ids 时 domain 全域 fallback）；matched_terms 为空不进结果；同分按 chunk_id 排序保证确定性；超长 text 围绕首个命中 term 截 1200 字；CLI 支持 --qid/--top-k/--output/--chunks。
- `tests/test_retrieve.py`：12 项要求全覆盖（含 CLI 子进程测试、md5 快照校验 Task 3 产物不变）。
- 无第三方新依赖，纯标准库。

### 运行命令

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m agent.retrieve --qid ins_a_007 --top-k 5 --output processed_data/retrieval_samples/ins_a_007.json
python -m pytest tests/test_retrieve.py -q
python -m pytest tests/test_doc_id_map.py tests/test_parse_documents.py tests/test_retrieve.py -q
```

### ins_a_007 检索摘要

- 候选 chunks=50（严格来自 doc_ids 1、2、16），检索耗时 0.13s。
- 每选项 evidence=5 条，score 降序，evidence 的 doc 分布：A→[16,1,1,1,16]，B→[16,2,2,16,2]，C→[16×5]，D→[16,16,16,16,1]。
- 无空 evidence 选项。
- 关键验收：A 选项 top1（insurance:16:9:0）命中原文"保单贷款…贷款金额不得超过本合同当时现金价值的 80%"，matched_terms 含 保单贷款、80%；B、C 选项 evidence text 均含 借款/保单贷款。
- 产物 `processed_data/retrieval_samples/ins_a_007.json` 合法 JSON，含 qid/domain/question/answer_format/doc_ids/top_k/options（每选项 option_text + query_terms + evidence，evidence 含 chunk_id/doc_id/source_type/source_path/page/section/score/matched_terms/text）。

### 测试结果

- test_retrieve.py：11 passed（12 项要求中"Task 3 产物不变"由 md5 快照 fixture 在 teardown 断言，不单列 test 函数）。
- 全量回归：31 passed（doc_id_map 10 + parse_documents 10 + retrieve 11）。
- Task 3 产物校验：chunks.jsonl 与 parse_report.json 的 md5 在任务前后完全一致（b9e79dfe… / b18086e2…），未被修改。

### 当前限制

- 这是确定性关键词/BM25 风格检索，不是语义向量检索；同义改写（如"保单贷款"vs"借款"）依赖 n-gram 重叠，语义鸿沟大的选项可能漏召回。
- 不处理最终答案，不调用 Qwen。
- B 榜无 doc_ids 时仅保留 domain 全域 fallback，未做候选文档定位优化，本任务不处理。
- 检索质量需通过 A 榜线上反馈与错题复盘持续迭代（下一步可用更多已人工解过的题抽查）。
- evidence 质量受 Task 3 解析限制：PDF section 为空、表格结构丢失、csrc HTML 含导航噪声。

### 下一步 Task 5：Qwen 客户端与逐项判断

接入百炼平台 Qwen API（读环境变量 API key，不硬编码）：qwen client 封装（含 token 用量记录、重试、超时）；judgment prompt 模板——给定题目+选项+evidence，逐选项输出 支持/反驳/证据不足；答案合成与格式校验（mcq/tf 单字母、multi 排序无分隔符）；把 run_submission 的 mock 替换为真实管线但保留 mock 模式开关；每题记录 prompt/completion/total token 进 answer.csv 与 evidence.json。先跑通 ins_a_007 单题，人工核对判断合理性。

## 2026-07-05 Task 5：Qwen 客户端与逐项判断

### 本任务目标

打通单题（ins_a_007）完整链路：题目 -> doc_ids 限定检索 -> 逐选项 evidence -> Qwen 逐项判断（support/refute/insufficient）-> 按题型合成合法答案 -> 三个提交产物。

### 创建/修改的文件

新建：
- `agent/qwen_client.py`：标准库 urllib 实现 OpenAI-compatible 调用；key 从 DASHSCOPE_API_KEY（fallback QWEN_API_KEY）读取，QWEN_MODEL 默认 qwen-plus，QWEN_BASE_URL 默认百炼 compatible-mode；429/5xx 重试；MissingApiKeyError/QwenApiError；key 不打印、不写文件、不出现在 repr 和异常中。
- `agent/prompts.py`：evidence-grounded 单选项判断 prompt——只准用给定证据、禁外部知识、禁猜测、证据不足必须 insufficient、严格 JSON 输出、evidence_refs 引用证据编号。
- `agent/reason_qwen.py`：`judge_option_with_qwen`（API/解析失败记 error 不崩题）、`reason_question_with_qwen`（client 可注入）、`reason_question_dry_run`（零 API 调用）、JSON 提取（容忍 markdown 包裹/前后杂文字）、token 逐选项累加、保存 reasoning sample。
- `agent/normalize_answer.py`：multi 按 support 排序拼接；mcq 多 support 取 evidence_refs 最多者；tf A/B 互斥判断；无 support 一律 fallback 最前合法选项 + low_confidence + warning；validate_answer_format 强校验。
- `tests/test_normalize_answer.py`（11 项）、`tests/test_reason_qwen.py`（7 项，fake client）、`tests/test_qwen_client.py`（5 项，含 key 不泄漏测试）。

修改（最小改动）：
- `agent/run_submission.py`：重构为 检索->判断->输出 全链路；新增 `--dry-run`（默认行为，mode=dry_run_mock）与 `--use-qwen`（互斥；无 key 时 exit 1 并提示设置环境变量）；自动调用 retrieve_for_question，无需手动读 retrieval_samples。
- `agent/output_writer.py`：evidence.json 追加 retrieval/option_judgments/warnings/low_confidence/model 字段，Task 1 基本字段不变。
- 未改动 Task 3/Task 4 任何代码；chunks.jsonl md5 校验任务前后一致。

### 运行命令与结果

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m pytest tests/test_normalize_answer.py tests/test_reason_qwen.py tests/test_qwen_client.py -q  # 23 passed
python -m pytest tests/ -q                            # 全量回归 54 passed
python -m agent.run_submission --qid ins_a_007 --dry-run  # exit 0
python -m agent.run_submission --qid ins_a_007 --use-qwen # （无 key 环境）exit 1，明确报错
```

### dry-run 结果

- mode=dry_run_mock，CLI 输出明确标注"未调用 Qwen，fallback 占位答案，非正式推理结果"。
- 四个选项 judgment=insufficient，token=0，answer=A（multi fallback），low_confidence=true 且带 warning。
- answer.csv：header + summary(0,0,0) + ins_a_007 行；evidence.json 含题目信息、每选项 5 条检索证据、option_judgments、warnings、low_confidence、mode、model；run_manifest.json mode=dry_run_mock；reasoning_samples/ins_a_007.json 结构齐全。

### --use-qwen 是否运行

未真实调用。原因：当前执行环境未配置 DASHSCOPE_API_KEY / QWEN_API_KEY（且本地沙盒网络受限，即使有 key 也可能无法直连百炼）。已验证无 key 时 --use-qwen 清楚失败（exit 1），不产生伪正式答案。待在配置了 key 的本机终端运行：
`DASHSCOPE_API_KEY=... python -m agent.run_submission --qid ins_a_007 --use-qwen`

### Token 统计方式

每次 chat 调用从响应 usage 读取 prompt/completion/total_tokens -> 记入该选项 judgment -> 选项累加为题级 token -> 题级累加为 answer.csv summary 行与 manifest 总计。usage 缺失时按 0 计并可从 raw 排查。

### 当前限制

- dry-run 不是正式答案，仅验证链路和格式。
- 当前只验证单题 ins_a_007，未跑 insurance 20 题。
- Qwen 判断质量强依赖 Task 4 检索证据质量（证据不含正确条款时只能 insufficient）。
- multi/mcq/tf 的 fallback 只保证格式合法，不代表高置信答案；low_confidence 题目是后续复盘重点。
- 逐选项独立调用（multi 一题 4 次调用），token 成本偏高，后续可评估合并判断以省 token。
- 真实 Qwen 输出的 JSON 遵循度未验证，需要拿到 key 后实测。

### 下一步 Task 6：跑 insurance 20 题

批量 runner：按领域跑 insurance 全部 20 题（--use-qwen），逐题保存 reasoning sample 与 trace；answer.csv 含 20 行 + summary；统计每题 token、判断分布（support/refute/insufficient/error 比例）、low_confidence 题目清单；人工抽查 3-5 题判断合理性；按失败类型分类（检索漏证据/判断错/格式错）为 Task 7 优化提供输入。

## 2026-07-05 Task 6/7 前置护栏：提交安全校验

### 本任务目标

在批量跑题前补一个独立校验器，防止把 dry-run 生成的合法 `answer.csv` 误传到天池。校验器只检查提交产物一致性，不调用模型、不修改答案、不参与推理。

### 创建/修改的文件

- `agent/validate_submission.py`：新增 CLI 与 `validate_submission_files()`，读取 `answer.csv`、`evidence.json`、`run_manifest.json`，检查是否来自真实 Qwen 运行、Token 汇总是否一致、答案格式是否合法、三份文件是否互相对齐。
- `tests/test_validate_submission.py`：新增 6 项测试，覆盖真实 Qwen 产物通过、dry-run 产物拒绝、summary token 不一致拒绝、答案格式非法拒绝、evidence 缺记录拒绝、CLI 非法产物返回非 0。

### 运行命令与结果

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m pytest tests/test_validate_submission.py -q  # 6 passed
python -m pytest tests/ -q                             # 60 passed
python -m agent.validate_submission submission/answer.csv
```

当前 `submission/` 中的真实 Qwen 单题产物校验结果：

```text
[VALID] questions=1 total_tokens=11979
```

### 校验规则

- `run_manifest.mode` 必须是 `qwen`，不能是 `dry_run_mock`。
- `run_manifest.failure_count` 必须为 0。
- `answer.csv` 第一行数据必须是 `summary`。
- `summary` 的 prompt/completion/total token 必须等于所有题目行之和。
- `run_manifest` 的 token 总数必须与 `answer.csv` summary 对齐。
- `answer.csv` 每个 qid 必须能在 `evidence.json` 中找到对应记录。
- `answer.csv` 与 `evidence.json` 的 answer 和 token 必须一致。
- 每题 `prompt_tokens` 和 `total_tokens` 必须大于 0。
- 每题 `evidence.mode` 必须是 `qwen`。
- 答案必须符合题型格式：`mcq/tf` 单字母，`multi` 排序去重且无分隔符。

### 当前限制

- 这个校验器只能判断“能不能安全上传”，不能判断答案是否正确。
- `low_confidence` 目前不作为失败条件；它是后续错题复盘和提分的重点。
- 当前只验证了单题 Qwen 产物；Task 6/7 需要在 20 题和 100 题产物上继续运行同一校验器。

### 下一步 Task 6：跑 insurance 20 题

Task 6 批量生成 `answer.csv` 后必须先运行：

```bash
python -m agent.validate_submission submission/answer.csv
```

只有校验结果为 `VALID`，才允许把它视作可上传候选文件。

## 2026-07-05 Task 6：insurance 领域批量运行能力

### 本任务目标

把 Task 5 的单题链路扩展成领域批量链路，先支持 insurance 20 题：单题失败不中断，批量输出 `answer.csv`、`evidence.json`、`run_manifest.json`，并在 manifest 中记录失败题、低置信题、Token 与 judgment 分布。

### 创建/修改的文件

- `agent/load_questions.py`：新增 `load_questions_by_domain(domain)`，按领域读取题目并保持题目文件内顺序。
- `agent/run_submission.py`：新增 `--domain`、`--all`、`--limit`；新增 `run_questions()` 批量执行函数；manifest 增加 `qids`、`failures`、`low_confidence_qids`、`judgment_distribution`、`average_total_tokens`。
- `tests/test_run_submission_batch.py`：新增 4 项测试，覆盖 insurance 题目加载顺序、`--domain insurance --limit 2 --dry-run` 输出、未知 domain 失败、单题失败后继续处理后续题。

### 运行命令与结果

```bash
cd "/Users/xuzijian/Desktop/Agent Competition"
python -m pytest tests/test_run_submission_batch.py -q  # 4 passed
python -m pytest tests/ -q                             # 64 passed
python -m agent.run_submission --domain insurance --limit 2 --dry-run
python -m agent.validate_submission submission/answer.csv
```

dry-run 冒烟结果：

- `requested_scope=domain:insurance limit=2`
- success=2，failure=0
- low_confidence=2
- judgment_distribution：support=0、refute=0、insufficient=8、error=0
- token=0
- 生成了 2 题 `answer.csv/evidence.json/run_manifest.json`

安全校验结果符合预期：

```text
[INVALID] questions=2 total_tokens=0
```

原因是该产物为 `dry_run_mock`，Token 为 0，因此不能上传。这验证了 Task 6/7 前置护栏有效。

### --use-qwen 状态

本 Codex 执行环境未配置用户的 `DASHSCOPE_API_KEY/QWEN_API_KEY`，因此未代跑真实 insurance 20 题。已验证无 key 时命令会清楚失败，不会生成伪正式产物：

```bash
python -m agent.run_submission --domain insurance --limit 2 --use-qwen
# [error] 未配置 Qwen API key。请设置环境变量 DASHSCOPE_API_KEY（或 QWEN_API_KEY）。
```

### 用户本地真实运行建议

在已经设置好 API key 的同一个终端中，先跑小样本：

```bash
python -m agent.run_submission --domain insurance --limit 2 --use-qwen
python -m agent.validate_submission submission/answer.csv
```

如果 `VALID`，再跑完整 insurance 20 题：

```bash
python -m agent.run_submission --domain insurance --use-qwen
python -m agent.validate_submission submission/answer.csv
```

### 当前限制

- 批量能力已完成并通过 dry-run 验证，但真实 insurance 20 题需要在持有 API key 的终端执行。
- 当前流程仍是每个选项一次 Qwen 调用，保险 20 题预计约 80 次模型调用，需关注额度。
- 批量产物会覆盖 `submission/` 下同名文件，跑正式 20 题前如需保留单题产物，需要手动备份。
- 答案正确率尚未优化；Task 6 主要目标是稳定跑通与收集失败/低置信/Token 统计。

### 下一步

在本机带 API key 终端真实跑 `--domain insurance --limit 2 --use-qwen`，确认 `VALID` 后再跑 20 题。跑完后根据 `run_manifest.json` 和 `evidence.json` 汇总低置信题、失败题和 Token 成本，再决定是否进入 Task 7 或先做一轮保险领域错误复盘。
## 2026-07-05 A 榜 v0 基准冻结：线上分数 63.2607

本轮将 A 榜第一次完整有效提交冻结为后续 v1 优化基准。冻结目录：

```text
workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/
```

冻结产物：

- `answer.csv`
- `evidence.json`
- `run_manifest.json`
- `baseline_record.md`

线上提交信息：

- 提交时间：2026-07-05 15:47:32
- 线上分数：63.2607
- 本地校验：`[VALID] questions=100 total_tokens=1161593`
- A 榜 100 题全部生成成功，`failure_count=0`
- `low_confidence_count=17`
- `reused_from_cache_count=77`

SHA256：

```text
c1a70a5697fbb55b0248d2a6b9aa34ca7279975ed3689d5cadc5f9a7b22421ff  answer.csv
ba5ee86f9155672cace1fe7a2428bb30ec8e01f62bb96bef9dbdf8133029de49  evidence.json
b22230895d9f421a578ecf49e70e58e46f93bde5a8434acf1040fb77f1d8e451  run_manifest.json
```

后续 v1 微调不直接覆盖该目录。所有新提交应与本基准比较线上分数、token、low confidence、失败题和疑似错题类型。

## 2026-07-08 提交记录补记：v1s1

- 变量：S1 确定性层修复，包含 csrc_0009_att1 解析修复、doc_meta 标题、证据 source_header、邻近 chunk 合并、多实体配额和缓存版本化。
- 线上分数：61.8540 | 与 63.2607 差：-1.4067 | 与上一次提交差：-1.4067
- 答案 diff：8 题变化（相对 v0），清单：ins_a_005 ABCD->ABD；ins_a_007 AC->BC；ins_a_009 BC->C；ins_a_010 ABCD->ABD；ins_a_014 ACD->AC；ins_a_015 AB->A；ins_a_016 CD->A；ins_a_019 ABC->A。
- token：原始 total=1280096（系数约 0.9232）；注意本地测试在冻结前覆盖了 `submission/` 和 ins_a_001/ins_a_002 reasoning sample，因此 `2026-07-05_v1s1_score_61_8540/` 是审计重建目录，不是字节级原始提交件。
- low_confidence：原始观测 20 题。
- 结论：S1 未提升，反推约从 68/100 降到 67/100；证据质量改善没有穿透逐选项判断层，且增加了 token 成本。
- 下一步：进入 v2-0/v2-1；先用权威 `evaluation/local_labels.md` 做 tf 回归，再只重跑 20 道 tf，避免混入 mcq/multi 变量。

执行中观察到的越界问题：

- `tests/test_run_submission_batch.py::test_domain_limit_dry_run_cli_writes_two_question_outputs` 会覆盖 `submission/`，且 dry-run 会覆盖 reasoning sample；后续实验提交前必须重新生成正式 `submission/answer.csv` 并校验 `VALID`。
- v1-S1 原始提交件未能在跑测试前冻结，这是本次记录断档的直接原因；后续每次线上提交后先冻结，再跑任何测试。

## 2026-07-08 v2-0 / v2-1 实施记录：v2s1

目标：

- v2-0：补记 v1-S1，建立本地真值集，明确 v2-1 的 tf 验收样本。
- v2-1：新增判断题题干级 true/false/uncertain 链路，废除正式推理中的 A/B 选项级 tf 判断。

改动文件：

- `workspace/03_baseline_improvement/evaluation/local_labels.md`（2026-07-15 已由旧位置迁移）
- `workspace/03_baseline_improvement/submissions/a_leaderboard_v0/v2_s1/tf_rerun_qids.txt`
- `workspace/03_baseline_improvement/submissions/a_leaderboard_v0/v2_s1/tf_rerun_qids.json`
- `agent/prompts.py`
- `agent/reason_qwen.py`
- `agent/retrieve.py`
- `agent/run_submission.py`
- `agent/normalize_answer.py`
- `tests/test_reason_tf.py`
- `tests/test_normalize_answer.py`

验收命令与结果：

```text
python -m pytest tests/test_reason_tf.py tests/test_normalize_answer.py -q
16 passed

python -m pytest tests/ -q
88 passed

python -m agent.validate_submission workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/answer.csv --evidence workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/evidence.json --manifest workspace/03_baseline_improvement/submissions/a_leaderboard_v0/2026-07-05_score_63_2607/run_manifest.json
[VALID] questions=100 total_tokens=1161593

python -m agent.validate_submission submission/answer.csv
[VALID] questions=100 total_tokens=1161593
```

离线观察：

- `PIPELINE_VERSION=v2s1`。
- 20 道 tf 重跑清单已生成。
- `retrieve_for_tf_question` 不再输出 A/B options 结构，而是题干级 `tf.evidence`。
- 抽查 `fc_a_003/fc_a_013/fin_a_013/res_a_003`，每个题面 doc_id 至少有 2 条证据覆盖。
- `local_labels.md` 当前 11 题，其中 8 道 tf 的本地标签均为 A；因此 v2-1 的已知标签收益上限可能不高，重点是让 tf 链路可审计，并暴露隐藏 B 题。

当前限制：

- 尚未调用 Qwen 跑 v2s1；当前 `submission/` 已恢复为 v0 安全副本，不能代表 v2s1。
- 由于 v1-S1 原始本地产物曾被测试覆盖，v1-S1 冻结目录只能作为审计重建件，不能作为字节级提交原件。

执行中观察到的越界问题：

- dry-run CLI 测试会覆盖 `submission/`；本次已在测试后把 `submission/` 恢复为 v0 安全副本。真正提交前必须重新跑 v2s1 Qwen 并再次 `validate`。

## 2026-07-15 E001 提交前记录：v2s1 TF-only

- 变量：20 道 TF 使用已有 v2s1 题干级判断链路包；其余 80 题从冻结 v0 产物级继承。
- 独立门槛：S2a 的 `reg_a_010`、`res_a_013` 均标为 B/high，完整性复验 2/2、0 errors。
- 本地结果：10 道已标 TF 从 8/10 提升为 10/10；N=2、M=0、净 +2。
- 答案 diff：仅 `reg_a_010 A→B`、`res_a_013 A→B`；其余 98 道答案不变。
- Token：total=1,168,763，相对 v0 +7,170。
- 全量测试：132 passed。
- 校验：候选 validator `VALID / 100 / 1,168,763`；E001 专属审计 12/12 PASS。
- 候选：`outputs/candidates/v2s1_tf_only/`；已逐字节晋升至根 `submission/`。
- SHA256：answer `5e082b6f...90c69`；evidence `f19091ec...5614`；manifest `1f160f36...7b87`。
- 线上状态：尚未上传；预期约 65.0912，仅为两题净提升推算。
- 当前决策：`PILOT / READY_TO_UPLOAD`；取得线上分数后再写 KEEP_SCORE 或 ROLLBACK。

可追溯性说明：20 道缓存没有保存调用时完整 retrieval；本次 evidence 使用当前冻结
chunks 和检索代码重建，相关哈希在 rerun manifest 中。不能声称原始 Prompt 可字节级复现。
