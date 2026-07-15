"""
probe_mcq_loop_effect.py —— 只重跑 15 道 mcq，记录【初答】和【循环后终答】，看循环到底改没改 mcq 答案。

回答用户的问题：mcq 那 15 题，循环有没有改变过它们的答案？改了是变好还是变坏？
  - 若循环从没改过 mcq 答案(初答==终答) → 循环对 mcq 纯空转，砍掉是纯赚。
  - 若改过 → 看改对了还是改错了(对 Claude 尺子)，决定该不该对 mcq 也保留循环。

只跑 mcq(15题)、单变量复刻 v15 的 agent_solve，额外返回初答。用同一网关模型，可比。
"""
import csv
from pathlib import Path

import run_v6_retrieval as v6
import run_v9_multi_topn as v9
import run_v14_agent_loop as v14
import run_v15_loop_on_direct as v15

HERE = Path(__file__).parent


def load_answers(path: Path) -> dict:
    ans = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r or r[0] in ("qid", "summary"):
                continue
            ans[r[0]] = r[1] if len(r) > 1 else ""
    return ans


def solve_with_initial(client, q: dict):
    """复刻 v15.agent_solve，但额外返回初答，看循环前后变化。"""
    fmt = q.get("answer_format")
    top_n = v15.MULTI_TOP_N if fmt == "multi" else v15.BASE_TOP_N
    docs = v9.build_docs(q, top_n)
    raw, _, _ = v9.ask_gw(client, v6.build_prompt(q, docs))
    init_ans = v6.normalize_answer(raw, fmt)
    evidence = "\n".join(f"【文档{d}】\n{t}" for d, t in docs.items())

    ans = init_ans
    rounds = 0
    for _ in range(v15.MAX_ROUNDS):
        sc_raw, _, _ = v9.ask_gw(client, v14.build_selfcheck_prompt(q, evidence, ans))
        ok, missing = v14.parse_selfcheck(sc_raw)
        if ok or not missing:
            break
        supp = v14.supplementary_retrieve(q, missing)
        if not supp:
            break
        docs = {**docs, f"补查{rounds+1}": supp}
        evidence = evidence + "\n\n【补查到的额外证据】\n" + supp
        raw, _, _ = v9.ask_gw(client, v6.build_prompt(q, docs))
        ans = v6.normalize_answer(raw, fmt)
        rounds += 1
    return init_ans, ans, rounds


def main():
    import os
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("❌ 没读到网关 key"); return 1
    client = v9.make_client()
    v9.MAX_TOKENS = v15.MAX_TOKENS
    ref = load_answers(HERE / "reference_claude.csv")
    mcqs = [q for q in v6.load_all_questions() if q.get("answer_format") == "mcq"]
    print(f"重跑 {len(mcqs)} 道 mcq，看循环改没改答案\n")

    changed = same = 0
    changed_better = changed_worse = changed_neutral = 0
    print(f"  {'qid':<12}{'初答':<6}{'终答':<6}{'尺子':<6}{'轮':<4}变化")
    for q in mcqs:
        qid = q["qid"]
        init, final, rounds = solve_with_initial(client, q)
        r = ref.get(qid, "")
        if init == final:
            same += 1
            tag = "—未变"
        else:
            changed += 1
            iok, fok = (init == r), (final == r)
            if fok and not iok:
                changed_better += 1; tag = "✅改对了(初错→终对)"
            elif iok and not fok:
                changed_worse += 1; tag = "❌改坏了(初对→终错)"
            else:
                changed_neutral += 1; tag = "〰改了但对错没变"
        print(f"  {qid:<12}{init or '空':<6}{final or '空':<6}{r or '空':<6}{rounds:<4}{tag}")

    print("\n" + "=" * 52)
    print(f"  循环【没改】答案: {same}/{len(mcqs)} 题")
    print(f"  循环【改了】答案: {changed}/{len(mcqs)} 题  (改对{changed_better} / 改坏{changed_worse} / 中性{changed_neutral})")
    if changed == 0:
        print("  → 循环对 mcq 纯空转，砍掉是纯赚(省token不损准确率)。")
    elif changed_better > changed_worse:
        print("  → 循环对 mcq 净有益，不该砍。")
    elif changed_worse > changed_better:
        print("  → 循环对 mcq 净有害，更该砍(还能提准确率)。")
    else:
        print("  → 循环对 mcq 改对改坏抵消，砍掉省token、准确率不亏。")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
