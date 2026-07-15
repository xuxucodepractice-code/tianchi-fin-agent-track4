"""
v19 —— 保守动作 + 增量喂，都跑在 deepseek 网关上（与v18同模型，干净单变量对照）。

为什么用 deepseek 而非 qwen3.7-plus：
  - v18(网关·保守·全段喂) 真实准确率 79%、token 365万。
  - v19(网关·保守·增量喂)：**唯一变量=增量喂**。直接测「增量喂省token时，会不会碰坏 v18 那 79% 的准确率」。
    锁死同一网关模型 → 准确率若仍≈79% = 增量喂零准确率代价被证实；token 应从365万降到136万量级。
  - 待网关证实"保守+增量喂"两不误后，再照例港成 qwen3.7-plus 出可提交版(下一步)。

三条已验证结论合体：
  - v18 证明【多选再答只增不减】把真实准确率抬到 79%(全场最高，超v10天花板77%)。
  - v17 证明【增量喂】(答题+自检合并一次 + 再答只喂增量) 把 token 砍74%。
  - deepseek 网关 = v9/v14/v15/v18 同款开发模型，便于单变量归因。

v19 = 在 v17 的增量喂骨架上：①模型换回 deepseek 网关(v9.ask_gw)；②"再答"对 multi 套 v18 保守合并(并集)。
  增量喂的两个prompt(v17.build_answer_selfcheck_prompt / build_reanswer_incremental_prompt)本身模型无关，直接复用。

模型 deepseek-v4-pro(网关)。合规：正式提交须换Qwen，本版是网关对照。
"""
import os
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9        # make_client / ask_gw / build_docs / MAX_TOKENS
import run_v14_agent_loop as v14      # supplementary_retrieve（纯BM25定向补查）
import run_v17_incremental as v17     # build_answer_selfcheck_prompt / build_reanswer_incremental_prompt / parse_ans_missing

MULTI_TOP_N = 24
BASE_TOP_N = 8
MAX_TOKENS = 8192                     # 网关推理模型，给足防思考截断返回空(同v14/v15/v18)
MAX_ROUNDS = 2
OUT_CSV = "answer_v19.csv"


def merge_multi_conservative(prev_ans: str, new_ans: str) -> str:
    """多选保守合并(同v18)：最终 = 初答已选 ∪ 再答新选。只增不减，结构上防把对的改错。"""
    union = set(prev_ans) | set(new_ans)
    return "".join(sorted(c for c in union if c.isalpha()))


def agent_solve(client, q: dict):
    """v19 单题循环：答题+自检合并(全段喂1次，v17增量喂) → 缺则补查 → 再答只喂增量(v17)
    → ★multi再答用保守合并(只增不减，v18)。模型=deepseek网关。返回(答案,in,out,轮数)。"""
    fmt = q.get("answer_format")
    top_n = MULTI_TOP_N if fmt == "multi" else BASE_TOP_N
    itok = otok = 0

    docs = v9.build_docs(q, top_n)
    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    # 刀①(v17)：答题+自检合并一次（全段证据仅此一次）
    raw, i0, o0 = v9.ask_gw(client, v17.build_answer_selfcheck_prompt(q, evidence))
    itok += i0; otok += o0
    ans, missing = v17.parse_ans_missing(raw, fmt)

    rounds = 0
    for _ in range(MAX_ROUNDS):
        if not missing:
            break
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        # 刀②(v17)：再答只喂增量（上一轮答案 + 新补段，不重喂旧全段）
        raw, ai, ao = v9.ask_gw(client, v17.build_reanswer_incremental_prompt(q, ans, supp))
        itok += ai; otok += ao
        new_ans, missing = v17.parse_ans_missing(raw, fmt)
        # ★v19核心(v18)：多选只增不减(补漏)，mcq/tf 自由替换
        ans = merge_multi_conservative(ans, new_ans) if fmt == "multi" else new_ans
        rounds += 1

    return ans, itok, otok, rounds


def load_existing(path: Path) -> dict:
    """断点续跑：读已有CSV非空答案，重跑时跳过；空题重答。"""
    done = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            if len(r) >= 5 and r[1].strip():
                try:
                    done[r[0]] = (r[1], int(r[2]), int(r[3]))
                except ValueError:
                    pass
    return done


def main() -> int:
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = MAX_TOKENS         # ask_gw 内部读 v9.MAX_TOKENS
    questions = v6.load_all_questions()
    out = Path(__file__).parent / OUT_CSV
    done = load_existing(out)
    if done:
        print(f"🔁 断点续跑：已有 {len(done)} 题，本次只跑 {len(questions) - len(done)} 题\n")
    print(f"v19 保守动作+增量喂 | 多选只增不减·再答喂增量 | multi={MULTI_TOP_N} 其余={BASE_TOP_N} | 最多补{MAX_ROUNDS}轮 | 网关 {v9.MODEL}\n")

    rows, sum_i, sum_o, total_rounds = [], 0, 0, 0
    for i, q in enumerate(questions, 1):
        qid, fmt = q["qid"], q.get("answer_format")
        if qid in done:
            ans, itok, otok = done[qid]
            rows.append((qid, ans, itok, otok, itok + otok))
            sum_i += itok; sum_o += otok
            print(f"  [{i}/100] {qid} ({fmt}) -> {ans} | 已有(跳过)")
            continue
        try:
            ans, itok, otok, rounds = agent_solve(client, q)
        except Exception as e:
            print(f"  [{i}/100] {qid} ❌ {e}")
            ans, itok, otok, rounds = "", 0, 0, 0
        rows.append((qid, ans, itok, otok, itok + otok))
        sum_i += itok; sum_o += otok; total_rounds += rounds
        flag = f" [补{rounds}轮]" if rounds else ""
        print(f"  [{i}/100] {qid} ({fmt}) -> {ans or '空'} | tok {itok}+{otok}{flag}")

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sum_i, sum_o, sum_i + sum_o])
        for r in rows:
            w.writerow(r)

    budget = 5_000_000
    tscore = max(0, min(1, (budget - (sum_i + sum_o)) / budget))
    print("\n" + "=" * 52)
    print(f"✅ 已写出 {out}")
    print(f"   空答案: {sum(1 for r in rows if not r[1])}")
    print(f"   触发补查总轮数: {total_rounds}")
    print(f"   总token: in={sum_i} out={sum_o} total={sum_i + sum_o}  TokenScore≈{tscore:.4f}  (对比 v18=365万/v17=136万)")
    print(f"   下一步: ./.venv/bin/python my_benchmark.py {OUT_CSV}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
