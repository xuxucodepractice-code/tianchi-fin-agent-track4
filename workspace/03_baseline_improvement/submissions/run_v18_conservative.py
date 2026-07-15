"""
v18 —— 路线A：让 agent 动作【结构上保守】，把"病=多选漏选"这个领域知识编进动作空间。

背景（改进策略.md 第十五节）：
  v17 实测 68.8705 没超过最简单的 v10 直接喂(70.91)。诊断：强模型在"再答"时【过度自我怀疑】——
  本该只补漏选，却把初答里【对的选项删掉】了。而多选题的病自始至终只有一种：【漏选】
  (v9→83%、多喂证据能治、probe_omission 也证实)。从没有"多选一开始选多了要删"这种病。

v18 唯一改动（相对 v15）：**多选题的"再答"只允许在新证据下补选、不允许删改初答已选的**。
  实现 = 最终答案取【初答已选 ∪ 再答新选】的并集 → 循环在结构上只可能补漏、不可能把对的改错。
  把"病=漏选"的先验直接钉进 agent 的动作空间，而不是靠模型自觉。

  - 只对 multi 生效。mcq/tf 保持自由替换（它们的病不是漏选，probe_mcq_loop 证明单选改答net有益、救回过题）。
  - 其余全部锁死同 v15：deepseek 网关(便于对照)、直接喂、MULTI_TOP_N=24、MAX_ROUNDS=2、自检/补查复用v14。

两条干净的单变量对照（锁同一网关模型）：
  - v15(多选再答自由替换 73%) → v18(多选再答只增不减)：测"保守动作"是否止住"改错"的血
  - v9 (直接喂·无循环 76.45)   → v18(保守循环)         ：测循环在最好地基上能否终于变净收益

模型：deepseek-v4-pro（开发期网关，同 v9/v14/v15，便于归因）。跑完过 my_benchmark.py 看估分+过拟合仪表。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9       # make_client / ask_gw / build_docs / MODEL / MAX_TOKENS
import run_v14_agent_loop as v14     # build_selfcheck_prompt / parse_selfcheck / supplementary_retrieve

MULTI_TOP_N = 24
BASE_TOP_N = 8
MAX_TOKENS = 8192
MAX_ROUNDS = 2
OUT_CSV = "answer_v18.csv"


def merge_multi_conservative(prev_ans: str, new_ans: str) -> str:
    """多选保守合并：最终 = 初答已选 ∪ 再答新选。【只增不减】——
    结构上保证初答选中的字母永远保留，循环只可能补漏、不可能把对的删成错的。"""
    union = set(prev_ans) | set(new_ans)
    return "".join(sorted(c for c in union if c.isalpha()))


def agent_solve(client, q: dict):
    """单题 agent 循环（直接喂地基 + 多选保守动作）。相对 v15 唯一区别：
    多选题再答用 merge_multi_conservative 取并集(只增不减)，mcq/tf 照旧整体替换。
    返回 (答案, in_tok累加, out_tok累加, 补查轮数)。"""
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    # --- 初答：检索(天然抽取式压缩) → 直接喂检索段答（同 v15/v10） ---
    docs = v9.build_docs(q, top_n)
    raw, ai, ao = v9.ask_gw(client, v6.build_prompt(q, docs))
    itok += ai; otok += ao
    ans = v6.normalize_answer(raw, fmt)

    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    rounds = 0
    for _ in range(MAX_ROUNDS):
        # --- 自检(复用v14)：多选查漏选 / tf 查复合句每半 / mcq 查区分度 → {ok, missing} ---
        sc_raw, si, so = v9.ask_gw(client, v14.build_selfcheck_prompt(q, evidence, ans))
        itok += si; otok += so
        ok, missing = v14.parse_selfcheck(sc_raw)
        if ok or not missing:
            break
        # --- 定向补查(复用v14，纯BM25) → 追加证据 → 再答 ---
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        docs = {**docs, f"补查{rounds + 1}": supp}
        evidence = evidence + "\n\n【补查到的额外证据】\n" + supp
        raw, ai, ao = v9.ask_gw(client, v6.build_prompt(q, docs))
        itok += ai; otok += ao
        new_ans = v6.normalize_answer(raw, fmt)
        # ★v18 核心：多选只增不减(补漏)，mcq/tf 自由替换 ---
        ans = merge_multi_conservative(ans, new_ans) if fmt == "multi" else new_ans
        rounds += 1

    return ans, itok, otok, rounds


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS
    questions = v6.load_all_questions()
    print(f"v18 保守动作(多选只增不减) | 直接喂 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | 网关 {v9.MODEL}\n")

    rows, sum_i, sum_o, total_rounds = [], 0, 0, 0
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
    print(f"   触发补查总轮数: {total_rounds}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  (对比 v15≈370万 / v9≈132万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
