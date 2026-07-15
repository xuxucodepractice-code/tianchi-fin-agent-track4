"""
v15 —— 把 v14 的 agent 推理循环，从「压缩地基」搬到「直接喂检索段地基」（=v9/v10 的地基）。

路线判断（改进策略.md 第十五节，本版新增）：
  - v14 证明了「答→自检→缺则定向补查→再答」这个 agent 循环方向对（泛化 +0.0 最健康、
    tf 70→75 / multi 69→71 确在治病），但它被套在「LLM 重写压缩」这个已掉到 68% 的次优地基上，
    修补到 71% 就到头，追不上最简单的「直接喂检索段」v10 的 77%。
  - 拆分数公式看清了主因：token 那项被 (0.7+0.3×TokenScore) 封顶、只剩 8% 空间；准确率是线性直乘、无上限。
    v14 掉的 7.68 分里，准确率占 5.34（主因），token 只占 2.34。→ 现阶段唯一的杠杆是准确率，不是省 token。
  - 「压缩」这个赛题核心，其实检索这一步已经承担了：BM25 把几百页抽成喂进去的 ~12000 字（数千倍压缩），
    是【不掉准确率、不烧模型 token 的天然抽取式压缩】。v12/13/14 掉分的是在检索【之上又加的那层 LLM 重写压缩】——
    它才是杀准确率的凶手，而且要先把候选段全读进去才能压，连 token 都没省下来。
  - 结论：两个赛题要素各由一个部件承担、不再互相拖累——
      地基（把长文塞进小上下文）= 检索这个天然抽取式压缩
      agent（推理能力、B榜泛化）= 自检 + 定向补查循环

相对 v14【唯一变量】：去掉 LLM 重写压缩层。
  - v14：检索 → 【question-aware 压缩成笔记】 → 基于笔记答 → 自检 → 补查 → 再答
  - v15：检索 → 【直接喂检索段】       → 直接答   → 自检 → 补查 → 再答
  自检/补查/循环骨架完全复用 v14，只把「压缩+基于笔记答」换成「直接喂段答」（=v9/v10 的答法）。

两条干净的单变量对照（都锁死同一网关模型）：
  - v9 (直接喂·无循环) 76.45  →  v15 (直接喂·有循环)：测「循环对最好地基的增益」
  - v14(压缩·有循环)   63.23  →  v15 (直接喂·有循环)：测「去掉压缩层的影响」

模型：deepseek-v4-pro（开发期网关，与 v9/v14 同模型，便于归因）。
      若 v15 在网关上赢过 v9 的 76.45，下一步照 v10 的例港成 qwen3.7-plus 正式提交版。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9       # make_client / ask_gw / build_docs / MODEL / MAX_TOKENS
import run_v14_agent_loop as v14     # build_selfcheck_prompt / parse_selfcheck / supplementary_retrieve

MULTI_TOP_N = 24      # 多选题高 TOP_N 治漏选（原样保留 v9/v14 的分治）
BASE_TOP_N = 8        # mcq/tf 基线
MAX_TOKENS = 8192     # 网关是推理模型，给足防思考吃光 max_tokens 返回空（v14 同款，实测 0 空）
MAX_ROUNDS = 2        # 自检→补查最多补 2 轮（防死循环；0 轮 = 退回 v9 直接喂）
OUT_CSV = "answer_v15.csv"


def agent_solve(client, q: dict):
    """单题 agent 循环（直接喂地基版）：直接喂检索段答 → 自检 → (缺则补查→再答) × MAX_ROUNDS。

    与 v14 唯一不同：初答/再答都是【直接喂检索段】（v6.build_prompt），不再经过 LLM 压缩成笔记。
    自检用的证据文本 = 检索段本身（替代 v14 的压缩笔记）。
    返回 (答案, in_tok累加, out_tok累加, 补查轮数)。
    """
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    # --- 初答：检索(天然抽取式压缩) → 直接喂检索段答（v9/v10 式，无 LLM 压缩层） ---
    docs = v9.build_docs(q, top_n)
    raw, ai, ao = v9.ask_gw(client, v6.build_prompt(q, docs))
    itok += ai; otok += ao
    ans = v6.normalize_answer(raw, fmt)

    # 自检用的证据文本：把检索段拼成一段（替代 v14 里那份压缩笔记）
    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    rounds = 0
    for _ in range(MAX_ROUNDS):
        # --- 自检（复用 v14）：多选查漏选 / tf 查复合句每半 / mcq 查区分度 → {ok, missing} ---
        sc_raw, si, so = v9.ask_gw(client, v14.build_selfcheck_prompt(q, evidence, ans))
        itok += si; otok += so
        ok, missing = v14.parse_selfcheck(sc_raw)
        if ok or not missing:
            break
        # --- 定向补查（复用 v14）：缺口关键词在本题文档内 BM25 再检索 → 追加进证据 → 再答 ---
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        docs = {**docs, f"补查{rounds + 1}": supp}
        evidence = evidence + "\n\n【补查到的额外证据】\n" + supp
        raw, ai, ao = v9.ask_gw(client, v6.build_prompt(q, docs))
        itok += ai; otok += ao
        ans = v6.normalize_answer(raw, fmt)
        rounds += 1

    return ans, itok, otok, rounds


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS      # ask_gw 内部读 v9.MAX_TOKENS，覆盖成 8192 防思考截断（同 v14）
    questions = v6.load_all_questions()
    print(f"v15 直接喂地基+agent循环 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | 网关 {v9.MODEL}\n")

    rows = []
    sum_i = sum_o = 0
    total_rounds = 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        try:
            ans, itok, otok, rounds = agent_solve(client, q)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, itok, otok, rounds = "", 0, 0, 0
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_i += itok; sum_o += otok; total_rounds += rounds
        flag = f" [补{rounds}轮]" if rounds else ""
        print(f"  [{i}/100] {qid} ({fmt}) -> {ans or '空'} | tok {itok}+{otok}{flag}")

    out = Path(__file__).parent / OUT_CSV
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_i, sum_o, sum_i + sum_o])
        for r in rows:
            w.writerow(r)

    print("\n" + "=" * 52)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   触发补查的总轮数: {total_rounds}（越多说明 agent 越常发现证据不足去补）")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  (对比 v14≈182万 / v9≈132万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
